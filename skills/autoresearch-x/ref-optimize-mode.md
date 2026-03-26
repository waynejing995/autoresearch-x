# Reference: Optimize Mode

## Phases

Optimize mode has two phases:
- **BASELINE:** run eval with no changes, record the starting metric. This is iteration 0.
- **ITERATE:** one change per iteration, measure, keep/discard.

There is no phase escalation (unlike debug mode). Every iteration has full access to scoped files from the start.

## Keep/Discard Decision Rules

| Outcome | Decision | Rationale |
|---|---|---|
| Metric improved | **keep** | Clear win, branch advances |
| Metric equal, code simpler | **keep** | Simplification is value even without metric gain |
| Metric equal, code same complexity | **discard** | No value added |
| Metric worse | **discard** | Regression, revert |
| Metric improved but test suite regresses | **discard** | Correctness trumps performance |
| Eval crashes or times out | **discard** | Broken change, revert and log crash |

**Ties go to discard.** When in doubt, revert and try something else.

## When a Keep is Later Proven Wrong — Invalidation Logic

A kept change can be invalidated if a later iteration reveals it caused a hidden regression. Do NOT modify past rows. Add new rows that supersede:

| Situation | Action |
|---|---|
| Later iteration reveals regression from iter N | Add `iterate discard` row referencing iter N, revert to pre-N state |
| Two kept changes interact badly | Add `iterate discard` for the later one, keep the earlier one |
| Baseline was measured wrong | Re-run baseline, add new `baseline keep` row, note discrepancy |

Example:
```
a1b  baseline  keep     -  -  312  baseline: 312ms
b2c  iterate   keep     -  -  245  connection pooling
c3d  iterate   keep     -  -  189  query caching
d4e  iterate   discard  -  -  210  async handlers — worse
e5f  iterate   discard  -  -  195  found c3d cache causes stale reads, reverting c3d
f6g  iterate   keep     -  -  201  connection pooling only (re-baseline after c3d revert)
```

## Profiling Strategy — MANDATORY Before Iteration

<HARD-GATE>
DO NOT START ITERATING BLINDLY. You MUST profile or trace first to identify the actual bottleneck. Guessing what's slow wastes iterations.
</HARD-GATE>

**Before the first non-baseline iteration**, plant profiling/tracing to find the bottleneck:

1. **Add instrumentation** — insert timing logs, profiling hooks, or tracing calls into the code
   - Python: `cProfile`, `line_profiler`, `time.perf_counter()` around suspect sections
   - JS/TS: `console.time/timeEnd`, `perf_hooks`, Chrome DevTools profiling
   - Systems: `strace`, `perf stat`, `dtrace`, custom timing macros
   - Network: request/response timing, connection pool stats, queue depths
2. **Run with real workload** — use the actual eval command or representative benchmark cases, NOT synthetic toy inputs. The bottleneck under real load is often different from toy benchmarks.
3. **Analyze the profile output** — identify the top 3 hotspots by time/resource consumption
4. **Record findings** — write a profiling iteration (`iter 1: profile`) with the breakdown:
   ```
   Profiling results:
   - 45%: database queries in get_users() — N+1 query pattern
   - 30%: JSON serialization in format_response()
   - 15%: auth middleware token validation
   - 10%: other
   ```
5. **Plan iterations based on profile data** — attack the biggest bottleneck first

**Re-profile after every 5 iterations** or when 3 consecutive discards suggest the bottleneck has shifted. Kept changes can move the bottleneck elsewhere.

**Selection order** for what to try next:
1. **Profile-guided** — target the biggest bottleneck first (highest % of time/resources)
2. **Diminishing returns aware** — if 3 iterations target the same subsystem with <5% gain each, move to a different subsystem
3. **Algorithmic before micro** — try O(n²)→O(n log n) before loop unrolling
4. **Cheapest to test** — quick changes first, large refactors later
5. **Orthogonal** — after 2 discards in the same direction, try a completely different axis

## Iteration Detail Format

Each iteration note in `.autoresearch-x/<tag>/iterations/<commit>.md`:

```markdown
## Optimization: <title>

## TIME <timestamp from tool or bash>

### Hypothesis
<Why this change should improve the metric>

### Change
<What was modified, one sentence>

### Result
- before: <previous best metric>
- after: <new metric>
- delta: <absolute and % change>

### Decision
KEEP | DISCARD

### Reasoning
<Why this decision — metric comparison, side effects, code quality>

### Next Direction
<What to try next based on this result>
```

## Plateau Detection

If **3 consecutive iterations** produce keeps with <2% improvement each:
1. The easy gains are exhausted — switch optimization strategy
2. Profile again to find the new bottleneck
3. Consider: is the target still achievable, or should it be revised?

If **5 consecutive iterations** are all discards:
1. Trigger the Stuck Protocol (see main SKILL.md)
2. Re-profile — the bottleneck may have shifted after earlier keeps
3. Try a fundamentally different approach (different algorithm, architecture, data structure)
