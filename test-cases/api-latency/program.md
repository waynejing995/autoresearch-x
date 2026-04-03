# autoresearch-x: API Latency Optimization

## Target
Reduce overall p99 API latency below 50ms

## Mode
optimize

## Checklist
- [ ] Establish baseline
- [ ] Profile hot paths
- [ ] Optimize critical path
- [ ] Verify target met

## Scope
- modify: test-cases/api-latency/server.py
- readonly: test-cases/api-latency/bench.py

## Evaluation
- command: uv run python test-cases/api-latency/bench.py --json
- metric: p99_latency_ms
- target: < 50

## Constraints
- max_iterations: 20
- timeout: 30min

## Context
The server at test-cases/api-latency/server.py is a FastAPI app with deliberate performance issues.
Start the server with: uvicorn test-cases.api-latency.server:app --host 127.0.0.1 --port 8000
Benchmark with: uv run python test-cases/api-latency/bench.py --json

## Reviewed: PASS
