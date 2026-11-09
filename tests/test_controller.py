"""Unit tests for the controller modules."""
import pytest
from controller.models import (
    matches_cohort,
    assign_cohort,
    compute_config_diff,
    compute_max_shift,
    total_variation_distance
)
from controller.analytics import wilson_score_interval, two_sample_proportion_test
from controller.db import Database


def test_cohort_matching():
    cohort = {"id": "senior_ta", "where": {"age_band": ["60+"], "lang": ["ta"]}}
    
    assert matches_cohort({"age_band": "60+", "lang": "ta", "city_tier": "1"}, cohort["where"]) is True
    assert matches_cohort({"age_band": "18-30", "lang": "ta"}, cohort["where"]) is False
    assert matches_cohort({"age_band": "60+", "lang": "hi"}, cohort["where"]) is False


def test_assign_cohort():
    cohorts = [
        {"id": "senior_ta", "where": {"age_band": ["60+"], "lang": ["ta"]}},
        {"id": "young", "where": {"age_band": ["18-30"]}}
    ]
    
    assert assign_cohort({"age_band": "60+", "lang": "ta"}, cohorts) == "senior_ta"
    assert assign_cohort({"age_band": "18-30", "lang": "en"}, cohorts) == "young"
    assert assign_cohort({"age_band": "31-45", "lang": "hi"}, cohorts) == "default"


def test_tv_distance_and_max_shift():
    p = {"A": 1.0}
    q = {"A": 0.8, "B": 0.2}
    assert pytest.approx(total_variation_distance(p, q), 0.01) == 0.2

    cfg_old = {"allocations": {"default": {"voice": {"V1": 1.0}}}}
    cfg_new = {"allocations": {"default": {"voice": {"V1": 0.8, "V2": 0.2}}}}
    assert pytest.approx(compute_max_shift(cfg_old, cfg_new), 0.01) == 0.2


def test_diff_computation():
    cfg_old = {"prompt_version": "P1", "allocations": {"default": {"voice": {"V1": 1.0}}}}
    cfg_new = {"prompt_version": "P3", "allocations": {"default": {"voice": {"V2": 1.0}}}}
    
    diff = compute_config_diff(cfg_old, cfg_new)
    assert "prompt_version" in diff
    assert "allocations.default.voice" in diff


def test_wilson_interval():
    p, lower, upper = wilson_score_interval(50, 100)
    assert p == 0.5
    assert 0.40 < lower < 0.45
    assert 0.55 < upper < 0.60


def test_db_operations():
    db = Database(":memory:")
    db.set_meta("test_key", "test_val")
    assert db.get_meta("test_key") == "test_val"

    db.log_audit(
        sim_minute=100,
        ts="D0 01:40",
        workflow_id="wf_1",
        event_type="test",
        actor="unit_test",
        summary="testing db audit",
        details={"foo": "bar"}
    )
    logs = db.query_audit_log(workflow_id="wf_1")
    assert len(logs) == 1
    assert logs[0]["summary"] == "testing db audit"
    db.close()
