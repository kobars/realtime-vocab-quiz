#!/usr/bin/env bash
# AI-ASSISTED: checks the links and anchors in the tracked Markdown files with lychee in Docker.
# make check passes --offline (relative links and anchors only); the weekly workflow checks URLs too.
set -euo pipefail
cd "$(dirname "$0")/.."
git ls-files -z '*.md' | tr '\0' '\n' |
  docker run --rm -i -e GITHUB_TOKEN -v "$PWD:/input:ro" -w /input lycheeverse/lychee:0.24.2@sha256:e2d19e57cf6ab037026f20b8e449a1f30d9d7f81eef4194763aab2eab20bd28d \
    --include-fragments --no-progress --files-from - "$@"
