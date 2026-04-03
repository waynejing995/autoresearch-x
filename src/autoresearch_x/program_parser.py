"""Program.md parser — extracts eval_command, metric, target, scope."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional


def parse_program_md(path: str | Path) -> Dict[str, object]:
    """Parse a program.md file and extract structured fields.

    Returns dict with: eval_command, metric_name, target, scope, readonly,
    mode, target_desc, max_iterations, timeout_minutes.
    """
    text = Path(path).read_text()
    result: Dict[str, object] = {
        "eval_command": "",
        "metric_name": "",
        "target": "",
        "scope": [],
        "readonly": [],
        "mode": "",
        "target_desc": "",
        "max_iterations": None,
        "timeout_minutes": None,
    }

    result["mode"] = _extract_mode(text)
    result["target_desc"] = _extract_target(text)
    result["scope"], result["readonly"] = _extract_scope(text)
    result["eval_command"], result["metric_name"], result["target"] = _extract_evaluation(text)
    result["max_iterations"], result["timeout_minutes"] = _extract_constraints(text)

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
            scope.append(stripped[len("- modify:") :].strip())
        elif in_scope and stripped.startswith("- readonly:"):
            readonly.append(stripped[len("- readonly:") :].strip())
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
            val = stripped[len("- command:") :].strip()
            eval_command = val.strip("`")
        elif stripped.startswith("- metric:"):
            metric_name = stripped[len("- metric:") :].strip()
        elif stripped.startswith("- target:"):
            target = stripped[len("- target:") :].strip()
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
