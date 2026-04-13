"""
Hypothesis tracker.

Maintains structured, explainable belief states for a fixed set of failure
explanations.  Hypotheses are updated by heuristic rules — NOT by Bayesian
inference.  The goal is full auditability: each update has a clear English
reason attached.

Hypotheses are consumed by the notes writer and escalation system to produce
human-readable explanations.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from ..models.device import DeviceStatus, TrendState
from ..models.run_state import HypothesisRecord, HypothesisType

if TYPE_CHECKING:
    from ..models.device import DeviceRecord
    from ..models.run_state import RunState
    from .suspicion import SuspicionResult
    from .neighbors import NeighborComparison, SpatialCluster
    from .trends import TrendFeatures


# Support level delta constants
STRONG_SUPPORT = 0.30
MODERATE_SUPPORT = 0.15
WEAK_SUPPORT = 0.08
MILD_AGAINST = -0.10
STRONG_AGAINST = -0.25

# Threshold above which a hypothesis is considered "active"
ACTIVE_THRESHOLD = 0.35


@dataclass
class HypothesisEvent:
    """
    A single piece of evidence that the tracker processes.

    Each event updates one or more hypothesis support levels.
    """
    event_type: str          # descriptive label, e.g. "contact_issue_detected"
    device_id: Optional[str] = None
    description: str = ""    # plain-language description of the evidence


class HypothesisTracker:
    """
    Maintains the current support level for each hypothesis and updates
    them as evidence arrives during the run.

    All methods return the current hypotheses dict so callers can inspect
    the updated state immediately.
    """

    def __init__(self, run_state: "RunState") -> None:
        self.run_state = run_state
        self._init_hypotheses()

    def _init_hypotheses(self) -> None:
        """Initialise all hypotheses with zero support."""
        for h_type in HypothesisType:
            self.run_state.hypotheses[h_type.value] = HypothesisRecord(
                hypothesis=h_type, support_level=0.0, active=False
            )

    def get_active(self) -> list[HypothesisRecord]:
        """Return all hypotheses above the active threshold, sorted by support."""
        return sorted(
            [h for h in self.run_state.hypotheses.values() if h.active],
            key=lambda h: h.support_level,
            reverse=True,
        )

    def get_top(self, n: int = 3) -> list[HypothesisRecord]:
        """Return the top n hypotheses by support level."""
        return sorted(
            self.run_state.hypotheses.values(),
            key=lambda h: h.support_level,
            reverse=True,
        )[:n]

    # -----------------------------------------------------------------------
    # Update methods — called by the orchestration layer at key events
    # -----------------------------------------------------------------------

    def on_device_classified(
        self, device: "DeviceRecord", event: HypothesisEvent
    ) -> None:
        """Update hypotheses based on how a device was classified."""
        status = device.status

        if status == DeviceStatus.SHORTED:
            self._update(HypothesisType.PRE_EXISTING_SHORT, MODERATE_SUPPORT, event)
            self._update(HypothesisType.CONTACT_DEGRADATION, MILD_AGAINST, event)

        elif status == DeviceStatus.CONTACT_ISSUE:
            self._update(HypothesisType.CONTACT_DEGRADATION, MODERATE_SUPPORT, event)
            self._update(HypothesisType.TRUE_DEVICE_DEGRADATION, MILD_AGAINST, event)
            self._update(HypothesisType.MEASUREMENT_NOISE_ISSUE, WEAK_SUPPORT, event)

        elif status == DeviceStatus.FAILED:
            self._update(HypothesisType.TRUE_DEVICE_DEGRADATION, MODERATE_SUPPORT, event)
            self._update(HypothesisType.PRE_EXISTING_SHORT, MILD_AGAINST, event)

        elif status == DeviceStatus.DEGRADING:
            self._update(HypothesisType.TRUE_DEVICE_DEGRADATION, WEAK_SUPPORT, event)

        elif status == DeviceStatus.HEALTHY:
            self._update(HypothesisType.CONTACT_DEGRADATION, MILD_AGAINST, event)
            self._update(HypothesisType.SETUP_DRIFT, MILD_AGAINST, event)

    def on_control_check_result(
        self, control_healthy: bool, event: HypothesisEvent
    ) -> None:
        """
        After measuring a control device, update hypotheses based on the result.

        - Control healthy → contact/setup issues are local, not instrument-wide
        - Control degraded → setup/instrument issue is more likely
        """
        if control_healthy:
            self._update(HypothesisType.CONTACT_DEGRADATION, STRONG_SUPPORT, event)
            self._update(HypothesisType.LOCAL_SPATIAL_DEFECT, MODERATE_SUPPORT, event)
            self._update(HypothesisType.SETUP_DRIFT, STRONG_AGAINST, event)
            evidence_str = "Control device is healthy — issue is local, not instrument-wide"
            self.run_state.hypotheses[HypothesisType.CONTACT_DEGRADATION.value].evidence_for.append(
                evidence_str
            )
        else:
            self._update(HypothesisType.SETUP_DRIFT, STRONG_SUPPORT, event)
            self._update(HypothesisType.MEASUREMENT_NOISE_ISSUE, MODERATE_SUPPORT, event)
            self._update(HypothesisType.LOCAL_SPATIAL_DEFECT, STRONG_AGAINST, event)
            self._update(HypothesisType.CONTACT_DEGRADATION, MODERATE_SUPPORT, event)
            evidence_str = "Control device is degraded — possible setup or instrument issue"
            self.run_state.hypotheses[HypothesisType.SETUP_DRIFT.value].evidence_for.append(
                evidence_str
            )

    def on_spatial_cluster_detected(
        self, cluster: "SpatialCluster", event: HypothesisEvent
    ) -> None:
        """Spatial clusters support local defect and corner-effect hypotheses."""
        if "corner" in cluster.grid_position_label or "bottom" in cluster.grid_position_label:
            self._update(HypothesisType.CORNER_EFFECT, STRONG_SUPPORT, event)
            self._update(HypothesisType.LOCAL_SPATIAL_DEFECT, MODERATE_SUPPORT, event)
            self.run_state.hypotheses[HypothesisType.CORNER_EFFECT.value].evidence_for.append(
                cluster.description
            )
        else:
            self._update(HypothesisType.LOCAL_SPATIAL_DEFECT, STRONG_SUPPORT, event)
            self.run_state.hypotheses[HypothesisType.LOCAL_SPATIAL_DEFECT.value].evidence_for.append(
                cluster.description
            )

    def on_rapid_degradation(
        self, device: "DeviceRecord", trend: "TrendFeatures", event: HypothesisEvent
    ) -> None:
        """Fast degradation supports true device degradation hypothesis."""
        if trend.trend_state in (TrendState.RAPIDLY_WORSENING, TrendState.NEAR_BREAKDOWN):
            self._update(HypothesisType.TRUE_DEVICE_DEGRADATION, STRONG_SUPPORT, event)
            self._update(HypothesisType.CONTACT_DEGRADATION, MILD_AGAINST, event)
        elif trend.trend_state == TrendState.ABRUPT_FAILURE:
            self._update(HypothesisType.TRUE_DEVICE_DEGRADATION, STRONG_SUPPORT, event)
            self._update(HypothesisType.PRE_EXISTING_SHORT, WEAK_SUPPORT, event)

    def on_noisy_measurements(self, event: HypothesisEvent) -> None:
        """Noisy traces support measurement noise / setup drift."""
        self._update(HypothesisType.MEASUREMENT_NOISE_ISSUE, MODERATE_SUPPORT, event)
        self._update(HypothesisType.SETUP_DRIFT, WEAK_SUPPORT, event)

    def on_consecutive_contact_failures(
        self, n: int, event: HypothesisEvent
    ) -> None:
        """Multiple consecutive contact failures strongly suggest probe-tip wear."""
        delta = min(STRONG_SUPPORT, WEAK_SUPPORT * n)
        self._update(HypothesisType.CONTACT_DEGRADATION, delta, event)
        if n >= 4:
            self._update(HypothesisType.SETUP_DRIFT, WEAK_SUPPORT, event)

    def on_grid_position_effect(
        self, device: "DeviceRecord", event: HypothesisEvent
    ) -> None:
        """Corner / edge devices with issues support the corner effect hypothesis."""
        from ..models.device import GridPosition
        if device.grid_position in (GridPosition.CORNER, GridPosition.EDGE):
            if device.status in (DeviceStatus.FAILED, DeviceStatus.DEGRADING, DeviceStatus.NEAR_FAILURE):
                self._update(HypothesisType.CORNER_EFFECT, WEAK_SUPPORT, event)

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _update(
        self,
        h_type: HypothesisType,
        delta: float,
        event: HypothesisEvent,
    ) -> None:
        """Apply a delta to a hypothesis's support level and update metadata."""
        h = self.run_state.hypotheses[h_type.value]
        h.support_level = max(0.0, min(1.0, h.support_level + delta))
        h.active = h.support_level >= ACTIVE_THRESHOLD
        h.last_updated = datetime.now()

        if delta > 0:
            evidence_entry = f"[{event.event_type}] {event.description}"
            if evidence_entry not in h.evidence_for:
                h.evidence_for.append(evidence_entry)
        elif delta < 0:
            evidence_entry = f"[{event.event_type}] {event.description}"
            if evidence_entry not in h.evidence_against:
                h.evidence_against.append(evidence_entry)

    def format_summary(self) -> str:
        """Return a compact text summary of active hypotheses for notes/alerts."""
        active = self.get_active()
        if not active:
            return "No active hypotheses."
        lines = []
        for h in active:
            bar = "█" * int(h.support_level * 10) + "░" * (10 - int(h.support_level * 10))
            lines.append(f"  {h.label:<35} [{bar}] {h.support_level:.2f}")
        return "\n".join(lines)
