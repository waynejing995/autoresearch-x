# autoresearch-x

*Iterate anything. Prove everything.*

An autonomous iteration engine for [Claude Code](https://claude.ai/claude-code) with evidence-chain tracking. Set up a tracked run and iterate autonomously — optimizing code, debugging failures, or investigating questions — until the target is met or the budget is exhausted.

Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch) — generalized to any domain.

## Why

Most AI coding agents try one fix, check if it worked, and move on. Real engineering problems require **structured iteration**: controlled experiments, hypothesis tracking, metric-driven decisions, and clear evidence chains.

autoresearch-x enforces scientific rigor:

- **One change per iteration** — isolate variables so you know what actually worked
- **Separated execution and evaluation** — the agent that writes the fix cannot judge if it worked (prevents confirmation bias)
- **Evidence chains** — every decision is backed by data, tracked in `results.tsv`
- **Guardrail hooks** — scope guards, iteration gates, and completion checks enforce discipline automatically

## Three Modes

| Mode | Goal | Phases | Use When |
|------|------|--------|----------|
| **optimize** | Improve a metric | baseline → iterate | Reducing latency, improving throughput, lowering error rates |
| **debug** | Fix a failure | observe → diagnose → fix | Systematic debugging with hypothesis tracking |
| **investigate** | Answer questions | gather → analyze → conclude | Log analysis, root cause investigation, evidence-based research |

## Architecture

```
Main Agent (orchestrator)
├── Worker subagent      — executes code changes (cannot see eval results)
├── Evaluator subagent   — runs eval commands (cannot see code changes)
├── Reviewer subagent    — validates program.md before runs start
└── Strategist subagent  — dispatched after 5 consecutive discards to pivot strategy

Guardrail Hooks
├── scope-guard          — blocks edits outside declared scope
├── iteration-gate       — enforces one-change-per-iteration rule
├── eval-bypass-detector — catches attempts to run eval directly
└── completion-check     — blocks stopping without a final report
```

## Installation

### Claude Code (Recommended)

```bash
# Add as a marketplace, then install
claude plugin marketplace add --source github --repo waynejing995/autoresearch-x
claude plugin install autoresearch-x@autoresearch-x

# Or clone manually
git clone https://github.com/waynejing995/autoresearch-x.git ~/.claude/plugins/autoresearch-x
```

### Codex

```bash
git clone https://github.com/waynejing995/autoresearch-x.git ~/.codex/skills/autoresearch-x
```

### Other AI Tools

Clone into your tool's plugin directory:

```bash
git clone https://github.com/waynejing995/autoresearch-x.git <your-plugin-dir>/autoresearch-x
```

### Update

```bash
cd ~/.claude/plugins/autoresearch-x && git pull
```

### Usage

Once installed, invoke via natural language or slash command:

```
# Interactive setup (guided questions)
/autoresearch-x

# Start from a template
/autoresearch-x --template optimize
/autoresearch-x --template debug
/autoresearch-x --template investigate

# Use an existing program.md
/autoresearch-x --program path/to/program.md

# Resume a previous run
/autoresearch-x resume <tag>

# Check status
/autoresearch-x status
```

Or just describe your task naturally:

> "My API endpoint is responding in 400ms, I need it under 200ms. The benchmark is at scripts/bench.py. Iterate on it overnight."

> "test_auth keeps failing with 403 but only on Mondays. Debug it systematically."

> "Investigate why webhook processing has been unreliable this month. Check logs, analyze patterns, give me an evidence-backed report."

## The 9-Step Protocol

Every iteration follows this exact protocol:

1. **Review & Plan** — analyze previous results, state ONE specific change to try
2. **Dispatch Worker** — send the change to the worker subagent
3. **Review Diff** — verify scope compliance and single-change rule
4. **Commit** — `git commit -m "iter N: <description>"`
5. **Dispatch Evaluator** — send eval command to the evaluator subagent
6. **Decide** — keep (metric improved) or discard (metric same/worse)
7. **Act** — advance branch or revert to previous commit
8. **Record** — append row to `results.tsv`
9. **Write Detail** — create `iterations/<commit>.md`, update `report.md`

## Example Runs

### Optimize: API Latency

```
results.tsv:
2026-03-23T10:01  a1b2c3d  baseline  keep     312  baseline: 312ms
2026-03-23T10:07  b2c3d4e  iterate   keep     245  added connection pooling
2026-03-23T10:14  c3d4e5f  iterate   discard  251  tried async handlers — worse
2026-03-23T10:20  d4e5f6g  iterate   keep     189  query result caching — target met!
```

### Debug: Auth Failure

```
results.tsv:
10:01  a1b  observe   keep  added logging for H1,H2,H3 (batch)
10:05  b2c  observe   keep  added timing probes for all 3
10:09  c3d  diagnose  keep  matrix: H2 eliminated (rate=0)
10:16  e5f  diagnose  keep  H3 eliminated, H1 confirmed
10:22  f6g  fix       discard  tried cert pre-stage — still fails
10:33  h8i  diagnose  keep  cert gap is in renewal, not rotation
10:38  i9j  fix       keep  added cert renewal overlap — PASSES
```

### Investigate: Error Patterns

```
results.tsv:
10:01  a1b  gather   keep  collected 7 days of error logs
10:05  b2c  gather   keep  fetched deploy timestamps from CI
10:09  c3d  analyze  keep  403 correlates with deploy (7/7)
10:17  e5f  analyze  keep  cert rotation is the mechanism
10:24  g7h  conclude keep  root cause: deploy triggers cert rotation
```

## program.md

Each run is governed by a `program.md` that defines:

```markdown
# autoresearch-x: <run name>

## Target
Reduce p99 API latency below 200ms

## Mode
optimize

## Checklist
- [ ] Establish baseline
- [ ] Profile hot paths
- [ ] Optimize critical path

## Scope
- modify: src/server.py
- readonly: scripts/bench.py

## Evaluation
- command: `python scripts/bench.py --json`
- metric: p99_latency_ms
- target: < 200

## Constraints
- max_iterations: 30
- timeout: 1h
```

### Constraint Presets

| Preset | Iterations | Timeout |
|--------|-----------|---------|
| Light | 10 | 30min |
| Medium | 30 | 1h |
| Heavy | 50 | 2h |
| Infinite | No limit | No limit |

## Project Structure

```
autoresearch-x/
├── .claude-plugin/
│   └── plugin.json            # Plugin metadata
├── agents/
│   ├── worker.md              # Code modification agent (isolated from eval)
│   ├── evaluator.md           # Evaluation agent (isolated from code changes)
│   ├── reviewer.md            # Program.md validation agent
│   └── strategist.md          # Strategy pivot agent (dispatched on stall)
├── skills/
│   └── autoresearch-x/
│       ├── SKILL.md           # Main skill definition
│       ├── ref-optimize-mode.md
│       ├── ref-debug-mode.md
│       ├── ref-investigate-mode.md
│       ├── ref-tracking.md
│       ├── ref-branching.md   # Branching & strategy pivot reference
│       └── templates/         # program.md templates & report formats
├── hooks/
│   ├── hooks.json             # Hook registration
│   ├── scope-guard.sh         # Blocks out-of-scope edits
│   ├── iteration-gate.sh      # Enforces one-change-per-iteration
│   ├── eval-bypass-detector.sh # Catches direct eval execution
│   ├── completion-check.sh    # Requires final report before stopping
│   ├── run-control.sh         # Activate/deactivate hooks per run
│   └── lib.sh                 # Shared utilities
├── evals/
│   └── evals.json             # Skill evaluation test cases
├── LICENSE
└── README.md
```

## Run Artifacts

During a run, autoresearch-x creates:

```
.autoresearch-x/<tag>/
├── results.tsv                # One row per iteration (metrics, decisions)
├── report.md                  # Running report with conclusion
└── iterations/
    ├── a1b2c3d.md             # Detailed notes per iteration
    ├── b2c3d4e.md
    └── ...
```

## Autonomy & Safety

- **Never-Stop Rule** — once started, runs autonomously until target met, budget exhausted, or human interrupts
- **Stuck Protocol** — after 5 consecutive discards, automatically dispatches the Strategist subagent for a full strategy pivot with branching support
- **Crash Handling** — quick fixes applied automatically; 3 consecutive crashes trigger a radically different approach
- **Scope Guard** — hooks prevent modifications outside declared scope
- **Completion Check** — cannot stop without writing a final report with conclusion

## License

[MIT](LICENSE)
