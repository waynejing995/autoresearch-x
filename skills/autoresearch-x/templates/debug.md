# autoresearch-x: <run name>

## TIME <timestamp from tool or bash>

## Target
<What failure to fix? e.g., "test_auth_token_refresh passes with exit code 0">

## Mode
debug

## Scope
- modify: <path/to/suspected/module.py>
- modify: <path/to/related/module.py>
- readonly: <path/to/tests.py>

## Checklist
- [ ] Reproduce the failure reliably
- [ ] Add logging around suspected area
- [ ] List competing hypotheses (at least 2-3)
- [ ] Gather evidence to eliminate hypotheses
- [ ] Identify root cause with evidence (qualifier >= HIGH)
- [ ] Implement and verify fix
- [ ] Check for related edge cases

## Evaluation
- command: `<test command, e.g., uv run pytest tests/test_auth.py::test_token_refresh -x>`
- pass: exit code 0
- fail: any non-zero exit code

## Constraints
- max_iterations: 30
- timeout: 1h
- Progressive scope applies:
  - OBSERVE: logging/prints only, no logic changes
  - DIAGNOSE: test inputs, assertions, repro scripts
  - FIX: logic changes allowed

## Context
<When did the failure start? What changed recently? What's been tried?
Include: error message, stack trace, relevant architecture docs>
