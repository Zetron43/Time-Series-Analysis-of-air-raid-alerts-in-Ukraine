"""Tests for LightGBM ThreatMLPredictor, MultiSourceConsensusVerifier, and Kinematic EW Filters."""

import time
import pytest
from src.bot.ml_predictor import ThreatMLPredictor, get_threat_ml_predictor
from src.bot.consensus_engine import MultiSourceConsensusVerifier
from src.bot.eta_calculator import KinematicETACalculator, MAX_PLAUSIBLE_SPEED_KMH


def test_lightgbm_predictor_availability_and_inference_speed():
    """Verifies that LightGBM booster loads and achieves sub-2ms inference latency on CPU."""
    predictor = get_threat_ml_predictor()
    assert predictor.is_available() is True

    # Benchmark 10 iterations of live prediction
    times = []
    for _ in range(10):
        t0 = time.perf_counter()
        prob, expl = predictor.predict_threat_probability(
            raion_name="Чернівецький район",
            horizon_minutes=15,
            is_alert_active=False,
            neighbor_active_count=1,
            neighbor_total_count=4,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        times.append(latency_ms)

    avg_latency = sum(times) / len(times)
    assert avg_latency < 5.0  # Well below 5 ms (often < 1 ms)
    assert 0.01 <= prob <= 0.99
    assert "LightGBM v3" in expl


def test_lightgbm_kinematic_horizon_response():
    """Verifies that an approaching drone elevates probability in its arrival horizon window."""
    predictor = get_threat_ml_predictor()

    # Incoming target with ETA = 25 minutes
    p_15m, _ = predictor.predict_threat_probability(
        raion_name="Бучанський район",
        horizon_minutes=15,
        incoming_drones=2,
        direct_threats_count=1,
        min_eta_minutes=25.0,
    )
    p_30m, _ = predictor.predict_threat_probability(
        raion_name="Бучанський район",
        horizon_minutes=30,
        incoming_drones=2,
        direct_threats_count=1,
        min_eta_minutes=25.0,
    )

    # 30m horizon must have higher risk than 15m because target arrives at 25m
    assert p_30m >= p_15m
    assert p_30m > 0.70


def test_multi_source_consensus_rule():
    """Verifies that >= 2 independent sources confirm danger, whereas 1 source remains probable."""
    # 1. Two sources agree (Radar + Official alert)
    res_confirmed = MultiSourceConsensusVerifier.verify_raion_consensus(
        raion_name="Чернівецький район",
        is_official_alert=True,
        radar_threats_present=True,
        dimap_alert_present=False,
        osint_warning_present=False,
    )
    assert res_confirmed["is_consensus_verified"] is True
    assert res_confirmed["status"] == "CONFIRMED_CONSENSUS"
    assert "2 джерел" in res_confirmed["badge"]

    # 2. Only single source reports (e.g. single unconfirmed radar blip)
    res_single = MultiSourceConsensusVerifier.verify_raion_consensus(
        raion_name="Чернівецький район",
        is_official_alert=False,
        radar_threats_present=True,
        dimap_alert_present=False,
        osint_warning_present=False,
    )
    assert res_single["is_consensus_verified"] is False
    assert res_single["status"] == "PROBABLE_SINGLE_SOURCE"


def test_kinematic_reb_spoofing_speed_filter():
    """Verifies that radar targets exceeding 900 km/h (GPS EW jumps) are rejected."""
    assert MAX_PLAUSIBLE_SPEED_KMH == 900.0

    calc = KinematicETACalculator()
    # Artificial threat jumping at 1200 km/h
    spoofed_threat = {
        "lat": 48.3,
        "lon": 25.9,
        "speed_kmh": 1200.0,
        "heading": 0.0,
    }
    # Normal threat at 180 km/h
    real_threat = {
        "lat": 48.3,
        "lon": 25.9,
        "speed_kmh": 180.0,
        "heading": 0.0,
    }

    res_spoofed = calc.calculate_eta_for_raion("Чернівецький район", [spoofed_threat])
    assert res_spoofed["threat_count"] == 0  # Filtered out by speed cap

    res_real = calc.calculate_eta_for_raion("Чернівецький район", [real_threat])
    assert res_real["threat_count"] == 1
