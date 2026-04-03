"""Coordinator CLI — main entry point for autoresearch-x Agent Teams."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
from loguru import logger

from .branch_manager import BranchManager
from .models import (
    Decision,
    EvaluatorResult,
    PlannerResult,
    ResultRow,
    RunMode,
    RunState,
    WorkerResult,
)
from .program_parser import parse_program_md
from .sdk_teammate import extract_json_from_result, run_teammate_sync
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
@click.option("--chat", is_flag=True, help="Start with interactive chat to refine program.md")
@click.option("--max-turns", default=20, help="Max turns per teammate")
@click.option("--idle-timeout", default=300, help="Idle timeout in seconds")
@click.option("--debug-dump", is_flag=True, help="Dump raw teammate output for debugging")
def run(
    program_path: str,
    tag: Optional[str],
    project_dir: Optional[str],
    chat: bool,
    max_turns: int,
    idle_timeout: int,
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
# Core iteration loop
# ---------------------------------------------------------------------------


def _run_loop(
    state: RunState,
    state_mgr: StateManager,
    branch_mgr: BranchManager,
    proj: Path,
    max_turns: int = 20,
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

        state_mgr.clear_outbox()

        planner_result = _run_planner(state, state_mgr, proj, max_turns, debug_dump)
        if planner_result is None:
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

        worker_result = _run_worker(state, state_mgr, planner_result, proj, max_turns, debug_dump)
        if worker_result is None:
            logger.error("Worker failed")
            if state.crash_count >= MAX_AGENT_RETRIES - 1:
                logger.error(f"Worker retry limit reached ({MAX_AGENT_RETRIES}), aborting")
                state.status = "agent_retry_exhausted"
                state_mgr.save_state(state)
                break
            state.crash_count += 1
            state_mgr.save_state(state)
            continue

        eval_result = _run_evaluator(state, state_mgr, proj, max_turns, debug_dump)
        if eval_result is None:
            logger.error("Evaluator failed")
            if state.crash_count >= MAX_AGENT_RETRIES - 1:
                logger.error(f"Evaluator retry limit reached ({MAX_AGENT_RETRIES}), aborting")
                state.status = "agent_retry_exhausted"
                state_mgr.save_state(state)
                break
            state.crash_count += 1
            state_mgr.save_state(state)
            continue

        commit = _git_commit_or_revert(state, worker_result, proj)
        decision = _decide(state, eval_result)
        _record(
            state, state_mgr, commit, decision, eval_result, planner_result, next_branch.branch_id
        )

        if decision == Decision.KEEP:
            state.consecutive_discards = 0
            if eval_result.metric_value is not None:
                if state.best_metric is None or _is_better(
                    eval_result.metric_value, state.best_metric, state.target_expr
                ):
                    state.best_metric = eval_result.metric_value
                    state.best_commit = commit
        else:
            state.consecutive_discards += 1
            if state.consecutive_discards >= 5:
                branch_mgr.mark_stalled(next_branch.branch_id)

        state.iteration_count += 1
        if eval_result.target_met:
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
) -> Optional[PlannerResult]:
    program_text = Path(state.program_md_path).read_text() if state.program_md_path else ""
    outbox_path = state_mgr.outbox_dir / "planner.json"
    state_mgr.outbox_dir.mkdir(parents=True, exist_ok=True)

    prompt = (
        f"You are the Planner in an autoresearch-x iteration loop.\n\n"
        f"## Task\n"
        f"Analyze the iteration history and propose ONE change to reduce latency.\n\n"
        f"## Context\n"
        f"- State: {state_mgr.state_path}\n"
        f"- Results: {state_mgr.results_path}\n"
        f"- Iterations dir: {state_mgr.iterations_dir}\n\n"
        f"## Program\n"
        f"{program_text}\n\n"
        f"## CRITICAL OUTPUT REQUIREMENT\n"
        f"You MUST write a JSON file to: {outbox_path}\n"
        f"Use the Write tool to create this file with the following JSON:\n"
        f'{{"status": "success", "plan": {{\n'
        f'  "change_description": "one sentence description",\n'
        f'  "rationale": "why this works",\n'
        f'  "expected_signal": "what metric change to expect",\n'
        f'  "files_to_modify": ["path/to/file.py"]\n'
        f"}}}}\n"
        f"Do NOT just describe the analysis in text. You MUST write the JSON file."
    )

    try:
        result = run_teammate_sync(
            prompt=prompt,
            project_dir=str(proj),
            max_turns=max_turns,
            allowed_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS"],
        )
    except Exception as e:
        logger.error(f"Planner SDK error: {e}")
        return None

    if debug_dump:
        dump_file = state_mgr.run_dir / f"planner-iter-{state.iteration_count + 1}-raw.json"
        dump_file.write_text(json.dumps(result.raw_messages, indent=2, default=str))
        logger.info(f"Dumped planner raw messages to {dump_file}")

    # Primary: read the outbox file the agent wrote
    outbox_text = state_mgr.read_outbox("planner") or ""
    if outbox_text:
        try:
            data = json.loads(outbox_text)
            return PlannerResult(**data)
        except (json.JSONDecodeError, Exception) as e:
            logger.debug(f"Outbox JSON parse error: {e}")

    # Fallback: extract from agent's text response
    data = extract_json_from_result(result)
    if data is None:
        logger.error(
            f"Planner produced no parseable JSON. Full text: {result.get_full_text()[:500]}"
        )
        return None

    try:
        return PlannerResult(**data)
    except Exception as e:
        logger.error(f"Failed to parse planner result: {e}")
        return None


def _run_worker(
    state: RunState,
    state_mgr: StateManager,
    plan: PlannerResult,
    proj: Path,
    max_turns: int,
    debug_dump: bool,
) -> Optional[WorkerResult]:
    plan_data = plan.plan or {}
    outbox_path = state_mgr.outbox_dir / "worker.json"
    state_mgr.outbox_dir.mkdir(parents=True, exist_ok=True)

    prompt = (
        f"You are the Worker in an autoresearch-x iteration loop.\n\n"
        f"## Task\n"
        f"Execute the planned change.\n\n"
        f"## Plan\n"
        f"{json.dumps(plan_data, indent=2)}\n\n"
        f"## Scope\n"
        f"Only modify: {', '.join(state.scope) if state.scope else 'any file'}\n"
        f"Readonly: {', '.join(state.readonly) if state.readonly else 'none'}\n\n"
        f"## CRITICAL OUTPUT REQUIREMENT\n"
        f"After making changes, you MUST write a JSON file to: {outbox_path}\n"
        f"Use the Write tool to create this file with:\n"
        f'{{"status": "success", "files_modified": ["path.py"],\n'
        f'  "changes_summary": "what you changed",\n'
        f'  "observations": "anything notable"}}\n'
        f"Do NOT just describe changes in text. You MUST write the JSON file."
    )

    try:
        result = run_teammate_sync(
            prompt=prompt,
            project_dir=str(proj),
            max_turns=max_turns,
            allowed_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS"],
            readonly=state.readonly,
            scope=state.scope,
        )
    except Exception as e:
        logger.error(f"Worker SDK error: {e}")
        return None

    if debug_dump:
        dump_file = state_mgr.run_dir / f"worker-iter-{state.iteration_count + 1}-raw.json"
        dump_file.write_text(json.dumps(result.raw_messages, indent=2, default=str))
        logger.info(f"Dumped worker raw messages to {dump_file}")

    # Primary: read the outbox file
    outbox_text = state_mgr.read_outbox("worker") or ""
    if outbox_text:
        try:
            data = json.loads(outbox_text)
            return WorkerResult(**data)
        except (json.JSONDecodeError, Exception) as e:
            logger.debug(f"Worker outbox JSON parse error: {e}")

    # Fallback: extract from agent's text response
    data = extract_json_from_result(result)
    if data is None:
        logger.error(
            f"Worker produced no parseable JSON. Full text: {result.get_full_text()[:500]}"
        )
        return None

    try:
        return WorkerResult(**data)
    except Exception as e:
        logger.error(f"Failed to parse worker result: {e}")
        return None


def _run_evaluator(
    state: RunState,
    state_mgr: StateManager,
    proj: Path,
    max_turns: int,
    debug_dump: bool,
) -> Optional[EvaluatorResult]:
    outbox_path = state_mgr.outbox_dir / "evaluator.json"
    state_mgr.outbox_dir.mkdir(parents=True, exist_ok=True)

    prompt = (
        f"You are the Evaluator in an autoresearch-x iteration loop.\n\n"
        f"## Task\n"
        f"Run the evaluation command and extract the metric.\n\n"
        f"## Evaluation\n"
        f"- Command: {state.eval_command}\n"
        f"- Metric: {state.metric_name}\n"
        f"- Target: {state.target_expr}\n\n"
        f"## Steps\n"
        f"1. Run the eval command using Bash\n"
        f"2. Parse the output to find the metric value\n"
        f"3. Write the result JSON file\n\n"
        f"## CRITICAL OUTPUT REQUIREMENT\n"
        f"You MUST write a JSON file to: {outbox_path}\n"
        f"Use the Write tool to create this file with:\n"
        f'{{"status": "success", "exit_code": 0, "metric_value": 123.4,\n'
        f'  "target_met": false, "extraction_method": "grep",\n'
        f'  "peak_output": "first 200 chars of output"}}\n'
        f"Do NOT just describe results in text. You MUST write the JSON file."
    )

    try:
        result = run_teammate_sync(
            prompt=prompt,
            project_dir=str(proj),
            max_turns=max_turns,
            allowed_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS"],
        )
    except Exception as e:
        logger.error(f"Evaluator SDK error: {e}")
        return None

    if debug_dump:
        dump_file = state_mgr.run_dir / f"evaluator-iter-{state.iteration_count + 1}-raw.json"
        dump_file.write_text(json.dumps(result.raw_messages, indent=2, default=str))
        logger.info(f"Dumped evaluator raw messages to {dump_file}")

    # Primary: read the outbox file
    outbox_text = state_mgr.read_outbox("evaluator") or ""
    if outbox_text:
        try:
            data = json.loads(outbox_text)
            return EvaluatorResult(**data)
        except (json.JSONDecodeError, Exception) as e:
            logger.debug(f"Evaluator outbox JSON parse error: {e}")

    # Fallback: extract from agent's text response
    data = extract_json_from_result(result)
    if data is None:
        logger.error(
            f"Evaluator produced no parseable JSON. Full text: {result.get_full_text()[:500]}"
        )
        return None

    try:
        return EvaluatorResult(**data)
    except Exception as e:
        logger.error(f"Failed to parse evaluator result: {e}")
        return None


def _git_commit_or_revert(
    state: RunState,
    worker_result: WorkerResult,
    proj: Path,
) -> str:
    files = worker_result.files_modified or []
    if not files:
        return "no-change"
    try:
        subprocess.run(["git", "add"] + files, cwd=proj, capture_output=True, check=True)
        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                f"iter {state.iteration_count + 1}: {worker_result.changes_summary}",
            ],
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


def _decide(state: RunState, eval_result: EvaluatorResult) -> Decision:
    if eval_result.status != "success" or eval_result.metric_value is None:
        return Decision.DISCARD
    if state.best_metric is None:
        return Decision.KEEP
    if _is_better(eval_result.metric_value, state.best_metric, state.target_expr):
        return Decision.KEEP
    return Decision.DISCARD


def _is_better(new_val: float, old_val: float, target_expr: str) -> bool:
    import re

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
    eval_result: EvaluatorResult,
    plan_result: PlannerResult,
    branch_id: str,
) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    plan_data = plan_result.plan or {} if plan_result else {}
    desc = plan_data.get("change_description", "") if plan_data else ""
    phase = "baseline" if state.iteration_count == 0 else "iterate"
    metric_str = str(eval_result.metric_value) if eval_result.metric_value is not None else "-"

    row = ResultRow(
        timestamp=ts,
        commit=commit,
        phase=phase,
        decision=decision.value,
        metric_value=metric_str,
        description=desc,
    )
    state_mgr.append_result(row, branch_id)

    detail = f"# Iteration {state.iteration_count + 1}\n\n"
    detail += f"- **Commit:** {commit}\n"
    detail += f"- **Decision:** {decision.value}\n"
    detail += f"- **Metric:** {metric_str}\n"
    detail += f"- **Description:** {desc}\n"
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
            allowed_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS"],
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
