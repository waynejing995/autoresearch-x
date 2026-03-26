---
name: autoresearch-x
description: >
  Iterate anything. Prove everything. Autonomous iteration engine with
  evidence-chain tracking. Use when: "iterate on X", "optimize X until Y",
  "autoresearch", "auto-research", "run experiment loop", "debug X systematically",
  "investigate X", "analyze X with checklist", "loop until fixed",
  "overnight experiment", "keep trying until it works", or any task requiring
  autonomous iteration with structured tracking. Supports three modes:
  optimize (metric-driven code iteration), debug (phased diagnosis with
  hypothesis tracking), investigate (evidence-based research/analysis).
  Inspired by karpathy/autoresearch — generalized to any domain.
---

# autoresearch-x

*Iterate anything. Prove everything.*

An autonomous iteration engine. Set up a tracked run and iterate autonomously — optimizing code, debugging failures, or investigating questions — until the target is met or the user interrupts.

## When to Use

- Optimizing code against a benchmark metric
- Debugging a failure systematically (not random fix attempts)
- Investigating logs, data, or systems against a checklist
- Running overnight experiments while you sleep

Do NOT use for one-shot tasks, tasks without measurable criteria, or simple edits.

## Invocation

- `/autoresearch-x` — interactive setup (guided questions)
- `/autoresearch-x --template optimize|debug|investigate` — start from a template
- `/autoresearch-x --program path/to/program.md` — use an existing program.md
- `/autoresearch-x resume <tag>` — resume a previous run
- `/autoresearch-x status` — show current run status
- **Natural language** — if the user describes a task (e.g., "optimize the API latency", "debug why auth fails"), infer mode/target/scope from context, draft a program.md, and present it for review. No flags needed.

## Three Modes (summary)

| Mode | Goal | Phases | Key rule |
|---|---|---|---|
| **optimize** | Improve a metric | baseline → iterate | One change per iteration, keep/discard by metric |
| **debug** | Fix a failure | observe → diagnose → fix | Progressive scope, hypothesis matrix |
| **investigate** | Answer questions | gather → analyze → conclude | Evidence chains, Toulmin structure |

BEFORE PROCEEDING: Read the reference files for your selected mode.

- optimize: <reference>MUST READ: ref-optimize-mode.md</reference>
- debug: <reference>MUST READ: ref-debug-mode.md</reference>
- investigate: <reference>MUST READ: ref-investigate-mode.md</reference>

All modes: <reference>MUST READ: ref-tracking.md</reference>

## Setup Phase

Before the loop starts, complete this checklist:

1. **Read reference files** — already loaded via `<reference>` tags above.
2. **Agree on a run tag** — date-based default (e.g., `mar23-api-latency`). If tag exists, append suffix.
3. **Create branch** — `git checkout -b autoresearch-x/<tag>` from current HEAD.
4. **Read/write program.md** — user provides one, selects a template, or use the **Interactive Setup** flow below.

### Interactive Setup (when no program.md provided)

If the user's task description gives enough context, **infer necessary info from context** — draft a complete program.md and skip straight to the Program Review step. Only ask questions (Steps A-F) for sections you can't confidently infer. The goal is to get to iteration fast, not to interrogate the user.

**Track inferred sections:** As you build the draft, maintain a list of which sections were inferred from context vs explicitly provided by the user. For example, if the user said "optimize my API latency" and you inferred the eval command from project files, record `inferred_sections: [Evaluation, Scope, Constraints, Checklist]`. This list is passed to the reviewer for extra scrutiny on inferred content.

If the user provides no context at all (bare `/autoresearch-x`), guide them through this flow:

**Step A: Mode** (AskUserQuestion — 3 choices)
> "What kind of iteration are you doing?"
- **optimize** — improve a measurable metric (latency, accuracy, throughput)
- **debug** — systematically diagnose and fix a failure
- **investigate** — answer questions with evidence chains

**Step B: Target** (free-form)
> "Describe success in one sentence — what does 'done' look like?"
> Example: "Reduce p99 API latency below 200ms" / "Auth test passes reliably" / "Root cause of 403 errors identified with evidence"

**Step C: Scope** (AskUserQuestion + free-form)
Auto-detect candidate files from recent git changes, error stacktraces, or project structure. Present detected files and ask user to confirm, add, or remove. Classify each as `modify` or `readonly`.

**Step D: Evaluation** (free-form, with mode-specific examples)
> "What command measures progress? What metric should I track?"
Show examples based on selected mode:
- optimize: `uv run bench.py --json` → metric: `p99_latency_ms` → target: `< 200`
- debug: `pytest tests/test_auth.py -x` → metric: `pass/fail` → target: `pass`
- investigate: checklist completion → metric: `items_resolved` → target: `all`

**Step E: Constraints** (AskUserQuestion — presets + free-form override)
> "How much budget for this run?"
- **Light** — 10 iterations, 30min timeout
- **Medium** — 30 iterations, 1h timeout
- **Heavy** — 50 iterations, 2h timeout
- **Infinite** -- <HIGHLIGHT>no max iteration, no timeout, no stop!!!</HIGHLIGHT>
- User can override any value after selecting preset.

**Step F: Context** (free-form, optional — can skip)
> "Any background I should know? What's been tried before?"
If user says "skip" or "none", leave `## Context` empty.

**Step F.1: Program Review** (automated — no user interaction)

Dispatch the reviewer subagent to validate the draft program.md:

```
Agent(
  subagent_type="autoresearch-x:reviewer",
  description="review draft program",
  prompt="
    Review this draft program.md for an autoresearch-x run.

    ## Draft Program
    <full program.md content assembled from Steps A-F>

    ## Mode
    <selected mode>

    ## Project Root
    <current working directory>

    ## Inferred Sections
    <list of section names that were inferred vs user-provided>

    Follow your review protocol. Return structured review.
  "
)
```

**Process the review results:**

- **Status: Approved** — proceed directly to Step G.
- **Status: Issues Found** — process each finding:
  - **BLOCK items:** Ask the user a targeted question for each (one at a time via AskUserQuestion). Incorporate their answer into the draft. If the answer changes the mode, re-dispatch the reviewer.
  - **AUTO-FIX items:** Apply the suggested fix to the draft silently. Note auto-fixes to show in Step G (e.g., "Auto-filled: pass/fail criteria set to exit code 0").
  - **Recommendations:** Collect to show as notes in Step G.

After processing, proceed to Step G with the polished draft.

**Skip conditions — do NOT dispatch the reviewer when:**
- `--program path/to/program.md` is used and the program contains `## Reviewed: PASS` (previously reviewed)
- `resume <tag>` is used (resuming an existing run)

When `--program` is used without `## Reviewed: PASS`, the reviewer DOES run to validate the user-supplied program. Set `inferred_sections: []` (none inferred, all user-provided).

**Step G: Review & Approve** (AskUserQuestion — approve / edit section)
Show the polished program.md to the user. If there were auto-fixes or recommendations from the reviewer, show them:
> "Here's your program.md. Ready to go?"
>
> If auto-fixes were applied: "Note: I auto-filled [section] with [value] based on project context."
> If recommendations exist: "Reviewer notes: [recommendation text]"
- **Approve** — write file (append `## Reviewed: PASS` marker), continue setup
- **Edit a section** — user picks which section to revise, re-ask that step. If the edit changes Scope, Evaluation, or Target, re-dispatch Step F.1 before re-showing Step G. For cosmetic edits (Context, Constraints presets), skip re-review.

Auto-generate the `## Checklist` based on mode and answers:
- **optimize**: baseline → profile → 3 approach slots (named from context if available)
- **debug**: observe (add logging) → diagnose (test hypotheses) → fix (apply solution)
- **investigate**: one checklist item per question/topic from the target
5. **Parse checklist** — extract items from program.md, initialize tracking.
6. **Create `.autoresearch-x/<tag>/`** — results.tsv (header only), report.md (skeleton), iterations/ directory.
7. **Add to .gitignore** — append `.autoresearch-x/` to project root `.gitignore` if not present. Create `.autoresearch-x/.gitignore` containing `!*`.
8. **Activate guardrail hooks** — run `bash ${CLAUDE_PLUGIN_ROOT}/hooks/run-control.sh activate <tag>` to enable iteration discipline hooks. This creates `.autoresearch-x/.active` which activates scope-guard, iteration-gate, eval-bypass-detector, and completion-check hooks.
9. **Verify prerequisites** — eval command runs, scope files exist, dependencies available.
10. **Establish baseline** — first run with no changes. Record baseline metric.
11. **Confirm with user** — show setup summary, then go autonomous.

## program.md Structure

Required sections marked with *.

```markdown
# autoresearch-x: <run name>

## Target *
<One specific, measurable sentence.>

## Mode *
optimize | debug | investigate

## Checklist *
- [ ] Item 1
- [ ] Item 2

## Scope
- modify: path/to/file.py
- readonly: path/to/other.py

## Evaluation
- command: `uv run bench.py --json`
- metric: val_bpb
- target: < 0.95

## Constraints
- max_iterations: 50
- timeout: 2h

## Context
<Background, what's been tried, domain knowledge>

## Reviewed: PASS
<Appended automatically by setup flow on approval — do not add manually>
```

---

# ★ THE ITERATION LOOP ★

This is the core of autoresearch-x. Everything above is setup. **This section governs every iteration.**

<HARD-GATE>
EACH ITERATION = EXACTLY ONE EXPERIMENTAL IDEA

- ONE optimization (e.g., add TCP_NODELAY), OR
- ONE algorithm change (e.g., replace bytes concat with bytearray), OR
- ONE parameter tuning (e.g., increase buffer size to 256KB)
- If your change description needs "and" or "also", split into separate iterations
- If you think "while I'm here, I'll also..." — STOP. That is the NEXT iteration.

In debug mode OBSERVE phase: you MAY batch logging for multiple hypotheses in
one commit (logging does not conflict). But you still cannot batch logic changes.

WHY: Multiple simultaneous changes make it impossible to attribute improvement
or regression to any single change. Science requires controlling variables.
</HARD-GATE>

<HARD-GATE>
MAIN AGENT MUST DISPATCH — NEVER DO THE WORK DIRECTLY

To modify code → dispatch Worker subagent (subagent_type: "autoresearch-x:worker")
To run eval → dispatch Evaluator subagent (subagent_type: "autoresearch-x:evaluator")

Main agent ONLY: orchestrate, review diffs, decide keep/discard, git ops, tracking.

If you catch yourself opening a file to edit: STOP. Write a Worker dispatch instead.
If you catch yourself running the eval command: STOP. Write an Evaluator dispatch instead.

WHY: The agent that writes the fix must not judge if it worked.
Separating them prevents confirmation bias and rationalization.
</HARD-GATE>

## Pre-Iteration Self-Check

Before EVERY iteration, verify:

- [ ] Previous iteration fully recorded? (results.tsv row + iterations/ file)
- [ ] About to try EXACTLY ONE change? (not two, not three)
- [ ] Will dispatch to Worker? (not write code myself)
- [ ] Will dispatch to Evaluator? (not run eval myself)
- [ ] Budget remaining? (show: `[iter N/max | N remaining | best: X | target: Y]`), if no remaining budget, abort!!!!
- [ ] Total time remaining? (read program.md for start time & total timeout, show `[start: X | remaining: Y]`), if no remaining budget, abort!!!!

## The 9-Step Protocol

REPEAT until target met or budget exhausted or timeout:

### Step 1: REVIEW & PLAN

**First, review previous results** before planning:

1. Read `results.tsv` — scan all rows for patterns (what worked, what didn't, streaks)
2. Read the last 2-3 `iterations/<commit>.md` files for detailed observations
3. Check: any "keep" results to build on? Any "discard" patterns to avoid?
4. Check: stuck? (5+ consecutive discards → trigger Stuck Protocol)

**Then state ONE specific change to try**, informed by what you just reviewed.

> "Iterations 2-4 all tried CPU-side optimizations with no gain. The eval output shows I/O wait is 80%. Try adding TCP_NODELAY to reduce small-frame latency."

For debug mode, also state the phase (observe/diagnose/fix), target hypothesis, and which evidence supports this direction.

### Step 2: DISPATCH WORKER

```
Agent(subagent_type="autoresearch-x:worker", prompt="...", description="iter N: ...")
```

Include: program.md content, ONE instruction, scope, phase, previous iteration descriptions (NO metrics).

Worker reports: files changed, lines modified, observations.

### Step 3: REVIEW DIFF

Verify:
- Only scoped files modified
- Only ONE idea implemented (not two smuggled in)
- Phase rules respected (debug: no logic in OBSERVE/DIAGNOSE)

Violations → discard with description "out-of-scope change rejected."

### Step 4: COMMIT

```bash
git add <scoped files>
git commit -m "iter N: <one-sentence description>"
```

Record the short commit hash (7 chars).

### Step 5: DISPATCH EVALUATOR

```
Agent(subagent_type="autoresearch-x:evaluator", prompt="...", description="eval iter N")
```

Include: eval command, metric name, target comparison, extraction command, timeout.

Evaluator reports: metric_value, target_met, extraction_method, eval_duration, peak_output.

### Step 6: DECIDE

- **keep:** metric improved, or metric equal with simpler code
- **discard:** metric same or worse without simplification benefit
- Debug mode: keep = test passes or useful evidence gathered

### Step 7: ACT ON DECISION

- **keep:** update "current best" metric. Branch advances.
- **discard:** `git checkout <prev_commit> -- <scoped files>` then commit the revert.

### Step 8: RECORD

retrieve current time via timetool or bash `date`!!!

Append one row to `.autoresearch-x/<tag>/results.tsv`. All columns required. Use `-` for N/A.

### Step 9: WRITE DETAIL

Create `.autoresearch-x/<tag>/iterations/<commit>.md`. Update report.md.

<HARD-GATE>
DO NOT START THE NEXT ITERATION until ALL of these are done:

1. Change committed or reverted (step 4 or 7)
2. Row appended to results.tsv (step 8)
3. iterations/<commit>.md written (step 9) with retrieved current time

These three artifacts are PROOF that an iteration happened.
Without them, the iteration did not happen. Proceed to step 1 ONLY after step 9.
</HARD-GATE>

---

# Autonomy Protocol

## Never-Stop Rule

Once the loop begins, do NOT pause to ask "should I continue?" Work autonomously until:
- **Optimize:** metric target met
- **Debug:** target test passes
- **Investigate:** all checklist items resolved with evidence
- **Budget exhausted** or **human interrupts**

## Stuck Protocol

If **5 consecutive iterations** produce no `keep`:
1. Re-read program.md for new angles
2. Try combining previous near-miss approaches
3. Try radically different approaches
4. Log "stuck" in report.md
5. Continue with new plan until budget exhausted, DON'T STOP!!!!

## Crash Handling

- Quick fix (typo, missing import): fix and re-run
- Fundamental issue: log `crash`, revert, move on
- 3 consecutive crashes: try radically different approach
- Continue with new plan until budget exhausted, DON'T STOP!!!!

## Run Completion

When the run ends (target met, budget exhausted, or user interrupts):

<HARD-GATE>
YOU CANNOT STOP WITHOUT A FINAL REPORT.

The completion-check hook will BLOCK you from stopping if report.md is missing
a `## Conclusion` section. Complete ALL steps below before stopping.
</HARD-GATE>

1. **Finalize report.md** — add a `## Conclusion` section at the end with:
   - **Outcome:** whether the target was met (YES/NO + evidence)
   - **Statistics:** total iterations, keeps, discards, crashes
   - **Best result:** the best metric achieved and which commit produced it
   - **Key findings:** (optimize) what worked and why; (debug) root cause and fix; (investigate) answers to each checklist question
   - **Recommendations:** next steps if target not met, or how to maintain gains if it was
   - **Timeline:** start time, end time, total duration

2. **Deactivate guardrail hooks:**
   ```bash
   bash ${CLAUDE_PLUGIN_ROOT}/hooks/run-control.sh deactivate
   ```

3. **Show final status to user** — display the conclusion summary inline so the user sees it without opening the report file

---

# Examples

## Optimize: API Latency

```
results.tsv:
2026-03-23T10:01  a1b2c3d  baseline  keep     -  -  312  baseline: 312ms
2026-03-23T10:07  b2c3d4e  iterate   keep     -  -  245  added connection pooling
2026-03-23T10:14  c3d4e5f  iterate   discard  -  -  251  tried async handlers — worse
2026-03-23T10:20  d4e5f6g  iterate   keep     -  -  189  query result caching — target met!
```

## Debug: Auth Failure

```
results.tsv:
10:01  a1b  observe   keep  -          -          -  added logging for H1,H2,H3 (batch)
10:05  b2c  observe   keep  -          -          -  added timing probes for all 3
10:09  c3d  diagnose  keep  a1b,b2c    H1:++,H2:--,H3:?  -  matrix: H2 eliminated (rate=0)
10:16  e5f  diagnose  keep  a1b..d4e   H1:++,H3:--        -  H3 eliminated, H1 confirmed
10:22  f6g  fix       discard  e5f     H1:confirmed       -  tried cert pre-stage — still fails
10:33  h8i  diagnose  keep  g7h        H1:refined         -  cert gap is in renewal, not rotation
10:38  i9j  fix       keep  h8i        -          -  added cert renewal overlap — PASSES
```

## Investigate: Error Patterns

```
results.tsv:
10:01  a1b  gather   keep  -      -  -  collected 7 days of error logs
10:05  b2c  gather   keep  -      -  -  fetched deploy timestamps from CI
10:09  c3d  analyze  keep  a1b,b2c  H1:++  -  403 correlates with deploy (7/7)
10:17  e5f  analyze  keep  c3d,d4e  H1:++  -  cert rotation is the mechanism
10:24  g7h  conclude keep  c3d,e5f  -  -  root cause: deploy triggers cert rotation
```
