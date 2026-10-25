# Spec: Log Triage

Status: DRAFT v0.1 (agreed in discussion, items marked OPEN are undecided)

## Problem

When a service fails, an on-call engineer faces thousands of log lines, mostly noise, from several services.
They need to know quickly: what is actually wrong, how bad is it, and what to try first.

## Goal

Given a time window of logs from multiple services, produce a structured **triage report**:
key events, severity, category, probable root-cause service, and ordered suggested next steps.

## Non-goals (v1)

- No automated remediation or any action on real systems (advisory only)
- No live log streaming
- No UI (CLI that reads files is enough)
- No memory across incidents, no RAG over runbooks (possible v2)

## Input

A log file (or set of files) covering a time window from multiple services, where the root cause may sit in a
different service from the loudest symptom.

## Pipeline

| Stage | Input | Output |
|---|---|---|
| Parser | raw log text | structured events (timestamp, service, level, message) |
| Digest (deterministic, no LLM) | structured events | per-service onset, grouped message patterns with counts, first/last seen, example line numbers, NEW flags |
| Classifier | digest | severity + category + ranked root-cause candidates |
| Fix suggestor | classified incident | probable cause + ordered remediation steps |

Escalation: a junior-engineer persona handles triage and reports a confidence value; low confidence escalates to a
senior-engineer persona that reviews and can overrule. Personas are a hypothesis to be tested in evals, not decoration.

## Open questions

- DECIDED (v1): the parser is deterministic Python (`src/log_triage/parser.py`), wrapped as a CrewAI tool that
  returns a compact summary. A hybrid (LLM for rejected lines) is parked in `docs/ideas.md`; revisit with
  measurements on noisy logs. Candidate ADR.
- OPEN: how is confidence produced and what is the escalation threshold?
- OPEN: CrewAI process type (sequential vs hierarchical) for the escalation flow.
- OPEN: observability tool (Langfuse, Arize Phoenix, AgentOps, plain OpenTelemetry).

## Data contracts

Defined with Pydantic in `src/log_triage/schemas.py`.

Agreed and implemented:
- `LogEvent`: `line_number`, `timestamp` (UTC), `service`, `level` (INFO | WARN | ERROR), `message` (text after the
  level), `raw` (the whole original line).
- `UnparsedLine`: `line_number`, `raw`, `reason` (empty | continuation | malformed | bad_timestamp | unknown_level).
  Rejected lines are kept and counted, never dropped. Stack-trace continuation lines stay unparsed in v1.
- `ParseResult` (`events`, `unparsed`) and `ParseSummary` (a tiny stats view returned by the parse tool).
- `Digest` -> `ServiceDigest` -> `MessagePattern`: the evidence the agents read instead of every line. Patterns group
  messages that differ only in numbers; `novel` marks patterns first seen after the quiet first quarter of the
  window; each pattern carries one example `LogEvent` whose `line_number` a report can cite.

To be agreed before coding: `ClassifiedIncident`, `TriageReport`.
