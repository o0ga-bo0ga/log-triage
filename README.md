# Log Triage

A multi-agent system (CrewAI) that triages logs from multiple services: what is wrong, how severe, probable root
cause, and suggested next steps. Built as an AgentOps learning project with a labeled eval set.

Status: synthetic log generator, deterministic parser, CrewAI parse tool and digest stage built and tested (roadmap
steps 1 to 3b). Agents (step 4) are next. See `docs/specs/ROADMAP.md`.

## Docs
- `docs/specs/SPEC.md` problem, scope, pipeline
- `docs/specs/EVALS.md` how quality is measured
- `docs/specs/ROADMAP.md` build order
- `docs/decisions/` architecture decision records
- `docs/ideas.md` parked ideas for future iterations
- `docs/HANDOVER.md` current state and context for picking the project up in a new session

## Setup
1. Python 3.11+. Create a virtualenv, then `pip install -r requirements.txt` and `pip install -e .`
2. Copy `.env.example` to `.env` and add your Groq API key.
3. `pytest -q` to run the tests; `python -m generator.generate --all --seeds 3` to generate sample logs.
