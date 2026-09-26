# Spec: cmdb-proposal-review-ui

## Purpose

Defines the human review surface for AI-proposed CMDB Configuration Items. The UI lives at `/proposals/cmdb` and lets a user with `CI_APPROVE_PROPOSAL` list pending proposals, inspect a per-proposal diff between the proposed manifest and the live CMDB state, approve or revoke with confirmation, and view the lifecycle audit timeline. A pending-count badge in `AIAgentConsole` deep-links the current user to their queue.

## Requirements

### REQ-CMPR-001: Proposal list view with filters

The list view MUST render rows for every proposal returned by `GET /api/cmdb/proposals`, MUST support server-side filters for `status`, `category`, `proposed_by`, and `created_at` range, and MUST paginate.

#### Scenario: Reviewer filters by status and date range

- GIVEN proposals with mixed statuses and creation dates
- WHEN the reviewer selects `status=DRAFT` and a `created_at` window
- THEN the table MUST refresh with the matching subset
- AND MUST update the URL query string.

### REQ-CMPR-002: Detail view shows manifest vs live CMDB diff

The detail view MUST render, side by side, the proposed manifest and the current CMDB state for the target `ci.id`. The view MUST highlight added, changed, and removed fields and MUST show a "collision" badge when `ci.id` already exists on `:CI` and a "category drift" badge when the live `Category` set no longer contains `ci.category`.

#### Scenario: Diff highlights added and changed fields

- GIVEN a DRAFT proposal and a live CMDB state for the same `ci.id`
- WHEN the reviewer opens detail
- THEN the view MUST list every added field in one column and every changed field with old → new in another.

#### Scenario: Collision badge is shown

- GIVEN a proposal whose `ci.id` already exists on `:CI`
- WHEN the reviewer opens detail
- THEN the view MUST display a visible "collision" badge.

### REQ-CMPR-003: Approve action requires confirmation and emits success feedback

The detail view MUST expose an "Approve" button gated on `CI_APPROVE_PROPOSAL`. A click MUST open a confirmation dialog describing the resulting `:CI.id` and MUST submit `POST /api/cmdb/proposals/{id}/approve` on confirm. On success, the view MUST show the new `:CI.id` and deep-link.

#### Scenario: Approve creates the CI and updates the row

- GIVEN a DRAFT proposal and a reviewer with `CI_APPROVE_PROPOSAL`
- WHEN the reviewer confirms approve
- THEN the UI MUST POST approve
- AND on HTTP 200 MUST show the resulting `:CI.id` and a success toast.

#### Scenario: Approve blocked by guardrail shows denial reason

- GIVEN approve fails with HTTP 200 + `denied=true`
- WHEN the response is rendered
- THEN the UI MUST show the structured denial reason
- AND MUST NOT advance the proposal status.

### REQ-CMPR-004: Revoke action requires confirmation

The detail view MUST expose a "Revoke" button gated on `CI_APPROVE_PROPOSAL`. A click MUST open a confirmation dialog and MUST submit `POST /api/cmdb/proposals/{id}/revoke` on confirm.

#### Scenario: Revoke updates the row to REVOKED

- GIVEN a DRAFT or APPROVED proposal and a reviewer with `CI_APPROVE_PROPOSAL`
- WHEN the reviewer confirms revoke
- THEN the UI MUST POST revoke
- AND on HTTP 200 MUST update the proposal status to `REVOKED` in the list.

### REQ-CMPR-005: Audit timeline of proposal lifecycle events

The detail view MUST render a vertical timeline of every audit row whose `event_type` is one of `CI_PROPOSAL_CREATE`, `CI_PROPOSAL_APPROVE`, `CI_PROPOSAL_REVOKE`, with timestamp, actor, previous → next state, and version.

#### Scenario: Timeline shows all transitions for a proposal

- GIVEN a proposal with at least one CREATE row
- WHEN the reviewer opens detail
- THEN the timeline MUST list the CREATE row and any subsequent APPROVE / REVOKE rows in chronological order.

### REQ-CMPR-006: Permission-aware action buttons

The detail view MUST NOT render Approve or Revoke buttons when the current user lacks `CI_APPROVE_PROPOSAL`. The view MUST still render read-only sections (list, diff, timeline) for users without the permission.

#### Scenario: Reviewer without CI_APPROVE_PROPOSAL sees no buttons

- GIVEN a user authenticated but lacking `CI_APPROVE_PROPOSAL`
- WHEN the user opens detail
- THEN Approve and Revoke buttons MUST NOT be visible or interactive.

### REQ-CMPR-007: Pending count badge in AIAgentConsole

`AIAgentConsole` MUST render a numeric badge showing the count of DRAFT proposals the current user can review, MUST poll that count at the existing `useSystemStatusQuery` cadence (every 3s) or slower, and MUST deep-link to `/proposals/cmdb?status=DRAFT`.

#### Scenario: Badge increments when a new proposal arrives

- GIVEN the badge currently shows 2
- WHEN a new DRAFT proposal is created
- THEN the badge MUST update to 3 on the next poll
- AND clicking it MUST navigate to the DRAFT filter.

### REQ-CMPR-008: Empty state when no proposals match

The list view MUST render an explicit empty state when filters return zero rows. The state MUST include a hint to clear filters and MUST NOT show a broken table.

#### Scenario: Empty state renders

- GIVEN a filter that matches zero proposals
- WHEN the list view renders
- THEN the empty-state component MUST appear
- AND the table headers MUST NOT be displayed.

### REQ-CMPR-009: Loading state during fetch

The list and detail views MUST render a loading skeleton while data is in flight, MUST NOT block other UI actions, and MUST time out gracefully.

#### Scenario: Skeleton renders on initial load

- GIVEN the user navigates to `/proposals/cmdb`
- WHEN the query is in flight
- THEN a skeleton placeholder MUST render until data arrives.

### REQ-CMPR-010: Error state surfaces structured failures

The views MUST render a structured error component on HTTP 5xx or network failure, MUST include a retry control, and MUST NOT swallow `denied=true` payloads into a generic error.

#### Scenario: 5xx error renders retryable banner

- GIVEN the backend returns HTTP 503
- WHEN the view renders
- THEN an error banner MUST appear with a Retry button.

## Scenarios

See per-requirement scenarios. Coverage: list filtering (001), diff view (002), approve (003), revoke (004), timeline (005), permission gating (006), badge (007), empty (008), loading (009), error (010).

## Out of Scope

- Bulk approve or bulk revoke.
- In-place editing of proposals; re-propose instead.
- A revoke-reason input field in v1.
- Real-time websocket push of new proposals (badge polls instead).
- Approver delegation or two-person approval flows.
- Editing manifest fields in the detail view.

## Dependencies

- `cmdb-ai-proposals` — backend endpoints and lifecycle states rendered by the UI.
- Frontend infra: React Query polling, route registration in `App.tsx`, the existing `AIAgentConsole` component for the badge.