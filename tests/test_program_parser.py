"""Tests for program.md parser."""

from pathlib import Path

import pytest

from autoresearch_x.program_parser import parse_program_md


@pytest.fixture
def sample_program(tmp_path: Path) -> Path:
    content = """# autoresearch-x: API Latency Optimization

## Target
Reduce p99 API latency below 200ms

## Mode
optimize

## Checklist
- [ ] Establish baseline
- [ ] Profile hot paths
- [ ] Optimize critical path

## Scope
- modify: src/server.py
- modify: src/cache.py
- readonly: scripts/bench.py

## Evaluation
- command: python scripts/bench.py --json
- metric: p99_latency_ms
- target: < 200

## Constraints
- max_iterations: 30
- timeout: 1h

## Context
Current p99 is around 400ms.
"""
    path = tmp_path / "program.md"
    path.write_text(content)
    return path


def test_parse_mode(sample_program: Path):
    result = parse_program_md(sample_program)
    assert result["mode"] == "optimize"


def test_parse_target(sample_program: Path):
    result = parse_program_md(sample_program)
    assert result["target_desc"] == "Reduce p99 API latency below 200ms"


def test_parse_scope(sample_program: Path):
    result = parse_program_md(sample_program)
    assert result["scope"] == ["src/server.py", "src/cache.py"]
    assert result["readonly"] == ["scripts/bench.py"]


def test_parse_evaluation(sample_program: Path):
    result = parse_program_md(sample_program)
    assert result["eval_command"] == "python scripts/bench.py --json"
    assert result["metric_name"] == "p99_latency_ms"
    assert result["target"] == "< 200"


def test_parse_constraints(sample_program: Path):
    result = parse_program_md(sample_program)
    assert result["max_iterations"] == 30
    assert result["timeout_minutes"] == 60


def test_parse_debug_mode(tmp_path: Path):
    content = """# Debug Run

## Target
Auth test passes

## Mode
debug

## Evaluation
- command: pytest tests/test_auth.py -x
- metric: exit_code
- target: == 0

## Constraints
- max_iterations: 15
- timeout: 30min
"""
    path = tmp_path / "program.md"
    path.write_text(content)
    result = parse_program_md(path)
    assert result["mode"] == "debug"
    assert result["max_iterations"] == 15
    assert result["timeout_minutes"] == 30


def test_parse_empty(tmp_path: Path):
    path = tmp_path / "program.md"
    path.write_text("")
    result = parse_program_md(path)
    assert result["mode"] == ""
    assert result["scope"] == []
