"""Teammate manager — Claude Agent SDK based teammate orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ToolPermissionContext,
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


def _build_scope_hook(
    readonly: list[str],
    scope: Optional[list[str]] = None,
) -> dict[str, list[HookMatcher]]:
    """Build PreToolUse hook that enforces scope restrictions.

    - Blocks Write/Edit on readonly files
    - Blocks Write/Edit outside scope (if scope is set)
    - Allows all other tools
    """

    async def _scope_guard(
        input_data: dict,
        tool_use_id: str,
        context: ToolPermissionContext,
    ) -> dict:
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        if tool_name not in ("Write", "Edit"):
            return {}

        file_path = tool_input.get("file_path", "")
        if not file_path:
            return {}

        # Normalize to relative path for matching
        rel_path = _normalize_path(file_path)

        # Check readonly
        for ro in readonly:
            if _path_matches(rel_path, ro):
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": f"File '{rel_path}' is readonly",
                    }
                }

        # Check scope (if set, only allow files within scope)
        if scope:
            allowed = any(_path_matches(rel_path, s) for s in scope)
            if not allowed:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": f"File '{rel_path}' is outside scope",
                    }
                }

        return {}

    return {
        "PreToolUse": [HookMatcher(matcher="Write", hooks=[_scope_guard])],
    }


def _normalize_path(p: str) -> str:
    """Normalize path for consistent matching."""
    return p.replace("\\", "/")


def _path_matches(file_path: str, pattern: str) -> bool:
    """Check if file_path matches a glob-like pattern.

    Supports:
    - Exact match: "server.py"
    - Prefix match: "src/" matches "src/server.py"
    - Suffix match: "*.py" matches "server.py"
    """
    file_path = _normalize_path(file_path)
    pattern = _normalize_path(pattern)

    if file_path == pattern:
        return True
    if pattern.endswith("/") and file_path.startswith(pattern):
        return True
    if pattern.startswith("*") and file_path.endswith(pattern[1:]):
        return True
    if file_path.endswith("/" + pattern):
        return True
    return False


async def run_teammate(
    prompt: str,
    project_dir: str,
    max_turns: int = 20,
    allowed_tools: Optional[list[str]] = None,
    system_prompt: Optional[str] = None,
    readonly: Optional[list[str]] = None,
    scope: Optional[list[str]] = None,
) -> TeammateResult:
    """Run a single teammate query using the Claude Agent SDK."""
    default_tools = ["Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS"]
    tools = allowed_tools or default_tools

    hooks = None
    if readonly or scope:
        hooks = _build_scope_hook(readonly or [], scope)

    options = ClaudeAgentOptions(
        cwd=project_dir,
        max_turns=max_turns,
        allowed_tools=tools,
        permission_mode="bypassPermissions",
        system_prompt=system_prompt,
        hooks=hooks,
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
    """Extract JSON from teammate result text."""
    full_text = result.get_full_text()

    import re

    json_blocks = re.findall(r"```json\s*(.*?)\s*```", full_text, re.DOTALL)
    if json_blocks:
        try:
            return json.loads(json_blocks[-1])
        except json.JSONDecodeError:
            pass

    full_text = full_text.strip()
    if full_text.startswith("{"):
        try:
            return json.loads(full_text)
        except json.JSONDecodeError:
            pass

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
    readonly: Optional[list[str]] = None,
    scope: Optional[list[str]] = None,
) -> TeammateResult:
    """Synchronous wrapper for run_teammate."""
    return anyio.run(
        run_teammate,
        prompt,
        project_dir,
        max_turns,
        allowed_tools,
        system_prompt,
        readonly,
        scope,
    )
