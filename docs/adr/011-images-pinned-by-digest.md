# ADR-011 — Images pinned by digest; the runtime stages keep the OS package upgrade

[All decisions](../DECISIONS.md)

<!-- AI-ASSISTED-BEGIN: ADR-011 drafted with Claude Code from the Dockerfiles, compose.yaml, the CI workflows and .github/dependabot.yml. -->

- **Status:** accepted
- **Date:** 2026-10-02

## Context

The Dockerfiles, `compose.yaml`, the CI Redis service and the integration-test fixture named their images by tag only (`python:3.14-slim`, `redis:8-alpine`). A tag moves, so the image that Trivy scanned on a pull request was not necessarily the image a later build used. The runtime stages also run `apt-get upgrade` (API) and `apk upgrade` (web), because the base tags lag behind the distribution's security fixes and the image scan fails on a CRITICAL or HIGH finding that has a fix.

## Decision

- Every image is written as `name:tag@sha256:<digest>`, where the digest is the multi-platform index, so the same line builds on amd64 CI runners and arm64 laptops: each `FROM`, the `COPY --from` uv image, both Redis services of `compose.yaml`, the CI Redis service, the test fixture's Redis and the tool images that `docker run` pulls (hadolint in `.github/workflows/containers.yml`, lychee in `scripts/check_links.sh`). The API and web images that `make build` makes keep their local tag. Redis is pinned to a minor version (`8.10-alpine`).
- Dependabot (`docker` for the Dockerfiles, `docker-compose` for `compose.yaml`) proposes new digests weekly, after its 7-day cooldown.
- The runtime stages keep the OS package upgrade.

## Alternatives considered

- **Drop the upgrade and take OS fixes only through Dependabot digest updates:** a fully reproducible image, but a new digest arrives only after the upstream image is rebuilt and the cooldown has passed, often days or weeks after the distribution fix, and the image scan fails in the meantime. Rejected.
- **Tags only:** no update churn, but the scanned image and the shipped image can differ. Rejected.
- **Pin each OS package version:** reproducible, but every security fix becomes a hand edit across many packages. Rejected.

## Consequences

- The base layers are fixed per commit. The upgraded OS packages depend on the build day, so two builds of one commit can differ there; the containers workflow scans the image it built in the same job, so the scanned image is the one that run built.
- A Dependabot `docker-compose` update changes `compose.yaml` only; `.github/workflows/ci.yml` and `api/tests/conftest.py` take the same line in that pull request, which `scripts/tests/test_images.py` enforces. Dependabot does not read `docker run` commands, so the hadolint and lychee digests are updated by hand; the same test fails on any of them without a digest.

<!-- AI-ASSISTED-END -->
