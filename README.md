# Data branch

Processed tables built by `python -m nhlmodel.ingest.process` on `main`. Regenerable from
the raw NHL responses; `raw_manifest/manifest.jsonl` lists every raw fetch (URL, UTC time,
HTTP status, sha256). Restore into a checkout of `main` with:

    git fetch origin data
    git archive origin/data processed | tar -x --strip-components=1 -C data/processed
    python -m nhlmodel.features.build      # features.parquet and labels.parquet (~1.5 min)
