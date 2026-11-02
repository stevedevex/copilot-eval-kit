# Scoring rubric for golden-task runs

Quality and cost are scored **separately**. The score below covers quality only. Cost (credits, model calls, follow-ups, fix minutes) goes in its own scorecard columns, so you can compare *quality per credit*.

## Gate: `pass` (Y/N)

`Y` only if **every** objective acceptance check in the task passes (build, hidden tests, scope check). This is the headline metric.

## Quality score (0–10)

| Dimension | Points | 0 | middle | max |
|---|---|---|---|---|
| **Correctness** | 0–4 | Doesn't build, or solves the wrong problem | 1 = builds but fails hidden tests/acceptance · 2 = most checks pass, a notable gap · 3 = all checks pass, minor issue | 4 = all checks pass, as good as or better than the reference commit |
| **Conventions** | 0–2 | Ignores our patterns (e.g. hand-rolled config instead of our starter, wrong exception hierarchy, wrong test style) | 1 = partly | 2 = follows every applicable rule in our instructions/skills |
| **Context use** | 0–2 | Hallucinated APIs, classes or config keys, or worked in the wrong module | 1 = right area, but missed an existing helper and duplicated it | 2 = reused existing code; the right agent/skill was used |
| **Scope** | 0–1 | Unrelated edits, gratuitous refactors, mass reformatting | | 1 = only what the task needed |
| **Safety** | 0–1 | Secrets in code or logs, disabled or skipped tests (`@Disabled`, `-DskipTests`), weakened security config | | 1 = none of these |

`score_total` = sum of the five.

## Cost and effort columns (filled from the Agent Debug panel and the user)

| Column | Meaning |
|---|---|
| `model_calls` | Number of LLM requests in the session (Agent Debug → Summary / Logs) |
| `input_tokens` | **Uncached** input tokens. If the panel shows total input including cached, subtract the cached part. |
| `cached_tokens` | Cached input tokens (read from cache) |
| `cache_write_tokens` | Tokens written to cache, if shown (Anthropic models charge for this). Otherwise 0. |
| `output_tokens` | Generated tokens |
| `credits` | Leave empty; `measure_context.py --scorecard` computes it from `pricing.csv` |
| `followups` | Prompts the user sent after the first one (clarifications don't count; corrections do) |
| `fix_minutes` | The user's estimate of minutes needed to finish or fix the result by hand |

## Headline metrics (computed by the script)

- **Pass rate** per config
- **Uplift** = pass rate (config) − pass rate (`baseline`, i.e. no repo customizations)
- **Credits per run**, and **credits per pass** (total credits ÷ passes), the real price of a *working* result
- **Follow-ups** and **fix minutes**: human effort the agent didn't save
