# ADR 0002: Call Groq through its OpenAI-compatible endpoint, not LiteLLM

Status: Accepted (provisional, for development). Supersedes ADR 0001.

## Context
ADR 0001 chose Groq via CrewAI's LiteLLM integration (`groq/<model>`). In crewai 1.15.30, Groq is not a native
provider, so that route needs the `crewai[litellm]` extra. CrewAI also adds a `cache_breakpoint` field to system
messages, and only its native provider classes strip it. Through the LiteLLM path the field reaches Groq, which
rejects the request (400, `property 'cache_breakpoint' is unsupported`).

## Decision
Use CrewAI's native OpenAI provider against Groq's OpenAI-compatible endpoint:
`LLM(model="openai/<groq-model-id>", base_url="https://api.groq.com/openai/v1", custom_openai=True, api_key=GROQ_API_KEY)`.
`GROQ_MODEL` in `.env` holds the bare Groq model ID (no prefix); the default is `openai/gpt-oss-20b`, which is
available on the owner's account. Model availability varies per account and Groq's docs page was out of date, so
list real models via the `/openai/v1/models` endpoint instead of trusting docs.

## Alternatives considered
- Stay on LiteLLM and pin an older crewai: rejected, it freezes us on an old CrewAI.
- Patch or wrap the LiteLLM path to strip the field: rejected, it works around a library bug and is fragile.
- A different provider: not needed, Groq works.

## Consequences
- Fewer dependencies (no LiteLLM).
- Moving to a provider that is not OpenAI-compatible later means changing how `LLM(...)` is constructed.
- Evals must record which model ID produced each result.
- The upstream bug may be fixed in a later crewai; recheck on upgrade.
- Free-tier rate limits still need retry/backoff handling (ROADMAP step 6).
