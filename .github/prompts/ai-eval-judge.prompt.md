---
name: ai-eval-judge
description: 'Grade one golden-task run: run the acceptance checks and hidden tests, compare with the reference commit, score with the rubric, append a row to the scorecard.'
agent: 'agent'
argument-hint: '<task id> <config> <worktree path> [run #]   e.g.  T03 current ../eval/T03-current 1'
---
# Grade a golden-task run

> Run this in a **new chat**, preferably with a **different model** from the one that did the task, so the work isn't grading itself.

## Inputs

Read these from the text after the command. Ask **once**, in a single message, for anything missing.

- **task id**, from `.github/ai-eval/golden-tasks.md`
- **config label**, e.g. `baseline`, `current`, `v2-skills`
- **worktree path**, where the agent under test made its changes
- **run number** (default 1)
- **From the user**, read off VS Code's Agent Debug panel for that run (Summary view, or the per-request Logs view):
  - model used, and custom agent used (if any)
  - number of model calls (LLM requests)
  - input tokens (uncached), cached input tokens, cache-write tokens (if shown), output tokens. If only a total is shown, put it in input tokens and note it.
  - follow-up prompts the user had to send after the first one
  - minutes the user would need to finish or fix the result by hand

## Steps

1. Read the task block, and read `.github/ai-eval/rubric.md`.
2. **Save the agent's work before touching anything:**
   ```
   git -C <wt> add -A
   git -C <wt> diff --cached <start-commit> -- . ":(exclude).github" ":(exclude)AGENTS.md" > .github/ai-eval/runs/<task>-<config>-<run>.patch
   ```
   Create `.github/ai-eval/runs/` if it doesn't exist. Then read the patch.
3. **Objective checks.** Run every acceptance command inside the worktree. For hidden tests:
   `git -C <wt> checkout <reference-commit> -- <hidden test paths>`, then run them.
   Record pass/fail per check. For failures, keep the last 30 lines of output.
   (The worktree is disposable; it's fine to add hidden tests to it.)
4. **Compare with the reference** (`git show <reference-commit>`). Is the behaviour equivalent? Any missing cases, extra scope, or a better or worse design?
5. **Conventions.** List the specific rules from our instructions and skills that applied to this change. For each, say followed or violated, citing the patch line.
6. **Hallucinations.** List any API, class, method, config key, dependency or command used that doesn't exist in the repo or its dependencies.
7. **Score with the rubric.** Be strict: a change that doesn't compile scores 0 on correctness, whatever its style. `pass` = Y only if **all** objective checks pass.

## Output

1. In chat: a verdict of at most 8 lines (pass/fail, scores, the single biggest problem, and which customization should have prevented it).
2. Append exactly one row to `.github/ai-eval/scorecard.csv`, matching its header column order. Rules:
   - `date` is today (YYYY-MM-DD).
   - Leave `credits` empty; `measure_context.py --scorecard` computes it.
   - Put a short reason in `notes`, with commas replaced by semicolons.
3. If a customization caused the failure (wrong rule, missing rule, wrong skill triggered), say which file and what to change.
