# Handover for a new Claude Code session

Written 2026-10-26 at the end of the first working session, on the owner's old laptop. Claude Code's memory does not
move between machines, so this file is the memory. Read it fully, then read the files in "Read next" before doing
anything.

**Owner, to start the new session:** clone the repo, open Claude Code in it, and say:
"Read docs/HANDOVER.md and every file it tells you to read, then tell me what you understand and what is next."

## 1. What this project is

A CrewAI multi-agent system that reads logs from several services and writes an advisory triage report: what is
wrong, how severe, the probable root-cause service, and ordered next steps. It never takes actions. It is a learning
project and portfolio piece for AgentOps, so evals and observability matter as much as the agents. The hard case it
exists for: the root cause is in a quiet service while a different service is the loudest.

## 2. How the owner wants to work (most important)

- **Claude writes the code and explains it; the owner reviews.** The owner works at an AI-native company, uses AI
  tools daily, and wants to upskill by building with AI rather than typing everything. (This changed during session 1;
  CLAUDE.md is already updated.)
- One small roadmap step at a time. After each piece, ask the owner one "why" question so the review is active.
- **Recommend, do not decide silently.** Design decisions are discussed first, then recorded in specs or ADRs.
  When the owner says "whatever you think is best", decide, say what you chose and why.
- The owner often asks "explain simply". Use plain words, a concrete example from this project, no jargon walls.
- When the owner answers a "why" question partly right, say which part is right and correct the rest kindly.
- Expansion ideas go to `docs/ideas.md`, not into the current scope. The owner asked for this explicitly.
- Never trust memory for CrewAI APIs or Groq model names. Check the installed package source or the live API and say
  when something is unverified. This caught three real problems in session 1 (see section 7).
- Be honest about weak results, including your own mistakes. The owner values that.

## 3. Read next, in this order

| File | What it contains |
|---|---|
| `CLAUDE.md` | Working agreement, stack, layout, conventions. Loaded automatically, but read it. |
| `docs/specs/SPEC.md` | Problem, goal, non-goals, pipeline (parser, digest, classifier, fix suggestor), escalation idea, open questions, data contracts. |
| `docs/specs/EVALS.md` | How quality is measured: label fields, severity rubric, metrics per stage, baselines including a no-LLM floor. |
| `docs/specs/ROADMAP.md` | Steps 0 to 8 with checkboxes. Steps 0, 1, 2, 3 and 3b are done. |
| `docs/decisions/0002-groq-via-openai-compatible-endpoint.md` | Why Groq is called through its OpenAI-compatible endpoint (0001 is superseded). |
| `docs/ideas.md` | Parked future ideas with reasons and prerequisites. |
| `src/log_triage/schemas.py` | All Pydantic data contracts so far. |
| `src/log_triage/digest.py` | The newest and most design-heavy code; its docstring states its assumption. |
| `generator/generate.py` | How scenarios, difficulty, severity and noise are produced. |

Then skim the rest as needed:

| Path | What it is |
|---|---|
| `src/log_triage/hello.py` | Step 1: one agent, one task, Groq LLM config. The working LLM setup to copy. |
| `src/log_triage/parser.py` | Deterministic parser: `parse_line`, `parse_log`, `summarize`. |
| `src/log_triage/tools/log_parser.py` | `ParseLogFileTool` (CrewAI `BaseTool`), confined to a `log_dir`. |
| `generator/topology.py` | 9 services, who calls whom, healthy log templates, `callers_by_depth`. |
| `generator/faults.py` | 8 fault types: origin services, lead-in clue, origin/caller messages, decoy messages. |
| `tests/` | `test_generator.py`, `test_parser.py`, `test_digest.py` (283 tests, all passing at handover). |
| `.claude/commands/` | Project slash commands: `/next-step`, `/explain`, `/review-code`, `/spec-check`, `/adr`. |
| `.env.example` | `GROQ_API_KEY`, optional `GROQ_MODEL`. |

## 4. Setup on the new laptop

1. Python 3.11 or newer. (The old laptop's system Python was 3.9, too old; we used Homebrew's 3.13.)
2. `python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt && .venv/bin/python -m pip install -e .`
3. `cp .env.example .env`, then put the Groq key in `GROQ_API_KEY`. Leave `GROQ_MODEL` empty or set a bare Groq ID.
4. Check: `.venv/bin/python -m pytest -q` (expect 283 passed) and `.venv/bin/python -m log_triage.hello` (one
   sentence about a timeout log line).
5. Sample data is gitignored, so regenerate it: `.venv/bin/python -m generator.generate --all --seeds 3`
   (add `--noise 0.01` for unparseable lines). View a digest: `.venv/bin/python -m log_triage.digest <file.log>`.

## 5. What is built

- **Step 1, hello crew** (`hello.py`): works live on Groq with `openai/gpt-oss-20b`.
- **Step 2, generator**: 9 services, 8 faults, 3 difficulties. `easy` = root cause loudest; `ambiguous` = an unrelated
  decoy service has exactly the same error count as the root cause (exact, so loudness carries zero signal);
  `hard` = root cause only logs a few warnings plus one lead-in clue line. Severity is not fixed per fault: each
  scenario picks a target share of failing frontend requests, all rates scale together, and the label is computed
  from the lines written (critical >= 50%, high >= 30%, medium >= 10%, else low). Every difficulty contains all four
  severities. Fully seeded. `--noise` inserts lines the parser must reject, recorded in `expected_unparsed`.
- **Step 3, parser + tool**: `LogEvent` (line_number, timestamp, service, level, message, raw). Rejected lines are
  `UnparsedLine` with a reason (empty, continuation, malformed, bad_timestamp, unknown_level) and are never dropped.
  The tool returns a ~1.4 KB JSON summary, not the events. An agent called it live through Groq and answered correctly.
- **Step 3b, digest** (added in session 1): deterministic summary the agents read instead of 8,000 lines. Per
  service: onset (start of the first chain of 5+ WARN/ERROR lines, each within 10s of the last), level counts, top 5
  message patterns (numbers replaced by `<n>`), NEW flag (first seen after the first quarter of the window), one
  citable example line per pattern. NEW patterns rank first so a quiet root cause is not crowded out. Tests check
  counts, citations, size (< 14k chars) and that the root cause's fault signal always survives as a shown NEW pattern.

## 6. Decisions

Recorded in docs:
- Groq via OpenAI-compatible endpoint, native CrewAI OpenAI provider, `custom_openai=True` (ADR 0002).
- Parser is deterministic for v1; hybrid parser parked (SPEC). Strict levels in v1 (ideas.md).
- Stack-trace continuation lines stay unparsed in v1 (SPEC).
- Severity derived from measured user impact, independent of difficulty (EVALS).
- Digest stage between parser and agents (SPEC, ROADMAP 3b).
- Closed category list for v1: the 8 fault types plus `unknown`; open taxonomy parked (ideas.md).
- Logging-quality observations deferred past v1 (ideas.md).

Agreed in conversation but NOT yet written into specs or ADRs (do this when the relevant step starts):
- **Process:** a sequential crew for triage; escalation (junior to senior) is a plain-Python branch on confidence,
  not CrewAI's hierarchical process. Hierarchical is kept only as a baseline experiment. Candidate ADR.
- **Confidence:** do not trust a bare self-reported number. Junior returns ranked candidates with scores plus overall
  confidence; escalate if confidence is low OR the top two candidates are close. Threshold is a config value chosen
  from eval data (calibration), not guessed. Self-consistency is a later experiment (ideas.md).
- **Dependency map:** run evals both with the map given to the agents and withheld, and compare.
- **Digest format for agents:** the model reads the plain-text `render()` output; code keeps the structured `Digest`
  to validate citations. (Claude's call; the owner said "whatever you think is best".)
- **Observability (step 7):** leaning Arize Phoenix (local, no account), Langfuse second. Unverified; check docs then.
  Whatever the tool, the eval runner records tokens, cost, latency and model ID from step 5 on.

## 7. Verified facts and gotchas

- CrewAI is pinned at 1.15.30. Groq is not a native provider there; a `groq/...` model string falls back to LiteLLM,
  and CrewAI adds a `cache_breakpoint` field to system messages that only native providers strip, so Groq rejects
  the request. Hence ADR 0002. Recheck on any CrewAI upgrade.
- `custom_openai=True` strips one leading `openai/` from the model string, so `hello.py` always prepends exactly one.
  That is why `GROQ_MODEL` holds the bare Groq ID (e.g. `openai/gpt-oss-20b`).
- Groq's docs page listed Llama models that the owner's key could not use. Trust the live list:
  `curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"`. On the old laptop it showed
  `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b` and others. A new key may differ.
- An empty `GROQ_MODEL=` in `.env` once broke the run; `hello.py` now treats empty as unset.
- Verified in source: CrewAI tools subclass `crewai.tools.BaseTool` (`name`, `description`, `args_schema`, `_run`);
  `Task` has `output_pydantic` / `output_json` for structured output.
- Verified live: tool calling works with `openai/gpt-oss-20b` on Groq.
- **Not verified:** whether `gpt-oss-20b` on Groq supports schema-constrained structured output. Test this first in
  step 4.
- Log content is untrusted input (prompt injection), which is why the parse tool is confined to `log_dir`.

## 8. Measurements and known weaknesses

- A crude no-LLM heuristic ("service whose WARN/ERROR burst starts first") found the root cause in 38/80 easy,
  28/80 ambiguous and 14/80 hard scenarios (random is about 11%). It is the floor the LLM must beat.
- Digest onset is a noisy cue: a stray background line can pull onset a second or so early, and a quiet root cause
  has no onset. The digest header says `onset none` does not mean healthy. Ordering experiment is in ideas.md.
- `normalize` turns every number into `<n>`, merging HTTP 502 and 504. Parked in ideas.md. (This was also the open
  "why" question to the owner at handover; they had not answered it yet.)

## 9. Next: step 4

Classifier and fix suggestor agents with structured outputs, in a sequential crew, reading the rendered digest.
Proposed fields (the owner has seen them and not objected; confirm before coding):

- `ClassifiedIncident`: `severity` (low|medium|high|critical), `category` (8 fault types or `unknown`),
  `root_cause_candidates` (ranked 1 to 3: service, confidence, evidence line numbers), `confidence` (0 to 1),
  `summary`.
- `TriageReport`: the classified incident, `key_events`, `next_steps` (ordered: action, rationale, what to check
  first), `caveats` (e.g. unparsed line count), model ID.

Plan: first test structured output on Groq live; allow "unknown / insufficient evidence"; validate cited line
numbers in code (they must exist and belong to the claimed service). Then step 5, the eval runner.

## 10. Housekeeping

- Git: initialized at handover with small commits. Push to GitHub needed the owner's repo URL (no `gh` CLI on the old
  laptop).
- Update this file at the end of each working session, or when moving machines again.
