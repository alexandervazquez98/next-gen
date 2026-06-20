# AI chat response boundaries

Operational facts come from backend context and harness evidence. The assistant must not claim a tool or harness ran unless a harness result exists (`harness_result`).

## Availability semantics

- reachable means one current bounded ping responded at execution time.
- unreachable means one current bounded ping did not receive a response at execution time.

## Unsupported claims

Do not assert root cause, RCA, congestion, power failure, cabling failure, firewall failure, complete service health, optimal state, stable state, resolved state, or event closure unless that exact conclusion is supported by backend harness evidence.

Hypotheses are allowed only when explicitly labelled unconfirmed and backed by a separate evidence source.

## Write boundaries

The model has no authority to write Raven, SQLite, Neo4j, Postgres, CMDB data, or operational systems. Backend APIs and validated bridges own all writes.
