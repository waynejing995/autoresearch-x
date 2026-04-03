"""Integration test: full coordinator loop with mocked SDK teammates."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from autoresearch_x.branch_manager import BranchManager
from autoresearch_x.models import RunMode
from autoresearch_x.sdk_teammate import TeammateResult
from autoresearch_x.state_manager import StateManager


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


def _make_sdk_result(json_data: dict, text: str = "") -> TeammateResult:
    result = TeammateResult()
    result.add_text(text)
    result.add_text(f"```json\n{json.dumps(json_data)}\n```")
    return result


def test_single_iteration_keep(run_setup):
    proj, state_mgr, state = run_setup

    from autoresearch_x.coordinator import (
        _decide,
        _git_commit_or_revert,
        _record,
        _run_evaluator,
        _run_planner,
        _run_worker,
    )
    from autoresearch_x.models import Decision

    planner_data = {
        "status": "success",
        "plan": {
            "change_description": "Optimization attempt 1",
            "files_to_modify": ["server.py"],
        },
    }
    with patch(
        "autoresearch_x.coordinator.run_teammate_sync",
        return_value=_make_sdk_result(planner_data),
    ):
        planner = _run_planner(state, state_mgr, proj, max_turns=15, debug_dump=False)
    assert planner is not None
    assert planner.status == "success"

    worker_data = {
        "status": "success",
        "files_modified": ["server.py"],
        "changes_summary": "Applied optimization 1",
    }
    with patch(
        "autoresearch_x.coordinator.run_teammate_sync",
        return_value=_make_sdk_result(worker_data),
    ):
        worker = _run_worker(state, state_mgr, planner, proj, max_turns=15, debug_dump=False)
    assert worker is not None
    assert worker.status == "success"

    eval_data = {
        "status": "success",
        "exit_code": 0,
        "metric_value": 350.0,
        "target_met": False,
        "extraction_method": "grep",
    }
    with patch(
        "autoresearch_x.coordinator.run_teammate_sync",
        return_value=_make_sdk_result(eval_data),
    ):
        evaluator = _run_evaluator(state, state_mgr, proj, max_turns=15, debug_dump=False)
    assert evaluator is not None
    assert evaluator.metric_value == 350.0

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {"returncode": 0, "stdout": "abc1234\n"})()
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
