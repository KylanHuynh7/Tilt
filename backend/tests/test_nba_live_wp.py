"""NBA v1.1 live WP: sampling, clock parsing, fit, checks, guardrails.
Offline; never scores the test seasons.
"""

import math
import random
from pathlib import Path

import pytest

from app.nba import live_wp, pbp
from scripts import nba_live_wp_evaluate


def _play(period, clock, h, a):
    return {"period": {"number": period}, "clock": {"displayValue": clock},
            "homeScore": h, "awayScore": a}


def test_parse_clock_formats():
    assert pbp.parse_clock("11:34") == 694
    assert pbp.parse_clock("34.5") == 34.5
    assert pbp.parse_clock("0.0") == 0.0


def test_minute_marks_regulation_and_ot():
    assert len(pbp.minute_marks(4)) == 48
    assert len(pbp.minute_marks(5)) == 53
    assert pbp.minute_marks(5)[48] == (5, 300)


def test_samples_use_score_at_or_before_mark():
    plays = [_play(1, "12:00", 0, 0), _play(1, "11:30", 2, 0), _play(1, "11:00", 2, 3),
             _play(2, "12:00", 20, 18), _play(4, "0.0", 100, 98)]
    s = pbp.samples_from_plays(plays, 4)
    assert s[0] == (1, 720, 0, 0)
    assert s[1] == (1, 660, 2, 3)        # play exactly at 11:00 counts
    assert s[12] == (2, 720, 20, 18)     # start of Q2
    assert s[-1][2:] == (20, 18)         # last mark is 1:00 of Q4; final play is after it


def test_tau_and_features():
    assert live_wp.tau_for(1, 720) == 2880
    assert live_wp.tau_for(4, 60) == 60
    assert live_wp.tau_for(5, 300) == 300   # OT is its own short period
    x1, x2 = live_wp.features(1.0, 2880, 6)
    assert x1 == 1.0 and math.isclose(x2, 6 / math.sqrt(49))


def test_fit_recovers_known_coefficients():
    rng = random.Random(7)
    truth = live_wp.Model(0.1, 1.2, 0.6)
    samples = []
    for g in range(3000):
        pre = rng.uniform(-1.5, 1.5)
        tau = rng.choice(range(60, 2881, 60))
        d = rng.randint(-15, 15)
        x1, x2 = live_wp.features(pre, tau, d)
        p = live_wp.sigmoid(truth.b0 + truth.b1 * x1 + truth.b2 * x2)
        samples.append(live_wp.Sample(g, 1, tau, pre, d, rng.random() < p))
    m = live_wp.fit(samples)
    assert abs(m.b0 - 0.1) < 0.12 and abs(m.b1 - 1.2) < 0.2 and abs(m.b2 - 0.6) < 0.08


def test_checks_on_identity_like_model():
    m = live_wp.Model(0.0, 1.0, 0.8)
    c = live_wp.checks(m, [0.3, 0.7])
    assert c["tipoff_within_0_01"] and c["monotone_in_score_diff"]
    assert c["leader_by_20_with_2_min_left_ge_0_97"]


def test_live_evaluator_guardrails(tmp_path: Path):
    assert nba_live_wp_evaluate.main(["--out", str(tmp_path / "x.json")]) == 2
    existing = tmp_path / "r.json"
    existing.write_text("{}")
    assert nba_live_wp_evaluate.main(["--confirm", "--out", str(existing)]) == 3
    assert existing.read_text() == "{}"


@pytest.mark.skipif(not live_wp.ARTIFACT.exists(), reason="live model not fitted")
def test_artifact_trained_on_training_seasons_only():
    import json
    a = json.loads(live_wp.ARTIFACT.read_text())
    assert a["training_seasons"] == pbp.TRAIN_SEASONS
    assert not set(a["training_seasons"]) & set(pbp.TEST_SEASONS)
