"""
Feature extraction from raw I-V curves.

All functions operate on IVCurve objects and return IVMetrics instances.
The thresholds used for flagging come from ThresholdConfig so they can be
tuned in the YAML config without touching code.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..config.schema import ThresholdConfig
from ..models.measurement import IVCurve, IVMetrics, MeasurementStatus


def _find_current_at_voltage(
    voltages: np.ndarray, currents: np.ndarray, target_v: float
) -> float:
    """Return the measured current at the voltage closest to target_v."""
    if len(voltages) == 0:
        return 0.0
    idx = int(np.argmin(np.abs(voltages - target_v)))
    return float(currents[idx])


def _estimate_noise(currents: np.ndarray) -> float:
    """
    Estimate RMS noise from the high-frequency component of the current trace.

    Uses the difference between adjacent samples as a proxy for noise.
    Robust to slow drift (which would not appear in the diff).
    """
    if len(currents) < 4:
        return 0.0
    diffs = np.diff(currents)
    # Median absolute deviation of diffs is robust to outliers
    mad = float(np.median(np.abs(diffs - np.median(diffs))))
    return mad * 1.4826  # MAD → sigma conversion


def _find_breakdown_voltage(
    voltages: np.ndarray,
    currents: np.ndarray,
    compliance_hit: bool,
    compliance_hit_index: Optional[int],
) -> Optional[float]:
    """
    Return the voltage at which the instrument hit its compliance limit.

    Returns None if compliance was never reached (healthy device in sweep range).
    This avoids false positives from the normal exponential leakage slope.
    """
    if not compliance_hit or compliance_hit_index is None:
        return None
    idx = min(compliance_hit_index, len(voltages) - 1)
    return float(voltages[idx])


def extract_iv_metrics(
    curve: IVCurve,
    thresholds: ThresholdConfig,
) -> IVMetrics:
    """
    Extract all scalar features from a raw I-V curve.

    This is the primary entry point called after every measurement.
    The resulting IVMetrics object is stored in DeviceRecord.metrics_history.
    """
    voltages = curve.v_array
    currents = curve.i_array

    if len(voltages) == 0 or len(currents) == 0:
        return IVMetrics(
            device_id=curve.device_id,
            protocol_name=curve.protocol_name,
            sweep_index=curve.sweep_index,
            timestamp=curve.timestamp,
            measurement_status=MeasurementStatus.INVALID,
        )

    v_max = voltages[-1]
    compliance = thresholds.min_current_at_max_v_A  # used for open-circuit detection

    # Primary leakage indicators
    leakage_1v = _find_current_at_voltage(voltages, currents, 1.0)
    leakage_half = _find_current_at_voltage(voltages, currents, v_max * 0.5)
    leakage_max = float(currents[-1])

    # Estimated resistance at 1 V
    if leakage_1v > 1.0e-15:
        R_est = 1.0 / leakage_1v
    else:
        R_est = 1.0e15  # effectively open

    # Breakdown voltage: only set when compliance was actually hit
    v_bd = _find_breakdown_voltage(
        voltages, currents,
        curve.compliance_hit,
        curve.compliance_hit_at_index,
    )

    # Noise estimation
    noise_std = _estimate_noise(currents)

    # Curve integral (area under log|I| vs V) — a shape descriptor
    with np.errstate(divide="ignore", invalid="ignore"):
        safe_currents = np.where(currents > 0, currents, 1.0e-15)
        log_i = np.where(currents > 1.0e-15, np.log10(safe_currents), -15.0)
    _trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz")
    curve_integral = float(_trapz(log_i, voltages))

    # --- Classification flags ---

    # Shorted: current at 1 V implies very low resistance
    is_shorted = (R_est < thresholds.short_resistance_threshold_ohm) or (
        leakage_1v > 1.0e-4
    )

    # Open circuit / no contact: current at Vmax is suspiciously low
    is_open = (
        leakage_max < thresholds.min_current_at_max_v_A and not is_shorted
    )

    # Measurement quality
    if is_shorted or is_open:
        status = MeasurementStatus.VALID  # valid but unusual
    elif noise_std > leakage_1v * 2.0 and leakage_1v > 1.0e-13:
        status = MeasurementStatus.NOISY
    elif curve.compliance_hit:
        status = MeasurementStatus.COMPLIANCE_HIT
    else:
        status = MeasurementStatus.VALID

    # Quick health flags for the policy engine
    looks_healthy = (
        not is_shorted
        and not is_open
        and leakage_1v < thresholds.max_leakage_healthy_A
        and not curve.compliance_hit  # compliance not hit in sweep
    )
    looks_degraded = (
        not is_shorted
        and not is_open
        and thresholds.max_leakage_healthy_A <= leakage_1v <= thresholds.max_leakage_degraded_A
    )
    looks_failed = (
        is_shorted
        or (v_bd is not None and v_bd < thresholds.min_resistance_healthy_ohm * 0.0)
        or (leakage_1v > thresholds.max_leakage_degraded_A and not is_open)
    )

    return IVMetrics(
        device_id=curve.device_id,
        protocol_name=curve.protocol_name,
        sweep_index=curve.sweep_index,
        timestamp=curve.timestamp,
        measurement_status=status,
        leakage_at_1v_A=float(leakage_1v),
        leakage_at_half_vmax_A=float(leakage_half),
        leakage_at_vmax_A=float(leakage_max),
        breakdown_voltage_V=v_bd,
        estimated_resistance_ohm=float(R_est),
        curve_integral_log=float(curve_integral),
        noise_std_A=float(noise_std),
        is_shorted=is_shorted,
        is_open_circuit=is_open,
        compliance_hit=curve.compliance_hit,
        looks_healthy=looks_healthy,
        looks_degraded=looks_degraded,
        looks_failed=looks_failed,
    )
