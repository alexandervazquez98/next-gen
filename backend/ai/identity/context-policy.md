# Context policy

Keep incident context small. The assistant should receive only the facts needed for the current question.

## Prompt ordering

Use this order when composing the request:

1. User question.
2. Selected CI or event facts needed to answer.
3. Recent relevant state, not full history.
4. Harness result, if one exists.
5. Omit broad capability docs and unrelated records.

## Budget strategy

- Prefer summarized fields over raw object dumps.
- Include IDs, names, status, severity, timestamps, and the few metrics relevant to the question.
- Trim long notes, logs, and histories unless the user asks about them directly.
- Do not include the full tool catalog in every prompt.

## Why tools stay compact

Large tool catalogs waste context, dilute the incident facts, and increase the chance that the model focuses on unused capabilities instead of the operator's question. The backend should keep harness context limited to the current request.
