# ADR 0001: Use Groq through CrewAI's LiteLLM integration

Status: Superseded by ADR 0002 (the LiteLLM route sends a field Groq rejects in crewai 1.15.30)

## Context
The owner wants a low-cost way to run many agent calls during development and evals.

## Decision
Use Groq as the LLM provider, configured with a `groq/<model-name>` model string and `GROQ_API_KEY` in `.env`.
Exact model name to be chosen from Groq's current docs.

## Consequences
- Fast, cheap iteration; free-tier rate limits will force retry/backoff handling (ROADMAP step 6).
- Provider is swappable through the model string; evals should record which model produced each result.
