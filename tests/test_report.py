import json
import re

import pandas as pd
import pytest

from nhlmodel.report.build import TEMPLATE, _train_label, build


def test_template_is_pure_ascii():
    # Non-ASCII glyphs render from fallback fonts with different widths and break the column grid.
    assert not re.search(r"[^\x00-\x7F]", TEMPLATE.read_text())


def test_train_label():
    assert _train_label("20222023-20222023") == "2022-23"
    assert _train_label("20222023-20242025") == "2022-23 -> 2024-25"


def test_build_embeds_real_payload(tmp_path):
    from nhlmodel.config import load_config, repo_path

    if not (repo_path("data/processed/games.parquet")).exists():
        pytest.skip("games table not present")
    html = build(load_config("configs/data.yaml"), tmp_path).read_text()
    blob = re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S).group(1)
    payload = json.loads(blob.replace("<\\/", "</"))
    games = pd.read_parquet(repo_path("data/processed/games.parquet"))
    assert payload["data"]["total_games"] == len(games)
    assert "/*__DATA__*/" not in html
