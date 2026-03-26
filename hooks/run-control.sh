#!/bin/bash
# run-control.sh — Activate/deactivate autoresearch-x hooks for a run.
# Usage:
#   run-control.sh activate <run-tag>   — create .active marker
#   run-control.sh deactivate           — remove .active marker
#   run-control.sh status               — show current status
#
# Called by the skill during setup (activate) and completion (deactivate).

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
BASE_DIR="$PROJECT_DIR/.autoresearch-x"

action="${1:-status}"
run_tag="${2:-}"

case "$action" in
    activate)
        if [[ -z "$run_tag" ]]; then
            echo "Error: run tag required. Usage: run-control.sh activate <run-tag>" >&2
            exit 1
        fi
        if [[ ! -d "$BASE_DIR/$run_tag" ]]; then
            echo "Error: run directory '$BASE_DIR/$run_tag' does not exist." >&2
            exit 1
        fi
        echo "$run_tag" > "$BASE_DIR/.active"
        echo "Hooks activated for run: $run_tag"
        ;;
    deactivate)
        if [[ -f "$BASE_DIR/.active" ]]; then
            rm "$BASE_DIR/.active"
            echo "Hooks deactivated."
        else
            echo "No active run to deactivate."
        fi
        ;;
    status)
        if [[ -f "$BASE_DIR/.active" ]]; then
            active_tag=$(cat "$BASE_DIR/.active")
            echo "Active run: $active_tag"
            if [[ -f "$BASE_DIR/$active_tag/results.tsv" ]]; then
                rows=$(tail -n +2 "$BASE_DIR/$active_tag/results.tsv" | wc -l)
                echo "Iterations recorded: $rows"
            fi
        else
            echo "No active run. Hooks are dormant."
        fi
        ;;
    *)
        echo "Unknown action: $action. Use: activate, deactivate, status" >&2
        exit 1
        ;;
esac
