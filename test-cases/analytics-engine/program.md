# autoresearch-x: Analytics Engine Optimization

## Target
Reduce total pipeline p99 execution time below 1000ms for 1M events

## Mode
optimize

## Checklist
- [ ] Establish baseline
- [ ] Profile hot paths
- [ ] Optimize critical path
- [ ] Verify target met

## Scope
- modify: test-cases/analytics-engine/analytics.py
- readonly: test-cases/analytics-engine/bench.py

## Evaluation
- command: uv run python test-cases/analytics-engine/bench.py --json --iterations 1
- metric: pipeline_total_ms_p99
- target: < 1000

## Constraints
- max_iterations: 30
- timeout: 60min

## Context
The pipeline at test-cases/analytics-engine/analytics.py processes 1M events through 4 stages:
ingest → enrich → aggregate → anomaly detection

Current baseline: ~7200ms

Bottleneck distribution (no single dominant fix):
- aggregate: ~3600ms (50%) — sorting full value lists for percentiles, dict-of-dicts overhead
- ingest: ~2600ms (36%) — JSON parsing, schema validation, timestamp parsing per event
- enrich: ~950ms (13%) — dimension table lookups
- detect: ~1.5ms (0.02%) — negligible

Each bottleneck has multiple valid optimization approaches:
- Ingest: batch JSON parsing, lazy validation, cached timestamp parsing, orjson/ujson
- Enrich: pre-loaded dimensions, indexed lookups, or skip enrichment for non-purchase events
- Aggregate: partial sorting for percentiles (heapselect), numpy arrays, or streaming quantiles
- Pipeline: early filtering, parallel stages, or generator-based streaming

Benchmark outputs JSON with pipeline_total_ms_p99 metric.
Target is < 1000ms (86% reduction from baseline).
