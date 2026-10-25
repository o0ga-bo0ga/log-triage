# Evals

Status: DRAFT v0.1

## Principle

Quality is measured on a labeled scenario set, never judged by eye. Any prompt, model or persona change is
compared against the previous eval result.

## Scenario set

Mostly **synthetic**: `generator/` simulates several services, injects a known fault with a causal chain
(e.g. db slows, api times out, frontend returns 500), and emits the logs plus a label file together.
Parser-only checks may additionally use Loghub (to be reviewed by the owner).

Label file fields (draft):
- `root_cause_service`: the service where the fault starts (the "origin" in generator code)
- `category` (failure type): db_slowdown, connection_pool_exhaustion, cache_outage, memory_leak, bad_deploy,
  queue_backlog, cert_expiry, disk_full
- `severity`: low | medium | high | critical, derived from observed user impact (see below)
- `difficulty`: `easy` (root cause is loudest), `ambiguous` (an unrelated decoy service is exactly as loud as the
  root cause), `hard` (root cause only logs a few warnings; the loudest services are downstream symptoms)
- `affected_services`: root cause first, then callers by distance
- `decoy_service`: the unrelated noisy service in `ambiguous` scenarios, else null
- `fault_start`, `window_start`, `window_end`
- `impact_scale`, `user_error_rate`: how the severity was produced
- `noise`, `expected_unparsed`: with `--noise`, extra bad lines are inserted (stack-trace frames, blank lines, unknown
  levels, bad timestamps, JSON, truncated lines) and counted by rejection reason. Valid lines are untouched, so a
  correct parser recovers exactly the clean events and rejects exactly `expected_unparsed`.

### Severity rubric

Severity is computed from the generated lines, not assigned per fault type, so it can be checked against the log:
`user_error_rate` = failing share of `frontend` requests (ERROR / (ERROR + INFO)) from `fault_start` on.
critical >= 50%, high >= 30%, medium >= 10%, otherwise low. Each scenario picks a target impact level and scales all
fault rates together, so severity varies independently of difficulty (checked in `tests/test_generator.py`).

## Metrics

| Level | Metric |
|---|---|
| Parser | field accuracy against known lines |
| Digest | counts add up; every cited line is the real line; size fits an LLM; the root cause's fault signal survives as a shown NEW pattern (all checked in `tests/test_digest.py`, no LLM needed) |
| Classifier | severity and category accuracy; severity is ordinal, so also report within-one-level (OPEN: confirm) |
| Root cause | true service in top-1 and top-3 (v1 correctness = right service; failure type later) |
| Fix suggestions | rubric/keyword checklist; LLM-as-judge is an option, with known biases (OPEN) |
| Escalation | does escalation rate track difficulty label |
| Operational | cost, latency, tokens per incident |

## Handling non-determinism

Run each scenario N times (N to decide), report rates and spread rather than single pass/fail. Low temperature helps
but does not remove variance.

## Baselines

- No-LLM heuristic floor: "service whose WARN/ERROR burst starts first". An untuned version found the root cause in
  38/80 easy, 28/80 ambiguous and 14/80 hard generated scenarios (random guessing is about 11%). The LLM must beat it.
- Dependency map given to the agents vs withheld (same scenarios, both ways)
- Single agent, no personas, no escalation
- Deterministic parser vs LLM parser
- Personas vs no personas
