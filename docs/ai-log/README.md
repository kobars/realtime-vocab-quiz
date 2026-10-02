<!-- AI-ASSISTED: hand-written index of the AI-LOG entries: tools, reviews, how to read an entry, examples. -->
# AI log

Every pull request in this repository has one entry here, `PR-<n>.md`, where `<n>` is the
GitHub PR number. The design work before the first line of code is in
[design-phase.md](design-phase.md).

**Tools.** Claude Code (`claude-opus-5-5`) wrote the specs, the code, the tests and these
entries. Each PR is reviewed by Claude Code `/code-review` (high) and Codex (`gpt-6-astra`,
high or xhigh reasoning; the entry names which); the two finding lists are combined, each
finding is checked against the code, and the verified findings are posted as one PR comment. The first PRs were reviewed after they
merged, with the fixes in a follow-up PR; later PRs are reviewed before they merge. A PR that
only fixes listed review findings gets a fix check instead: another agent re-tests each listed
defect and runs no new review round. The **Reviewed by** line of each entry says which review
ran, when, and where its findings went.

**How to read an entry.** Each entry has six fields:

| Field | What it says |
|---|---|
| Tool | The tool and the model |
| Task | What the PR set out to do |
| Prompt / interaction | What the AI was given and what it produced, in a sentence or two |
| What was wrong or changed | The mistakes in the AI output, how each was found and how it was fixed |
| Verification | The commands that were run, their result, and the test that checks the change |
| Reviewed by | Who reviewed the PR, and when |

Most entries also give the date, the phase (design, implementation or testing) and the commit.
Every commit carries the trailer `AI-Assisted: Claude Code (<model>)`, and every source file
the AI wrote or changed carries an `AI-ASSISTED:` marker. Dependabot's commits are the
exception: a bot writes them, so they carry no trailer, and a PR made only of them has no entry.

**How AI-written code was verified.** No AI output counted as done on its own say-so:

- **Tests first.** New behavior gets a test that fails without the change, and the entry says so:
  [PR-156](PR-156.md) wrote its skip check test-first and broke `score_answer.lua` on purpose to
  see the invariants test fail; in [PR-122](PR-122.md) the Redis guard's test fails without the
  fixture and passes with it.
- **One gate, run twice.** `make check` runs before every push and CI runs it again with the
  Redis, stack, container and security workflows. In [PR-196](PR-196.md) a `make check` test
  found DESIGN.md missing a new route and script; in [PR-147](PR-147.md) the CI secret scan
  flagged an inline token in a README command.
- **Two independent reviewers per PR.** Claude Code `/code-review` and Codex review each PR
  (**Tools** above names the exceptions), and every finding is checked against the code and
  marked confirmed or refuted before anything is fixed: 7 confirmed and 4 refuted in [PR-180](PR-180.md), 9 confirmed and 1 refuted in
  [PR-175](PR-175.md).
- **End to end and under load.** System tests and browser specs run against the composed stack
  ([PR-161](PR-161.md), which removed nginx's `Upgrade` header to see four tests fail), and the
  bot swarm measures the latency target on two nodes ([PR-168](PR-168.md); since
  [PR-176](PR-176.md) a run that misses it fails).

**Where to start**, one or two entries per area:

- Scoring and the Redis store: [PR-10](PR-10.md) (the scoring rule), [PR-61](PR-61.md) (the serve and score scripts).
- Fan-out across nodes: [PR-105](PR-105.md) (the coalescing tick), [PR-145](PR-145.md) (two nodes, resubscribe and repair).
- WebSocket gateway: [PR-68](PR-68.md) (upgrade checks and limits), [PR-89](PR-89.md) (send buffers and conflation).
- Web client: [PR-37](PR-37.md) (the protocol client), [PR-165](PR-165.md) (the design system).
- Tests and CI: [PR-31](PR-31.md) (the acceptance suite), [PR-161](PR-161.md) (system tests and browser specs).

**Two examples where a review caught an AI mistake.**

- [PR-17](PR-17.md) ([#17](https://github.com/kobars/realtime-vocab-quiz/pull/17)), the
  session state machine: it accepted `next {N}` (finish the quiz) only from the last question,
  although the domain spec lets a player finish from any question. `test_next_n_finishes_from_any_cursor`
  in [`api/tests/unit/test_session.py`](../../api/tests/unit/test_session.py) now pins it.
- [PR-14](PR-14.md) ([#14](https://github.com/kobars/realtime-vocab-quiz/pull/14)), the
  client scaffold: the dev proxy forwarded `/api/sessions` unchanged, but the API serves
  `/sessions` at its root, so the client could not get a session.
  [`web/src/dev-proxy.test.ts`](../../web/src/dev-proxy.test.ts) now checks the rewrite.

New entries are written from [TEMPLATE.md](TEMPLATE.md).
