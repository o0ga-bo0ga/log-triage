"""Step 1: smallest possible crew (one agent, one task) to prove Groq works through CrewAI."""

import os

from crewai import LLM, Agent, Crew, Task
from dotenv import load_dotenv

# Groq's bare model ID. No provider prefix. Availability varies per account: list yours with
# `curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"`.
DEFAULT_MODEL = "openai/gpt-oss-20b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

SAMPLE_LOG_LINE = (
    "2026-10-25T10:42:07Z payments-api ERROR upstream timeout after 30000ms calling orders-db"
)


def build_crew() -> Crew:
    # Groq speaks the OpenAI API, so we use CrewAI's native OpenAI provider with a custom base URL.
    # The "groq/..." LiteLLM route in crewai 1.15.30 sends a `cache_breakpoint` field that Groq rejects.
    # custom_openai=True strips one leading "openai/" from the model, so we always add exactly one.
    llm = LLM(
        model=f"openai/{os.getenv('GROQ_MODEL') or DEFAULT_MODEL}",
        base_url=GROQ_BASE_URL,
        custom_openai=True,
        api_key=os.environ["GROQ_API_KEY"],
        temperature=0,
    )
    agent = Agent(
        role="Log reader",
        goal="Explain what a single log line says in plain English",
        backstory="You are an on-call engineer who reads logs all day.",
        llm=llm,
    )
    task = Task(
        description="Explain this log line in one sentence: {log_line}",
        expected_output="One plain-English sentence.",
        agent=agent,
    )
    return Crew(agents=[agent], tasks=[task])


def main() -> None:
    load_dotenv()
    result = build_crew().kickoff(inputs={"log_line": SAMPLE_LOG_LINE})
    print(result.raw)


if __name__ == "__main__":
    main()
