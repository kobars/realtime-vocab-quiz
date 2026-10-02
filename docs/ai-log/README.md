<!-- AI-ASSISTED: hand-written index of the AI-LOG entries: tools, reviews, how to read an entry, examples. -->
# AI log

Every pull request in this repository has one entry here, `PR-<n>.md`, where `<n>` is the
GitHub PR number. The design work before the first line of code is in
[design-phase.md](design-phase.md).

**Tools.** Claude Code (`claude-opus-5-5`) wrote the specs, the code, the tests and these
entries. Each PR is reviewed by Claude Code `/code-review` (high) and Codex (`gpt-6-astra`,
high reasoning); the two finding lists are combined, each finding is checked against the code,
and the verified findings are posted as one PR comment. The first PRs were reviewed after they
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
Every commit carries the trailer `AI-Assisted: Claude Code (<model>)`, and every file the AI
wrote or changed carries an `AI-ASSISTED:` marker.

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
