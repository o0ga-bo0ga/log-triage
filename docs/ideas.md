# Ideas

Parked expansion ideas. Nothing here is in scope for the current version. When a full version is built, revisit this
file for the next iteration. Add new ideas as they come up instead of growing the current scope.

Entry format: what, why, what it needs first, status.

## Logging observations (side notes on log quality)

Added 2026-10-25.

**What:** alongside the incident report, the tool points out gaps and anomalies in the logging itself, as a
"logging observations" section. A self-improving suggestion system: "here is the incident, and here is where your
logs let you down." These anomalies can also be evidence for the root cause.

**Why:** real production logs have discrepancies that good systems would not. Sometimes the discrepancy is where
the issue lives. For example, a crashed service goes silent while its callers are the loudest.

**Two kinds:**
1. Deterministic anomalies (plain Python, measurable):
   - unparsed lines, grouped by reason
   - timestamps out of order or clock jumps between services
   - a silent service: logged steadily, then stopped while others kept going (likely the most valuable)
   - duplicate bursts of identical lines
2. Judgment-based logging gaps (needs the LLM, harder to measure):
   - errors with no request or correlation ID
   - vague messages such as "error occurred"
   - a failing call the other side never logged

**Design notes (not decided):**
- A `LogAnomaly` model (kind, service, time range, evidence line numbers) returned by the parser next to `events`
  and `unparsed`; fed to the classifier and fix suggestor as evidence.
- A separate report section. Observations must not change severity, which stays tied to user impact.

**Needs first:**
- Generator support: inject anomalies (silent service, malformed lines, out-of-order timestamps) and record them in
  the labels (e.g. `injected_anomalies`: kind, service, time range). Today `cache_outage` keeps logging from the
  dead service, which is unrealistic.
- Spec changes: a goal in SPEC.md, a data contract, and a precision/recall metric in EVALS.md.
- Likely a split of ROADMAP step 3: 3a parser + `LogEvent` + unparsed handling, 3b anomaly detection + generator
  injection.

**Status:** deferred past v1 (owner decision, 2026-10-25): step 3 proceeds as originally planned. The parser still
returns `unparsed` lines with reasons, which is the foundation this idea builds on. Revisit after the first full
version.

## Parser variants

- **Hybrid parser:** deterministic first, an LLM tries only the lines the parser rejected. Decide with
  measurements on noisy logs (see SPEC open question). Needs the generator's noise option first.
- **Attach stack-trace continuation lines to the previous event** instead of leaving them unparsed. More realistic
  and keeps a trace together for the LLM, but the parser becomes stateful and can mis-attach. v1 leaves them
  unparsed (decided 2026-10-25).

- **Relax the strict parser (level and format normalization):** v1 rejects `WARNING`, `FATAL`, `DEBUG` and
  lowercase levels as `unknown_level`, because the generator never emits them. Real logs would need level aliases
  (WARNING -> WARN, FATAL -> ERROR), case-insensitive levels, and probably more than one timestamp format.
  Decided 2026-10-26: keep strict in v1 so the rejection reasons stay a clean signal. Revisit with real logs
  (Loghub), together with the hybrid parser.

## Safety and data handling

- **Redact secrets and PII before logs reach the LLM:** emails, tokens, API keys and IPs in log lines would
  otherwise be sent to a third-party provider. A deterministic redaction step before the digest, with a test
  that known secrets never appear in what the LLM sees. Our synthetic logs contain none, so it needs generator
  support to be testable.
- **Prompt injection through log content:** log lines can carry attacker-controlled text (request paths,
  user-agents, form fields). v1 limits the blast radius with least privilege (the parse tool only reads inside
  `log_dir`). Later: an eval scenario where a log line contains instructions, to measure whether the report
  obeys them.

## Digest

- **Service ordering experiment:** the digest orders services by onset (start of the first sustained burst of
  WARN/ERROR lines). That cue is noisy: a stray background line can pull a service's onset a few seconds early,
  and a quiet root cause (`hard`) has no onset at all and lands near the end. Compare, with evals, onset order vs
  alphabetical vs loudest-first, to see whether the order helps or misleads the model.
- **Finer message grouping:** `normalize` replaces every number with `<n>`, so HTTP 502 and 504 land in one
  pattern even though they mean different things. Keep status codes and ports, and measure whether it helps.
- **Smarter pattern selection:** novelty is judged against the first quarter of the window, which assumes the window
  starts before the incident. Alternatives: compare against a longer healthy baseline window, or learn per-service
  normal rates.

## Classification

- **Open category taxonomy:** v1 classifies into a closed list (the 8 generator fault types plus `unknown`), which
  makes accuracy measurable but ties the schema to the generator's fault catalog. Later: let the model propose a
  category outside the list, or learn categories from real incidents, and score it another way (e.g. rubric or
  LLM-as-judge). Agreed for v1 on 2026-10-26.

## Escalation and confidence

- **Self-consistency as a confidence signal:** run the junior triage N times and escalate on disagreement. Stronger
  than self-reported confidence, but multiplies cost. Try after the baseline escalation works.
- **Hierarchical CrewAI process as a baseline:** LLM manager versus coded branching, to compare cost and accuracy.

## Already parked in SPEC.md as v2

- Memory across incidents
- RAG over runbooks
