# autoresearch-x Report: <run name>

**Branch:** autoresearch-x/<tag>
**Started:** <ISO timestamp from `date --iso-8601=seconds`>
**Last updated:** <ISO timestamp from `date --iso-8601=seconds`>
**Target:** <metric> ≤ <value> (<pct>% reduction from baseline <baseline_value>)
**Status:** in_progress | completed | failed

---

## Benchmark Methodology

### How Each Scenario Is Tested

<Describe the system under test, what "one operation" means, and the test server/environment.>

| Scenario | How it runs | What it measures |
|---|---|---|
| <scenario_1> | <N threads × M ops, command used> | <what this stress-tests> |
| <scenario_2> | <N threads × M ops, command used> | <what this stress-tests> |
| <scenario_N> | <N threads × M ops, command used> | <what this stress-tests> |

### Metrics Explained

| Metric | Definition |
|---|---|
| **mean_ms** | Arithmetic mean of per-operation wall time (`time.perf_counter()` start→end per thread) |
| **p95_ms** | 95th percentile latency — excludes top 5% outliers |
| **errors** | Operations that raised an exception (timeout, connection refused, etc.) |
| **correctness** | Whether every response matched expected value |
| **composite_mean_ms** | `statistics.mean([mean_ms for all scenarios])` — equal-weight average |

### Composite Formula

```python
composite_ms = statistics.mean([s["mean_ms"] for s in all_scenarios])
# Example: (<v1> + <v2> + ... + <vN>) / N = <result>ms
```

---

## Performance Results

| Scenario | Baseline | Optimized | Delta | p95 Base | p95 Opt |
|---|---|---|---|---|---|
| <scenario_1> | Xms | Xms | -X% | Xms | Xms |
| <scenario_2> | Xms | Xms | -X% | Xms | Xms |
| <scenario_N> | Xms | Xms | **-X%** | Xms | Xms |
| **composite** | **X.Xms** | **X.Xms** | **-X%** | — | — |

> All scenarios: all_correct=True, total_errors=0

---

## Target Status

| Check | Target | Baseline | Optimized | Met? |
|---|---|---|---|---|
| Composite mean | ≤ Xms | X.Xms | X.Xms | ✓ / ✗ |
| No packet loss | errors=0 | ✓ | ✓ | ✓ |
| Correct ordering | all_correct=True | ✓ | ✓ | ✓ |

---

## Optimizations Applied

| Commit | Change | Before | After | Delta |
|---|---|---|---|---|
| <hash> | <description> | X.Xms | X.Xms | **-X%** |
| <hash> | <description> | X.Xms | X.Xms | -X% |

---

## Profiling Findings

> Run `cProfile` or equivalent early — before assuming what the bottleneck is.

| Call / Location | Mean time | % of total | Note |
|---|---|---|---|
| `<function>()` | Xms | X% | <interpretation> |
| `<function>()` | Xms | X% | <interpretation> |

**Root cause:** <one sentence describing the actual bottleneck>

---

## Conclusion

> **Added at run completion. The completion-check hook will block stopping without this section.**

**Outcome:** Target <met / not met>. Best metric: <value> (commit <hash>), vs baseline <value> = **<delta>%** improvement.

**Statistics:** <N> iterations total — <K> kept, <D> discarded, <C> crashed. Duration: <start> → <end> (<Xh Xmin>).

**What worked:**
- <optimization 1> — <why it helped>
- <optimization 2> — <why it helped>

**What didn't work:**
- <discarded attempt> — <why it failed>

**Recommendations:**
- <next steps if target not met, or maintenance notes if it was>

---

## Iteration Log

| # | Timestamp | Commit | Status | Metric | Description |
|---|---|---|---|---|---|
| 0 | <ts> | baseline | keep | X.Xms | baseline |
| 1 | <ts> | <hash> | **keep** / discard | X.Xms | <one-line description + why> |
| N | <ts> | <hash> | **keep** / discard | X.Xms | <one-line description + why> |

> Timestamps from `date --iso-8601=seconds` at time of iteration file creation.
