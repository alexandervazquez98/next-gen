# Assistant scope and permissions

The first assistant slice is read-only.

## Allowed

- Explain stored CI, event, monitoring, ITSM, and AIOps context provided by the backend.
- Interpret a backend-provided harness result.
- Answer from the backend-provided context and any pre-resolved harness result.

## Not allowed

- Create, update, delete, acknowledge, suppress, or close CIs, events, users, roles, or configuration.
- Run arbitrary shell commands.
- Perform broad network scanning or target discovery.
- Accept user-provided hostnames, IPs, shell flags, LM Studio URLs, or model names as execution authority.

## Authority model

Backend code decides whether an explicit diagnostic intent is authorized, resolves targets from stored NEX-GEN data, executes the harness, and returns the result.
