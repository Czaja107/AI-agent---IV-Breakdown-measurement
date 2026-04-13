"""
Device health classification based on extracted I-V metrics.

Returns a DeviceStatus and a contact quality estimate.
These are consumed by the policy engine to decide next actions.
"""
from __future__ import annotations

from ..config.schema import ThresholdConfig
from ..models.device import DeviceStatus
from ..models.measurement import IVMetrics, MeasurementStatus


def classify_device_health(
    metrics: IVMetrics,
    thresholds: ThresholdConfig,
) -> DeviceStatus:
    """
    Classify a device based on a single I-V measurement's extracted metrics.

    Called after the initial health-check measurement and after each stress batch.

    Classification hierarchy (checked in order):
    1. SHORTED  — low resistance at 1 V or immediate compliance hit
    2. CONTACT_ISSUE — suspiciously flat / near-zero current trace
    3. FAILED — leakage well above degraded threshold
    4. NEAR_FAILURE — leakage approaching failure OR compliance hit in health check
    5. DEGRADING — leakage elevated but below failure threshold
    6. HEALTHY — leakage low, no breakdown in sweep
    7. UNKNOWN — insufficient data or invalid measurement
    """
    if metrics.measurement_status == MeasurementStatus.INVALID:
        return DeviceStatus.UNKNOWN

    if metrics.is_shorted:
        return DeviceStatus.SHORTED

    if metrics.is_open_circuit:
        return DeviceStatus.CONTACT_ISSUE

    leakage = metrics.leakage_at_1v_A

    if leakage > thresholds.max_leakage_degraded_A:
        return DeviceStatus.FAILED

    # Compliance hit during a health-check sweep (low Vmax) signals near-failure
    if metrics.compliance_hit and metrics.breakdown_voltage_V is not None:
        if metrics.breakdown_voltage_V < thresholds.min_resistance_healthy_ohm * 0.0 + 6.0:
            return DeviceStatus.NEAR_FAILURE
        return DeviceStatus.NEAR_FAILURE

    if thresholds.max_leakage_healthy_A < leakage <= thresholds.max_leakage_degraded_A:
        return DeviceStatus.DEGRADING

    if leakage <= thresholds.max_leakage_healthy_A:
        return DeviceStatus.HEALTHY

    return DeviceStatus.UNKNOWN


def estimate_contact_quality(
    metrics: IVMetrics,
    prior_leakage_A: float | None = None,
) -> float:
    """
    Return a contact quality score in [0, 1]: 0 = bad contact, 1 = good contact.

    Heuristic rules:
    - Open circuit → 0.0
    - Very low leakage at Vmax compared to expected → low score
    - If prior leakage is known and current is << prior → low score
    """
    if metrics.is_open_circuit:
        return 0.0

    if metrics.is_shorted:
        # Shorted = contact is fine, device is just shorted
        return 1.0

    # If leakage at max voltage is very near noise floor, contact may be bad
    if metrics.leakage_at_vmax_A < 1.0e-13:
        return 0.1

    # If we have prior data and current leakage is 100× below prior, suspicious
    if prior_leakage_A and prior_leakage_A > 1.0e-12:
        ratio = metrics.leakage_at_vmax_A / prior_leakage_A
        if ratio < 0.01:
            return 0.2
        if ratio < 0.1:
            return 0.5

    return 1.0
