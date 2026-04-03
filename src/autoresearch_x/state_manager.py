"""State manager — atomic read/write of state.json, results.tsv, branches.tsv."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from loguru import logger

from .models import (
    ALL_RESULTS_TSV_HEADER,
    BRANCHES_TSV_HEADER,
    RESULTS_TSV_HEADER,
    BranchRow,
    ResultRow,
    RunMode,
    RunState,
)


class StateManager:
    """Manages all filesystem state for a run."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.state_path = run_dir / "state.json"
        self.results_path = run_dir / "results.tsv"
        self.all_results_path = run_dir / "all-results.tsv"
        self.branches_path = run_dir / "branches.tsv"
        self.inbox_dir = run_dir / "inbox"
        self.outbox_dir = run_dir / "outbox"
        self.iterations_dir = run_dir / "iterations"
        self.branches_dir = run_dir / "branches"

    # -- lifecycle -----------------------------------------------------------

    def init_run(
        self,
        tag: str,
        mode: RunMode,
        target: str,
        program_md_path: str,
        eval_command: str,
        metric_name: str,
        target_expr: str,
        scope: List[str],
        readonly: List[str],
        max_iterations: Optional[int] = None,
        timeout_minutes: Optional[int] = None,
    ) -> RunState:
        """Create run directory structure and initial state."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(exist_ok=True)
        self.outbox_dir.mkdir(exist_ok=True)
        self.iterations_dir.mkdir(exist_ok=True)
        self.branches_dir.mkdir(exist_ok=True)

        main_branch_dir = self.branches_dir / "main"
        main_branch_dir.mkdir(exist_ok=True)
        (main_branch_dir / "iterations").mkdir(exist_ok=True)

        now = datetime.now(timezone.utc).isoformat()

        state = RunState(
            tag=tag,
            mode=mode,
            target=target,
            started_at=now,
            max_iterations=max_iterations,
            timeout_minutes=timeout_minutes,
            program_md_path=program_md_path,
            eval_command=eval_command,
            metric_name=metric_name,
            target_expr=target_expr,
            scope=scope,
            readonly=readonly,
        )
        state.to_file(self.state_path)

        self.results_path.write_text(RESULTS_TSV_HEADER + "\n")
        self.all_results_path.write_text(ALL_RESULTS_TSV_HEADER + "\n")
        self.branches_path.write_text(
            BRANCHES_TSV_HEADER + "\n" + BranchRow(branch_id="main", created_at=now).to_tsv() + "\n"
        )
        (main_branch_dir / "results.tsv").write_text(RESULTS_TSV_HEADER + "\n")

        logger.info(f"Run initialized: tag={tag} dir={self.run_dir}")
        return state

    # -- state access --------------------------------------------------------

    def load_state(self) -> RunState:
        return RunState.from_file(self.state_path)

    def save_state(self, state: RunState) -> None:
        state.to_file(self.state_path)

    # -- results.tsv ---------------------------------------------------------

    def append_result(self, row: ResultRow, branch_id: str = "main") -> None:
        branch_results = self.branches_dir / branch_id / "results.tsv"
        if not branch_results.exists():
            branch_results.parent.mkdir(parents=True, exist_ok=True)
            branch_results.write_text(RESULTS_TSV_HEADER + "\n")
        with branch_results.open("a") as f:
            f.write(row.to_tsv() + "\n")

        with self.all_results_path.open("a") as f:
            f.write(f"{branch_id}\t{row.to_tsv()}\n")

    def read_branch_results(self, branch_id: str) -> List[ResultRow]:
        path = self.branches_dir / branch_id / "results.tsv"
        if not path.exists():
            return []
        lines = path.read_text().strip().split("\n")
        if len(lines) <= 1:
            return []
        return [ResultRow.from_tsv(line) for line in lines[1:] if line.strip()]

    def read_all_results(self) -> List[ResultRow]:
        if not self.all_results_path.exists():
            return []
        lines = self.all_results_path.read_text().strip().split("\n")
        if len(lines) <= 1:
            return []
        rows = []
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                rows.append(ResultRow.from_tsv(parts[1]))
        return rows

    # -- branches.tsv --------------------------------------------------------

    def read_branches(self) -> List[BranchRow]:
        if not self.branches_path.exists():
            return []
        lines = self.branches_path.read_text().strip().split("\n")
        if len(lines) <= 1:
            return []
        return [BranchRow.from_tsv(line) for line in lines[1:] if line.strip()]

    def update_branch(self, row: BranchRow) -> None:
        rows = self.read_branches()
        found = False
        for i, r in enumerate(rows):
            if r.branch_id == row.branch_id:
                rows[i] = row
                found = True
                break
        if not found:
            rows.append(row)
        self._write_branches(rows)

    def add_branch(self, row: BranchRow) -> None:
        rows = self.read_branches()
        rows.append(row)
        self._write_branches(rows)

        branch_dir = self.branches_dir / row.branch_id
        branch_dir.mkdir(parents=True, exist_ok=True)
        (branch_dir / "iterations").mkdir(exist_ok=True)
        (branch_dir / "results.tsv").write_text(RESULTS_TSV_HEADER + "\n")

    def _write_branches(self, rows: List[BranchRow]) -> None:
        lines = [BRANCHES_TSV_HEADER]
        for r in rows:
            lines.append(r.to_tsv())
        self.branches_path.write_text("\n".join(lines) + "\n")

    def get_active_branches(self) -> List[BranchRow]:
        return [b for b in self.read_branches() if b.status not in ("completed", "pruned")]

    def get_highest_priority_branch(self) -> Optional[BranchRow]:
        active = [b for b in self.read_branches() if b.status in ("active", "suspended")]
        if not active:
            return None
        return max(active, key=lambda b: b.priority)

    # -- inbox / outbox ------------------------------------------------------

    def write_inbox(self, role: str, data: dict) -> Path:
        self.inbox_dir.mkdir(exist_ok=True)
        path = self.inbox_dir / f"{role}.json"
        import json

        path.write_text(json.dumps(data, indent=2) + "\n")
        return path

    def read_outbox(self, role: str) -> Optional[str]:
        path = self.outbox_dir / f"{role}.json"
        if not path.exists():
            return None
        return path.read_text()

    def clear_outbox(self) -> None:
        if self.outbox_dir.exists():
            shutil.rmtree(self.outbox_dir)
        self.outbox_dir.mkdir(exist_ok=True)

    # -- iteration tracking --------------------------------------------------

    def write_iteration_detail(self, commit: str, content: str, branch_id: str = "main") -> Path:
        detail_dir = self.branches_dir / branch_id / "iterations"
        detail_dir.mkdir(parents=True, exist_ok=True)
        path = detail_dir / f"{commit}.md"
        path.write_text(content)
        return path

    def read_iteration_detail(self, commit: str, branch_id: str = "main") -> Optional[str]:
        path = self.branches_dir / branch_id / "iterations" / f"{commit}.md"
        if path.exists():
            return path.read_text()
        return None
