# Reference: Debug Mode

## Progressive Scope

What kind of changes are allowed escalates by phase:
- **OBSERVE:** add logging, print statements, run diagnostics. No logic changes.
- **DIAGNOSE:** add assertions, modify test inputs, create repro scripts. No logic changes.
- **FIX:** modify actual logic, refactor code. Full access to scoped files.

**Parallel observe, serial fix** — you CAN add logging for multiple hypotheses in one commit (logging doesn't conflict). You CANNOT try multiple fixes at once (fixes conflict). Diagnose evaluates all hypotheses against collected evidence simultaneously.

## When a Fix Fails — Invalidation Logic

A discarded fix does NOT automatically discard the diagnosis. Ask: "Did the fix fail on its own merits, or does the failure contradict the diagnosis?"

| Fix fails because... | Diagnosis status | Next step |
|---|---|---|
| Bad implementation, right idea | Stays `keep` | Try a different fix |
| Reveals diagnosis was wrong | Add new row: `diagnose discard` that supersedes the old one | Fall back to observe |
| Unclear | Keep diagnosis tentatively | Fall back to observe, gather more data |

results.tsv is append-only — never modify past rows. When a diagnosis is invalidated, add a **new** `diagnose discard` row that references the failed fix as evidence:

```
e5f  diagnose  keep     a1b,b2c   H1:confirmed     cert rotation is root cause
f6g  fix       discard  e5f       H1:confirmed     cert fix applied — still fails
g7h  diagnose  discard  f6g       H1:disproved     fix failure proves H1 wrong, reopen
h8i  observe   keep     -         H1:--,H2:?,H3:?  back to observe with new hypotheses
```

## Evidence Chains: Toulmin Structure

Each diagnose iteration note in `.autoresearch-x/<tag>/iterations/<commit>.md` follows:

```markdown
## Analysis: <title>

## TIME <timestamp from tool or bash>

### Grounds (evidence from OBSERVE)
- observe@<commit>: <what was observed>

### Warrant (reasoning connecting evidence to conclusion)
<How the evidence supports this conclusion>

### Qualifier (confidence)
HIGH | MEDIUM | LOW | NONE

### Rebuttal (when does this NOT hold?)
<Conditions under which this analysis would be wrong>

### Verdict
KEEP | DISCARD
```

**Chain validation rules:**
1. DIAGNOSE must cite OBSERVE commits. No evidence = discard immediately.
2. FIX must cite kept DIAGNOSE entries. Cannot cite discarded diagnosis.
3. LOW confidence = must observe more before fixing.
4. Rebuttals are mandatory. If you cannot state when it wouldn't hold, the analysis isn't rigorous.

## Evidence Chains: ACH Hypothesis Matrix

Track multiple hypotheses simultaneously, test one at a time, advance by **elimination not confirmation**. Maintained in `.autoresearch-x/<tag>/matrix.md`:

```markdown
| Evidence (commit)              | H1: cert rotation | H2: rate limit | H3: config reload |
|--------------------------------|:-----------------:|:--------------:|:-----------------:|
| 403 spikes 3-5min post deploy  | ++                | +              | +                 |
| Rate limit counter stays at 0  | n/a               | --             | n/a               |
| Cert has 5min validity gap     | ++                | n/a            | n/a               |
```

Legend: `++` strongly consistent, `+` weakly consistent, `--` inconsistent (disproves), `n/a` not relevant.

A hypothesis is **eliminated** when any evidence is `--`. The survivor with strongest `++` evidence is the leading candidate.

**Selection order** when deciding which hypothesis to test next:
1. Cheapest to disprove — one quick check eliminates it
2. Most diagnostic — one test distinguishes between multiple hypotheses
3. Least invasive — read-only check before code changes
