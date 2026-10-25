# Roadmap

Each step is small, runnable on its own, and written by the owner with Claude reviewing.

Learn-before notes use CrewAI concepts: Agent, Task, Crew, Process, Tool, structured outputs, LLM config, kickoff.
Defer for v1: memory, knowledge/RAG.

- [x] 0. Project scaffold, specs, rules (this repo)
- [x] 1. Hello crew: one agent, one task, Groq working. Learn: LLM config, kickoff and inputs
- [x] 2. Synthetic generator: logs + labels, plain Python. Learn: nothing CrewAI-specific
- [x] 3. Parser as a custom tool + Pydantic LogEvent. Learn: tools, structured outputs
- [x] 3b. Digest stage: deterministic evidence summary between parser and agents (added 2026-10-26)
- [ ] 4. Classifier and fix suggestor agents with structured outputs
- [ ] 5. Eval runner and first baseline numbers. Learn: testing and costs
- [ ] 6. Escalation (junior to senior) and baseline comparison. Learn: errors, retries, reliability
- [ ] 7. Tracing and cost tracking (choose tool, write ADR)
- [ ] 8. README with architecture diagram, results, what broke, and costs

Steps 1 and 2 are independent and can run in parallel.
