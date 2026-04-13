"""
Temporal trend analysis for repeated measurements on a single device.

Detects how a device's electrical behaviour is evolving across stress cycles:
stable / slowly worsening / rapidly worsening / near-breakdown / abrupt failure.

All analysis is purely numeric — no ML.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..config.schema import ThresholdConfig
from ..models.device import TrendState
from ..models.measurement import IVMetrics


@dataclass
class TrendFeatures:
    """Scalar trend features computed from a device's measurement history."""
    n_measurements: int = 0
    leakage_trend_slope: float = 0.0   # Δlog10(I) per measurement (>0 = worsening)
    leakage_ratio_first_last: float = 1.0  # last / first leakage at 1 V
    breakdown_voltage_drop_V: float = 0.0  # first_vbd - last_vbd (>0 = worse)
    leakage_acceleration: float = 0.0  # 2nd derivative of log10(I) trend
    noise_trend: float = 0.0          # change in noise_std over time
    fraction_compliance_hit: float = 0.0  # fraction of recent sweeps hitting compliance
    trend_state: TrendState = TrendState.INSUFFICIENT_DATA
    worsening_rate: float = 0.0       # normalised 0–1 score of how fast it degrades


class TrendAnalyzer:
    """
    Analyses a device's metrics history and returns TrendFeatures.

    Uses a window of the most recent N measurements to detect trends.
    """

    MINIMUM_MEASUREMENTS = 3
    WINDOW_SIZE = 8  # use at most the last 8 measurements for trend fitting

    def __init__(self, thresholds: ThresholdConfig) -> None:
        self.thresholds = thresholds

    def analyse(self, metrics_history: list[IVMetrics]) -> TrendFeatures:
        """
        Compute trend features from the full measurement history.

        Returns TrendFeatures with TrendState labelled.
        """
        features = TrendFeatures(n_measurements=len(metrics_history))

        if len(metrics_history) < self.MINIMUM_MEASUREMENTS:
            return features

        # Use a recent window
        window = metrics_history[-self.WINDOW_SIZE:]

        leakages = np.array([m.leakage_at_1v_A for m in window])
        vbds = [m.breakdown_voltage_V for m in window]
        noise_vals = np.array([m.noise_std_A for m in window])
        compliance_hits = [m.compliance_hit for m in window]

        # --- Leakage trend ---
        with np.errstate(divide="ignore", invalid="ignore"):
            log_leakages = np.where(
                leakages > 1.0e-15, np.log10(leakages), -15.0
            )

        x = np.arange(len(log_leakages), dtype=float)
        if len(x) >= 2:
            slope, _ = np.polyfit(x, log_leakages, 1)
            features.leakage_trend_slope = float(slope)
        else:
            features.leakage_trend_slope = 0.0

        # Ratio first → last
        if leakages[0] > 1.0e-15:
            features.leakage_ratio_first_last = float(leakages[-1] / leakages[0])
        else:
            features.leakage_ratio_first_last = 1.0

        # Leakage acceleration (2nd-order term of polynomial fit)
        if len(x) >= 4:
            coeffs = np.polyfit(x, log_leakages, 2)
            features.leakage_acceleration = float(coeffs[0])  # 2nd-order coefficient

        # --- Breakdown voltage trend ---
        valid_vbds = [(i, v) for i, v in enumerate(vbds) if v is not None]
        if len(valid_vbds) >= 2:
            vbd_vals = np.array([v for _, v in valid_vbds])
            features.breakdown_voltage_drop_V = float(vbd_vals[0] - vbd_vals[-1])

        # --- Noise trend ---
        if len(noise_vals) >= 2:
            features.noise_trend = float(noise_vals[-1] - noise_vals[0])

        # --- Compliance fraction ---
        features.fraction_compliance_hit = (
            sum(compliance_hits) / len(compliance_hits) if compliance_hits else 0.0
        )

        # --- Label trend state ---
        features.trend_state = self._label_trend(features)
        features.worsening_rate = self._compute_worsening_rate(features)

        return features

    def _label_trend(self, f: TrendFeatures) -> TrendState:
        """Assign a TrendState label from the computed features."""
        thr = self.thresholds

        # Near-breakdown: compliance hit frequently or very rapid degradation
        if f.fraction_compliance_hit >= 0.5:
            return TrendState.NEAR_BREAKDOWN

        if f.leakage_ratio_first_last > 1000.0 and f.n_measurements >= 4:
            return TrendState.ABRUPT_FAILURE

        # Rapidly worsening: slope > critical rate
        if f.leakage_trend_slope > thr.trend_worsening_rate_critical:
            return TrendState.RAPIDLY_WORSENING

        # Slowly worsening
        if f.leakage_trend_slope > thr.trend_worsening_rate_suspicious:
            return TrendState.SLOWLY_WORSENING

        # Recovering (negative slope)
        if f.leakage_trend_slope < -0.05 and f.leakage_ratio_first_last < 0.5:
            return TrendState.RECOVERING

        # Ambiguous: inconsistent direction
        if abs(f.leakage_acceleration) > 0.05 and f.n_measurements >= 4:
            return TrendState.AMBIGUOUS

        return TrendState.STABLE

    def _compute_worsening_rate(self, f: TrendFeatures) -> float:
        """
        Normalised worsening score in [0, 1].

        0 = stable, 1 = extremely rapid degradation.
        Used by the suspicion engine.
        """
        slope_contribution = min(1.0, max(0.0, f.leakage_trend_slope / 1.0))
        ratio_contribution = min(1.0, max(0.0, np.log10(max(1.0, f.leakage_ratio_first_last)) / 4.0))
        compliance_contribution = f.fraction_compliance_hit
        return float(
            0.5 * slope_contribution
            + 0.3 * ratio_contribution
            + 0.2 * compliance_contribution
        )
