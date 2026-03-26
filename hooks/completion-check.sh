#!/bin/bash
# Hook: completion-check (Stop)
# When the main agent tries to stop, verify:
# 1. Last iteration fully recorded (results.tsv + iterations/<commit>.md)
# 2. report.md exists with a finalized conclusion section
# 3. Hooks deactivated

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

# Always consume stdin first
consume_stdin

# Skip if no active run
find_active_run || pass_silently

# ─── Check 1: Last iteration fully recorded? ──────────────────────
tsv_rows=$(get_iteration_count)

if [[ "$tsv_rows" -gt 0 ]]; then
    last_commit=$(get_last_recorded_commit)

    if [[ -n "$last_commit" ]]; then
        if [[ ! -f "$ITERATIONS_DIR/$last_commit.md" ]]; then
            block_stop "Cannot stop: iterations/$last_commit.md is missing. The last iteration is not fully recorded. Create the detail file before stopping."
        fi
    fi
fi

# ─── Check 2: report.md exists? ───────────────────────────────────
if [[ "$tsv_rows" -gt 0 && ! -f "$ACTIVE_RUN_DIR/report.md" ]]; then
    block_stop "Cannot stop: report.md does not exist. Generate the final run report before stopping."
fi

# ─── Check 3: report.md has final summary section? ────────────────
if [[ -f "$ACTIVE_RUN_DIR/report.md" ]]; then
    # Check for any of the common final section headers
    if ! grep -qiE '^##\s+(Conclusion|Final Summary|Summary|Final Report|Results Summary)' "$ACTIVE_RUN_DIR/report.md"; then
        block_stop "Cannot stop: report.md is missing a final summary section. Before stopping, add a '## Conclusion' section to report.md that includes: (1) whether the target was met, (2) total iterations and keep/discard ratio, (3) key findings or best result achieved, (4) recommendations for next steps. Then deactivate hooks with: bash \${CLAUDE_PLUGIN_ROOT}/hooks/run-control.sh deactivate"
    fi
fi

# ─── Summary: Show run status on stop ─────────────────────────────
# If we got this far, all checks passed. Show summary.
{
    total=$tsv_rows
    keeps=$(tail -n +2 "$RESULTS_TSV" 2>/dev/null | awk -F'\t' '$4=="keep"' | wc -l | tr -d ' ')
    discards=$(tail -n +2 "$RESULTS_TSV" 2>/dev/null | awk -F'\t' '$4=="discard"' | wc -l | tr -d ' ')
    crashes=$(tail -n +2 "$RESULTS_TSV" 2>/dev/null | awk -F'\t' '$4=="crash"' | wc -l | tr -d ' ')
    last_metric=$(tail -n1 "$RESULTS_TSV" 2>/dev/null | cut -f7)
    target_line=$(grep -A1 "^## Target" "$PROGRAM_MD" 2>/dev/null | tail -1 | sed 's/^[[:space:]]*//' || echo "unknown")

    # Read mode from program.md
    mode=$(grep -A1 "^## Mode" "$PROGRAM_MD" 2>/dev/null | tail -1 | sed 's/^[[:space:]]*//' || echo "unknown")

    echo "[autoresearch-x] Run '$RUN_TAG' ($mode mode) complete."
    echo "  Iterations: $total total ($keeps kept, $discards discarded, $crashes crashed)"
    echo "  Last metric: ${last_metric:--} | Target: $target_line"
    echo "  Report: $ACTIVE_RUN_DIR/report.md"
    echo ""
    echo "  REMINDER: Deactivate hooks by running: bash \${CLAUDE_PLUGIN_ROOT}/hooks/run-control.sh deactivate"
}

exit 0
