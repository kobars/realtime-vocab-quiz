# Agent rules for this repository

These rules apply to every change, whether a person or a coding agent makes it.

## One change, one pull request

- One change = one branch = one PR of at most **400 changed lines**, not counting lock files
  (`uv.lock`, `pnpm-lock.yaml`) and generated files. Bigger work is split into several PRs.
- Branch names are `<type>/<slug>`, for example `feat/redis-adapter` or `fix/answer-dedup`.
- Rebase on `origin/main` and run `make check` before you push. `main` stays green.
- Every PR is reviewed before it merges, by two reviewers (Claude Code `/code-review` and Codex).
  Their findings are verified against the code, and the confirmed ones are fixed in the same PR
  before the merge. A PR merges when CI and `make check` are green and the confirmed findings
  are fixed.

## Tests

- Write the test first where behavior matters; new behavior has a test that fails without it.
- **Never edit the tests in `api/tests/acceptance/`** once they are merged. The PR that adds them
  is the only one that changes the folder; after it, the reviewer checks that the folder is
  unchanged in every PR.

## Checks

- `make help` lists the targets. `make check` runs every check a change must pass; run it from
  the repository root. `make test-integration` runs the tests that need Redis.

## Secrets and private data

- Never commit secrets, tokens or real credentials. Local settings go in `.env`, which git ignores.
- No personal data: no home paths and no personal email addresses in files, commits or PRs.
- Commit messages and PR text describe the code change only.

## AI-assisted work

- Every source file that AI wrote or changed carries a marker after the comment sign:
  `# AI-ASSISTED: <summary>` (Python, Makefile), `-- AI-ASSISTED: <summary>` (Lua),
  `// AI-ASSISTED: <summary>` (TypeScript), `<!-- AI-ASSISTED: <summary> -->` (Vue templates),
  or `AI-ASSISTED-BEGIN` … `AI-ASSISTED-END` around a block.
- Every commit ends with the trailer `AI-Assisted: Claude Code (<model>)`.
- Every PR has an AI-LOG entry `docs/ai-log/PR-<n>.md`, where `<n>` is the GitHub PR number.
  Write it by hand from `docs/ai-log/TEMPLATE.md` right after `gh pr create`, commit it and push
  again. Record real mistakes only, and name a test file that exists under **Verification**.
