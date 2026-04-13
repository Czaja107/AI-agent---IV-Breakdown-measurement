"""
Device-level data models.

These are the central records that the agent reads and updates as it steps
through the chip.  DeviceRecord is intentionally mutable — it accumulates
measurement history across the entire run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .measurement import IVMetrics, IVCurve


# ---------------------------------------------------------------------------
# Enums — all use str mixin so they serialise cleanly to JSON
# ---------------------------------------------------------------------------

class DeviceStatus(str, Enum):
    """Overall classification of a device after the agent processes it."""
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADING = "degrading"
    SUSPICIOUS = "suspicious"
    NEAR_FAILURE = "near_failure"
    FAILED = "failed"
    SHORTED = "shorted"
    CONTACT_ISSUE = "contact_issue"
    SKIPPED = "skipped"


class TrendState(str, Enum):
    """How the device's electrical behaviour is changing over stress cycles."""
    STABLE = "stable"
    SLOWLY_WORSENING = "slowly_worsening"
    RAPIDLY_WORSENING = "rapidly_worsening"
    NEAR_BREAKDOWN = "near_breakdown"
    ABRUPT_FAILURE = "abrupt_failure"
    RECOVERING = "recovering"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT_DATA = "insufficient_data"


class ProtocolMode(str, Enum):
    """The measurement protocol currently active for a device."""
    HEALTH_CHECK = "health_check"
    NORMAL_STRESS = "normal_stress"
    DENSE_MONITORING = "dense_monitoring"
    CONFIRMATORY = "confirmatory"
    LOW_STRESS_RECHECK = "low_stress_recheck"
    CONTROL_CHECK = "control_check"
    PAUSED = "paused"


class SuspicionLevel(str, Enum):
    """Qualitative suspicion score assigned by the suspicion engine."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def numeric(self) -> float:
        return {"none": 0.0, "low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}[
            self.value
        ]

    @classmethod
    def from_score(cls, score: float) -> "SuspicionLevel":
        if score < 0.15:
            return cls.NONE
        if score < 0.35:
            return cls.LOW
        if score < 0.60:
            return cls.MEDIUM
        if score < 0.80:
            return cls.HIGH
        return cls.CRITICAL


class GridPosition(str, Enum):
    """Coarse location of the device within the chip die."""
    CENTER = "center"
    EDGE = "edge"
    CORNER = "corner"


# ---------------------------------------------------------------------------
# DeviceRecord — mutable accumulator updated by the agent throughout the run
# ---------------------------------------------------------------------------

@dataclass
class DeviceRecord:
    """
    Everything the agent knows about a single capacitor device.

    The record grows as measurements are taken.  The agent reads it to make
    decisions and writes to it after each action.
    """

    # Identity
    device_id: str
    ix: int                    # column index on the chip grid
    iy: int                    # row index on the chip grid
    is_control_device: bool = False

    # Current state (updated by the agent)
    status: DeviceStatus = DeviceStatus.UNKNOWN
    grid_position: GridPosition = GridPosition.CENTER
    protocol_mode: ProtocolMode = ProtocolMode.HEALTH_CHECK
    trend_state: TrendState = TrendState.INSUFFICIENT_DATA
    suspicion_level: SuspicionLevel = SuspicionLevel.NONE
    suspicion_score: float = 0.0
    suspicion_reasons: list[str] = field(default_factory=list)

    # Measurement history (populated in order of measurement time)
    iv_curves: list["IVCurve"] = field(default_factory=list)
    metrics_history: list["IVMetrics"] = field(default_factory=list)

    # Stress tracking
    stress_batch_count: int = 0
    stress_cycles_total: int = 0
    confirmatory_count: int = 0
    inconsistent_confirmatory_count: int = 0
    breakdown_events: int = 0     # number of times compliance was hit during stress

    # Key scalar summary (updated after each measurement for quick access)
    latest_leakage_at_1v_A: float | None = None
    latest_breakdown_voltage_V: float | None = None
    baseline_leakage_at_1v_A: float | None = None  # first valid measurement

    # Timing
    measurement_start: datetime | None = None
    measurement_end: datetime | None = None

    # Self-generated notes from the notes writer
    device_notes: list[str] = field(default_factory=list)

    # True if the agent has already finished processing this device
    is_done: bool = False

    def __repr__(self) -> str:
        return (
            f"Device({self.device_id} [{self.ix},{self.iy}] "
            f"status={self.status.value} suspicion={self.suspicion_level.value})"
        )

    @property
    def manhattan_coord(self) -> tuple[int, int]:
        """Return (ix, iy) as a simple tuple for distance calculations."""
        return (self.ix, self.iy)

    def leakage_ratio_vs_baseline(self) -> float | None:
        """Return current leakage / baseline leakage, or None if data missing."""
        if self.latest_leakage_at_1v_A and self.baseline_leakage_at_1v_A:
            if self.baseline_leakage_at_1v_A > 0:
                return self.latest_leakage_at_1v_A / self.baseline_leakage_at_1v_A
        return None

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSON output."""
        return {
            "device_id": self.device_id,
            "ix": self.ix,
            "iy": self.iy,
            "is_control_device": self.is_control_device,
            "status": self.status.value,
            "grid_position": self.grid_position.value,
            "protocol_mode": self.protocol_mode.value,
            "trend_state": self.trend_state.value,
            "suspicion_level": self.suspicion_level.value,
            "suspicion_score": round(self.suspicion_score, 3),
            "suspicion_reasons": self.suspicion_reasons,
            "stress_batch_count": self.stress_batch_count,
            "stress_cycles_total": self.stress_cycles_total,
            "breakdown_events": self.breakdown_events,
            "latest_leakage_at_1v_A": self.latest_leakage_at_1v_A,
            "latest_breakdown_voltage_V": self.latest_breakdown_voltage_V,
            "baseline_leakage_at_1v_A": self.baseline_leakage_at_1v_A,
            "n_measurements": len(self.iv_curves),
            "confirmatory_count": self.confirmatory_count,
            "inconsistent_confirmatory_count": self.inconsistent_confirmatory_count,
            "device_notes": self.device_notes,
            "measurement_start": (
                self.measurement_start.isoformat() if self.measurement_start else None
            ),
            "measurement_end": (
                self.measurement_end.isoformat() if self.measurement_end else None
            ),
        }
