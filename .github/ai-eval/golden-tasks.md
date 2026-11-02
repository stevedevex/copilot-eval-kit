# Golden tasks

Benchmark tasks for evaluating our Copilot agents, instructions, skills and model choices.
Each task is replayed from a real commit: the agent starts at the **start commit**, and the **reference commit** is the human solution, used for hidden tests and comparison.

- Generate or refresh this file with `/ai-eval-build-tasks`, then **review every task by hand**. A bad task makes a bad benchmark.
- Keep 10–15 tasks. Mark 5 of them as the **smoke set**, to run on every change to the AI files.
- Never show the reference commit or hidden tests to the agent under test.
- Add a task whenever Copilot fails at something real in day-to-day work. Those are the most valuable ones.

---

<!-- EXAMPLES BELOW: illustrative only. /ai-eval-build-tasks replaces them with tasks from your own git history. -->

### T01 (EXAMPLE): Add paging to the section-history endpoint
- Category / difficulty: Feature / M
- Start commit: `<parent sha>`
- Reference commit: `<sha>`
- Module(s): `presentation-service`
- Prompt to give the agent:
  > The GET section-history endpoint returns everything at once and times out for large clients. Add page/size query parameters (default size 50, max 200) and return a page object with total count. Keep the existing response field names.
- Expected agent / skills: `java-developer` agent; `spring-rest` and `mongodb-starter` skills; `java.instructions.md`
- Hidden tests: `presentation-service/src/test/java/.../SectionHistoryControllerTest.java`
- Acceptance checks:
  - [ ] `mvn -q -pl presentation-service -am verify` passes
  - [ ] hidden tests pass
  - [ ] uses the shared paging DTO, not a new one
  - [ ] Mongo query uses the existing repository and index; no `findAll()` and then slicing in memory
- Reviewer notes: watch for in-memory paging, a missing max-size guard, and changed JSON field names.

### T02 (EXAMPLE): Fix cache not refreshed on other pods after a config update
- Category / difficulty: Bug fix / M
- Start commit: `<parent sha>`
- Reference commit: `<sha>`
- Module(s): `platform-config`
- Prompt to give the agent:
  > After updating an app config entry through the admin API, only the pod that handled the request shows the new value; other pods keep the old one until restart. Find and fix the cause.
- Expected agent / skills: default agent; `caching` skill
- Hidden tests: `platform-config/src/test/java/.../ConfigCacheInvalidationIT.java`
- Acceptance checks:
  - [ ] `mvn -q -pl platform-config -am verify` passes (Testcontainers)
  - [ ] hidden integration test passes
  - [ ] no polling or scheduled full reload added as a workaround
- Reviewer notes: a good fix uses the existing change-stream listener path; check the resume-token handling isn't broken.

---

## Coverage

| Category | Count | Customizations exercised |
|---|---|---|
| | | |

## Smoke set

`T01, T02, …`
