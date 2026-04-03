"""Tests for StateManager."""

from pathlib import Path

import pytest

from autoresearch_x.models import (
    BranchRow,
    ResultRow,
    RunMode,
)
from autoresearch_x.state_manager import StateManager


@pytest.fixture
def state_mgr(tmp_path: Path) -> StateManager:
    run_dir = tmp_path / ".autoresearch-x" / "test-run"
    mgr = StateManager(run_dir)
    mgr.init_run(
        tag="test-run",
        mode=RunMode.OPTIMIZE,
        target="latency < 200",
        program_md_path=str(tmp_path / "program.md"),
        eval_command="python bench.py",
        metric_name="latency_ms",
        target_expr="< 200",
        scope=["src/server.py"],
        readonly=[],
        max_iterations=10,
    )
    return mgr


def test_init_creates_structure(state_mgr: StateManager):
    assert state_mgr.state_path.exists()
    assert state_mgr.results_path.exists()
    assert state_mgr.branches_path.exists()
    assert state_mgr.inbox_dir.exists()
    assert state_mgr.outbox_dir.exists()
    assert (state_mgr.branches_dir / "main").exists()
    assert (state_mgr.branches_dir / "main" / "results.tsv").exists()


def test_state_roundtrip(state_mgr: StateManager):
    state = state_mgr.load_state()
    assert state.tag == "test-run"
    assert state.mode == RunMode.OPTIMIZE
    assert state.max_iterations == 10

    state.iteration_count = 5
    state_mgr.save_state(state)

    loaded = state_mgr.load_state()
    assert loaded.iteration_count == 5


def test_append_result(state_mgr: StateManager):
    row = ResultRow(
        timestamp="2026-04-01T10:00",
        commit="a1b2c3d",
        phase="baseline",
        decision="keep",
        metric_value="312",
        description="baseline",
    )
    state_mgr.append_result(row, "main")

    results = state_mgr.read_branch_results("main")
    assert len(results) == 1
    assert results[0].commit == "a1b2c3d"
    assert results[0].metric_value == "312"


def test_read_branches(state_mgr: StateManager):
    branches = state_mgr.read_branches()
    assert len(branches) == 1
    assert branches[0].branch_id == "main"
    assert branches[0].status == "active"


def test_add_branch(state_mgr: StateManager):
    row = BranchRow(
        branch_id="fork-1",
        parent_checkpoint="cp-001",
        status="suspended",
        priority=1.0,
    )
    state_mgr.add_branch(row)

    branches = state_mgr.read_branches()
    assert len(branches) == 2
    assert any(b.branch_id == "fork-1" for b in branches)
    assert (state_mgr.branches_dir / "fork-1" / "results.tsv").exists()


def test_update_branch(state_mgr: StateManager):
    row = BranchRow(branch_id="main", status="stalled", priority=0.0, stall_count=5)
    state_mgr.update_branch(row)

    branches = state_mgr.read_branches()
    main = [b for b in branches if b.branch_id == "main"][0]
    assert main.status == "stalled"
    assert main.stall_count == 5


def test_get_active_branches(state_mgr: StateManager):
    stalled = BranchRow(branch_id="fork-1", status="stalled")
    state_mgr.add_branch(stalled)

    active = state_mgr.get_active_branches()
    assert len(active) == 2


def test_inbox_outbox(state_mgr: StateManager):
    import json

    state_mgr.write_inbox("planner", {"role": "planner", "iteration": 1})
    inbox = state_mgr.inbox_dir / "planner.json"
    assert inbox.exists()
    data = json.loads(inbox.read_text())
    assert data["role"] == "planner"

    outbox = state_mgr.outbox_dir / "planner.json"
    outbox.write_text(json.dumps({"status": "success"}))
    result = state_mgr.read_outbox("planner")
    assert result is not None
    assert '"success"' in result


def test_iteration_detail(state_mgr: StateManager):
    state_mgr.write_iteration_detail("a1b2c3d", "# Iteration 1\n\nAdded caching", "main")
    detail = state_mgr.read_iteration_detail("a1b2c3d", "main")
    assert detail is not None
    assert "Added caching" in detail
