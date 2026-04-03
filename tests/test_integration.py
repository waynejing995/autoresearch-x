"""Integration test: full coordinator loop with mocked teammates.

Simulates a real performance tuning run by:
1. Creating a real StateManager with run directory
2. Mocking teammate spawn/wait/output to return controlled results
3. Running the coordinator loop for several iterations
4. Verifying results.tsv, state.json, and keep/discard logic
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autoresearch_x.branch_manager import BranchManager
from autoresearch_x.models import (
    RunMode,
    TeammateStatus,
)
from autoresearch_x.state_manager import StateManager
from autoresearch_x.teammate_manager import TeammateManager


@pytest.fixture
def run_setup(tmp_path: Path):
    proj = tmp_path / "project"
    proj.mkdir()
    (proj / ".git").mkdir()
    (proj / "program.md").write_text("# test program\n")

    run_dir = proj / ".autoresearch-x" / "test-integration"
    mgr = StateManager(run_dir)
    state = mgr.init_run(
        tag="test-integration",
        mode=RunMode.OPTIMIZE,
        target="latency < 200",
        program_md_path=str(proj / "program.md"),
        eval_command="python bench.py",
        metric_name="p99_latency_ms",
        target_expr="< 200",
        scope=["server.py"],
        readonly=["bench.py"],
        max_iterations=5,
    )
    return proj, mgr, state


def _mock_teammate_output(outbox_dir: Path, role: str, data: dict):
    import json

    outbox_dir.mkdir(exist_ok=True)
    (outbox_dir / f"{role}.json").write_text(f"```json\n{json.dumps(data)}\n```")


def _make_mock_tm(state_mgr: StateManager):
    tm = MagicMock(spec=TeammateManager)
    tm.spawn.return_value = "mock-agent"
    tm.wait_for_idle.return_value = TeammateStatus.IDLE
    tm.get_output.return_value = ("", "")
    return tm


def test_single_iteration_keep(run_setup):
    proj, state_mgr, state = run_setup

    tm = _make_mock_tm(state_mgr)

    metrics = [350.0, 280.0, 250.0]

    def write_outbox(role: str, data: dict):
        state_mgr.outbox_dir.mkdir(exist_ok=True)
        (state_mgr.outbox_dir / f"{role}.json").write_text(f"```json\n{json.dumps(data)}\n```")

    from autoresearch_x.coordinator import (
        _decide,
        _git_commit_or_revert,
        _record,
        _run_evaluator,
        _run_planner,
        _run_worker,
    )
    from autoresearch_x.models import Decision

    write_outbox(
        "planner",
        {
            "status": "success",
            "plan": {
                "change_description": "Optimization attempt 1",
                "files_to_modify": ["server.py"],
            },
        },
    )
    planner = _run_planner(state, state_mgr, tm, proj)
    assert planner is not None
    assert planner.status == "success"

    write_outbox(
        "worker",
        {
            "status": "success",
            "files_modified": ["server.py"],
            "changes_summary": "Applied optimization 1",
        },
    )
    worker = _run_worker(state, state_mgr, tm, planner, proj)
    assert worker is not None
    assert worker.status == "success"

    write_outbox(
        "evaluator",
        {
            "status": "success",
            "exit_code": 0,
            "metric_value": metrics[0],
            "target_met": metrics[0] < 200,
            "extraction_method": "grep",
        },
    )
    evaluator = _run_evaluator(state, state_mgr, tm, proj)
    assert evaluator is not None
    assert evaluator.metric_value == 350.0

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="abc1234\n")
        commit = _git_commit_or_revert(state, worker, proj)

    decision = _decide(state, evaluator)
    assert decision == Decision.KEEP

    _record(state, state_mgr, commit, decision, evaluator, planner, "main")

    results = state_mgr.read_branch_results("main")
    assert len(results) == 1
    assert results[0].decision == "keep"
    assert results[0].metric_value == "350.0"


def test_is_better():
    from autoresearch_x.coordinator import _is_better

    assert _is_better(150.0, 200.0, "< 200") is True
    assert _is_better(250.0, 200.0, "< 200") is False
    assert _is_better(0.96, 0.95, ">= 0.95") is True
    assert _is_better(0.90, 0.95, ">= 0.95") is False


def test_branch_priority_computation(run_setup):
    proj, state_mgr, state = run_setup
    branch_mgr = BranchManager(state_mgr, str(proj))

    state.best_metric = 300.0
    branch = state_mgr.read_branches()[0]
    branch.best_metric = "250"
    branch.iterations = 3
    branch.stall_count = 0
    state_mgr.update_branch(branch)

    priority = branch_mgr.compute_priority(branch, state)
    assert 0.0 <= priority <= 1.0


def test_globally_stalled_detection(run_setup):
    proj, state_mgr, state = run_setup
    branch_mgr = BranchManager(state_mgr, str(proj))

    assert branch_mgr.is_globally_stalled() is False

    branch = state_mgr.read_branches()[0]
    branch.status = "stalled"
    state_mgr.update_branch(branch)

    assert branch_mgr.is_globally_stalled() is True
