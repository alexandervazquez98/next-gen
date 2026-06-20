# AI Chat Specification

## Purpose

Define auditable AI chat operational policies, deterministic harness-backed response behavior, and developer documentation for NEX-GEN AI integrations while preserving backend-owned harness execution and LM Studio compatibility.

## Requirements

### Requirement: Markdown Policy Artifacts

The system MUST provide markdown policy artifacts for AI chat response boundaries, LM Studio runtime constraints, and follow-up intent behavior.

#### Scenario: Developer reviews response boundaries

- GIVEN a developer needs to understand operational AI chat limits
- WHEN the developer opens the AI chat policy artifacts
- THEN the artifacts MUST state that operational facts come from backend harness evidence
- AND the artifacts MUST state that the assistant must not claim a tool or harness ran unless a harness result exists
- AND the artifacts MUST define bounded meanings for reachable and unreachable availability outcomes
- AND the artifacts MUST prohibit unsupported claims of root cause, congestion, power failure, cabling failure, firewall failure, service health, optimal state, stable state, resolved state, or event closure unless supported by harness evidence

#### Scenario: Developer reviews follow-up intent policy

- GIVEN a developer needs to understand AI chat follow-up behavior
- WHEN the developer opens the follow-up intent policy artifact
- THEN the artifact MUST describe event-list trigger concepts
- AND the artifact MUST describe availability follow-up trigger concepts
- AND the artifact MUST describe named-area filtering behavior for follow-up availability checks
- AND the artifact SHOULD document stopword behavior used for named-area matching

### Requirement: Deterministic Operational Templates

The system MUST provide reviewed markdown templates for deterministic operational responses for `event_list`, `availability_check`, and `availability_check_batch` harness results.

#### Scenario: Event list template is reviewed

- GIVEN a developer reviews the `event_list` response template
- WHEN the template is read
- THEN it MUST define a response structure that includes event count, applied status or severity filters when present, observed events, observed diagnosis, limitations, and suggested next checks
- AND the observed diagnosis MUST be limited to symptoms evidenced by the event-list data
- AND the limitations MUST state that event-list data alone does not confirm root cause or event resolution

#### Scenario: Availability template is reviewed

- GIVEN a developer reviews an availability response template
- WHEN the template is read
- THEN it MUST define a response structure that includes CI identity, reachability status, target when available, latency when available, and detail when available
- AND it MUST state that reachability means only that the bounded ping check responded at the time of execution
- AND it MUST state that ping reachability does not confirm complete service health, root cause, or automatic event closure

### Requirement: Deterministic Harness-Backed Responses

The system MUST render primary responses for `event_list`, `availability_check`, and `availability_check_batch` harness results deterministically or through tightly controlled templates, without relying on free-form model rewriting for the primary operational answer.

#### Scenario: Event list response uses harness facts

- GIVEN a user asks for open events and diagnosis
- AND the backend executes an `event_list` harness successfully
- WHEN the assistant response is produced
- THEN the response MUST include the event facts returned by the harness
- AND the response MUST present diagnosis only as observed symptoms supported by those facts
- AND the response MUST NOT claim root cause, congestion, power failure, cabling failure, firewall failure, service health, optimal state, stable state, resolved state, or event closure unless that claim is present in supporting harness evidence

#### Scenario: Availability batch response uses bounded ping semantics

- GIVEN a user asks whether CIs from a prior event list are still up
- AND the backend executes an `availability_check_batch` harness successfully
- WHEN the assistant response is produced
- THEN the response MUST list each checked CI with the harness-reported reachability status
- AND the response MUST describe the result as a current bounded ping check
- AND the response MUST NOT present reachability as proof of full service health, root cause, or event closure

#### Scenario: Single availability response uses bounded ping semantics

- GIVEN a user asks for availability of one CI
- AND the backend executes an `availability_check` harness successfully
- WHEN the assistant response is produced
- THEN the response MUST identify the checked CI and the harness-reported target when available
- AND the response MUST include latency or detail values when provided by the harness
- AND the response MUST NOT present the check as proof of full service health, root cause, or event closure

### Requirement: No Invented Harness Execution

The system MUST prevent AI chat responses from claiming harness execution or tool results that did not occur.

#### Scenario: No harness result exists

- GIVEN a user asks an operational question
- AND no backend harness result exists for the response
- WHEN the assistant response is produced
- THEN the response MUST NOT claim that an event list, availability check, diagnostic tool, or other harness was executed
- AND the response SHOULD explain any limitation caused by the absence of harness evidence when operational certainty is requested

#### Scenario: Model returns empty content after harness execution

- GIVEN the backend has a successful harness result
- AND the language model returns empty assistant content
- WHEN the assistant response is produced
- THEN the system MUST provide a safe deterministic or fallback response based on the harness result
- AND the response MUST obey the same unsupported-claim restrictions as other harness-backed responses

### Requirement: Preserve Backend-Owned Harness Flow

The system MUST preserve the existing backend-owned AI chat harness flow for operational tools.

#### Scenario: Backend executes an operational harness

- GIVEN a user request maps to an allow-listed operational harness
- WHEN the request is processed
- THEN the backend MUST infer or validate the intent before execution
- AND the backend MUST enforce permissions before execution
- AND the backend MUST resolve CI targets from backend-owned data when target resolution is required
- AND the backend MUST store the harness result for same-user follow-up references
- AND the model MUST NOT execute tools directly as the primary operational path

#### Scenario: Event list filters are preserved

- GIVEN a user asks for events with status or severity constraints
- WHEN the backend executes `event_list`
- THEN the system MUST continue to support status filters for `OPEN`, `ACK`, `CLOSED`, `RECOVERED`, `ACTIVE`, and `CONSOLE`
- AND the system MUST continue to support severity filters for `CRITICAL`, `WARNING`, and `INFO`

#### Scenario: Follow-up availability check is preserved

- GIVEN a same-user prior response stored an `event_list` harness result with CI references
- WHEN the user asks a follow-up availability question for those CIs or a named subset
- THEN the backend MUST resolve the follow-up against the stored event-list harness metadata
- AND `availability_check_batch` MUST remain bounded to at most 5 CIs per batch response

### Requirement: LM Studio Compatibility and Runtime Boundaries

The system MUST preserve the OpenAI-compatible LM Studio integration path and document its runtime constraints.

#### Scenario: Chat completion endpoint remains provider-neutral

- GIVEN the backend sends a request to LM Studio
- WHEN it constructs the provider request
- THEN it MUST use the OpenAI-compatible `/v1/chat/completions` chat-completion style integration
- AND the backend MUST remain responsible for sending required chat history
- AND the system MUST NOT require LM Studio native stateful chat as the default integration path

#### Scenario: Reasoning-model runtime constraints are documented

- GIVEN a developer reviews the AI chat runtime documentation
- WHEN the developer reads the LM Studio section
- THEN it MUST describe that reasoning-capable models may return populated reasoning content with empty assistant content
- AND it MUST describe the relationship between completion token limits, context length, timeout, and response completeness

### Requirement: AI Developer Manual

The system MUST provide a developer-facing AI manual at `docs/ai.md`.

#### Scenario: Developer learns how to connect LM Studio

- GIVEN a developer opens `docs/ai.md`
- WHEN the developer reads the LM Studio connection section
- THEN the manual MUST describe required environment configuration
- AND it MUST identify the OpenAI-compatible `/v1/chat/completions` base path
- AND it MUST describe model, timeout, max-token, and context-length considerations

#### Scenario: Developer learns AI identity boundaries

- GIVEN a developer opens `docs/ai.md`
- WHEN the developer reads the identity section
- THEN the manual MUST describe the role of `backend/ai/identity/Soul.md`, `scope.md`, `context-policy.md`, and `session-bootstrap.md`
- AND it MUST explain that identity content is bounded by operational policy and does not grant execution or write authority

#### Scenario: Developer learns harness and toolcalling boundaries

- GIVEN a developer opens `docs/ai.md`
- WHEN the developer reads the toolcalling and harness sections
- THEN the manual MUST distinguish provider-native tool calling from backend-owned harnesses
- AND it MUST state that NEX-GEN uses backend-owned harnesses as the primary operational execution path
- AND it MUST describe intent inference, permission checks, target resolution, harness execution, harness-result injection or rendering, history persistence, and follow-up resolution
- AND it MUST state that provider-native tool adapters are future extension points rather than the primary path for this change

#### Scenario: Developer learns write boundaries

- GIVEN a developer opens `docs/ai.md`
- WHEN the developer reads the write-safety section
- THEN the manual MUST state that the model may not directly write to Raven, SQLite, Neo4j, Postgres, CMDB data, or operational systems
- AND it MUST describe the Raven boundary as backend-controlled rather than model-controlled

### Requirement: Regression Coverage for Operational Safety

The system MUST include validation that deterministic operational responses preserve harness facts and exclude unsupported claims.

#### Scenario: Unsupported claims are tested

- GIVEN automated tests or equivalent validation are run for AI chat operational responses
- WHEN deterministic `event_list`, `availability_check`, and `availability_check_batch` responses are generated
- THEN validation MUST verify that harness facts appear in the response
- AND validation MUST verify that unsupported root-cause, congestion, power, cabling, firewall, service-health, optimal, stable, resolved, and event-closure claims do not appear without supporting harness evidence

#### Scenario: Existing behavior remains covered

- GIVEN AI chat regression validation is run
- WHEN event filtering, follow-up availability resolution, permission enforcement, chat history, and empty-content fallback behavior are exercised
- THEN those behaviors MUST continue to satisfy their existing contracts
