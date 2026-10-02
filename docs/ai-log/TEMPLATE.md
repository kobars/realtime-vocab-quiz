## PR-<n> — <title>

- **Tool:** <tool and model, for example Claude Code (claude-opus-5-5)>
- **Task:** <what the PR set out to do>
- **Prompt / interaction:** <the nature of the interaction, in one or two sentences>
- **What was wrong or changed:** <"nothing" if none; else one sub-bullet per mistake in the AI output>
  - <mistake> → <how it was found> → <fix> (<test>)
- **Verification:** <the command that was run, its result, and a test path that exists>
- **Reviewed by:** <the reviewer>
- **Date:** <YYYY-MM-DD>
- **Phase:** <design | implementation | testing>
- **Commit:** <short SHA>

<!-- Required: Tool, Task, Prompt / interaction, What was wrong or changed, Verification, Reviewed by. Recommended: Date, Phase, Commit. Verification names a test file that exists: api/tests/**/test_*.py, scripts/tests/test_*.py or web/src/**/*.test.ts. -->
