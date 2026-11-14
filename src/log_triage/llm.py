"""The one place that knows how to build the LLM every agent uses."""

import os

from crewai import LLM

# Groq's bare model ID. No provider prefix. Availability varies per account: list yours with
# `curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"`.
DEFAULT_MODEL = "openai/gpt-oss-20b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# Room for a reasoning model's hidden thinking plus the answer. gpt-oss-20b spent 4,601 of 5,350 output tokens
# reasoning on one fix plan; Groq's lower default cap cut the JSON off mid-answer (json_validate_failed).
MAX_COMPLETION_TOKENS = 8192


def model_id() -> str:
    """The Groq model in use. An empty GROQ_MODEL= in .env counts as unset."""
    return os.getenv("GROQ_MODEL") or DEFAULT_MODEL


def build_llm(temperature: float = 0, reasoning_effort: str | None = None) -> LLM:
    """A NEW LLM object on every call. crewai adds up token usage per LLM object over its whole life, so two agents
    sharing one would count every call twice and spoil the cost numbers.

    reasoning_effort ("low", "medium", "high") only matters for reasoning models; None keeps the provider default.
    """
    # Groq speaks the OpenAI API, so we use CrewAI's native OpenAI provider with a custom base URL (ADR 0002).
    # The "groq/..." LiteLLM route in crewai 1.15.30 sends a `cache_breakpoint` field that Groq rejects.
    # custom_openai=True strips one leading "openai/" from the model, so we always add exactly one.
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:  # no sensible default exists, so stop here rather than with a 401 halfway through a run
        raise RuntimeError("GROQ_API_KEY is not set. Copy .env.example to .env and put your Groq key in it.")
    return LLM(
        model=f"openai/{model_id()}",
        base_url=GROQ_BASE_URL,
        custom_openai=True,
        api_key=api_key,
        temperature=temperature,
        max_completion_tokens=MAX_COMPLETION_TOKENS,
        reasoning_effort=reasoning_effort,
    )
