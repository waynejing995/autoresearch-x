"""Coordinator CLI — main entry point for autoresearch-x Agent Teams."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
from loguru import logger

from .branch_manager import BranchManager
from .models import Decision, ResultRow, RunMode, RunState
from .program_parser import parse_program_md
from .sdk_teammate import run_teammate_sync
from .state_manager import StateManager


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def cli(verbose: bool) -> None:
    """autoresearch-x Agent Teams Coordinator."""
    log_level = "DEBUG" if verbose else "INFO"
    logger.remove()
    logger.add(sys.stderr, level=log_level)


@cli.command()
@click.option("--program", "-p", "program_path", required=True, help="Path to program.md")
@click.option("--tag", "-t", default=None, help="Run tag (auto-generated if omitted)")
@click.option("--project-dir", "-d", default=None, help="Project directory")
@click.option("--max-turns", default=25, help="Max turns per teammate")
@click.option("--debug-dump", is_flag=True, help="Dump raw teammate output for debugging")
def run(
    program_path: str,
    tag: Optional[str],
    project_dir: Optional[str],
    max_turns: int,
    debug_dump: bool,
) -> None:
    """Start an Agent Teams iteration run."""
    proj = Path(project_dir) if project_dir else Path.cwd()
    program_file = Path(program_path)
    if not program_file.exists():
        logger.error(f"program.md not found: {program_path}")
        sys.exit(1)

    parsed = parse_program_md(program_file)
    if not tag:
        tag = _generate_tag(parsed.get("mode", "optimize"), parsed.get("target_desc", ""))

    run_dir = proj / ".autoresearch-x" / tag
    state_mgr = StateManager(run_dir)
    state = state_mgr.init_run(
        tag=tag,
        mode=RunMode(parsed["mode"]) if parsed["mode"] else RunMode.OPTIMIZE,
        target=parsed["target_desc"],
        program_md_path=str(program_file),
        eval_command=parsed["eval_command"],
        metric_name=parsed["metric_name"],
        target_expr=parsed["target"],
        scope=parsed["scope"],
        readonly=parsed["readonly"],
        max_iterations=parsed["max_iterations"],
        timeout_minutes=parsed["timeout_minutes"],
    )

    branch_mgr = BranchManager(state_mgr, str(proj))

    logger.info(f"Starting run: tag={tag} mode={state.mode.value} target={state.target}")
    _run_loop(state, state_mgr, branch_mgr, proj, max_turns=max_turns, debug_dump=debug_dump)


@cli.command()
@click.argument("tag")
@click.option("--project-dir", "-d", default=None)
def resume(tag: str, project_dir: Optional[str]) -> None:
    """Resume an interrupted run."""
    proj = Path(project_dir) if project_dir else Path.cwd()
    run_dir = proj / ".autoresearch-x" / tag
    if not run_dir.exists():
        logger.error(f"Run directory not found: {run_dir}")
        sys.exit(1)

    state_mgr = StateManager(run_dir)
    state = state_mgr.load_state()
    branch_mgr = BranchManager(state_mgr, str(proj))

    logger.info(f"Resuming run: tag={tag} iteration={state.iteration_count}")
    _run_loop(state, state_mgr, branch_mgr, proj)


@cli.command()
@click.argument("tag")
@click.option("--project-dir", "-d", default=None)
def status(tag: str, project_dir: Optional[str]) -> None:
    """Show status of a run."""
    proj = Path(project_dir) if project_dir else Path.cwd()
    run_dir = proj / ".autoresearch-x" / tag
    if not run_dir.exists():
        click.echo(f"No run found with tag: {tag}")
        return

    state_mgr = StateManager(run_dir)
    state = state_mgr.load_state()
    branches = state_mgr.read_branches()

    click.echo(f"Run: {tag}")
    click.echo(f"Mode: {state.mode.value}")
    click.echo(f"Target: {state.target}")
    click.echo(f"Status: {state.status}")
    click.echo(f"Iterations: {state.iteration_count}/{state.max_iterations or '∞'}")
    click.echo(f"Best metric: {state.best_metric or '-'}")
    click.echo(f"Crashes: {state.crash_count}")
    click.echo(f"Mind explosions: {state.mind_explosions}")
    click.echo("")
    click.echo("Branches:")
    for b in branches:
        click.echo(
            f"  {b.branch_id}: status={b.status} priority={b.priority:.2f} "
            f"iters={b.iterations} best={b.best_metric} stalls={b.stall_count}"
        )


@cli.command()
@click.option("--project-dir", "-d", default=None)
@click.option("--days", default=7, help="Remove runs older than N days")
def cleanup(project_dir: Optional[str], days: int) -> None:
    """Remove old run directories."""
    proj = Path(project_dir) if project_dir else Path.cwd()
    run_base = proj / ".autoresearch-x"
    if not run_base.exists():
        click.echo("No runs to clean up.")
        return

    cutoff = time.time() - days * 86400
    removed = 0
    for d in run_base.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            import shutil

            shutil.rmtree(d)
            removed += 1
            click.echo(f"Removed: {d.name}")
    click.echo(f"Cleaned up {removed} runs older than {days} days.")


# ---------------------------------------------------------------------------
# Prompts — plain text, no JSON required
# ---------------------------------------------------------------------------

_PLANNER_PROMPT = """\
You are the Planner in an autoresearch-x iteration loop.

## Task
Analyze the iteration history and propose ONE change to optimize the target metric.

## Program
{program_text}

## Iteration History
{history_text}

## Allowed Actions
- Read source files to understand current state
- Read iteration history and results.tsv for patterns
- Write to program.md to update lessons learned and tips (e.g., "Lesson: GPU test suite requires sudo for device access")

## Forbidden Actions
- Do NOT edit any source code files
- Do NOT run evaluation or build commands
- Do NOT modify state.json, results.tsv, or branches.tsv

## Learning Updates
When the iteration history reveals useful lessons (e.g. a technique that worked well,
a pattern that consistently fails, a performance gotcha, a useful constraint), update
program.md to record them. Use the following format in program.md:

## Lessons Learned
- [iter N] <what was learned>

You MAY directly edit program.md to append lessons learned — this is the only project
file you are allowed to modify directly. Write your update using the Edit tool.

## Output Format
Propose your plan as plain text with these sections:
1. **Change**: One specific, actionable change description
2. **Rationale**: Why this change should improve the metric, referencing prior iteration evidence
3. **Files**: List of files the Worker should modify
4. **Lesson** (optional): New insight to append to program.md
"""

_WORKER_PROMPT = """\
You are the Worker in an autoresearch-x iteration loop.

## Task
Execute the planned change.

## Plan
{plan_text}

## Scope
Only modify: {scope}
Readonly: {readonly}

## Allowed Actions
- Read any file to understand context
- Edit/Write files within scope only
- Run diagnostic Bash commands (e.g., grep, git diff) — no builds

## Forbidden Actions
- Do NOT modify files outside scope
- Do NOT touch readonly files
- Do NOT run the eval command (that's the Evaluator's job)
- Do NOT modify program.md or .autoresearch-x/ tracking files
- Do NOT make multiple changes — ONE change per iteration

## Output Format
After implementing, output a plain text summary with:
1. **Files Modified**: List of files changed
2. **Changes**: Brief description of each change
3. **Observations**: Any unexpected behavior or risks noticed during implementation
"""

_EVALUATOR_PROMPT = """\
You are the Evaluator in an autoresearch-x iteration loop.

## Task
Run the evaluation command and report the metric.

## Evaluation
- Command: {eval_command}
- Metric: {metric_name}
- Target: {target_expr}

## Allowed Actions
- Run the eval command using Bash
- Write eval logs to .autoresearch-x/<tag>/eval-logs/iter_{iteration}.log
- Read source files to interpret eval output

## Forbidden Actions
- Do NOT modify source code files
- Do NOT modify program.md, state.json, results.tsv, or branches.tsv

## Eval Log
After running the eval command, write a structured eval log to
.autoresearch-x/eval-logs/<timestamp>.md with the following format:

# Eval Log — Iteration <N>
- **Command:** <eval_command>
- **Metric (<metric_name>):** <value>
- **Target (<target_expr>):** <met / not met>
- **Exit code:** <code>

## Output (key lines)
<last 20 lines of eval command output>

Use the Write tool to create this log file.

## Output Format
Output a plain text report with:
1. **Exit Code**: Command exit code
2. **Metric Value**: The extracted metric number
3. **Target Met**: Yes/No (based on target expression)
4. **Key Excerpt**: Relevant lines from eval output (max 20 lines)
5. **Observations**: Anomalies, warnings, or notes about the eval run
"""


# ---------------------------------------------------------------------------
# Core iteration loop
# ---------------------------------------------------------------------------


def _run_loop(
    state: RunState,
    state_mgr: StateManager,
    branch_mgr: BranchManager,
    proj: Path,
    max_turns: int = 25,
    debug_dump: bool = False,
) -> None:
    """Main iteration loop."""
    MAX_AGENT_RETRIES = 3

    while not state.is_budget_exhausted():
        state = state_mgr.load_state()

        next_branch = branch_mgr.select_next_branch(state)
        if next_branch is None:
            logger.warning("No active branches remaining")
            break

        if next_branch.branch_id != state.current_branch:
            if not branch_mgr.switch_branch(next_branch.branch_id):
                logger.error(f"Failed to switch to branch {next_branch.branch_id}")
                break
            state.current_branch = next_branch.branch_id
            state_mgr.save_state(state)

        if next_branch.stall_count >= 5:
            branch_mgr.mark_stalled(next_branch.branch_id)
            if branch_mgr.is_globally_stalled():
                logger.info("All branches stalled — triggering Strategist")
                _trigger_strategist(state, state_mgr, branch_mgr, proj, max_turns)
            continue

        # ── Planner ──────────────────────────────────────────────────
        planner_text = _run_planner(state, state_mgr, proj, max_turns, debug_dump)
        if planner_text is None:
            logger.error("Planner failed")
            if state.crash_count >= MAX_AGENT_RETRIES - 1:
                logger.error(f"Planner retry limit reached ({MAX_AGENT_RETRIES}), aborting")
                state.status = "agent_retry_exhausted"
                state_mgr.save_state(state)
                break
            state.crash_count += 1
            state_mgr.save_state(state)
            continue

        state.crash_count = 0
        logger.info(f"\n{'=' * 60}")
        logger.info(f"PLANNER (iter {state.iteration_count + 1}):")
        logger.info(f"{'=' * 60}")
        logger.info(planner_text)

        # ── Worker ───────────────────────────────────────────────────
        worker_text = _run_worker(state, state_mgr, planner_text, proj, max_turns, debug_dump)
        if worker_text is None:
            logger.error("Worker failed")
            if state.crash_count >= MAX_AGENT_RETRIES - 1:
                logger.error(f"Worker retry limit reached ({MAX_AGENT_RETRIES}), aborting")
                state.status = "agent_retry_exhausted"
                state_mgr.save_state(state)
                break
            state.crash_count += 1
            state_mgr.save_state(state)
            continue

        logger.info(f"\n{'=' * 60}")
        logger.info(f"WORKER (iter {state.iteration_count + 1}):")
        logger.info(f"{'=' * 60}")
        logger.info(worker_text)

        # ── Git commit (before eval, so eval tests the committed code) ─
        commit = _git_commit_all(proj, state.iteration_count + 1)

        # ── Evaluator ────────────────────────────────────────────────
        eval_text = _run_evaluator(state, state_mgr, proj, max_turns, debug_dump)
        if eval_text is None:
            logger.error("Evaluator failed")
            if state.crash_count >= MAX_AGENT_RETRIES - 1:
                logger.error(f"Evaluator retry limit reached ({MAX_AGENT_RETRIES}), aborting")
                state.status = "agent_retry_exhausted"
                state_mgr.save_state(state)
                break
            state.crash_count += 1
            state_mgr.save_state(state)
            continue

        logger.info(f"\n{'=' * 60}")
        logger.info(f"EVALUATOR (iter {state.iteration_count + 1}):")
        logger.info(f"{'=' * 60}")
        logger.info(eval_text)

        # ── Parse metric from eval text ──────────────────────────────
        metric_value = _extract_metric(eval_text, state.metric_name)
        target_met = state.is_target_met(metric_value)

        # ── Decide ───────────────────────────────────────────────────
        decision = _decide(state, metric_value)

        logger.info(f"\n{'=' * 60}")
        logger.info(f"DECISION (iter {state.iteration_count + 1}):")
        logger.info(f"{'=' * 60}")
        logger.info(f"Commit: {commit}")
        logger.info(f"Metric: {metric_value} (target: {state.target_expr})")
        logger.info(f"Target met: {target_met}")
        logger.info(f"Decision: {decision.value}")

        # ── Act on decision ──────────────────────────────────────────
        if decision == Decision.DISCARD:
            logger.info(f"Reverting changes from commit {commit}")
            _git_revert(proj, commit)

        # ── Record ───────────────────────────────────────────────────
        desc = _extract_change_description(planner_text)
        _record(state, state_mgr, commit, decision, metric_value, desc, next_branch.branch_id)

        # ── Update state ─────────────────────────────────────────────
        if decision == Decision.KEEP:
            state.consecutive_discards = 0
            if metric_value is not None:
                if state.best_metric is None or _is_better(
                    metric_value, state.best_metric, state.target_expr
                ):
                    state.best_metric = metric_value
                    state.best_commit = commit
        else:
            state.consecutive_discards += 1
            if state.consecutive_discards >= 5:
                branch_mgr.mark_stalled(next_branch.branch_id)

        state.iteration_count += 1

        if target_met:
            logger.info("Target met! Writing final report...")
            state.status = "completed"
            state_mgr.save_state(state)
            break

        state_mgr.save_state(state)
        branch_mgr.update_priorities(state)

    _write_final_report(state, state_mgr, branch_mgr)
    logger.info(f"Run complete: tag={state.tag} status={state.status}")


def _run_planner(
    state: RunState,
    state_mgr: StateManager,
    proj: Path,
    max_turns: int,
    debug_dump: bool,
) -> Optional[str]:
    program_text = Path(state.program_md_path).read_text() if state.program_md_path else ""
    history_text = _build_history_text(state_mgr)

    prompt = _PLANNER_PROMPT.format(
        program_text=program_text,
        history_text=history_text,
    )

    # Planner: can write to program.md and .autoresearch-x/
    planner_scope = []
    if state.program_md_path:
        planner_scope.append(state.program_md_path)
    planner_scope.append(".autoresearch-x/")

    try:
        result = run_teammate_sync(
            prompt=prompt,
            project_dir=str(proj),
            max_turns=max_turns,
            allowed_tools=[
                "Read",
                "Write",
                "Edit",
                "Bash",
                "Grep",
                "Glob",
                "LS",
                "WebFetch",
                "WebSearch",
            ],
            readonly=state.readonly,
            scope=planner_scope,
        )
    except Exception as e:
        logger.error(f"Planner SDK error: {e}")
        return None

    if debug_dump:
        dump_file = state_mgr.run_dir / f"planner-iter-{state.iteration_count + 1}-raw.json"
        dump_file.write_text(json.dumps(result.raw_messages, indent=2, default=str))

    return result.get_full_text() or None


def _run_worker(
    state: RunState,
    state_mgr: StateManager,
    plan_text: str,
    proj: Path,
    max_turns: int,
    debug_dump: bool,
) -> Optional[str]:
    prompt = _WORKER_PROMPT.format(
        plan_text=plan_text,
        scope=", ".join(state.scope) if state.scope else "any file",
        readonly=", ".join(state.readonly) if state.readonly else "none",
    )

    try:
        result = run_teammate_sync(
            prompt=prompt,
            project_dir=str(proj),
            max_turns=max_turns,
            allowed_tools=[
                "Read",
                "Write",
                "Edit",
                "Bash",
                "Grep",
                "Glob",
                "LS",
                "WebFetch",
                "WebSearch",
            ],
            readonly=state.readonly,
            scope=state.scope,
        )
    except Exception as e:
        logger.error(f"Worker SDK error: {e}")
        return None

    if debug_dump:
        dump_file = state_mgr.run_dir / f"worker-iter-{state.iteration_count + 1}-raw.json"
        dump_file.write_text(json.dumps(result.raw_messages, indent=2, default=str))

    return result.get_full_text() or None


def _run_evaluator(
    state: RunState,
    state_mgr: StateManager,
    proj: Path,
    max_turns: int,
    debug_dump: bool,
) -> Optional[str]:
    prompt = _EVALUATOR_PROMPT.format(
        eval_command=state.eval_command,
        metric_name=state.metric_name,
        target_expr=state.target_expr,
    )

    # Evaluator: can only write to .autoresearch-x/ directory
    evaluator_scope = [".autoresearch-x/"]

    try:
        result = run_teammate_sync(
            prompt=prompt,
            project_dir=str(proj),
            max_turns=max_turns,
            allowed_tools=[
                "Read",
                "Write",
                "Edit",
                "Bash",
                "Grep",
                "Glob",
                "LS",
                "WebFetch",
                "WebSearch",
            ],
            readonly=state.readonly,
            scope=evaluator_scope,
        )
    except Exception as e:
        logger.error(f"Evaluator SDK error: {e}")
        return None

    if debug_dump:
        dump_file = state_mgr.run_dir / f"evaluator-iter-{state.iteration_count + 1}-raw.json"
        dump_file.write_text(json.dumps(result.raw_messages, indent=2, default=str))

    return result.get_full_text() or None


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------


def _git_commit_all(proj: Path, iteration: int) -> str:
    """Commit all changes. Returns commit hash or 'no-change'."""
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=proj,
            capture_output=True,
            text=True,
            check=True,
        )
        if not status.stdout.strip():
            return "no-change"

        subprocess.run(["git", "add", "-A"], cwd=proj, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"iter {iteration}"],
            cwd=proj,
            capture_output=True,
            text=True,
            check=True,
        )
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=proj,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"Git commit failed: {e}")
        return "commit-failed"


def _git_revert(proj: Path, commit: str) -> None:
    """Revert a specific commit's changes."""
    if commit in ("no-change", "commit-failed"):
        return
    try:
        subprocess.run(
            ["git", "revert", "--no-edit", commit],
            cwd=proj,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        # Fallback: reset to previous commit
        try:
            subprocess.run(
                ["git", "reset", "--hard", "HEAD~1"],
                cwd=proj,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Git revert failed: {e}")


# ---------------------------------------------------------------------------
# Metric extraction from plain text
# ---------------------------------------------------------------------------


def _extract_metric(text: str, metric_name: str) -> Optional[float]:
    """Extract metric value from evaluator's plain text output."""
    if not text or not metric_name:
        return None

    # Try: "metric_name: 123.45" or "metric_name = 123.45"
    patterns = [
        rf'{re.escape(metric_name)}["\s]*[:=]\s*([\d.]+)',
        rf"([\d.]+)\s*(?:ms|milliseconds)\s*(?:{re.escape(metric_name)})?",
        rf'(?:p99|pipeline_total)["\s]*[:=]\s*([\d.]+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass

    # Try: any standalone number near "p99" or "total"
    m = re.search(r'(?:p99|total)["\s]*[:=]\s*([\d.]+)', text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    return None


def _extract_change_description(planner_text: str) -> str:
    """Extract a one-line description from planner output."""
    if not planner_text:
        return ""
    # Use first non-empty line as description
    for line in planner_text.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("-"):
            return line[:200]
    return planner_text.strip()[:200]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_history_text(state_mgr: StateManager) -> str:
    """Build iteration history text for the planner."""
    rows = state_mgr.read_all_results()
    if not rows:
        return "No previous iterations — this is the baseline."

    lines = []
    for r in rows[-5:]:  # Last 5 iterations
        lines.append(
            f"- iter: commit={r.commit} decision={r.decision} "
            f"metric={r.metric_value} desc={r.description}"
        )
    return "\n".join(lines)


def _decide(state: RunState, metric_value: Optional[float]) -> Decision:
    if metric_value is None:
        return Decision.DISCARD
    if state.best_metric is None:
        return Decision.KEEP  # baseline always keeps
    if _is_better(metric_value, state.best_metric, state.target_expr):
        return Decision.KEEP
    return Decision.DISCARD


def _is_better(new_val: float, old_val: float, target_expr: str) -> bool:
    m = re.search(r"([<>=!]+)", target_expr)
    if m:
        op = m.group(1)
        if op in ("<", "<="):
            return new_val < old_val
        elif op in (">", ">="):
            return new_val > old_val
    return False


def _record(
    state: RunState,
    state_mgr: StateManager,
    commit: str,
    decision: Decision,
    metric_value: Optional[float],
    description: str,
    branch_id: str,
) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    phase = "baseline" if state.iteration_count == 0 else "iterate"
    metric_str = str(metric_value) if metric_value is not None else "-"

    row = ResultRow(
        timestamp=ts,
        commit=commit,
        phase=phase,
        decision=decision.value,
        metric_value=metric_str,
        description=description,
    )
    state_mgr.append_result(row, branch_id)

    detail = f"# Iteration {state.iteration_count + 1}\n\n"
    detail += f"- **Commit:** {commit}\n"
    detail += f"- **Decision:** {decision.value}\n"
    detail += f"- **Metric:** {metric_str}\n"
    detail += f"- **Description:** {description}\n"
    state_mgr.write_iteration_detail(commit, detail, branch_id)


def _trigger_strategist(
    state: RunState,
    state_mgr: StateManager,
    branch_mgr: BranchManager,
    proj: Path,
    max_turns: int,
) -> None:
    prompt = (
        f"You are the Strategist. All branches are stalled.\n\n"
        f"Analyze all branch failures and propose new strategies.\n\n"
        f"## Results\n"
        f"{_read_or_default(state_mgr.all_results_path, 'No results')}\n\n"
        f"## Program\n"
        f"{_read_or_default(_path_or_none(state.program_md_path), '')}\n\n"
        f"## Branches\n"
        f"{_read_or_default(state_mgr.branches_path, 'No branches')}"
    )

    try:
        result = run_teammate_sync(
            prompt=prompt,
            project_dir=str(proj),
            max_turns=max_turns,
            allowed_tools=[
                "Read",
                "Write",
                "Edit",
                "Bash",
                "Grep",
                "Glob",
                "LS",
                "WebFetch",
                "WebSearch",
            ],
        )
        logger.info(f"Strategist analysis: {result.get_full_text()[:500]}")
    except Exception as e:
        logger.error(f"Strategist SDK error: {e}")

    state.mind_explosions += 1
    state_mgr.save_state(state)


def _write_final_report(
    state: RunState,
    state_mgr: StateManager,
    branch_mgr: BranchManager,
) -> None:
    report = state_mgr.run_dir / "report.md"
    rows = state_mgr.read_all_results()
    branches = state_mgr.read_branches()

    keeps = sum(1 for r in rows if r.decision == "keep")
    discards = sum(1 for r in rows if r.decision == "discard")

    lines = [
        f"# Final Report: {state.tag}",
        "",
        "## Outcome",
        f"- **Target:** {state.target}",
        f"- **Status:** {state.status}",
        f"- **Best metric:** {state.best_metric}",
        f"- **Best commit:** {state.best_commit}",
        "",
        "## Statistics",
        f"- **Total iterations:** {state.iteration_count}",
        f"- **Keeps:** {keeps}",
        f"- **Discards:** {discards}",
        f"- **Crashes:** {state.crash_count}",
        f"- **Mind explosions:** {state.mind_explosions}",
        "",
        "## Branch Summary",
    ]
    for b in branches:
        lines.append(
            f"- **{b.branch_id}**: status={b.status} iters={b.iterations} best={b.best_metric}"
        )

    lines.append("")
    lines.append("## Timeline")
    lines.append(f"- **Started:** {state.started_at}")
    lines.append(f"- **Ended:** {datetime.now(timezone.utc).isoformat()}")

    report.write_text("\n".join(lines) + "\n")
    logger.info(f"Final report written to {report}")


def _path_or_none(s: str) -> Optional[Path]:
    return Path(s) if s else None


def _generate_tag(mode: str, target: str) -> str:
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%b%d").lower()
    topic = target.split()[0] if target else mode
    return f"{date_str}-{topic}"


def _read_or_default(path: Optional[Path], default: str) -> str:
    if path and path.exists():
        return path.read_text()
    return default
