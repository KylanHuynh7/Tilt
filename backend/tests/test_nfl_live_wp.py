"""NFL v1.1 live WP: features, n-dim fit, checks, guardrails (offline)."""

import json
import math
import random
from pathlib import Path

import pytest

from app.core import logistic
from app.nfl import live_wp, pbp
from scripts import nfl_live_wp_evaluate


def test_tau():
    assert live_wp.tau_for(1, 900) == 3600 and live_wp.tau_for(4, 60) == 60 and live_wp.tau_for(5, 600) == 600


def test_features_shape_and_possession_sign():
    x = live_wp.features(0.5, 3600, 7, 1, 20)
    assert len(x) == 5 and x[0] == 1.0
    assert math.isclose(live_wp.features(0.5, 3600, 7, -1, 20)[3], -x[3])


def test_logistic_fit_recovers_coefficients():
    rng = random.Random(3)
    truth = [0.2, -0.8, 1.1]
    xs, ys = [], []
    for _ in range(6000):
        x = [1.0, rng.uniform(-2, 2), rng.uniform(-2, 2)]
        xs.append(x)
        ys.append(1.0 if rng.random() < logistic.sigmoid(sum(b * v for b, v in zip(truth, x))) else 0.0)
    beta = logistic.fit(xs, ys)
    assert all(abs(b - t) < 0.12 for b, t in zip(beta, truth))


def test_evaluator_guardrails(tmp_path: Path):
    assert nfl_live_wp_evaluate.main(["--out", str(tmp_path / "x.json")]) == 2
    out = tmp_path / "r.json"
    out.write_text("{}")
    assert nfl_live_wp_evaluate.main(["--confirm", "--out", str(out)]) == 3


@pytest.mark.skipif(not live_wp.ARTIFACT.exists(), reason="not fitted")
def test_artifact_trained_on_training_seasons_only():
    a = json.loads(live_wp.ARTIFACT.read_text())
    assert a["training_seasons"] == pbp.TRAIN_SEASONS
    assert not set(a["training_seasons"]) & set(pbp.TEST_SEASONS)


def test_pbp_read_columns_exclude_model_outputs():
    forbidden = {"wp", "def_wp", "home_wp", "away_wp", "vegas_wp", "vegas_home_wp", "ep", "epa"}
    assert not set(pbp.READ_COLUMNS) & forbidden
