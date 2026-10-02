<!-- AI-ASSISTED: security policy: how to report a vulnerability, the supported version, the deliberate mocks, the deployment assumption, the known limits and the automated scans. -->
# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's private vulnerability reporting:
open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a
public issue for a security problem. Include the affected file or endpoint, the steps to
reproduce it and the impact you expect.

## Supported version

Only the `main` branch is supported. There are no releases; fixes land on `main`.

## Mocked on purpose

This is a demonstration build. These parts are mocks by design (DESIGN.md §14), so their
weaknesses are known limits, not vulnerabilities:

- **Identity.** `POST /sessions` issues an anonymous user ID and a session token to anyone;
  there is no login. The single-use 30 s WebSocket ticket is real.
- **Question bank.** Seed quizzes are read from JSON files in the repository.
- **Quiz admin.** The admin API is off unless `ADMIN_MOCK=1`, and then it is guarded by one
  shared `X-Admin-Token` instead of per-user roles.

Reports about the real-time service itself are in scope: the WebSocket gateway and its
limits, the ticket check, the Redis scripts and the client.

## Deployment assumption

API nodes are never published directly; nginx is the only public entry. The limits each node
enforces itself are in [DESIGN.md §12](DESIGN.md#12-security).

## Known limits

**The ticket in nginx's error log.** The API's logs and nginx's access log never record the query
string that holds the WebSocket ticket. nginx's error log (level `warn`, on its stderr) is the
exception: when an upgrade fails at a node (a refused connect or a timeout), its line quotes the
request line, ticket included. The node that failed may not have redeemed that ticket, so single
use does not protect it by itself: nginx passes the upgrade on to the other node, which normally
redeems it, but if that node fails too the ticket stays valid until it expires. That is low risk:
the ticket lives 30 s and gives only an anonymous mock identity. The log goes to whoever runs the
containers, and a failed run of the `stack` CI workflow uploads the stack's logs as an artifact;
that stack listens only on the CI runner, so its tickets cannot be used from outside, and it is
gone when the job ends.

## Automated checks

Every pull request and every push to `main` runs these security checks, and both workflows also
run weekly:

- **CodeQL** (`.github/workflows/codeql.yml`).
- **The security workflow** (`.github/workflows/security.yml`): a gitleaks scan of the whole git
  history of the checked-out commit (on a pull request, the merge commit, so other branches
  never fail it), dependency review that blocks a new dependency with a high-severity advisory,
  and audits of the locked Python (`pip-audit`) and production web (`pnpm audit`) dependencies.
  On a pull request the audits run only when a lock file or a file that sets how they run
  changes (the `audit-inputs` job lists them); pushes to `main` and the weekly runs audit every
  time.
- **Pinning.** Every action in the workflows is pinned to a commit SHA and every image to a
  digest; Dependabot updates them weekly, except the hadolint and lychee images that
  `docker run` pulls, which are updated by hand.
- **OpenSSF Scorecard** (`.github/workflows/scorecard.yml`) checks the repository's supply-chain
  practices on each push to `main` and weekly, and uploads its results to code scanning.

`make audit` runs the audits and the secret scan locally; it needs the network, a full clone (not
shallow) and gitleaks 8.25 or later on the `PATH` (CI uses 8.30.1). The other checks every change
passes are in [CONTRIBUTING.md](CONTRIBUTING.md#what-make-check-runs).
