---
description: Commit the current changes with a proper message, then push to main, leaving out files that must not be committed
argument-hint: [optional hint about what the commit is for]
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git add:*), Bash(git commit:*), Bash(git push origin main)
---

Commit the current work and push it to `main`. Hint from the owner (may be empty): $ARGUMENTS

## Steps

1. Run `git status`, `git diff` (staged and unstaged) and `git log -5 --oneline` to see what changed and the message style in use.
2. Decide which files belong in this commit. One commit = one logical change, small enough to review in one sitting.
   If the changes mix unrelated work, propose a split into several commits and do them one at a time.
3. Stage files **by name** (`git add path/to/file`). Never `git add -A` or `git add .`.
4. If the commit changes Python code, run `.venv/bin/python -m pytest -q` first. Do not commit on a failing run
   unless the owner says so; report the failure instead.
5. Show the owner the file list and the message, then commit.
6. Push with `git push origin main`. Only push from the `main` branch: if the current branch is not `main`, commit
   but do not push, and tell the owner. If the push is rejected, report it; do not force-push or pull/rebase unasked.
7. Run `git status` afterwards and report what was committed, what was pushed, and what was deliberately left out.

## Never commit

- **`docs/`**: the owner's private specs, ADRs, ideas and notes. It is gitignored and must never reach GitHub.
  Never force-add it (`git add -f`).
- Secrets and local config: `.env`, API keys, tokens, anything that looks like a credential. If a staged diff
  contains something that looks like a secret, stop and tell the owner.
- Local environment and caches: `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/`.
- Generated data: anything under `data/sample_logs/` except `.gitkeep`.
- Scratch files, probes and experiments that are not part of a roadmap step.

If a file is not covered here and you are unsure, leave it out and ask.

## Commit message

- Imperative mood, capitalised, no trailing full stop, no prefixes like `feat:`: `Add log event schema`,
  `Fix onset detection for quiet services`.
- Subject line 72 characters or fewer, saying **what** the commit does.
- Add a body only when the **why** is not obvious from the diff: a blank line, then short wrapped lines.
  Mention verified facts or tradeoffs worth remembering (for example "Groq rejects schemas without additionalProperties: false").
- End the message with this line, after a blank line:

      Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>

- Pass the message with a heredoc so the formatting survives.

## Rules

- Push only to `origin main`, only as the last step of this command.
- Never amend, rebase, reset or force-push anything unless asked.
- Never skip hooks (`--no-verify`) or signing.
- If a hook fails, fix the cause and make a new commit; do not work around it.
- If there is nothing to commit, say so and stop.
