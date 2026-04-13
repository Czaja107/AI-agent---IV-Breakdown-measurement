"""
Suspicion engine.

Maintains a structured suspicion state and updates it after every measurement
event.  Suspicion triggers extra actions — it is a first-class concept in the
agent architecture, not just a flag.

Suspicion is heuristic and rule-based: each rule contributes an additive delta
to a suspicion score.  The score is then mapped to a SuspicionLevel enum.
The engine also recommends follow-on actions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from ..config.schema import ThresholdConfig
from ..models.device import DeviceStatus, SuspicionLevel, TrendState
from ..models.measurement import IVMetrics, MeasurementStatus

if TYPE_CHECKING:
    from ..models.device import DeviceRecord
    from ..models.run_state import RunState
    from .trends import TrendFeatures
    from .neighbors import NeighborComparison


# ---------------------------------------------------------------------------
# Named suspicion reasons (used in alerts and notes)
# ---------------------------------------------------------------------------

REASON_CONSECUTIVE_FAILURES = "consecutive_device_failures"
REASON_INCONSISTENT_REPEATS = "inconsistent_confirmatory_repeats"
REASON_NEIGHBOR_MISMATCH = "high_leakage_vs_neighbors"
REASON_RAPID_DEGRADATION = "rapid_temporal_degradation"
REASON_NOISY_TRACE = "noisy_measurement_trace"
REASON_CONTROL_DEGRADED = "control_device_shows_degradation"
REASON_SPATIAL_CLUSTER = "spatial_cluster_of_anomalies"
REASON_OPEN_CIRCUIT = "open_circuit_measurement"
REASON_ACCELERATING_TREND = "accelerating_degradation_trend"
REASON_SUDDEN_FAILURE_AFTER_HEALTHY = "sudden_failure_after_healthy_streak"


@dataclass
class SuspicionContext:
    """
    All inputs available to the suspicion engine for one evaluation pass.

    Populated by the orchestration layer and passed to SuspicionEngine.evaluate().
    """
    device: "DeviceRecord"
    latest_metrics: IVMetrics
    run_state: "RunState"
    trend_features: Optional["TrendFeatures"] = None
    neighbor_comparison: Optional["NeighborComparison"] = None
    control_device_healthy: Optional[bool] = None   # None = not yet checked
    confirmatory_results: Optional[list[IVMetrics]] = None


@dataclass
class SuspicionResult:
    """Output of a single suspicion engine evaluation."""
    device_id: str
    score: float = 0.0                # 0.0 – 1.0
    level: SuspicionLevel = SuspicionLevel.NONE
    reasons: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    should_check_control: bool = False
    should_escalate: bool = False
    escalation_reason: str = ""


class SuspicionEngine:
    """
    Evaluates a SuspicionContext and returns a SuspicionResult.

    Each rule is a private method that returns (delta_score, reason_string | None).
    Rules are designed to be auditable: each has a clear human-readable justification.
    """

    MAX_SCORE = 1.0

    def __init__(self, thresholds: ThresholdConfig) -> None:
        self.thresholds = thresholds

    def evaluate(self, ctx: SuspicionContext) -> SuspicionResult:
        """
        Run all suspicion rules and aggregate the result.

        Rules are additive — multiple mild signals can combine into high suspicion.
        """
        result = SuspicionResult(device_id=ctx.device.device_id)
        score = 0.0
        reasons: list[str] = []
        actions: set[str] = set()

        # --- Rule: consecutive failures ---
        delta, reason = self._rule_consecutive_failures(ctx)
        if reason:
            score += delta
            reasons.append(reason)
            if ctx.run_state.consecutive_failures >= self.thresholds.consecutive_failures_suspicion:
                actions.add("run_confirmatory_check")
            if ctx.run_state.consecutive_failures >= self.thresholds.consecutive_failures_escalation:
                actions.add("escalate")
                result.escalation_reason = reason

        # --- Rule: inconsistent confirmatory repeats ---
        delta, reason = self._rule_inconsistent_confirmatory(ctx)
        if reason:
            score += delta
            reasons.append(reason)
            actions.add("check_control_device")

        # --- Rule: neighbor mismatch ---
        delta, reason = self._rule_neighbor_mismatch(ctx)
        if reason:
            score += delta
            reasons.append(reason)
            actions.add("inspect_neighbors")

        # --- Rule: rapid temporal degradation ---
        delta, reason = self._rule_rapid_degradation(ctx)
        if reason:
            score += delta
            reasons.append(reason)
            if delta >= 0.25:
                actions.add("switch_to_dense_monitoring")

        # --- Rule: noisy trace ---
        delta, reason = self._rule_noisy_trace(ctx)
        if reason:
            score += delta
            reasons.append(reason)
            actions.add("run_confirmatory_check")

        # --- Rule: open circuit / contact issue ---
        delta, reason = self._rule_open_circuit(ctx)
        if reason:
            score += delta
            reasons.append(reason)
            actions.add("run_confirmatory_check")

        # --- Rule: control device failure ---
        delta, reason = self._rule_control_degraded(ctx)
        if reason:
            score += delta
            reasons.append(reason)
            actions.add("escalate")
            result.escalation_reason = reason

        # --- Rule: accelerating degradation ---
        delta, reason = self._rule_accelerating_trend(ctx)
        if reason:
            score += delta
            reasons.append(reason)
            actions.add("switch_to_dense_monitoring")

        # --- Rule: sudden failure after healthy streak ---
        delta, reason = self._rule_sudden_failure(ctx)
        if reason:
            score += delta
            reasons.append(reason)
            actions.add("check_control_device")

        # Clamp score
        score = min(score, self.MAX_SCORE)

        result.score = round(score, 3)
        result.level = SuspicionLevel.from_score(score)
        result.reasons = reasons
        result.recommended_actions = sorted(actions)

        thr = self.thresholds
        result.should_check_control = (
            score >= thr.suspicion_score_for_control_check
            or "check_control_device" in actions
        )
        result.should_escalate = (
            score >= thr.suspicion_score_for_escalation
            or "escalate" in actions
        )

        return result

    # -----------------------------------------------------------------------
    # Individual suspicion rules
    # -----------------------------------------------------------------------

    def _rule_consecutive_failures(
        self, ctx: SuspicionContext
    ) -> tuple[float, str | None]:
        n = ctx.run_state.consecutive_failures
        thr = self.thresholds
        if n < thr.consecutive_failures_suspicion:
            return 0.0, None
        # Scale: suspicion → 0.3, escalation → 0.7+
        score = min(0.8, 0.15 * n)
        label = (
            f"{n} consecutive device failures "
            f"(threshold for suspicion: {thr.consecutive_failures_suspicion})"
        )
        return score, f"{REASON_CONSECUTIVE_FAILURES}: {label}"

    def _rule_inconsistent_confirmatory(
        self, ctx: SuspicionContext
    ) -> tuple[float, str | None]:
        n = ctx.device.inconsistent_confirmatory_count
        thr = self.thresholds
        if n < thr.confirmatory_inconsistency_count:
            return 0.0, None
        return 0.35, (
            f"{REASON_INCONSISTENT_REPEATS}: {n} inconsistent confirmatory "
            f"sweeps on device {ctx.device.device_id}"
        )

    def _rule_neighbor_mismatch(
        self, ctx: SuspicionContext
    ) -> tuple[float, str | None]:
        nc = ctx.neighbor_comparison
        if nc is None or not nc.is_outlier_high:
            return 0.0, None
        ratio = nc.leakage_ratio
        thr = self.thresholds
        if ratio >= thr.neighbor_leakage_ratio_critical:
            return 0.45, (
                f"{REASON_NEIGHBOR_MISMATCH}: leakage {ratio:.0f}× above "
                f"neighbor median (critical threshold: {thr.neighbor_leakage_ratio_critical:.0f}×)"
            )
        return 0.25, (
            f"{REASON_NEIGHBOR_MISMATCH}: leakage {ratio:.1f}× above "
            f"neighbor median (suspicious threshold: {thr.neighbor_leakage_ratio_suspicious:.0f}×)"
        )

    def _rule_rapid_degradation(
        self, ctx: SuspicionContext
    ) -> tuple[float, str | None]:
        tf = ctx.trend_features
        if tf is None:
            return 0.0, None
        thr = self.thresholds
        if tf.trend_state == TrendState.NEAR_BREAKDOWN:
            return 0.50, (
                f"{REASON_RAPID_DEGRADATION}: trend state = NEAR_BREAKDOWN "
                f"(compliance hit in {tf.fraction_compliance_hit*100:.0f}% of recent sweeps)"
            )
        if tf.trend_state == TrendState.RAPIDLY_WORSENING:
            return 0.35, (
                f"{REASON_RAPID_DEGRADATION}: trend state = RAPIDLY_WORSENING "
                f"(slope {tf.leakage_trend_slope:.2f} decades/sweep)"
            )
        if tf.trend_state == TrendState.SLOWLY_WORSENING and tf.worsening_rate > 0.4:
            return 0.20, (
                f"{REASON_RAPID_DEGRADATION}: leakage increased "
                f"{tf.leakage_ratio_first_last:.1f}× over {tf.n_measurements} measurements"
            )
        return 0.0, None

    def _rule_noisy_trace(
        self, ctx: SuspicionContext
    ) -> tuple[float, str | None]:
        m = ctx.latest_metrics
        if m.measurement_status != MeasurementStatus.NOISY:
            return 0.0, None
        if m.noise_std_A > m.leakage_at_1v_A * 3.0:
            return 0.20, (
                f"{REASON_NOISY_TRACE}: noise ({m.noise_std_A:.2e} A) exceeds "
                f"3× leakage signal at 1 V ({m.leakage_at_1v_A:.2e} A)"
            )
        return 0.10, f"{REASON_NOISY_TRACE}: elevated noise detected on measurement trace"

    def _rule_open_circuit(
        self, ctx: SuspicionContext
    ) -> tuple[float, str | None]:
        m = ctx.latest_metrics
        if not m.is_open_circuit:
            return 0.0, None
        return 0.30, (
            f"{REASON_OPEN_CIRCUIT}: near-zero current trace suggests bad probe contact "
            f"(I_max = {m.leakage_at_vmax_A:.2e} A)"
        )

    def _rule_control_degraded(
        self, ctx: SuspicionContext
    ) -> tuple[float, str | None]:
        if ctx.control_device_healthy is None:
            return 0.0, None
        if ctx.control_device_healthy:
            return 0.0, None
        return 0.70, (
            f"{REASON_CONTROL_DEGRADED}: designated healthy control device "
            f"shows anomalous behaviour — setup or instrument instability suspected"
        )

    def _rule_accelerating_trend(
        self, ctx: SuspicionContext
    ) -> tuple[float, str | None]:
        tf = ctx.trend_features
        if tf is None or tf.leakage_acceleration <= 0.05:
            return 0.0, None
        return 0.25, (
            f"{REASON_ACCELERATING_TREND}: degradation is accelerating "
            f"(2nd-order coefficient = {tf.leakage_acceleration:.3f})"
        )

    def _rule_sudden_failure(
        self, ctx: SuspicionContext
    ) -> tuple[float, str | None]:
        """Flags a sudden failure streak that follows a long healthy streak."""
        rs = ctx.run_state
        n_done = rs.n_devices_done
        n_fail = rs.consecutive_failures
        if n_fail < 2:
            return 0.0, None
        # If more than 30% of done devices were healthy before this streak
        n_healthy_prior = rs.n_healthy
        if n_done > 0 and n_healthy_prior / max(n_done, 1) > 0.5 and n_fail >= 3:
            return 0.30, (
                f"{REASON_SUDDEN_FAILURE_AFTER_HEALTHY}: {n_fail} consecutive failures "
                f"following a run of {n_healthy_prior} healthy devices — "
                f"sudden contact or probe degradation suspected"
            )
        return 0.0, None
