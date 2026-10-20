"""The assembled feature table carries no outcomes, and leaky columns are labelled as such."""
import pandas as pd
import pytest

from nhlmodel.config import repo_path
from nhlmodel.features.build import OUTCOME_COLS


@pytest.fixture(scope="module")
def tables():
    f, l = repo_path("data/processed/features.parquet"), repo_path("data/processed/labels.parquet")
    if not (f.exists() and l.exists()):
        pytest.skip("feature table not built")
    return pd.read_parquet(f), pd.read_parquet(l)


def test_no_outcome_columns(tables):
    feats, _ = tables
    assert not OUTCOME_COLS & set(feats.columns)


def test_actual_starter_columns_are_marked_leaky(tables):
    feats, _ = tables
    actual = [c for c in feats.columns if "actual_goalie" in c]
    assert actual and all("leaky_" in c for c in actual)


def test_features_and_labels_cover_the_same_games(tables):
    """Every labelled game has features; the only unlabelled feature rows are upcoming games."""
    feats, labels = tables
    assert feats["game_id"].is_unique and set(labels["game_id"]) <= set(feats["game_id"])
    up = repo_path("data/processed/upcoming.parquet")
    upcoming = set(pd.read_parquet(up)["game_id"]) if up.exists() else set()
    assert set(feats["game_id"]) - set(labels["game_id"]) <= upcoming
