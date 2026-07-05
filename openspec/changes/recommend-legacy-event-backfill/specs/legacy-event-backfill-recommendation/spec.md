# Delta for legacy-event-backfill-recommendation

## ADDED Requirements

### Requirement: Read-Only Recommendation Report
The system MUST generate a report-only recommendation for legacy event discriminator backfill readiness. It MUST NOT perform apply, write, backfill, migration, delete, create, or set operations, and it MUST preserve read-only access safeguards.

#### Scenario: Recommendation run completes without mutation
- GIVEN Slice 1 audit evidence is available
- WHEN the recommendation job runs
- THEN it produces only report artifacts
- AND no data mutation path is authorized

#### Scenario: Mutation safeguard blocks unsafe execution
- GIVEN a caller attempts to enable apply behavior
- WHEN the recommendation job evaluates the request
- THEN it MUST refuse mutation and remain read-only

### Requirement: Dual Markdown and JSON Output
The system MUST emit both Markdown and JSON outputs from the same recommendation model run. The outputs MUST contain equivalent candidate counts, confidence classifications, and operational guidance.

#### Scenario: Outputs are consistent
- GIVEN one model invocation completes
- WHEN Markdown and JSON are generated
- THEN both outputs report the same counts and bucket labels
- AND both are suitable for reviewer inspection and automated tests

### Requirement: Confidence Buckets and Candidate Counts
The system MUST classify records into safe candidates, ambiguous records, and no-touch records. It MUST report counts for each bucket and MUST include a conservative confidence label for every record or record group.

#### Scenario: Buckets are reported deterministically
- GIVEN a fixed input dataset
- WHEN the recommendation is repeated
- THEN the same records map to the same bucket counts
- AND ambiguous records remain explicitly separated from safe candidates

#### Scenario: No-touch records are excluded from backfill recommendation
- GIVEN records that are ineligible for backfill
- WHEN the report is produced
- THEN those records appear only in the no-touch bucket
- AND they are not counted as safe candidates

### Requirement: Scale-Readiness Guidance
The system MUST include batching guidance, rate or limit assumptions, idempotency expectations, rollback constraints, and operational risk notes for a future Slice 3 backfill. These recommendations MUST be framed as readiness guidance, not execution approval.

#### Scenario: Large-volume readiness is documented
- GIVEN a production-scale dataset
- WHEN the report is generated
- THEN it includes a bounded batching recommendation and retry assumptions
- AND it states rollback limitations after mutation

#### Scenario: Operational risk remains visible
- GIVEN ambiguous or high-volume records exist
- WHEN the report is generated
- THEN it highlights operational risk and scaling caveats

### Requirement: Review Gate for Slice 3
The report MUST be review-gated so it may recommend that Slice 3 is worth planning, but it MUST NOT authorize mutation by itself. Any approval to mutate MUST come from a separate review decision.

#### Scenario: Report can recommend further review
- GIVEN the dataset appears ready for a larger rollout
- WHEN the report is reviewed
- THEN it may recommend Slice 3 consideration
- AND it MUST NOT declare mutation approved

#### Scenario: Review gate prevents premature authorization
- GIVEN the report is consumed by automation
- WHEN downstream systems inspect it
- THEN they MUST treat it as advisory only
- AND they MUST not start backfill execution from the report alone

### Requirement: Deterministic Testable Output
The system MUST produce deterministic outputs for the same input dataset and model version so tests can assert stable counts, labels, and report structure.

#### Scenario: Same input yields same report
- GIVEN the same fixtures and model version
- WHEN the recommendation runs twice
- THEN the normalized Markdown and JSON outputs match
- AND the test harness can compare them reliably
