#!/usr/bin/env bash
# Force-push the built site/ folder to the `site` branch (Vercel deploys that branch).
# Run from the repo root on GitHub Actions: needs GITHUB_TOKEN, GITHUB_REPOSITORY and GITHUB_SHA.
set -euo pipefail

cp deploy/site-vercel.json site/vercel.json
cd site
rm -rf .git   # a fresh one-commit branch every time (the watcher publishes several times per job)
git init -q -b site
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -A
git commit -q -m "Site build $(date -u +%Y-%m-%dT%H:%MZ) from ${GITHUB_SHA::7}"
git push -q -f "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" site
