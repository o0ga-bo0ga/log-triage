"""The one place that knows how to build the LLM every agent uses."""

import os

from crewai import LLM

# Groq's bare model ID. No provider prefix. Availability varies per account: list yours with
# `curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"`.
DEFAULT_MODEL = "openai/gpt-oss-20b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def model_id() -> str:
    """The Groq model in use. An empty GROQ_MODEL= in .env counts as unset."""
    return os.getenv("GROQ_MODEL") or DEFAULT_MODEL


def build_llm(temperature: float = 0) -> LLM:
    """A NEW LLM object on every call. crewai adds up token usage per LLM object over its whole life, so two agents
    sharing one would count every call twice and spoil the cost numbers."""
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
    )
