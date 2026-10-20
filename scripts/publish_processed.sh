#!/usr/bin/env bash
# Publish processed tables (and the raw fetch manifest, for lineage) to the `data` branch.
# Raw JSON is never committed. Usage: scripts/publish_processed.sh "<commit message>"
#
# features.parquet and labels.parquet are left out: they are rebuilt from the other tables by
# `python -m nhlmodel.features.build` (~1.5 min), and the feature table alone is ~50 MB, which would
# add that much to the repository's history on every publish.
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
rm -f "$wt/processed/.gitkeep" "$wt/processed/features.parquet" "$wt/processed/labels.parquet"
# live-run outputs: rebuilt by `python -m nhlmodel.live`, never published here
rm -f "$wt/processed/upcoming.parquet" "$wt/processed/lineups_confirmed.parquet" \
      "$wt/processed/predictions_upcoming.parquet" "$wt/processed/predictions_season.parquet" \
      "$wt/processed/predictions_log.csv"
# The manifest only grows; without a local raw cache, keep the copy already on the branch.
if [ -f "$repo/data/raw/manifest.jsonl" ]; then
  cp "$repo/data/raw/manifest.jsonl" "$wt/raw_manifest/manifest.jsonl"
fi
cat > "$wt/README.md" <<'MD'
# Data branch

Processed tables built by `python -m nhlmodel.ingest.process` on `main`. Regenerable from
the raw NHL responses; `raw_manifest/manifest.jsonl` lists every raw fetch (URL, UTC time,
HTTP status, sha256). Restore into a checkout of `main` with:

    git fetch origin data
    git archive origin/data processed | tar -x --strip-components=1 -C data/processed
    python -m nhlmodel.features.build      # features.parquet and labels.parquet (~1.5 min)
MD
git -C "$wt" add -A
if git -C "$wt" diff --cached --quiet; then echo "nothing to publish"; exit 0; fi
git -C "$wt" commit -q -m "$msg"
git -C "$wt" push -u origin data
