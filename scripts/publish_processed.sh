#!/usr/bin/env bash
# Publish processed tables (and the raw fetch manifest, for lineage) to the `data` branch.
# Raw JSON is never committed. Usage: scripts/publish_processed.sh "<commit message>"
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
wt="$repo/../swedish-suede-data"
msg="${1:-Update processed data}"

if [ ! -d "$wt" ]; then
  if git -C "$repo" ls-remote --exit-code --heads origin data >/dev/null 2>&1; then
    git -C "$repo" fetch origin data
    git -C "$repo" worktree add "$wt" data
  else
    git -C "$repo" worktree add --orphan -b data "$wt"
  fi
fi

rm -rf "$wt/processed"
mkdir -p "$wt/processed" "$wt/raw_manifest"
cp -a "$repo/data/processed/." "$wt/processed/"
rm -f "$wt/processed/.gitkeep"
cp "$repo/data/raw/manifest.jsonl" "$wt/raw_manifest/manifest.jsonl"
cat > "$wt/README.md" <<'MD'
# Data branch

Processed tables built by `python -m nhlmodel.ingest.process` on `main`. Regenerable from
the raw NHL responses; `raw_manifest/manifest.jsonl` lists every raw fetch (URL, UTC time,
HTTP status, sha256). Restore into a checkout of `main` with:

    git fetch origin data
    git archive origin/data processed | tar -x --strip-components=1 -C data/processed
MD
git -C "$wt" add -A
if git -C "$wt" diff --cached --quiet; then echo "nothing to publish"; exit 0; fi
git -C "$wt" commit -q -m "$msg

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01EGYQsKZDeuiirJfPyiykDv"
git -C "$wt" push -u origin data
