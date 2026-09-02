# Delta for ai-chat-harness-guardrails

## ADDED Requirements

### Requirement: Follow-up availability inference recognizes Spanish verb stems

The system MUST classify a query as an `availability_check_batch` follow-up intent when the query text contains Spanish verb stems `verific*`, `chequ*`, `monitor*`, `revis*`, `comprob*`, or `consult*`, in addition to existing canonical English/Spanish noun triggers (`verifica`, `verificar`, `checa`, `chequeo`, `revisa`, `revisar`, `estatus`, `estado`, `siguen`, `disponibilidad`, `reachable`, `working`, `availability`).

#### Scenario: Spanish stem "verificación" triggers availability intent

- GIVEN a user has a recent event_list harness result
- WHEN the user submits a query containing "verificación de los switches"
- THEN `infer_followup_intent.asks_availability` MUST return truthy
- AND the downstream follow-up path MUST resolve to a batch availability harness attempt.

#### Scenario: Gerund conjugations trigger availability intent

- GIVEN a user has a recent event_list harness result
- WHEN the user submits a query containing "monitoreando los equipos" or "chequeando la red"
- THEN `infer_followup_intent.asks_availability` MUST return truthy for both forms.

#### Scenario: English stem "check" triggers availability intent

- GIVEN a user has a recent event_list harness result
- WHEN the user submits a query containing the literal token "check"
- THEN `infer_followup_intent.asks_availability` MUST return truthy.

#### Scenario: Canonical tokens remain recognized

- GIVEN a user has a recent event_list harness result
- WHEN the user submits a canonical query "verifica si están funcionando"
- THEN `infer_followup_intent.asks_availability` MUST still return truthy.

#### Scenario: Event-list phrasings alone do not trigger availability intent

- GIVEN a query contains only "tengo" or "tenemos" with no availability verb
- WHEN `infer_followup_intent` is evaluated
- THEN `asks_availability` MUST be falsy
- AND the function MUST NOT route to the availability batch harness.

### Requirement: Chat intent inference recognizes event-list phrasings

The system MUST classify a query as an event-list chat intent when the query contains `tengo`, `tenemos`, `cuáles`, or `cuales` AND the query also satisfies the existing `asks_for_events` precondition (mentions `evento(s)`, `events`, `alertas`, or `incidentes`).

#### Scenario: "tengo" with event marker triggers event-list intent

- GIVEN a query mentions events ("eventos", "alertas", "incidentes", or "events")
- WHEN the query also contains "tengo" or "tenemos"
- THEN `infer_chat_intent.asks_to_list` MUST return truthy
- AND the chat intent MUST resolve to the event-list harness path.

#### Scenario: "cuáles son los eventos" triggers event-list intent

- GIVEN a query contains both "cuáles" (or "cuales") and an event marker
- WHEN `infer_chat_intent` is evaluated
- THEN `asks_to_list` MUST return truthy.

#### Scenario: Conversational "tengo" without event marker does not trigger event-list intent

- GIVEN a query contains only "tengo una pregunta" with no event marker
- WHEN `infer_chat_intent` is evaluated
- THEN `asks_to_list` MUST be falsy
- AND the chat intent MUST NOT route to the event-list harness.

#### Scenario: Canonical event-list phrasings remain recognized

- GIVEN a query contains canonical tokens "lista", "mostrar", "abiertos", or "actuales"
- WHEN `infer_chat_intent` is evaluated
- THEN `asks_to_list` MUST still return truthy.

### Requirement: Wider match surface does not produce spurious harness runs

The system MUST ensure that broadening the availability and event-list regex patterns does not produce harness runs when the prior-context precondition is unmet.

#### Scenario: Availability stem without prior event_list returns None

- GIVEN a user has no recent event_list harness result in their session
- WHEN the user submits a query containing an availability stem ("verificación", "monitoreando", "chequeando", or "check")
- THEN `infer_followup_intent` MUST return `None`
- AND no `availability_check_batch` executor SHALL run.

#### Scenario: Event-list stem with no event marker returns None

- GIVEN a query contains "tengo" or "cuáles" with no event marker and no list marker
- WHEN `infer_chat_intent` is evaluated
- THEN the function MUST return `None`
- AND no chat intent SHALL be inferred.
