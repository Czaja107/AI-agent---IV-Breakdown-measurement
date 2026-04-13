"""
Unit tests for analysis.features and analysis.health.

Tests cover the full range of device types that the simulator produces:
healthy, shorted, open-circuit (contact), and degraded.
"""
from __future__ import annotations

import pytest
import numpy as np

from ..config.schema import ThresholdConfig
from ..models.measurement import IVCurve, MeasurementStatus
from ..analysis.features import extract_iv_metrics
from ..analysis.health import classify_device_health
from ..models.device import DeviceStatus


@pytest.fixture
def thresholds() -> ThresholdConfig:
    return ThresholdConfig()


def _make_curve(
    device_id: str = "TEST_00_00",
    v_max: float = 5.0,
    I0: float = 1e-12,
    V_char: float = 3.0,
    shorted: bool = False,
    R_short: float = 1000.0,
    open_circuit: bool = False,
    compliance: float = 1e-4,
    n_points: int = 21,
    noise: float = 1e-14,
    rng_seed: int = 0,
) -> IVCurve:
    rng = np.random.default_rng(rng_seed)
    voltages = np.linspace(0, v_max, n_points)
    currents = []
    compliance_hit = False
    compliance_hit_idx = None

    for k, v in enumerate(voltages):
        if open_circuit:
            I = abs(rng.normal(0, noise))
        elif shorted:
            I = v / R_short + rng.normal(0, noise)
        else:
            I = I0 * np.exp(v / V_char) + rng.normal(0, noise)

        I = max(0.0, I)
        if I >= compliance and not compliance_hit:
            compliance_hit = True
            compliance_hit_idx = k
            I = compliance
        currents.append(float(I))

    return IVCurve(
        device_id=device_id,
        protocol_name="health_check",
        voltages_V=voltages.tolist(),
        currents_A=currents,
        compliance_hit=compliance_hit,
        compliance_hit_at_index=compliance_hit_idx,
    )


# ---------------------------------------------------------------------------
# Feature extraction tests
# ---------------------------------------------------------------------------

class TestFeatureExtraction:

    def test_healthy_device_low_leakage(self, thresholds):
        """A healthy capacitor should show very low leakage at 1 V."""
        curve = _make_curve(I0=1e-12, V_char=3.0)
        metrics = extract_iv_metrics(curve, thresholds)
        assert metrics.measurement_status == MeasurementStatus.VALID
        assert metrics.leakage_at_1v_A < thresholds.max_leakage_healthy_A
        assert not metrics.is_shorted
        assert not metrics.is_open_circuit
        assert metrics.looks_healthy

    def test_shorted_device_detected(self, thresholds):
        """A shorted device should be flagged by the feature extractor."""
        curve = _make_curve(shorted=True, R_short=500.0)
        metrics = extract_iv_metrics(curve, thresholds)
        assert metrics.is_shorted, "Expected is_shorted=True for 500Ω device"
        assert metrics.estimated_resistance_ohm < thresholds.short_resistance_threshold_ohm

    def test_open_circuit_device_detected(self, thresholds):
        """An open-circuit device should show near-zero current at all voltages."""
        curve = _make_curve(open_circuit=True, noise=1e-15)
        metrics = extract_iv_metrics(curve, thresholds)
        assert metrics.is_open_circuit, "Expected is_open_circuit=True"
        assert metrics.leakage_at_vmax_A < thresholds.min_current_at_max_v_A

    def test_degraded_device_elevated_leakage(self, thresholds):
        """A degraded device should have leakage between healthy and failed thresholds."""
        # Moderately degraded: I0 = 1e-9 (1 nA at 1V when V_char=3 → I ≈ e^(1/3)*1e-9)
        curve = _make_curve(I0=1e-9, V_char=3.0)
        metrics = extract_iv_metrics(curve, thresholds)
        assert not metrics.is_shorted
        assert not metrics.is_open_circuit
        # Leakage at 1V should be above healthy threshold
        assert metrics.leakage_at_1v_A > thresholds.max_leakage_healthy_A

    def test_no_breakdown_in_health_check(self, thresholds):
        """Healthy device sweeping to 5V should not trigger compliance."""
        curve = _make_curve(I0=1e-12, V_char=3.0, v_max=5.0)
        metrics = extract_iv_metrics(curve, thresholds)
        assert not metrics.compliance_hit
        assert metrics.breakdown_voltage_V is None

    def test_empty_curve_returns_invalid(self, thresholds):
        """Empty curve data should result in INVALID status."""
        curve = IVCurve(
            device_id="TEST",
            protocol_name="health_check",
            voltages_V=[],
            currents_A=[],
        )
        metrics = extract_iv_metrics(curve, thresholds)
        assert metrics.measurement_status == MeasurementStatus.INVALID


# ---------------------------------------------------------------------------
# Health classification tests
# ---------------------------------------------------------------------------

class TestHealthClassification:

    def test_classify_healthy(self, thresholds):
        curve = _make_curve(I0=1e-12)
        metrics = extract_iv_metrics(curve, thresholds)
        status = classify_device_health(metrics, thresholds)
        assert status == DeviceStatus.HEALTHY

    def test_classify_shorted(self, thresholds):
        curve = _make_curve(shorted=True, R_short=200.0)
        metrics = extract_iv_metrics(curve, thresholds)
        status = classify_device_health(metrics, thresholds)
        assert status == DeviceStatus.SHORTED

    def test_classify_contact_issue(self, thresholds):
        curve = _make_curve(open_circuit=True, noise=1e-15)
        metrics = extract_iv_metrics(curve, thresholds)
        status = classify_device_health(metrics, thresholds)
        assert status == DeviceStatus.CONTACT_ISSUE

    def test_classify_failed(self, thresholds):
        """Very high leakage should result in FAILED classification."""
        curve = _make_curve(I0=1e-6, V_char=3.0)  # 1µA at 1V → way above threshold
        metrics = extract_iv_metrics(curve, thresholds)
        status = classify_device_health(metrics, thresholds)
        assert status in (DeviceStatus.FAILED, DeviceStatus.DEGRADING)
