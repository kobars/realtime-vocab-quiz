<!-- AI-ASSISTED: security policy: how to report a vulnerability, the supported version, the deliberate mocks, the deployment assumption and the automated scans. -->
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

An API node is never published directly: nginx is the only public entry, and in
`compose.yaml` the nodes publish no port. uvicorn runs with no connection limit of its own
and times no request body (nginx buffers each body before passing it on), and the gateway's
connection caps count only accepted sockets, so the node bounds the earlier stages itself (`api/src/quiz/adapters/ws/heartbeat.py`): a request head above 16 KiB gets 400, a head
not complete within `HEADER_TIMEOUT_MS` (10 s by default) is closed, a WebSocket message of more
than 64 fragments is closed with 1009, and the upgrade attempts of one client address are
throttled before the ticket lookup (`docs/spec/protocol.md` §8).

## Automated checks

Every pull request and every push to `main` runs CodeQL (`.github/workflows/codeql.yml`) and
the security workflow (`.github/workflows/security.yml`): a gitleaks scan of the whole git
history of the checked-out commit (on a pull request, the merge commit, so other branches
never fail it), dependency review that blocks a new dependency with a high-severity advisory,
and audits of the locked Python (`pip-audit`) and production web (`pnpm audit`) dependencies.
Both workflows also run weekly. `make audit` runs the audits and the secret scan locally; it
needs the network, a full clone (not shallow) and gitleaks 8.25 or later on the `PATH` (CI
uses 8.30.1).
