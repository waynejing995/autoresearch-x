#!/bin/bash
# run-control.sh — Activate/deactivate autoresearch-x hooks for a run.
# Usage:
#   run-control.sh activate <run-tag>       — create .active marker
#   run-control.sh switch-branch <branch>   — switch active branch
#   run-control.sh deactivate               — remove .active marker
#   run-control.sh status                   — show current status
#
# Called by the skill during setup (activate), branch switching, and completion (deactivate).

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
BASE_DIR="$PROJECT_DIR/.autoresearch-x"

action="${1:-status}"
arg2="${2:-}"  # run_tag for activate, branch_id for switch-branch

case "$action" in
    activate)
        if [[ -z "$arg2" ]]; then
            echo "Error: run tag required. Usage: run-control.sh activate <run-tag>" >&2
            exit 1
        fi
        if [[ ! -d "$BASE_DIR/$arg2" ]]; then
            echo "Error: run directory '$BASE_DIR/$arg2' does not exist." >&2
            exit 1
        fi
        # v2 format: <tag>:main (backward compat: hooks parse both formats)
        echo "${arg2}:main" > "$BASE_DIR/.active"
        echo "Hooks activated for run: $arg2 (branch: main)"
        ;;
    switch-branch)
        # Switch the active branch within the current run.
        # Usage: run-control.sh switch-branch <branch_id>
        # Called by the outer loop (Branch Manager) when rotating branches.
        if [[ -z "$arg2" ]]; then
            echo "Error: branch_id required. Usage: run-control.sh switch-branch <branch>" >&2
            exit 1
        fi
        if [[ ! -f "$BASE_DIR/.active" ]]; then
            echo "Error: no active run. Activate a run first." >&2
            exit 1
        fi
        current_tag=$(cut -d: -f1 < "$BASE_DIR/.active")
        echo "${current_tag}:${arg2}" > "$BASE_DIR/.active"
        echo "Switched active branch to: $arg2"
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
            active_content=$(cat "$BASE_DIR/.active")
            active_tag="${active_content%%:*}"
            active_branch="${active_content#*:}"
            # Handle v1 format (no colon)
            if [[ "$active_tag" == "$active_branch" && "$active_content" != *:* ]]; then
                active_branch="main"
            fi
            echo "Active run: $active_tag | branch: $active_branch"

            # Show branch-specific results if branching is active
            branch_tsv="$BASE_DIR/$active_tag/branches/$active_branch/results.tsv"
            if [[ -f "$branch_tsv" ]]; then
                rows=$(tail -n +2 "$branch_tsv" | wc -l | tr -d ' ')
                echo "Iterations on branch '$active_branch': $rows"
            elif [[ -f "$BASE_DIR/$active_tag/results.tsv" ]]; then
                rows=$(tail -n +2 "$BASE_DIR/$active_tag/results.tsv" | wc -l | tr -d ' ')
                echo "Iterations (single-branch mode): $rows"
            fi

            # Show branch registry summary if it exists
            branches_file="$BASE_DIR/$active_tag/branches.tsv"
            if [[ -f "$branches_file" ]]; then
                echo "Branches:"
                while IFS=$'\t' read -r bid _ bstatus _ biters bmetric _ _; do
                    [[ "$bid" == "branch_id" ]] && continue
                    echo "  $bid: $bstatus ($biters iters, best: ${bmetric:--})"
                done < "$branches_file"
            fi
        else
            echo "No active run. Hooks are dormant."
        fi
        ;;
    *)
        echo "Unknown action: $action. Use: activate, switch-branch, deactivate, status" >&2
        exit 1
        ;;
esac
