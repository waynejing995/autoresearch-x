# Reference: Investigate Mode

## Completion Criteria

For each checklist item:
1. Has at least one ANALYZE entry with confidence qualifier >= MEDIUM
2. Finding recorded in report.md under the checklist item
3. Finding cites at least one GATHER commit as evidence
4. Unresolvable items marked `blocked` with explanation

## When Conclusions are Invalidated

New evidence can contradict a previous conclusion. Do NOT modify past rows. Add new rows that supersede:

| Conclusion fails because... | Analyze status | Next step |
|---|---|---|
| New GATHER data contradicts it | Add new `analyze discard` row | Re-analyze with new data |
| Conclusion was based on incomplete data | Add new `conclude discard` row | Fall back to gather more |
| Rebuttal condition was triggered | Add new `analyze discard` citing rebuttal | Gather data for alternative hypothesis |

Example:
```
d4e  analyze   keep     a1b,b2c   H1:++    403 correlates with deploy (7/7)
e5f  conclude  keep     d4e       -        root cause: deploy triggers auth gap
f6g  gather    keep     -         -        found 403 spike on Mar 20 WITHOUT a deploy
g7h  analyze   discard  f6g,d4e   H1:--    counter-evidence invalidates H1 correlation
h8i  conclude  discard  g7h       -        previous conclusion invalidated
i9j  analyze   keep     a1b..f6g  H2:++    revised: cron job at same time as deploys
```

## Evidence Chains: Toulmin Structure

Each analyze iteration note in `.autoresearch-x/<tag>/iterations/<commit>.md` follows:

```markdown
## Analysis: <title>

## TIME <timestamp from tool or bash>

### Grounds (evidence from GATHER)
- gather@<commit>: <what was observed>

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
1. ANALYZE must cite GATHER commits. No evidence = discard immediately.
2. CONCLUDE must cite kept ANALYZE entries. Cannot cite discarded analysis.
3. LOW confidence = must gather more before concluding.
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
