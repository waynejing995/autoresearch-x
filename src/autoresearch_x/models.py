"""Core Pydantic models for autoresearch-x Agent Teams."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RunMode(str, Enum):
    OPTIMIZE = "optimize"
    DEBUG = "debug"
    INVESTIGATE = "investigate"


class BranchStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    STALLED = "stalled"
    COMPLETED = "completed"
    PRUNED = "pruned"


class IterationPhase(str, Enum):
    BASELINE = "baseline"
    ITERATE = "iterate"
    OBSERVE = "observe"
    DIAGNOSE = "diagnose"
    FIX = "fix"
    GATHER = "gather"
    ANALYZE = "analyze"
    CONCLUDE = "conclude"


class Decision(str, Enum):
    KEEP = "keep"
    DISCARD = "discard"
    DIGGING = "digging"      # INVESTIGATE: 持续深挖中
    BRANCHING = "branching"  # INVESTIGATE: 换方向/分支


class TeammateRole(str, Enum):
    PLANNER = "planner"
    WORKER = "worker"
    EVALUATOR = "evaluator"
    STRATEGIST = "strategist"
    CHAT_HOST = "chat_host"


class TeammateStatus(str, Enum):
    RUNNING = "running"
    IDLE = "idle"
    SHUTDOWN = "shutdown"
    CRASHED = "crashed"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class BranchInfo(BaseModel):
    """Single branch tracking entry."""

    id: str
    parent_checkpoint: str = "-"
    status: BranchStatus = BranchStatus.ACTIVE
    priority: float = 1.0
    iterations: int = 0
    best_metric: Optional[float] = None
    stall_count: int = 0
    consecutive_discards: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RunState(BaseModel):
    """Main state.json schema — atomic source of truth."""

    tag: str
    mode: RunMode
    target: str
    current_branch: str = "main"
    iteration_count: int = 0
    max_iterations: Optional[int] = None
    best_metric: Optional[float] = None
    best_commit: str = "-"
    consecutive_discards: int = 0
    crash_count: int = 0
    mind_explosions: int = 0
    active_branches: List[str] = Field(default_factory=lambda: ["main"])
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    timeout_minutes: Optional[int] = None
    program_md_path: str = ""
    eval_command: str = ""
    metric_name: str = ""
    target_expr: str = ""
    scope: List[str] = Field(default_factory=list)
    readonly: List[str] = Field(default_factory=list)
    current_phase: Optional[str] = None  # debug/observe/diagnose/fix, gather/analyze/conclude
    phase_iteration: int = 0  # iterations within current phase (reset on phase transition)
    status: str = "running"

    @field_validator("tag")
    @classmethod
    def tag_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("tag must be non-empty")
        return v.strip()

    @model_validator(mode="after")
    def validate_budget(self) -> "RunState":
        if self.max_iterations is not None and self.max_iterations <= 0:
            raise ValueError("max_iterations must be positive")
        if self.timeout_minutes is not None and self.timeout_minutes <= 0:
            raise ValueError("timeout_minutes must be positive")
        return self

    def time_remaining(self) -> Optional[float]:
        """Return remaining minutes, or None if no timeout."""
        if self.timeout_minutes is None:
            return None
        start = datetime.fromisoformat(self.started_at)
        elapsed = (datetime.now(timezone.utc) - start).total_seconds() / 60
        return max(0.0, self.timeout_minutes - elapsed)

    def iterations_remaining(self) -> Optional[int]:
        """Return remaining iterations, or None if unlimited."""
        if self.max_iterations is None:
            return None
        return max(0, self.max_iterations - self.iteration_count)

    def is_budget_exhausted(self) -> bool:
        iters = self.iterations_remaining()
        time = self.time_remaining()
        if iters is not None and iters <= 0:
            return True
        if time is not None and time <= 0:
            return True
        return False

    def is_target_met(self, current_metric: Optional[float]) -> bool:
        """Check if current metric meets the target expression."""
        if current_metric is None or not self.target_expr:
            return False
        return _eval_target(current_metric, self.target_expr)

    def to_file(self, path: Path) -> None:
        """Write state atomically (write temp + rename)."""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(self.model_dump_json(indent=2) + "\n")
        tmp.rename(path)

    @classmethod
    def from_file(cls, path: Path) -> "RunState":
        """Load state from file."""
        return cls.model_validate_json(path.read_text())


# ---------------------------------------------------------------------------
# Task / Result (inbox / outbox)
# ---------------------------------------------------------------------------


class PlannerTask(BaseModel):
    role: str = "planner"
    iteration: int
    task: str = "Analyze history and propose ONE change"
    state_path: str = ""
    results_path: str = ""
    iterations_dir: str = ""
    program_md: str = ""
    cross_branch_summary: str = ""


class PlannerResult(BaseModel):
    status: str = "success"
    plan: Optional[Dict[str, Any]] = None


class WorkerTask(BaseModel):
    role: str = "worker"
    iteration: int
    task: str = "Execute the planned change"
    plan: Dict[str, Any] = Field(default_factory=dict)
    scope: List[str] = Field(default_factory=list)
    readonly: List[str] = Field(default_factory=list)
    program_md: str = ""


class WorkerResult(BaseModel):
    status: str = "success"
    files_modified: List[str] = Field(default_factory=list)
    changes_summary: str = ""
    observations: str = ""


class EvaluatorTask(BaseModel):
    role: str = "evaluator"
    iteration: int
    task: str = "Run evaluation and extract metric"
    eval_command: str = ""
    metric_name: str = ""
    target: str = ""


class EvaluatorResult(BaseModel):
    status: str = "success"
    exit_code: int = 0
    metric_value: Optional[float] = None
    target_met: bool = False
    extraction_method: str = "grep"
    peak_output: str = ""


class StrategistTask(BaseModel):
    role: str = "strategist"
    task: str = "Analyze all branch failures and propose new strategies"
    all_results_path: str = ""
    program_md_path: str = ""
    branches_path: str = ""
    iterations_dir: str = ""


class StrategistResult(BaseModel):
    status: str = "success"
    analysis: Optional[Dict[str, Any]] = None
    proposals: List[Dict[str, Any]] = Field(default_factory=list)
    revised_program_md: Optional[str] = None


# ---------------------------------------------------------------------------
# Results TSV Row
# ---------------------------------------------------------------------------


class ResultRow(BaseModel):
    """Single row in results.tsv."""

    timestamp: str
    commit: str
    phase: str
    decision: str
    prev_commits: str = "-"
    hypotheses: str = "-"
    metric_value: str = "-"
    description: str = ""

    def to_tsv(self) -> str:
        return "\t".join(
            [
                self.timestamp,
                self.commit,
                self.phase,
                self.decision,
                self.prev_commits,
                self.hypotheses,
                self.metric_value,
                self.description,
            ]
        )

    @classmethod
    def from_tsv(cls, line: str) -> "ResultRow":
        parts = line.strip().split("\t")
        # Pad with defaults if fewer columns
        while len(parts) < 8:
            parts.append("-")
        return cls(
            timestamp=parts[0],
            commit=parts[1],
            phase=parts[2],
            decision=parts[3],
            prev_commits=parts[4],
            hypotheses=parts[5],
            metric_value=parts[6],
            description=parts[7],
        )


# ---------------------------------------------------------------------------
# Branch Registry Row
# ---------------------------------------------------------------------------


class BranchRow(BaseModel):
    """Single row in branches.tsv."""

    branch_id: str
    parent_checkpoint: str = "-"
    status: str = "active"
    priority: float = 1.0
    iterations: int = 0
    best_metric: str = "-"
    stall_count: int = 0
    created_at: str = ""

    def to_tsv(self) -> str:
        return "\t".join(
            [
                self.branch_id,
                self.parent_checkpoint,
                self.status,
                str(self.priority),
                str(self.iterations),
                self.best_metric,
                str(self.stall_count),
                self.created_at,
            ]
        )

    @classmethod
    def from_tsv(cls, line: str) -> "BranchRow":
        parts = line.strip().split("\t")
        while len(parts) < 8:
            parts.append("-")
        priority = 1.0
        iterations = 0
        stall_count = 0
        try:
            priority = float(parts[3])
        except (ValueError, IndexError):
            pass
        try:
            iterations = int(parts[4])
        except (ValueError, IndexError):
            pass
        try:
            stall_count = int(parts[6])
        except (ValueError, IndexError):
            pass
        return cls(
            branch_id=parts[0],
            parent_checkpoint=parts[1],
            status=parts[2],
            priority=priority,
            iterations=iterations,
            best_metric=parts[5],
            stall_count=stall_count,
            created_at=parts[7],
        )


# ---------------------------------------------------------------------------
# TSV Headers
# ---------------------------------------------------------------------------

RESULTS_TSV_HEADER = (
    "timestamp\tcommit\tphase\tdecision\tprev_commits\thypotheses\tmetric_value\tdescription"
)
BRANCHES_TSV_HEADER = (
    "branch_id\tparent_checkpoint\tstatus\tpriority\t"
    "iterations\tbest_metric\tstall_count\tcreated_at"
)
ALL_RESULTS_TSV_HEADER = "branch_id\t" + RESULTS_TSV_HEADER


# ---------------------------------------------------------------------------
# Target Expression Evaluator
# ---------------------------------------------------------------------------


def _eval_target(value: float, expr: str) -> bool:
    """Evaluate a target expression like '< 200', '>= 0.95', '== 0'."""
    expr = expr.strip()
    if not expr:
        return False

    ops = ["<=", ">=", "!=", "==", "<", ">"]
    for op in ops:
        if op in expr:
            parts = expr.split(op, 1)
            if len(parts) != 2:
                continue
            try:
                threshold = float(parts[1].strip())
            except ValueError:
                return False
            if op == "<":
                return value < threshold
            elif op == ">":
                return value > threshold
            elif op == "<=":
                return value <= threshold
            elif op == ">=":
                return value >= threshold
            elif op == "==":
                return value == threshold
            elif op == "!=":
                return value != threshold
    return False


# ---------------------------------------------------------------------------
# JSON Output Parser (for teammate outbox)
# ---------------------------------------------------------------------------


def parse_teammate_output(content: str) -> Dict[str, Any]:
    """Parse teammate output with multi-strategy fallback.

    1. Try parsing entire content as raw JSON
    2. Find ```json blocks, use LAST one
    3. Look for status: error pattern
    4. Regex extraction of key fields
    5. Raise on complete failure
    """
    import re

    # Step 1: Try parsing entire content as JSON
    content_stripped = content.strip()
    if content_stripped.startswith("{"):
        try:
            return json.loads(content_stripped)
        except json.JSONDecodeError:
            pass

    # Step 2: Find all ```json blocks
    json_blocks = re.findall(r"```json\s*(.*?)\s*```", content, re.DOTALL)
    if json_blocks:
        last_block = json_blocks[-1]
        try:
            return json.loads(last_block)
        except json.JSONDecodeError:
            pass

    # Step 3: Look for status: error pattern
    if "status: error" in content.lower():
        return {
            "status": "error",
            "error_type": "parse_failed",
            "raw_output": content,
        }

    # Step 4: Regex extraction
    status_match = re.search(r'"status"\s*:\s*"(\w+)"', content)
    if status_match:
        return {
            "status": status_match.group(1),
            "raw_output": content,
            "extraction_method": "regex_fallback",
        }

    raise ValueError("Cannot parse teammate output: no JSON or status found")


# ---------------------------------------------------------------------------
# Planner Output Schema (structured decision record)
# ---------------------------------------------------------------------------


class PlannerSummaryStatus(str, Enum):
    """Valid status values for Planner's structured summary block."""
    OBSERVATION = "observation"
    DIAGNOSIS_COMPLETE = "diagnosis_complete"
    FIX_PROPOSED = "fix_proposed"
    GATHER_COMPLETE = "gather_complete"
    GATHER_MORE = "gather_more"
    ANALYSIS_COMPLETE = "analysis_complete"
    CONCLUSION_READY = "conclusion_ready"
    REINVESTIGATE = "reinvestigate"


class PlannerSummary(BaseModel):
    """Schema for Planner's structured summary block (after --- separator)."""
    status: PlannerSummaryStatus
    files: List[str] = Field(default_factory=list)
    reason: str = ""


def parse_planner_summary(text: str) -> tuple[Optional[PlannerSummary], str]:
    """Parse the structured summary block from Planner output.

    Looks for a YAML block after '---' separator at the end of the text.
    Returns (summary, error_msg). If parsing succeeds, error_msg is empty.
    If no summary block found, returns (None, "no summary block found").
    """
    # Find the last '---' separator — try multiple patterns
    parts = text.rsplit("\n---\n", 1)
    if len(parts) < 2:
        parts = text.rsplit("\n---", 1)
    if len(parts) < 2:
        parts = text.split("---\n", 1)  # handle --- at start of text
    if len(parts) < 2:
        return None, "No '---' summary block found in output"

    yaml_block = parts[1].strip()
    if not yaml_block:
        return None, "Summary block is empty"

    # Parse YAML-style key: value pairs
    try:
        import yaml
        data = yaml.safe_load(yaml_block)
    except Exception as e:
        return None, f"YAML parse error: {e}"

    if not isinstance(data, dict):
        return None, f"Summary block is not a dict (got {type(data).__name__})"

    # Validate with Pydantic
    try:
        summary = PlannerSummary.model_validate(data)
        return summary, ""
    except Exception as e:
        return None, f"Schema validation failed: {e}"
