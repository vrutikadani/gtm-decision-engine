# ADR 0001: A headless decision engine; Slack is only a delivery surface

**Status:** accepted

## Context
The obvious build is a Slack workflow, a Salesforce Flow or a Clay table that reacts to a job-change row and posts a message. That puts the decision rules inside the delivery tool. Then the rules cannot be tested, versioned, replayed or reused when the surface changes (email digest, CRM task, a different chat tool).

## Decision
All decisions happen in one Python service (`gde/service.py`, `gde/decisions/engine.py`) behind an API (`gde/api.py`). Slack is an adapter (`gde/delivery/slack.py`) that renders a decision that already exists. The demo UI calls the same API, and the in-browser demo calls the same router (`gde/bridge.py`). `tests/test_api.py` asserts that the HTTP routes and the browser routes are identical.

## Consequences
- The decision, its trace and its side effects are records in our database, not messages in a chat log.
- A NEEDS_REVIEW or SUPPRESS decision exists even though no message was sent. That is how the system can show restraint.
- Cost: we own a service. It has to be deployed, monitored and on-called. For a team with one GTM engineer, that is a real cost.

