"""
Measurement data models: raw I-V curves and extracted metrics.

IVCurve holds the raw voltage/current arrays as produced by the instrument.
IVMetrics holds the features extracted by the analysis layer.
Both are Pydantic models so they can be serialised to JSON without extra work.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

import numpy as np
from pydantic import BaseModel, Field


class MeasurementStatus(str, Enum):
    """Quality flag assigned during feature extraction."""
    VALID = "valid"
    NOISY = "noisy"            # high noise but still usable
    INCONSISTENT = "inconsistent"  # disagrees with prior measurement on same device
    INVALID = "invalid"        # cannot be trusted (e.g. instrument error)
    COMPLIANCE_HIT = "compliance_hit"  # current hit the compliance limit


class IVCurve(BaseModel):
    """
    Raw I-V measurement: voltage sweep and the corresponding current response.

    Stored as lists (JSON-serialisable); convert to numpy arrays in analysis.
    """

    device_id: str
    protocol_name: str          # which protocol variant was used
    sweep_index: int = 0        # 0-based index within a stress batch
    voltages_V: list[float]     # voltage setpoints [V]
    currents_A: list[float]     # measured currents [A]
    compliance_hit: bool = False
    compliance_hit_at_index: Optional[int] = None  # first index where compliance hit
    timestamp: datetime = Field(default_factory=datetime.now)
    notes: str = ""

    @property
    def v_array(self) -> np.ndarray:
        return np.array(self.voltages_V)

    @property
    def i_array(self) -> np.ndarray:
        return np.array(self.currents_A)

    @property
    def max_voltage(self) -> float:
        return max(self.voltages_V) if self.voltages_V else 0.0

    @property
    def max_current(self) -> float:
        return max(abs(c) for c in self.currents_A) if self.currents_A else 0.0


class IVMetrics(BaseModel):
    """
    Features extracted from a single I-V curve by analysis.features.

    These are the values the suspicion engine, trend analyser, and
    policy engine operate on — not raw arrays.
    """

    device_id: str
    protocol_name: str
    sweep_index: int = 0
    timestamp: datetime = Field(default_factory=datetime.now)
    measurement_status: MeasurementStatus = MeasurementStatus.VALID

    # Primary health indicators
    leakage_at_1v_A: float = 0.0        # current at 1 V (or nearest)
    leakage_at_half_vmax_A: float = 0.0 # current at 50 % of sweep max voltage
    leakage_at_vmax_A: float = 0.0      # current at the top of the sweep
    breakdown_voltage_V: Optional[float] = None  # None if compliance never hit
    estimated_resistance_ohm: float = 1e15  # V/I at 1 V

    # Quality / shape metrics
    curve_integral_log: float = 0.0    # integral of log10|I| over V sweep
    noise_std_A: float = 0.0          # estimated RMS noise on the current signal
    is_shorted: bool = False
    is_open_circuit: bool = False
    compliance_hit: bool = False

    # Derived flags for quick decision logic
    looks_healthy: bool = False
    looks_degraded: bool = False
    looks_failed: bool = False

    def to_dict(self) -> dict:
        d = self.model_dump()
        # Convert datetime to ISO string
        d["timestamp"] = self.timestamp.isoformat()
        return d


class StressBatch(BaseModel):
    """
    One batch of repeated stress sweeps on a device (n_cycles consecutive sweeps).

    The batch stores all individual curves and the per-batch aggregate metrics
    (e.g. the worst-case breakdown voltage within the batch).
    """

    device_id: str
    batch_index: int
    protocol_name: str
    curves: list[IVCurve] = Field(default_factory=list)
    metrics: list[IVMetrics] = Field(default_factory=list)
    timestamp_start: datetime = Field(default_factory=datetime.now)
    timestamp_end: Optional[datetime] = None
    any_compliance_hit: bool = False
    min_breakdown_voltage_V: Optional[float] = None  # worst case in this batch
    mean_leakage_at_1v_A: float = 0.0

    def finalise(self) -> None:
        """Compute aggregate metrics from individual curve metrics."""
        if not self.metrics:
            return
        self.any_compliance_hit = any(m.compliance_hit for m in self.metrics)
        vbds = [m.breakdown_voltage_V for m in self.metrics if m.breakdown_voltage_V]
        self.min_breakdown_voltage_V = min(vbds) if vbds else None
        self.mean_leakage_at_1v_A = float(
            np.mean([m.leakage_at_1v_A for m in self.metrics])
        )
        self.timestamp_end = datetime.now()
