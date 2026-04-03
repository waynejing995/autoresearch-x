"""Branch manager — priority scoring, fork creation, stall detection, strategist trigger."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from .models import BranchRow, RunState
from .state_manager import StateManager


class BranchManager:
    """Manages branching lifecycle."""

    def __init__(self, state_mgr: StateManager, project_dir: str) -> None:
        self.state_mgr = state_mgr
        self.project_dir = project_dir
        self.max_branches = 8
        self.max_fork_depth = 3

    def compute_priority(self, branch: BranchRow, state: RunState) -> float:
        if branch.status in ("stalled", "completed", "pruned"):
            return 0.0
        if branch.iterations == 0:
            return 1.0

        improvement_rate = self._improvement_rate(branch, state)
        freshness = max(0.0, 1.0 - (branch.stall_count / 5.0))
        proximity = self._proximity(branch, state)

        return improvement_rate * 0.5 + freshness * 0.3 + proximity * 0.2

    def _improvement_rate(self, branch: BranchRow, state: RunState) -> float:
        if branch.best_metric is None or branch.best_metric == "-" or state.best_metric is None:
            return 0.5
        try:
            best = float(branch.best_metric)
        except (ValueError, TypeError):
            return 0.5
        baseline = state.best_metric
        if baseline == 0:
            return 0.5
        delta = abs(baseline - best) / abs(baseline)
        return min(1.0, delta)

    def _proximity(self, branch: BranchRow, state: RunState) -> float:
        if branch.best_metric is None or branch.best_metric == "-" or not state.target_expr:
            return 0.5
        try:
            current = float(branch.best_metric)
        except (ValueError, TypeError):
            return 0.5
        target_val = self._extract_target_value(state.target_expr)
        if target_val is None:
            return 0.5
        baseline = state.best_metric
        if baseline == target_val:
            return 1.0
        denom = abs(baseline - target_val)
        if denom == 0:
            return 1.0
        return max(0.0, min(1.0, 1.0 - abs(current - target_val) / denom))

    @staticmethod
    def _extract_target_value(expr: str) -> Optional[float]:
        import re

        m = re.search(r"([<>=!]+)\s*([\d.]+)", expr)
        if m:
            try:
                return float(m.group(2))
            except ValueError:
                pass
        return None

    def update_priorities(self, state: RunState) -> None:
        for branch in self.state_mgr.read_branches():
            branch.priority = self.compute_priority(branch, state)
            self.state_mgr.update_branch(branch)

    def select_next_branch(self, state: RunState) -> Optional[BranchRow]:
        best = self.state_mgr.get_highest_priority_branch()
        if best is None:
            return None
        best.priority = self.compute_priority(best, state)
        self.state_mgr.update_branch(best)
        return best

    def is_globally_stalled(self) -> bool:
        active = self.state_mgr.get_active_branches()
        if not active:
            return True
        return all(b.status in ("stalled",) for b in active)

    def switch_branch(self, branch_id: str) -> bool:
        try:
            subprocess.run(
                [
                    "git",
                    "stash",
                    "push",
                    "-m",
                    f"autoresearch-x: stash before switch to {branch_id}",
                ],
                cwd=self.project_dir,
                capture_output=True,
                check=False,
            )
            result = subprocess.run(
                ["git", "checkout", f"autoresearch-x/{self.state_mgr.run_dir.name}/{branch_id}"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logger.error(f"Failed to switch to branch {branch_id}: {result.stderr}")
                return False
            logger.info(f"Switched to branch: {branch_id}")
            return True
        except Exception as e:
            logger.error(f"Branch switch failed: {e}")
            return False

    def create_fork(
        self,
        fork_name: str,
        parent_checkpoint: str,
        tag: str,
    ) -> Optional[BranchRow]:
        active = self.state_mgr.get_active_branches()
        non_pruned = [b for b in active if b.status != "pruned"]
        if len(non_pruned) >= self.max_branches:
            logger.warning(f"Max branches ({self.max_branches}) reached, cannot fork {fork_name}")
            return None

        try:
            subprocess.run(
                ["git", "checkout", "-b", f"autoresearch-x/{tag}/{fork_name}", parent_checkpoint],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            subprocess.run(
                ["git", "checkout", f"autoresearch-x/{tag}/main"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create fork {fork_name}: {e}")
            return None

        now = datetime.now(timezone.utc).isoformat()
        row = BranchRow(
            branch_id=fork_name,
            parent_checkpoint=parent_checkpoint,
            status="suspended",
            priority=1.0,
            created_at=now,
        )
        self.state_mgr.add_branch(row)
        logger.info(f"Created fork: {fork_name} from {parent_checkpoint}")
        return row

    def mark_stalled(self, branch_id: str) -> None:
        branch = self._get_branch(branch_id)
        if branch:
            branch.status = "stalled"
            branch.priority = 0.0
            self.state_mgr.update_branch(branch)
            logger.warning(f"Branch {branch_id} marked as stalled")

    def _get_branch(self, branch_id: str) -> Optional[BranchRow]:
        for b in self.state_mgr.read_branches():
            if b.branch_id == branch_id:
                return b
        return None
