"""Teammate manager — Claude Agent SDK based teammate orchestration."""

from __future__ import annotations

import json
from typing import Any, Optional

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


class TeammateResult:
    """Structured result from a teammate execution."""

    def __init__(self) -> None:
        self.text_parts: list[str] = []
        self.tool_uses: list[dict] = []
        self.tool_results: list[dict] = []
        self.final_answer: str = ""
        self.raw_messages: list[dict] = []

    def add_text(self, text: str) -> None:
        self.text_parts.append(text)

    def add_tool_use(self, tool_use: dict) -> None:
        self.tool_uses.append(tool_use)

    def add_tool_result(self, tool_result: dict) -> None:
        self.tool_results.append(tool_result)

    def get_full_text(self) -> str:
        return "\n".join(self.text_parts)


async def run_teammate(
    prompt: str,
    project_dir: str,
    max_turns: int = 20,
    allowed_tools: Optional[list[str]] = None,
    system_prompt: Optional[str] = None,
) -> TeammateResult:
    """Run a single teammate query using the Claude Agent SDK.

    Returns structured TeammateResult with all text, tool calls, and final answer.
    """
    default_tools = ["Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS"]
    tools = allowed_tools or default_tools

    options = ClaudeAgentOptions(
        cwd=project_dir,
        max_turns=max_turns,
        allowed_tools=tools,
        permission_mode="acceptEdits",
        system_prompt=system_prompt,
    )

    result = TeammateResult()

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            result.raw_messages.append(_message_to_dict(message))

            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        result.add_text(block.text)
                    elif isinstance(block, ToolUseBlock):
                        result.add_tool_use(
                            {
                                "name": block.name,
                                "input": block.input,
                            }
                        )

            elif isinstance(message, ToolResultBlock):
                result.add_tool_result(
                    {
                        "tool_use_id": getattr(message, "tool_use_id", ""),
                        "content": str(getattr(message, "content", ""))[:500],
                    }
                )

            elif isinstance(message, ResultMessage):
                if hasattr(message, "result") and message.result:
                    result.final_answer = str(message.result)

    return result


def _message_to_dict(message: Any) -> dict:
    """Convert SDK message to dict for debugging/dumping."""
    msg_type = type(message).__name__
    try:
        if hasattr(message, "__dict__"):
            return {"type": msg_type, **{k: str(v)[:200] for k, v in message.__dict__.items()}}
        return {"type": msg_type, "repr": repr(message)[:500]}
    except Exception:
        return {"type": msg_type}


def extract_json_from_result(result: TeammateResult) -> Optional[dict]:
    """Extract JSON from teammate result text.

    Searches text parts for ```json blocks or raw JSON objects.
    """
    full_text = result.get_full_text()

    # Try ```json blocks
    import re

    json_blocks = re.findall(r"```json\s*(.*?)\s*```", full_text, re.DOTALL)
    if json_blocks:
        try:
            return json.loads(json_blocks[-1])
        except json.JSONDecodeError:
            pass

    # Try raw JSON at start
    full_text = full_text.strip()
    if full_text.startswith("{"):
        try:
            return json.loads(full_text)
        except json.JSONDecodeError:
            pass

    # Try regex for status field
    status_match = re.search(r'"status"\s*:\s*"(\w+)"', full_text)
    if status_match:
        return {"status": status_match.group(1), "raw_text": full_text[:500]}

    return None


def run_teammate_sync(
    prompt: str,
    project_dir: str,
    max_turns: int = 20,
    allowed_tools: Optional[list[str]] = None,
    system_prompt: Optional[str] = None,
) -> TeammateResult:
    """Synchronous wrapper for run_teammate."""
    return anyio.run(
        run_teammate,
        prompt,
        project_dir,
        max_turns,
        allowed_tools,
        system_prompt,
    )
