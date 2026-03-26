#!/bin/bash
# Hook: eval-bypass-detector (PostToolUse on Bash)
# Detects when the main agent runs the eval command directly
# instead of dispatching the evaluator subagent.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

# Always consume stdin first
consume_stdin

# Skip if no active run
find_active_run || pass_silently

# Parse the executed command
command=$(echo "$HOOK_INPUT" | jq -r '.tool_input.command // empty')
[[ -n "$command" ]] || pass_silently

# ─── Rule: Eval command bypass detection ──────────────────────────
parse_eval_command

# If no eval command defined in program.md, nothing to check
[[ -n "$EVAL_COMMAND" ]] || pass_silently

# Normalize: strip whitespace, collapse spaces
norm_cmd=$(echo "$command" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | tr -s ' ')
norm_eval=$(echo "$EVAL_COMMAND" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | tr -s ' ')

# Direct match: command contains the eval command string
if [[ "$norm_cmd" == *"$norm_eval"* ]]; then
    block_with_message "EVAL BYPASS: You ran the evaluation command directly ('$command'). Dispatch the Evaluator subagent instead: Agent(subagent_type=\"autoresearch-x:evaluator\", ...). Separation of concerns prevents rationalization bias."
fi

# Fuzzy match: same base executable as eval command
# (catches variations like 'pytest tests/' when eval is 'pytest tests/test_auth.py -x')
eval_base=$(echo "$norm_eval" | awk '{print $1}')
cmd_base=$(echo "$norm_cmd" | awk '{print $1}')

# Exclude common utility commands from fuzzy matching
case "$eval_base" in
    git|date|cat|echo|ls|cd|mkdir|cp|mv|rm|grep|rg|find|jq|head|tail|wc|sed|awk|sort|curl|wget|pip|uv|npm|node|python3)
        # Too generic to flag — these could be anything
        ;;
    *)
        if [[ "$cmd_base" == "$eval_base" ]]; then
            warn_with_message "You ran '$cmd_base' which matches the eval command base ('$norm_eval'). If this is evaluation-related, dispatch the Evaluator subagent instead."
        fi
        ;;
esac

pass_silently
