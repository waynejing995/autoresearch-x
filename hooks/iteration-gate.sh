#!/bin/bash
# Hook: iteration-gate (PostToolUse on Bash)
# After a git commit, checks that the previous iteration's tracking
# artifacts exist. Blocks progression if artifacts are missing.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

# Always consume stdin first
consume_stdin

# Skip if no active run
find_active_run || pass_silently

# Only trigger on git commit commands
command=$(echo "$HOOK_INPUT" | jq -r '.tool_input.command // empty')
[[ "$command" == *"git commit"* ]] || pass_silently

# ─── Check: Previous iteration fully recorded? ───────────────────
# If results.tsv has rows, verify the LAST recorded iteration has its
# detail file. This catches the case where Claude committed new code
# but forgot to write iterations/<commit>.md for the previous iteration.

tsv_rows=$(get_iteration_count)

if [[ "$tsv_rows" -gt 0 ]]; then
    last_commit=$(get_last_recorded_commit)
    if [[ -n "$last_commit" ]]; then
        if [[ ! -f "$ITERATIONS_DIR/$last_commit.md" ]]; then
            block_with_message "INCOMPLETE ITERATION: iterations/$last_commit.md is missing for the last recorded iteration (commit $last_commit). The 3-artifact rule requires: (1) commit, (2) results.tsv row, (3) iterations/<commit>.md. Create the detail file BEFORE making new commits."
        fi
    fi
fi

# ─── Check: No unrecorded iteration gap ──────────────────────────
# Compare the number of "iter N:" commit messages on the current branch
# against results.tsv row count. A gap means an iteration was committed
# but never recorded in results.tsv.
#
# Only count commits since the run branch diverged from its parent.
# The branch is autoresearch-x/<tag>, find the merge-base to scope the count.
run_branch="autoresearch-x/$RUN_TAG"
merge_base=$(git merge-base "$run_branch" "$run_branch@{upstream}" 2>/dev/null \
    || git merge-base "$run_branch" main 2>/dev/null \
    || git merge-base "$run_branch" master 2>/dev/null \
    || echo "")

if [[ -n "$merge_base" ]]; then
    iter_commits=$(git log --oneline "$merge_base"..HEAD 2>/dev/null | grep -cE "^[a-f0-9]+ iter [0-9]" || echo 0)
else
    # Fallback: no merge-base found, count all (original behavior)
    iter_commits=$(git log --oneline HEAD 2>/dev/null | grep -cE "^[a-f0-9]+ iter [0-9]" || echo 0)
fi

if [[ "$iter_commits" -gt "$tsv_rows" ]]; then
    gap=$((iter_commits - tsv_rows))
    block_with_message "TRACKING GAP: Found $iter_commits iteration commits but only $tsv_rows rows in results.tsv. $gap iteration(s) not recorded. Append the missing row(s) to results.tsv BEFORE making new commits."
fi

pass_silently
