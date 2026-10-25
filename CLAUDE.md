# Log Triage — CrewAI multi-agent system

A learning project and portfolio piece for AgentOps. Multi-service logs go in; a triage report comes out
(what is wrong, how severe, probable root cause, suggested next steps). Advisory only: it never takes actions.

Source of truth for scope: `docs/specs/SPEC.md`. Evals: `docs/specs/EVALS.md`. Plan: `docs/specs/ROADMAP.md`.
Design decisions live in `docs/decisions/` (ADRs). Expansion ideas outside the current scope are parked in
`docs/ideas.md`: add new ones there instead of growing the current scope, and revisit it after a full version ships.

## Working agreement (most important section)

The owner is learning CrewAI and AgentOps by building with AI assistance, the way they work day to day. Claude writes
the code and explains it; the owner reviews, questions and decides.

- **Claude writes the implementation code**, one small roadmap step at a time, and explains what each piece does and why.
- After each piece, ask the owner one "why" question so the review is active, not a skim. Keep the code small enough to review in one sitting.
- The owner owns the design. Point out tradeoffs and recommend, but do not decide silently.
- Discuss a design decision before it is recorded in a spec or ADR. Never decide silently.
- Docs and specs may be edited by Claude once the owner has agreed the content in conversation.
- Do not trust memory for CrewAI APIs or Groq model names; they change fast. Check the official docs or installed
  package source and say when something is unverified.
- Be honest about uncertainty. If the owner's approach is weaker than an alternative, say so with the reasoning.

## Stack

- Python, CrewAI, Pydantic, python-dotenv, pytest
- LLM: Groq, called through its OpenAI-compatible endpoint with CrewAI's native OpenAI provider (ADR 0002)
- Observability tool: undecided (see ROADMAP step 7)

## Layout

- `src/log_triage/` application package (`src` layout)
- `src/log_triage/tools/` custom CrewAI tools (e.g. deterministic log parser)
- `generator/` synthetic multi-service log + label generator (plain Python, no LLM)
- `evals/` eval runner and scenario files
- `tests/` unit tests (deterministic code only; LLM behaviour is covered by evals)
- `data/sample_logs/` generated or downloaded logs (large files gitignored)
- `docs/` specs and ADRs

## Conventions

- Python 3.11+, type hints on all function signatures, Pydantic models for any data crossing an agent boundary.
- Keep deterministic work in plain Python; use the LLM only where judgment or ambiguity is needed.
- Secrets only in `.env` (gitignored). Add new variable names to `.env.example` in the same change.
- Pin dependency versions in `requirements.txt` once a working set is installed.
- Every behaviour change to an agent prompt should be checked against the eval set, not judged by eye.
- Small commits, imperative messages (`Add log event schema`).

## Commands

Project slash commands live in `.claude/commands/`:

- `/next-step` what to work on next per the roadmap, with what to learn first
- `/explain <concept>` teach a concept with no code solution
- `/review-code <path>` review the owner's code for bugs, design and learning points
- `/spec-check` check the code and specs still agree
- `/adr <title>` draft an ADR after a decision has been discussed

Dev commands (fill in as they come to exist): none yet.
