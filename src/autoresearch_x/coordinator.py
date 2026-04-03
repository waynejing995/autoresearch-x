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
    TeammateRole,
    TeammateStatus,
    WorkerResult,
    parse_teammate_output,
)
from .program_parser import parse_program_md
from .state_manager import StateManager
from .teammate_manager import TeammateManager


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

    team_name = f"autoresearch-x:{tag}"
    tm = TeammateManager(
        team_name=team_name,
        max_turns=max_turns,
        idle_timeout=idle_timeout,
    )
    branch_mgr = BranchManager(state_mgr, str(proj))

    logger.info(f"Starting run: tag={tag} mode={state.mode.value} target={state.target}")
    _run_loop(state, state_mgr, tm, branch_mgr, proj, debug_dump=debug_dump)


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
    team_name = f"autoresearch-x:{tag}"
    tm = TeammateManager(team_name=team_name)
    branch_mgr = BranchManager(state_mgr, str(proj))

    logger.info(f"Resuming run: tag={tag} iteration={state.iteration_count}")
    _run_loop(state, state_mgr, tm, branch_mgr, proj)


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
    tm: TeammateManager,
    branch_mgr: BranchManager,
    proj: Path,
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
                _trigger_strategist(state, state_mgr, tm, branch_mgr, proj)
            continue

        state_mgr.clear_outbox()

        planner_result = _run_planner(state, state_mgr, tm, proj)
        if planner_result is None:
            agent_name = f"planner-iter-{state.iteration_count + 1}"
            exit_code = tm.get_exit_code(agent_name)
            raw_log = tm.get_raw_log(agent_name)[-500:]
            logger.error(f"Planner failed (exit={exit_code}): {raw_log}")
            if state.crash_count >= MAX_AGENT_RETRIES - 1:
                logger.error(f"Planner retry limit reached ({MAX_AGENT_RETRIES}), aborting")
                state.status = "agent_retry_exhausted"
                state_mgr.save_state(state)
                break
            state.crash_count += 1
            state_mgr.save_state(state)
            continue

        state.crash_count = 0

        worker_result = _run_worker(state, state_mgr, tm, planner_result, proj)
        if worker_result is None:
            agent_name = f"worker-iter-{state.iteration_count + 1}"
            exit_code = tm.get_exit_code(agent_name)
            raw_log = tm.get_raw_log(agent_name)[-500:]
            logger.error(f"Worker failed (exit={exit_code}): {raw_log}")
            if state.crash_count >= MAX_AGENT_RETRIES - 1:
                logger.error(f"Worker retry limit reached ({MAX_AGENT_RETRIES}), aborting")
                state.status = "agent_retry_exhausted"
                state_mgr.save_state(state)
                break
            state.crash_count += 1
            state_mgr.save_state(state)
            continue

        eval_result = _run_evaluator(state, state_mgr, tm, proj)
        if eval_result is None:
            agent_name = f"evaluator-iter-{state.iteration_count + 1}"
            exit_code = tm.get_exit_code(agent_name)
            raw_log = tm.get_raw_log(agent_name)[-500:]
            logger.error(f"Evaluator failed (exit={exit_code}): {raw_log}")
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
    tm: TeammateManager,
    proj: Path,
    debug_dump: bool = False,
) -> Optional[PlannerResult]:
    program_text = Path(state.program_md_path).read_text() if state.program_md_path else ""
    task = {
        "role": "planner",
        "iteration": state.iteration_count + 1,
        "task": "Analyze history and propose ONE change to reduce latency",
        "state_path": str(state_mgr.state_path),
        "results_path": str(state_mgr.results_path),
        "iterations_dir": str(state_mgr.iterations_dir),
        "program_md": program_text,
    }
    state_mgr.write_inbox("planner", task)

    outbox_path = state_mgr.outbox_dir / "planner.json"
    prompt = (
        f"Read the task from {state_mgr.inbox_dir / 'planner.json'}. "
        f"Execute the task. "
        f"Write your result as a JSON object to {outbox_path}. "
        f"Then output ONLY the JSON object, wrapped in ```json code blocks."
    )
    agent_name = tm.spawn(
        TeammateRole.PLANNER,
        state.iteration_count + 1,
        prompt,
        str(proj),
    )
    status = tm.wait_for_idle(agent_name)
    logger.info(f"Planner status: {status.value}")
    if status != TeammateStatus.IDLE:
        return None

    # Primary: read the outbox file the agent wrote
    raw_output = state_mgr.read_outbox("planner") or ""

    # Fallback: extract from Claude's JSON envelope
    if not raw_output:
        raw_output, raw_envelope = tm.get_output(agent_name)
        if debug_dump and raw_envelope:
            dump_file = state_mgr.run_dir / f"planner-iter-{state.iteration_count + 1}-raw.json"
            dump_file.write_text(raw_envelope)
            logger.info(f"Dumped raw envelope to {dump_file}")

    if debug_dump and raw_output:
        dump_file = state_mgr.run_dir / f"planner-iter-{state.iteration_count + 1}-output.txt"
        dump_file.write_text(raw_output)
        logger.info(f"Dumped planner output to {dump_file}")

    if not raw_output:
        logger.error("Planner produced no output at all")
        return None
    try:
        data = parse_teammate_output(raw_output)
        return PlannerResult(**data)
    except Exception as e:
        logger.error(f"Failed to parse planner output: {e}")
        logger.debug(f"Raw output that failed: {raw_output[:1000]}")
        return None
    try:
        data = parse_teammate_output(raw_output)
        return PlannerResult(**data)
    except Exception as e:
        logger.error(f"Failed to parse planner output: {e}")
        logger.debug(f"Raw output that failed: {raw_output[:1000]}")
        return None


def _run_worker(
    state: RunState,
    state_mgr: StateManager,
    tm: TeammateManager,
    plan: PlannerResult,
    proj: Path,
    debug_dump: bool = False,
) -> Optional[WorkerResult]:
    plan_data = plan.plan or {}
    task = {
        "role": "worker",
        "iteration": state.iteration_count + 1,
        "task": "Execute the planned change",
        "plan": plan_data,
        "scope": state.scope,
        "readonly": state.readonly,
        "program_md": Path(state.program_md_path).read_text() if state.program_md_path else "",
    }
    state_mgr.write_inbox("worker", task)

    outbox_path = state_mgr.outbox_dir / "worker.json"
    prompt = (
        f"Read the task from {state_mgr.inbox_dir / 'worker.json'}. "
        f"Execute the task. "
        f"Write your result as a JSON object to {outbox_path}. "
        f"Then output ONLY the JSON object, wrapped in ```json code blocks."
    )
    agent_name = tm.spawn(
        TeammateRole.WORKER,
        state.iteration_count + 1,
        prompt,
        str(proj),
    )
    status = tm.wait_for_idle(agent_name)
    logger.info(f"Worker status: {status.value}")
    if status != TeammateStatus.IDLE:
        return None

    raw_output = state_mgr.read_outbox("worker") or ""
    if not raw_output:
        raw_output, raw_envelope = tm.get_output(agent_name)
        if debug_dump and raw_envelope:
            dump_file = state_mgr.run_dir / f"worker-iter-{state.iteration_count + 1}-raw.json"
            dump_file.write_text(raw_envelope)
            logger.info(f"Dumped worker raw envelope to {dump_file}")

    if debug_dump and raw_output:
        dump_file = state_mgr.run_dir / f"worker-iter-{state.iteration_count + 1}-output.txt"
        dump_file.write_text(raw_output)
        logger.info(f"Dumped worker output to {dump_file}")

    if not raw_output:
        logger.error("Worker produced no output at all")
        return None
    try:
        data = parse_teammate_output(raw_output)
        return WorkerResult(**data)
    except Exception as e:
        logger.error(f"Failed to parse worker output: {e}")
        logger.debug(f"Raw output that failed: {raw_output[:1000]}")
        return None


def _run_evaluator(
    state: RunState,
    state_mgr: StateManager,
    tm: TeammateManager,
    proj: Path,
) -> Optional[EvaluatorResult]:
    task = {
        "role": "evaluator",
        "iteration": state.iteration_count + 1,
        "task": "Run evaluation and extract metric",
        "eval_command": state.eval_command,
        "metric_name": state.metric_name,
        "target": state.target_expr,
    }
    state_mgr.write_inbox("evaluator", task)

    outbox_path = state_mgr.outbox_dir / "evaluator.json"
    prompt = (
        f"Read the task from {state_mgr.inbox_dir / 'evaluator.json'}. "
        f"Execute the task. "
        f"Write your result as a JSON object to {outbox_path}. "
        f"Then output ONLY the JSON object, wrapped in ```json code blocks."
    )
    agent_name = tm.spawn(
        TeammateRole.EVALUATOR,
        state.iteration_count + 1,
        prompt,
        str(proj),
    )
    status = tm.wait_for_idle(agent_name)
    logger.info(f"Evaluator status: {status.value}")
    if status != TeammateStatus.IDLE:
        return None

    raw_output, _ = tm.get_output(agent_name)
    if raw_output:
        logger.debug(f"Evaluator raw output: {raw_output[:500]}")
    else:
        raw_output = state_mgr.read_outbox("evaluator") or ""
        logger.debug(f"Evaluator outbox fallback: {raw_output[:500]}")

    if not raw_output:
        logger.error("Evaluator produced no output at all")
        return None
    try:
        data = parse_teammate_output(raw_output)
        return EvaluatorResult(**data)
    except Exception as e:
        logger.error(f"Failed to parse evaluator output: {e}")
        logger.debug(f"Raw output that failed: {raw_output[:1000]}")
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
    tm: TeammateManager,
    branch_mgr: BranchManager,
    proj: Path,
) -> None:
    task = {
        "role": "strategist",
        "task": "Analyze all branch failures and propose new strategies",
        "all_results_path": str(state_mgr.all_results_path),
        "program_md_path": state.program_md_path,
        "branches_path": str(state_mgr.branches_path),
        "iterations_dir": str(state_mgr.iterations_dir),
    }
    state_mgr.write_inbox("strategist", task)

    agent_name = tm.spawn(
        TeammateRole.STRATEGIST,
        state.iteration_count + 1,
        f"Read {state_mgr.inbox_dir / 'strategist.json'} and execute the task",
        str(proj),
    )
    status = tm.wait_for_idle(agent_name, timeout=600)
    if status == TeammateStatus.IDLE:
        output = state_mgr.read_outbox("strategist")
        if output:
            try:
                data = parse_teammate_output(output)
                logger.info(f"Strategist analysis complete: {json.dumps(data, indent=2)[:500]}")
            except Exception:
                pass
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


def _generate_tag(mode: str, target: str) -> str:
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%b%d").lower()
    topic = target.split()[0] if target else mode
    return f"{date_str}-{topic}"
