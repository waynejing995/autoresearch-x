# autoresearch-x Report: <run name>

**Branch:** autoresearch-x/<tag>
**Started:** <ISO timestamp from `date --iso-8601=seconds`>
**Last updated:** <ISO timestamp from `date --iso-8601=seconds`>
**Target:** All checklist items answered with evidence
**Status:** in_progress | completed | failed

---

## Investigation Question

> <One paragraph: what is being investigated, why it matters, what data sources are available>

---

## Checklist

| # | Question | Status | Answer |
|---|---|---|---|
| 1 | <question> | ✓ resolved / ✗ blocked | <one-line answer> |
| 2 | <question> | ✓ resolved / ✗ blocked | <one-line answer> |
| N | <question> | ✓ resolved / ✗ blocked | <one-line answer> |

---

## Key Findings

| Finding | Evidence | Confidence |
|---|---|---|
| <finding> | <GATHER commits cited> | HIGH / MEDIUM / LOW |
| <finding> | <ANALYZE commits cited> | HIGH / MEDIUM / LOW |

---

## Conclusion

**Root cause / Answer:** <one paragraph with citations>

**Evidence chain:**
- GATHER <hash>: <data collected>
- ANALYZE <hash>: <what it proved, Toulmin warrant>
- CONCLUDE <hash>: <final conclusion>

**Rebuttal (when does this NOT hold):** <describe edge cases or limitations>

---

## Target Status

| Check | Met? |
|---|---|
| All checklist items resolved | ✓ / ✗ (<N>/<total> resolved) |
| Every ANALYZE cites GATHER | ✓ / ✗ |
| Conclusion cites ANALYZE | ✓ / ✗ |
| No LOW-confidence unresolved items | ✓ / ✗ |

---

## Iteration Log

| # | Timestamp | Commit | Phase | Status | Description |
|---|---|---|---|---|---|
| 0 | <ts> | <hash> | gather | keep | <what data was collected> |
| 1 | <ts> | <hash> | analyze | keep | <what it showed, H1:++> |
| N | <ts> | <hash> | conclude | keep | <final answer with evidence> |

> Timestamps from `date --iso-8601=seconds` at time of iteration file creation.
