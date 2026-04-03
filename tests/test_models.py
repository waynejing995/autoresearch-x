"""Tests for Pydantic models."""

from pathlib import Path

import pytest

from autoresearch_x.models import (
    BranchRow,
    ResultRow,
    RunMode,
    RunState,
    _eval_target,
    parse_teammate_output,
)


class TestEvalTarget:
    def test_less_than_met(self):
        assert _eval_target(150.0, "< 200") is True

    def test_less_than_not_met(self):
        assert _eval_target(250.0, "< 200") is False

    def test_greater_than_met(self):
        assert _eval_target(0.96, ">= 0.95") is True

    def test_greater_than_not_met(self):
        assert _eval_target(0.90, ">= 0.95") is False

    def test_equals_met(self):
        assert _eval_target(0.0, "== 0") is True

    def test_empty_expr(self):
        assert _eval_target(100.0, "") is False

    def test_invalid_threshold(self):
        assert _eval_target(100.0, "< abc") is False


class TestParseTeammateOutput:
    def test_json_block(self):
        content = 'Some reasoning\n\n```json\n{"status": "success", "value": 42}\n```'
        result = parse_teammate_output(content)
        assert result["status"] == "success"
        assert result["value"] == 42

    def test_last_json_block_used(self):
        content = '```json\n{"status": "first"}\n```\n\n```json\n{"status": "second"}\n```'
        result = parse_teammate_output(content)
        assert result["status"] == "second"

    def test_status_error_fallback(self):
        content = "Something went wrong\nstatus: error\nDetails: timeout"
        result = parse_teammate_output(content)
        assert result["status"] == "error"
        assert result["error_type"] == "parse_failed"

    def test_regex_fallback(self):
        content = '{"status": "success", "metric_value": 123}'
        result = parse_teammate_output(content)
        assert result["status"] == "success"

    def test_complete_failure(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_teammate_output("just plain text with no json")


class TestResultRow:
    def test_to_tsv(self):
        row = ResultRow(
            timestamp="2026-04-01T10:00",
            commit="a1b2c3d",
            phase="iterate",
            decision="keep",
            metric_value="245",
            description="added caching",
        )
        tsv = row.to_tsv()
        parts = tsv.split("\t")
        assert len(parts) == 8
        assert parts[2] == "iterate"
        assert parts[3] == "keep"

    def test_from_tsv(self):
        line = "2026-04-01T10:00\ta1b2c3d\titerate\tkeep\t-\t-\t245\tadded caching"
        row = ResultRow.from_tsv(line)
        assert row.commit == "a1b2c3d"
        assert row.decision == "keep"
        assert row.metric_value == "245"

    def test_from_tsv_short_line(self):
        line = "2026-04-01T10:00\ta1b\tbaseline\tkeep"
        row = ResultRow.from_tsv(line)
        assert row.prev_commits == "-"
        assert row.description == "-"


class TestBranchRow:
    def test_to_tsv(self):
        row = BranchRow(branch_id="main", status="active", priority=0.8)
        tsv = row.to_tsv()
        parts = tsv.split("\t")
        assert parts[0] == "main"
        assert parts[2] == "active"

    def test_from_tsv(self):
        line = "main\t-\tactive\t0.8\t5\t245\t0\t2026-04-01T10:00:00"
        row = BranchRow.from_tsv(line)
        assert row.branch_id == "main"
        assert row.priority == 0.8
        assert row.iterations == 5


class TestRunState:
    def test_valid_state(self):
        state = RunState(
            tag="test-run",
            mode=RunMode.OPTIMIZE,
            target="p99 < 200",
        )
        assert state.tag == "test-run"
        assert state.current_branch == "main"

    def test_empty_tag_rejected(self):
        with pytest.raises(ValueError):
            RunState(tag="", mode=RunMode.OPTIMIZE, target="x")

    def test_budget_exhausted_iterations(self):
        state = RunState(
            tag="t",
            mode=RunMode.OPTIMIZE,
            target="x",
            max_iterations=10,
            iteration_count=10,
        )
        assert state.is_budget_exhausted() is True

    def test_budget_not_exhausted(self):
        state = RunState(
            tag="t",
            mode=RunMode.OPTIMIZE,
            target="x",
            max_iterations=10,
            iteration_count=5,
        )
        assert state.is_budget_exhausted() is False

    def test_budget_unlimited(self):
        state = RunState(
            tag="t",
            mode=RunMode.OPTIMIZE,
            target="x",
        )
        assert state.is_budget_exhausted() is False

    def test_target_met(self):
        state = RunState(
            tag="t",
            mode=RunMode.OPTIMIZE,
            target="x",
            target_expr="< 200",
        )
        assert state.is_target_met(150.0) is True
        assert state.is_target_met(250.0) is False
        assert state.is_target_met(None) is False

    def test_state_roundtrip(self, tmp_path: Path):
        state = RunState(
            tag="roundtrip",
            mode=RunMode.OPTIMIZE,
            target="latency < 100",
            target_expr="< 100",
            best_metric=120.0,
            best_commit="abc1234",
        )
        path = tmp_path / "state.json"
        state.to_file(path)
        loaded = RunState.from_file(path)
        assert loaded.tag == "roundtrip"
        assert loaded.best_metric == 120.0
        assert loaded.best_commit == "abc1234"
