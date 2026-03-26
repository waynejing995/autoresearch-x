# autoresearch-x: <run name>

## TIME <timestamp from tool or bash>

## Target
<What question to answer? e.g., "Determine why 403 errors spike after deploys, with evidence">

## Mode
investigate

## Scope
- readonly: <path/to/logs/>
- readonly: <path/to/config/>
- modify: <path/to/analysis/scripts/>

## Checklist
- [ ] <Specific question 1, e.g., "What error patterns appear in last 7 days?">
- [ ] <Specific question 2, e.g., "Which component produces the most errors?">
- [ ] <Specific question 3, e.g., "Is there a time-of-day correlation?">
- [ ] <Specific question 4, e.g., "Are errors caused by upstream dependencies?">
- [ ] <Specific question 5, e.g., "What is the user impact of each error type?">

## Evaluation
- All checklist items answered with evidence citations
- Each finding has at least one GATHER reference
- No ANALYZE items with qualifier=LOW remain unresolved
- Unresolvable items marked as blocked with explanation

## Constraints
- max_iterations: 40
- timeout: 2h
- Evidence chain rules:
  - ANALYZE must cite GATHER commits (no speculation kept)
  - CONCLUDE must cite kept ANALYZE entries only
  - Rebuttal required for every analysis (when does this NOT hold?)

## Context
<Background: what prompted this investigation, known facts,
data sources available, related documentation>
