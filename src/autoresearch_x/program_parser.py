"""Program definition parser — supports YAML source and legacy markdown format.

YAML is the canonical input format. Coordinator parses YAML → fills RunState →
generates program.md as human-readable output.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


def parse_program(path: str | Path) -> Dict[str, Any]:
    """Parse a program definition file (YAML or markdown).

    Auto-detects format by extension: .yaml/.yml → YAML, .md → markdown.
    Returns a unified dict with all fields needed by RunState.
    """
    path = Path(path)
    if path.suffix in (".yaml", ".yml"):
        return _parse_yaml(path)
    else:
        return parse_program_md(path)


# ---------------------------------------------------------------------------
# YAML parser (canonical)
# ---------------------------------------------------------------------------


def _parse_yaml(path: Path) -> Dict[str, Any]:
    """Parse YAML program definition.

    Returns dict with: mode, target_desc, scope, readonly, eval_command,
    metric_name, target, max_iterations, timeout_minutes, name, context,
    checklist, phase_permissions.
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping, got {type(data).__name__}")

    scope_block = data.get("scope") or {}
    modify_list = scope_block.get("modify", []) if isinstance(scope_block, dict) else []
    readonly_list = scope_block.get("readonly", []) if isinstance(scope_block, dict) else []

    eval_block = data.get("evaluation") or {}
    constraints = data.get("constraints") or {}

    max_iter, timeout = _parse_constraints_dict(constraints)

    return {
        "name": data.get("name", ""),
        "mode": data.get("mode", "optimize"),
        "target_desc": data.get("target", ""),
        "scope": modify_list,
        "readonly": readonly_list,
        "eval_command": eval_block.get("command", ""),
        "metric_name": eval_block.get("metric", ""),
        "target": eval_block.get("target", ""),
        "max_iterations": max_iter,
        "timeout_minutes": timeout,
        "context": data.get("context", ""),
        "checklist": data.get("checklist", []),
        "phase_permissions": data.get("phase_permissions", {}),
    }


def _parse_constraints_dict(constraints: dict) -> Tuple[Optional[int], Optional[int]]:
    """Parse constraints from a dict (YAML format)."""
    max_iterations = constraints.get("max_iterations")
    if max_iterations is not None:
        max_iterations = int(max_iterations)

    timeout_raw = constraints.get("timeout")
    timeout_minutes = None
    if timeout_raw is not None:
        timeout_minutes = _parse_timeout(str(timeout_raw))

    return max_iterations, timeout_minutes


def _parse_timeout(value: str) -> Optional[int]:
    """Parse timeout string like '30min', '1h', '90' → minutes."""
    value = value.strip().lower()
    m = re.match(r"(\d+)\s*(min|minute|h|hour)?", value)
    if not m:
        return None
    val = int(m.group(1))
    unit = (m.group(2) or "min").lower()
    if unit.startswith("h"):
        return val * 60
    return val


def generate_program_md(data: Dict[str, Any]) -> str:
    """Generate program.md content from parsed YAML data.

    This is the human-readable output that Planner/Worker read.
    """
    lines = [f"# autoresearch-x: {data.get('name', 'Run')}"]

    lines.append("")
    lines.append("## Target")
    lines.append(data.get("target_desc", ""))

    lines.append("")
    lines.append("## Mode")
    lines.append(data.get("mode", "optimize"))

    # Checklist
    checklist = data.get("checklist", [])
    if checklist:
        lines.append("")
        lines.append("## Checklist")
        for item in checklist:
            lines.append(f"- [ ] {item}")

    # Scope
    lines.append("")
    lines.append("## Scope")
    for s in data.get("scope", []):
        lines.append(f"- modify: {s}")
    for s in data.get("readonly", []):
        lines.append(f"- readonly: {s}")

    # Evaluation
    lines.append("")
    lines.append("## Evaluation")
    eval_cmd = data.get("eval_command", "")
    lines.append(f"- command: `{eval_cmd}`")
    metric = data.get("metric_name", "")
    if metric:
        lines.append(f"- metric: {metric}")
    target = data.get("target", "")
    if target:
        lines.append(f"- target: {target}")

    # Constraints
    lines.append("")
    lines.append("## Constraints")
    max_iter = data.get("max_iterations")
    if max_iter:
        lines.append(f"- max_iterations: {max_iter}")
    timeout = data.get("timeout_minutes")
    if timeout:
        lines.append(f"- timeout: {timeout}min")

    # Phase permissions (debug mode)
    phase_perms = data.get("phase_permissions", {})
    if phase_perms:
        lines.append("")
        lines.append("## Phase Permissions")
        for phase, perms in phase_perms.items():
            tools = perms.get("allowed_tools", [])
            lines.append(f"- {phase}: {', '.join(tools)}")

    # Context
    context = data.get("context", "")
    if context:
        lines.append("")
        lines.append("## Context")
        lines.append(context.strip())

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Legacy markdown parser (backward compat)
# ---------------------------------------------------------------------------


def parse_program_md(path: str | Path) -> Dict[str, Any]:
    """Parse a program.md file and extract structured fields.

    Returns dict with: eval_command, metric_name, target, scope, readonly,
    mode, target_desc, max_iterations, timeout_minutes.
    """
    text = Path(path).read_text()
    result: Dict[str, Any] = {
        "eval_command": "",
        "metric_name": "",
        "target": "",
        "scope": [],
        "readonly": [],
        "mode": "",
        "target_desc": "",
        "max_iterations": None,
        "timeout_minutes": None,
        "context": "",
        "checklist": [],
        "phase_permissions": {},
    }

    result["mode"] = _extract_mode(text)
    result["target_desc"] = _extract_target(text)
    result["scope"], result["readonly"] = _extract_scope(text)
    result["eval_command"], result["metric_name"], result["target"] = _extract_evaluation(text)
    result["max_iterations"], result["timeout_minutes"] = _extract_constraints(text)
    result["checklist"] = _extract_checklist(text)
    result["context"] = _extract_context(text)

    return result


def _extract_mode(text: str) -> str:
    m = re.search(r"##\s*Mode\s*\n\s*(optimize|debug|investigate)", text, re.IGNORECASE)
    return m.group(1).strip().lower() if m else ""


def _extract_target(text: str) -> str:
    m = re.search(r"##\s*Target\s*\n\s*(.+)", text)
    return m.group(1).strip() if m else ""


def _extract_scope(text: str) -> tuple[List[str], List[str]]:
    scope: List[str] = []
    readonly: List[str] = []
    in_scope = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## Scope"):
            in_scope = True
            continue
        if in_scope and stripped.startswith("## "):
            break
        if in_scope and stripped.startswith("- modify:"):
            scope.append(stripped[len("- modify:"):].strip())
        elif in_scope and stripped.startswith("- readonly:"):
            readonly.append(stripped[len("- readonly:"):].strip())
    return scope, readonly


def _extract_evaluation(text: str) -> tuple[str, str, str]:
    eval_command = ""
    metric_name = ""
    target = ""
    in_eval = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## Evaluation"):
            in_eval = True
            continue
        if in_eval and stripped.startswith("## "):
            break
        if not in_eval:
            continue
        if stripped.startswith("- command:"):
            val = stripped[len("- command:"):].strip()
            eval_command = val.strip("`")
        elif stripped.startswith("- metric:"):
            metric_name = stripped[len("- metric:"):].strip()
        elif stripped.startswith("- target:"):
            target = stripped[len("- target:"):].strip()
    return eval_command, metric_name, target


def _extract_constraints(text: str) -> tuple[Optional[int], Optional[int]]:
    max_iterations = None
    timeout_minutes = None
    in_constraints = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## Constraints"):
            in_constraints = True
            continue
        if in_constraints and stripped.startswith("## "):
            break
        if not in_constraints:
            continue
        m_iter = re.match(r"-?\s*max_iterations:\s*(\d+)", stripped)
        if m_iter:
            max_iterations = int(m_iter.group(1))
        m_timeout = re.match(r"-?\s*timeout:\s*(\d+)\s*(min|minute|h|hour)?", stripped)
        if m_timeout:
            val = int(m_timeout.group(1))
            unit = (m_timeout.group(2) or "min").lower()
            if unit.startswith("h"):
                timeout_minutes = val * 60
            else:
                timeout_minutes = val
    return max_iterations, timeout_minutes


def _extract_checklist(text: str) -> List[str]:
    """Extract checklist items from ## Checklist section."""
    items: List[str] = []
    in_checklist = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## Checklist"):
            in_checklist = True
            continue
        if in_checklist and stripped.startswith("## "):
            break
        if in_checklist:
            m = re.match(r"- \[[ x]\]\s*(.+)", stripped)
            if m:
                items.append(m.group(1).strip())
    return items


def _extract_context(text: str) -> str:
    """Extract free-text from ## Context section."""
    in_context = False
    lines: List[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## Context"):
            in_context = True
            continue
        if in_context and stripped.startswith("## "):
            break
        if in_context:
            lines.append(line)
    return "\n".join(lines).strip()
