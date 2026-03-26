#!/bin/bash
# Hook: scope-guard (PreToolUse on Edit|Write)
# Blocks edits to files outside the declared scope in program.md.
# Also blocks edits to tracking files (.autoresearch-x/).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

# Always consume stdin first to avoid broken pipe
consume_stdin

# Skip if no active run
find_active_run || pass_silently

# Parse hook input
file_path=$(echo "$HOOK_INPUT" | jq -r '.tool_input.file_path // empty')

[[ -n "$file_path" ]] || pass_silently

# ─── Rule 1: Never touch tracking files ───────────────────────────
if [[ "$file_path" == *".autoresearch-x/"* ]]; then
    # Extract the path after the run-tag directory
    tracking_path="${file_path##*.autoresearch-x/*/}"
    case "$tracking_path" in
        results.tsv|report.md|matrix.md|iterations/*.md|program.md)
            # These are tracking artifacts the main agent IS supposed to write
            pass_silently
            ;;
        *)
            deny_tool_use "Cannot modify tracking file '$file_path'. Only results.tsv, report.md, matrix.md, iterations/*.md, and program.md are allowed."
            ;;
    esac
fi

# ─── Rule 2: Scope enforcement ────────────────────────────────────
parse_scope

# If no scope defined, allow all (scope is optional)
if [[ ${#SCOPE_MODIFY[@]} -eq 0 && ${#SCOPE_READONLY[@]} -eq 0 ]]; then
    pass_silently
fi

# Resolve file_path relative to project dir
project_dir="${CLAUDE_PROJECT_DIR:-.}"
rel_path="${file_path#"$project_dir"/}"

# Check if file is in modify scope
for pattern in "${SCOPE_MODIFY[@]}"; do
    # Support glob patterns via bash pattern matching
    # shellcheck disable=SC2053
    if [[ "$rel_path" == $pattern ]]; then
        pass_silently
    fi
done

# Check if file is in readonly scope (blocked for writes)
for pattern in "${SCOPE_READONLY[@]}"; do
    # shellcheck disable=SC2053
    if [[ "$rel_path" == $pattern ]]; then
        deny_tool_use "'$rel_path' is declared as readonly in program.md scope. You may read it but not modify it. If you need to modify this file, update the scope in program.md first."
    fi
done

# File not in any scope — warn but don't block
# (scope might use directory patterns, or user may have forgotten to list it)
warn_with_message "'$rel_path' is not explicitly listed in program.md scope. Scoped modify files: ${SCOPE_MODIFY[*]:-none}. Verify this file should be modified."
