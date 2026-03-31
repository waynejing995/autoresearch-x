#!/bin/bash
# Shared library for autoresearch-x hooks
# All hooks source this for common state detection and utilities.

set -euo pipefail

# ─── Stdin Consumption ────────────────────────────────────────────
# Read stdin once into HOOK_INPUT. Must be called before any exit
# to avoid broken pipe errors from the hook runner.
HOOK_INPUT=""
consume_stdin() {
    HOOK_INPUT=$(cat)
}

# ─── Active Run Detection ──────────────────────────────────────────
# Finds the active run directory. Returns 1 if no run is active.
# Sets: ACTIVE_RUN_DIR, RUN_TAG, ACTIVE_BRANCH, PROGRAM_MD,
#       RESULTS_TSV, ITERATIONS_DIR, BRANCHES_TSV
find_active_run() {
    local project_dir="${CLAUDE_PROJECT_DIR:-.}"
    local base_dir="$project_dir/.autoresearch-x"

    # No .autoresearch-x directory at all
    [[ -d "$base_dir" ]] || return 1

    # Look for the .active marker file
    local active_file="$base_dir/.active"
    [[ -f "$active_file" ]] || return 1

    local active_content
    active_content=$(cat "$active_file")
    [[ -n "$active_content" ]] || return 1

    # Parse <tag>:<branch_id> format
    # Backward compat: no colon = tag only, assume main branch
    if [[ "$active_content" == *:* ]]; then
        RUN_TAG="${active_content%%:*}"
        ACTIVE_BRANCH="${active_content#*:}"
    else
        RUN_TAG="$active_content"
        ACTIVE_BRANCH="main"
    fi

    ACTIVE_RUN_DIR="$base_dir/$RUN_TAG"
    [[ -d "$ACTIVE_RUN_DIR" ]] || return 1

    PROGRAM_MD="$ACTIVE_RUN_DIR/program.md"

    # Branch-aware path resolution:
    # If branches/<branch_id>/ exists → use branch-specific paths
    # Otherwise → fall back to top-level (v1 compat / single-branch run)
    local branch_dir="$ACTIVE_RUN_DIR/branches/$ACTIVE_BRANCH"
    if [[ -d "$branch_dir" ]]; then
        RESULTS_TSV="$branch_dir/results.tsv"
        ITERATIONS_DIR="$branch_dir/iterations"
    else
        RESULTS_TSV="$ACTIVE_RUN_DIR/results.tsv"
        ITERATIONS_DIR="$ACTIVE_RUN_DIR/iterations"
    fi

    # Branch registry path (may not exist in v1 runs)
    BRANCHES_TSV="$ACTIVE_RUN_DIR/branches.tsv"

    return 0
}

# ─── Scope Parsing ─────────────────────────────────────────────────
# Extracts modify/readonly scope from program.md
# Sets: SCOPE_MODIFY (array), SCOPE_READONLY (array)
parse_scope() {
    SCOPE_MODIFY=()
    SCOPE_READONLY=()

    [[ -f "$PROGRAM_MD" ]] || return 1

    local in_scope=0
    while IFS= read -r line; do
        # Enter scope section
        if [[ "$line" =~ ^##[[:space:]]+Scope ]]; then
            in_scope=1
            continue
        fi
        # Exit on next section
        if [[ $in_scope -eq 1 && "$line" =~ ^## ]]; then
            break
        fi
        if [[ $in_scope -eq 1 ]]; then
            if [[ "$line" =~ ^-[[:space:]]+modify:[[:space:]]*(.+) ]]; then
                SCOPE_MODIFY+=("${BASH_REMATCH[1]}")
            elif [[ "$line" =~ ^-[[:space:]]+readonly:[[:space:]]*(.+) ]]; then
                SCOPE_READONLY+=("${BASH_REMATCH[1]}")
            fi
        fi
    done < "$PROGRAM_MD"
}

# ─── Eval Command Extraction ──────────────────────────────────────
# Extracts the eval command from program.md
# Sets: EVAL_COMMAND
parse_eval_command() {
    EVAL_COMMAND=""
    [[ -f "$PROGRAM_MD" ]] || return 1

    local in_eval=0
    while IFS= read -r line; do
        if [[ "$line" =~ ^##[[:space:]]+Evaluation ]]; then
            in_eval=1
            continue
        fi
        if [[ $in_eval -eq 1 && "$line" =~ ^## ]]; then
            break
        fi
        if [[ $in_eval -eq 1 && "$line" =~ ^-[[:space:]]+command:[[:space:]]*\`(.+)\` ]]; then
            EVAL_COMMAND="${BASH_REMATCH[1]}"
            return 0
        fi
    done < "$PROGRAM_MD"
}

# ─── Last Commit Detection ────────────────────────────────────────
# Gets the last commit hash from results.tsv
get_last_recorded_commit() {
    [[ -f "$RESULTS_TSV" ]] || return 1
    local last_line
    last_line=$(tail -n1 "$RESULTS_TSV")
    # Skip if it's the header
    [[ "$last_line" == timestamp* ]] && return 1
    echo "$last_line" | cut -f2
}

# ─── Iteration Count ──────────────────────────────────────────────
# Gets the current iteration number (rows in results.tsv minus header)
get_iteration_count() {
    [[ -f "$RESULTS_TSV" ]] || { echo 0; return; }
    local count
    count=$(tail -n +2 "$RESULTS_TSV" | wc -l | tr -d ' ')
    echo "$count"
}

# ─── Output Helpers ───────────────────────────────────────────────

# PreToolUse: deny with message (proper hookSpecificOutput format)
deny_tool_use() {
    local msg="$1"
    cat <<EOF
{"hookSpecificOutput":{"permissionDecision":"deny"},"systemMessage":"[autoresearch-x guardrail] $msg"}
EOF
    exit 0
}

# PostToolUse/general: blocking error (exit 2 = stderr fed back to Claude)
block_with_message() {
    local msg="$1"
    echo "[autoresearch-x guardrail] $msg" >&2
    exit 2
}

# Stop hook: block with JSON decision
block_stop() {
    local msg="$1"
    echo "{\"decision\":\"block\",\"reason\":\"[autoresearch-x] $msg\"}" >&2
    exit 2
}

# Warning (exit 0 = shown in transcript)
warn_with_message() {
    local msg="$1"
    echo "[autoresearch-x warning] $msg"
    exit 0
}

# Silent pass
pass_silently() {
    exit 0
}
