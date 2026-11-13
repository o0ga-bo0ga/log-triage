"""Step 1: smallest possible crew (one agent, one task) to prove Groq works through CrewAI."""

from crewai import Agent, Crew, Task
from dotenv import load_dotenv

from log_triage.llm import build_llm

SAMPLE_LOG_LINE = (
    "2026-10-25T10:42:07Z payments-api ERROR upstream timeout after 30000ms calling orders-db"
)


def build_crew() -> Crew:
    agent = Agent(
        role="Log reader",
        goal="Explain what a single log line says in plain English",
        backstory="You are an on-call engineer who reads logs all day.",
        llm=build_llm(),
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
