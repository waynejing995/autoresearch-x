# autoresearch-x Report: <run name>

**Branch:** autoresearch-x/<tag>
**Started:** <ISO timestamp from `date --iso-8601=seconds`>
**Last updated:** <ISO timestamp from `date --iso-8601=seconds`>
**Target:** <test command> passes with exit code 0
**Status:** in_progress | completed | failed

---

## Failure Description

| Field | Value |
|---|---|
| **Failing test / command** | `<command>` |
| **Error message** | `<exact error>` |
| **First seen** | <date or commit> |
| **Reproducible?** | Yes / Flaky / No |
| **Affected scope** | <files / modules> |

---

## Hypothesis Matrix

| ID | Hypothesis | Evidence For | Evidence Against | Status |
|---|---|---|---|---|
| H1 | <hypothesis> | <commits> | <commits> | ++ / -- / ? |
| H2 | <hypothesis> | <commits> | <commits> | ++ / -- / ? |
| H3 | <hypothesis> | <commits> | <commits> | ++ / -- / ? |

> `++` = confirmed, `--` = eliminated, `?` = unresolved

---

## Root Cause

**Confirmed hypothesis:** H<N> — <one sentence>

**Evidence chain:**
- GATHER <hash>: <what was observed>
- DIAGNOSE <hash>: <what it proved>
- FIX <hash>: <what was changed and why it works>

**Fix:** `<file>:<line>` — <description of the fix>

---

## Target Status

| Check | Target | Met? |
|---|---|---|
| Test passes | exit code 0 | ✓ / ✗ |
| No regressions | full suite green | ✓ / ✗ |
| Root cause identified | confirmed hypothesis | ✓ / ✗ |

---

## Conclusion

> **Added at run completion. The completion-check hook will block stopping without this section.**

**Outcome:** Target <met / not met>. Root cause <identified / not identified>.

**Statistics:** <N> iterations total — <K> kept, <D> discarded, <C> crashed. Phases: <O> observe, <D> diagnose, <F> fix. Duration: <start> → <end> (<Xh Xmin>).

**Root cause summary:** <one paragraph — what broke, why, and how the fix works>

**Fix applied:** `<file>:<line>` — <description>. Commit: <hash>.

**Hypotheses explored:**
- H<N> (confirmed): <summary>
- H<N> (eliminated): <summary and what disproved it>

**Recommendations:**
- <regression prevention, test coverage, monitoring suggestions>

---

## Iteration Log

| # | Timestamp | Commit | Phase | Status | Hypotheses | Description |
|---|---|---|---|---|---|---|
| 0 | <ts> | <hash> | observe | keep | H1,H2,H3 | added logging for all 3 |
| 1 | <ts> | <hash> | diagnose | keep | H1:++,H2:-- | H2 eliminated |
| N | <ts> | <hash> | fix | keep | H1:confirmed | patched root cause — test passes |

> Timestamps from `date --iso-8601=seconds` at time of iteration file creation.
