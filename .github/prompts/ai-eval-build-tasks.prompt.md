---
name: ai-eval-build-tasks
description: 'Draft a golden task set for evaluating our Copilot agents/skills, replayed from real commits so every task has a known-good reference solution and an objective check.'
agent: 'agent'
argument-hint: 'optional: number of tasks (default 12) and/or a module to focus on'
---
# Build a golden task set from our real history

Goal: produce 10–15 tasks that represent the work this team really does. Each task must be replayable from git history, so that it has a **reference solution** (the real commit) and an **objective pass/fail check**. This set is the benchmark for every future change to our agents, instructions, skills and model choices.

If the user typed a number or module name after the command, use it.

## Ground rules

- **Read-only**, except for writing `.github/ai-eval/golden-tasks.md`. Do not check out, reset or modify any branch.
- **Never leak the solution into the task prompt**: no code, and no names of classes or files that the commit *created*, unless the developer would already have known them.
- If an audit report exists in `.github/ai-eval/reports/`, read its "Golden-task candidates" section first and favour those task types.

## Step 1: Find candidate commits

Run this, widening the window if history is thin:

```
git log --since="180 days ago" --no-merges --date=short --pretty=format:"%h|%ad|%s" --shortstat | head -800
```

A good candidate commit:

- is self-contained: one logical change, ideally 1–8 files and under about 400 changed lines;
- has an objective check: a test added or changed in the same commit, or a build/lint/static-analysis rule that fails before and passes after;
- doesn't depend on secrets, external systems or manual steps;
- builds at its parent commit. Check with `git show --stat <sha>` and judge from the files.

Aim for this mix, adapted to what the history actually contains:

| Category | Share |
|---|---|
| Feature: endpoint, service method, mapper, config property | ~30% |
| Bug fix with a regression test | ~20% |
| Test authoring: unit or integration (e.g. Testcontainers) | ~15% |
| Refactor or pattern adoption: our starters, exception hierarchy, shared libs | ~10% |
| Data/schema: repository, index, migration/changeset, generated models (OpenAPI/JSON-schema) | ~10% |
| Build/CI/infra: pom, CI pipeline, Helm/K8s manifests | ~10% |
| Review/explain: no code change, graded on findings | ~5% |

Also include 2–3 tasks that exercise **each important custom agent or skill**, so every customization gets tested.

## Step 2: Write each task

Write the prompt **the way a developer would have asked for it before the change existed**.

Use this format for every task:

```
### T01: <short title>
- Category / difficulty: Feature / M          (S = <30 min human, M = 1–2 h, L = half day+)
- Start commit: <parent sha>                   (the agent starts from here)
- Reference commit: <sha>                      (the human solution; never shown to the agent under test)
- Module(s): <module path>
- Prompt to give the agent:
  > <1–6 sentences, realistic; may include ticket-style context>
- Expected agent / skills: <custom agent to select; skills and instructions that should load; or "none">
- Hidden tests: <test file paths from the reference commit to apply after the agent finishes, or "none">
- Acceptance checks (objective):
  - [ ] `<exact build/test command>` passes, e.g. `mvn -q -pl <module> -am verify`
  - [ ] hidden tests pass
  - [ ] only touches <area>; no unrelated files
  - [ ] follows <convention>: cite instruction/skill file and rule
- Reviewer notes: what a good solution must include; typical failure modes to look for.
```

**Hidden tests** are the strongest signal. The tests from the reference commit are withheld from the agent and copied in after it finishes. Only for test-authoring tasks do you show nothing about the tests, and grade them by whether they fail against the parent's buggy code (if it's a bug) and pass against the fix.

If a commit has no tests, write acceptance checks a reviewer can decide in under 2 minutes.

## Step 3: Save

Write all tasks to `.github/ai-eval/golden-tasks.md`. Keep its header section and replace the example tasks.

End the file with:

- a coverage table: category × count, and which customization each task exercises;
- a **smoke set**: the 5 tasks that best cover the setup, to run on every change to the AI files.

Reply in chat with only the coverage table and the smoke set.
