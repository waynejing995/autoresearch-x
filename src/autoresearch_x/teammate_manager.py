"""Teammate manager — spawn, poll, shutdown Claude Code teammates."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from .models import TeammateRole, TeammateStatus


class TeammateManager:
    """Manages Claude Code teammate subprocess lifecycle."""

    def __init__(
        self,
        team_name: str,
        claude_bin: str = "claude",
        max_turns: int = 20,
        poll_interval: float = 10.0,
        idle_timeout: float = 300.0,
        shutdown_timeout: float = 30.0,
    ) -> None:
        self.team_name = team_name
        self.claude_bin = claude_bin
        self.max_turns = max_turns
        self.poll_interval = poll_interval
        self.idle_timeout = idle_timeout
        self.shutdown_timeout = shutdown_timeout
        self._processes: dict[str, subprocess.Popen] = {}
        self._log_files: dict[str, Path] = {}

    def spawn(
        self,
        role: TeammateRole,
        iteration: int,
        message: str,
        project_dir: Optional[str] = None,
    ) -> str:
        agent_name = f"{role.value}-iter-{iteration}"
        log_file = Path(tempfile.gettempdir()) / f"autoresearch-x-{agent_name}.log"
        cmd = [
            self.claude_bin,
            "--print",
            "--max-turns",
            str(self.max_turns),
            "--output-format",
            "json",
            message,
        ]
        logger.info(f"Spawning teammate: {agent_name} cmd={' '.join(cmd[:4])}...")
        logger.debug(f"Full command: {' '.join(cmd)}")
        log_fh = open(log_file, "w")
        proc = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=project_dir,
        )
        self._processes[agent_name] = proc
        self._log_files[agent_name] = log_file
        log_fh.close()
        return agent_name

    def poll_status(self, agent_name: str) -> TeammateStatus:
        proc = self._processes.get(agent_name)
        if proc is None:
            return TeammateStatus.SHUTDOWN
        ret = proc.poll()
        if ret is None:
            return TeammateStatus.RUNNING
        if ret == 0:
            return TeammateStatus.IDLE
        return TeammateStatus.CRASHED

    def wait_for_idle(
        self,
        agent_name: str,
        timeout: Optional[float] = None,
    ) -> TeammateStatus:
        deadline = time.monotonic() + (timeout or self.idle_timeout)
        while time.monotonic() < deadline:
            status = self.poll_status(agent_name)
            if status in (TeammateStatus.IDLE, TeammateStatus.CRASHED, TeammateStatus.SHUTDOWN):
                return status
            time.sleep(self.poll_interval)
        logger.warning(f"Teammate {agent_name} timed out after {timeout or self.idle_timeout}s")
        return TeammateStatus.CRASHED

    def get_exit_code(self, agent_name: str) -> Optional[int]:
        proc = self._processes.get(agent_name)
        if proc is None:
            return None
        return proc.poll()

    def get_output(self, agent_name: str) -> tuple[str, str]:
        log_file = self._log_files.get(agent_name)
        if not log_file or not log_file.exists():
            return "", ""
        content = log_file.read_text()
        try:
            envelope = json.loads(content.strip())
            result_text = envelope.get("result", "")
            return result_text, json.dumps(envelope, indent=2)
        except json.JSONDecodeError:
            return content, content

    def get_raw_log(self, agent_name: str) -> str:
        log_file = self._log_files.get(agent_name)
        if not log_file or not log_file.exists():
            return ""
        return log_file.read_text()

    def get_last_lines(self, agent_name: str, n: int = 50) -> str:
        log_file = self._log_files.get(agent_name)
        if not log_file or not log_file.exists():
            return ""
        lines = log_file.read_text().splitlines()
        return "\n".join(lines[-n:])

    def shutdown(self, agent_name: str) -> None:
        proc = self._processes.pop(agent_name, None)
        if proc is None:
            return
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=self.shutdown_timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        logger.info(f"Teammate {agent_name} shut down")

    def list_teammates(self) -> list[dict]:
        try:
            result = subprocess.run(
                [self.claude_bin, "agents"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            pass
        return []
