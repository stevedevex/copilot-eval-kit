---
name: ai-skill-trigger-test
description: 'Generate should-trigger and should-not-trigger test prompts for every skill and custom agent, simulate routing from the descriptions, and flag vague or overlapping descriptions.'
agent: 'agent'
argument-hint: 'optional: a single skill or agent name'
---
# Trigger test for skills and custom agents

A skill only helps if Copilot loads it at the right moment, and the model decides mostly from the skill's **name + description**. A vague or overlapping description means the skill is either never used (wasted effort) or used when it shouldn't be (wasted tokens and wrong guidance). The same applies to custom agents' descriptions when they're used as subagents or handoffs.

If the user named one skill or agent after the command, test only that one.

## Ground rules

- Read-only, except for writing `.github/ai-eval/trigger-tests.md`.
- Skip `.github/ai-eval/**` and `.github/prompts/ai-*.prompt.md`.

## Steps

1. Collect every `SKILL.md` under `.github/skills/`, `.claude/skills/` and `.agents/skills/`, and every `.github/agents/*.agent.md`.
2. For each one, first read **only** the frontmatter `name` and `description`, because that is what the router sees. Then read the body to learn what it really does.
3. For each one, write:
   - **5 should-trigger prompts**: realistic developer requests in varied wording. At least 2 must *not* use the obvious keywords from the description.
   - **5 should-NOT prompts**: near misses, i.e. adjacent tasks that belong to another skill or to no skill.
4. **Simulate routing.** For every prompt, look at *all* the descriptions side by side and decide which skill(s) you would load. Mark ✅ match or ❌ mismatch against the expected answer.
5. **Flag problems:**
   - vague descriptions (e.g. "helps with Java"), or ones too broad to discriminate;
   - overlapping pairs: the same prompt plausibly triggers both;
   - body capabilities missing from the description, so they will never be discovered;
   - description promises the body doesn't keep;
   - `name` doesn't match the folder name, description missing, or description over 1024 characters.
6. **Propose a rewritten description** for each flagged item, in 1–2 sentences covering what it does, when to use it, the key trigger terms, and when *not* to use it.

## Output

Write `.github/ai-eval/trigger-tests.md` with one table per skill or agent:

| # | Prompt | Expected | Simulated | ✅/❌ | Actual (fill in after a real run) |
|---|---|---|---|---|---|

followed by the problems found and the proposed descriptions.

Then reply in chat with only the list of vague or overlapping items and the file path.

### How the human completes the test (for the file's footer)

Add this footer to the file:

> Run each prompt in a **new chat** with your team's usual model. Watch the Agent Debug panel (or ask `/troubleshoot which skills and instructions were loaded for the last request?`). As soon as you can see which customizations loaded, **cancel the request** to save credits, and fill in the "Actual" column. Trigger precision = correct loads ÷ all loads. Recall = correct loads ÷ should-trigger prompts. Aim for ≥ 80% on both.
