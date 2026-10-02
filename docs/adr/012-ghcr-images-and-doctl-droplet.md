# ADR-012 — Prebuilt images on GHCR, and doctl over Terraform for one Droplet

[All decisions](../DECISIONS.md)

<!-- AI-ASSISTED-BEGIN: ADR-012 drafted with Claude Code from .github/workflows/containers.yml, compose.images.yaml and scripts/deploy/. -->

- **Status:** accepted
- **Date:** 2026-10-02

## Context

`make prod-up` built both images on the public host. The web build (pnpm and Vite) needs more memory than a 1 GiB Droplet has and takes minutes on a small one, and the host ran images that no scan had seen. Creating the Droplet, its firewall and its DNS record was manual work in the DigitalOcean control panel.

## Decision

- The containers workflow publishes the API and web images to GitHub Container Registry on every push to `main` and on `vX.Y.Z` tags, after the config and image checks. Each platform (amd64 and arm64) builds on a native runner and pushes by digest only, with a BuildKit SBOM and `mode=max` provenance; Trivy scans that digest as pulled; a second job then tags the multi-arch image (`main` and the short SHA, or the version) and adds a signed GitHub provenance attestation. Only those two jobs hold `packages: write`, and only the tagging job holds `id-token: write`.
- `compose.images.yaml` names the published images by `IMAGE_TAG` (default `main`). The prod targets add it whenever `IMAGE_TAG` is set; empty, the host builds as before. A pull replaces the tag's local images, so `make prod-update` first tags the running ones `rollback` and goes back to them when the update does not get ready.
- `scripts/deploy/droplet.sh` (`make do-deploy`, `make do-destroy`) drives an already signed-in `doctl`: a Cloud Firewall bound to the tag `realtime-vocab-quiz`, one SSH-key-only Droplet with that tag and the cloud-init user data, and the A record when the domain is a DigitalOcean zone. Destroy deletes only what carries the tag or the firewall's name, after a typed `yes`.

## Alternatives considered

- **Build on the host (as before):** no registry, but a larger Droplet, minutes per deploy and unscanned images. Kept behind `--build` and an empty `IMAGE_TAG` for branches without published images.
- **Docker Hub:** a second account and a token in CI; GHCR uses the workflow's own `GITHUB_TOKEN` and links each image to the repository and its attestations. Rejected.
- **Terraform (or Pulumi) for the Droplet:** declarative state and drift detection, but it adds a tool, a provider and a state file that must live somewhere and holds the Droplet's details, all for one Droplet, one firewall and one record that a single command creates and the tag finds again. Rejected for this size; the next step if the host grows into several resources or environments.
- **One multi-arch build under QEMU on one runner:** one job, but the arm64 web build runs emulated and slowly. Rejected for native arm64 runners.
- **Pin the host to a digest:** the most exact, but every update would edit `.env`. The host takes a tag; the short-SHA and version tags never move, and the attestation ties each digest to its commit.

## Consequences

- A small Droplet runs the stack, and an update is a pull: about the time to download two images.
- The `main` images trail a merge by the workflow's run time; `make prod-update` started earlier pulls the previous `main` images with the new checkout's config.
- A new GHCR package starts private: each is set to public once, so a VM pulls without a login. Until then, and before a tag's first publish, the pull fails and the host builds the images itself under the published names, so a fresh install still starts.
- The tag `realtime-vocab-quiz` marks what `make do-destroy` deletes: one Droplet per account and tag at a time, and nothing else with that tag should exist.

<!-- AI-ASSISTED-END -->
