#!/usr/bin/env bash
# AI-ASSISTED: checks the links and anchors in the tracked Markdown files with lychee in Docker.
# make check passes --offline (relative links and anchors only); the weekly workflow checks URLs too.
set -euo pipefail
cd "$(dirname "$0")/.."
git ls-files -z '*.md' | tr '\0' '\n' |
  docker run --rm -i -e GITHUB_TOKEN -v "$PWD:/input:ro" -w /input lycheeverse/lychee:0.24.2 \
    --include-fragments --no-progress --files-from - "$@"
