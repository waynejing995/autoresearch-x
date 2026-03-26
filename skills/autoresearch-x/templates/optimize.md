# autoresearch-x: <run name>

## TIME <timestamp from tool or bash>

## Target
<What metric to optimize? e.g., "Reduce p99 latency below 200ms on /api/users endpoint">

## Mode
optimize

## Scope
- modify: <path/to/main/file.py>
- modify: <path/to/config.py>
- readonly: <path/to/tests.py>

## Checklist
- [ ] Establish baseline metric
- [ ] Profile/tracing to identify primary bottleneck
- [ ] Try optimization approach A: <describe>
- [ ] Try optimization approach B: <describe>
- [ ] Try optimization approach C: <describe>
- [ ] Verify no regressions in test suite

## Evaluation
- command: `<your benchmark command, e.g., uv run bench.py --json>`
- metric: <metric name, e.g., p99_latency_ms>
- target: < <target value>
- extract: `<optional extraction command, e.g., jq '.p99' result.json>`

## Constraints
- max_iterations: 50
- timeout: 2h
- time_per_iteration: 5 minutes
- <other constraints: no new deps, backward compatible, etc.>

## Context
<Background: why this matters, what's been tried, domain knowledge, related docs>
