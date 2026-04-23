"""
Policy engine — the decision-making core of the experiment agent.

All measurement-result → next-action logic lives here.  The engine is a pure
function of its inputs (PolicyContext → PolicyDecision) with no side effects,
making it independently unit-testable.

Protocol switching is explicit: each state has its own decision method that
returns a PolicyDecision with a named AgentAction.
"""
from __future__ import annotations

from ..config.schema import AgentConfig, ThresholdConfig
from ..models.device import DeviceStatus, SuspicionLevel, TrendState, ProtocolMode
from .states import AgentAction, AgentState, PolicyContext, PolicyDecision


class PolicyEngine:
    """
    Stateless decision engine.

    Call decide(context) to get the recommended action for the current
    agent state and measurement results.

    The engine implements 'if-this-then-that' policy tables for each agent
    state.  Each decision path is explicit, labelled, and returns a full
    PolicyDecision with a human-readable reason.
    """

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.thresholds: ThresholdConfig = config.thresholds

    def decide(self, ctx: PolicyContext) -> PolicyDecision:
        """Route to the appropriate state-specific decision method."""
        dispatch = {
            AgentState.MEASURING_INITIAL_HEALTH: self._decide_after_health_check,
            AgentState.CLASSIFYING_DEVICE: self._decide_classification,
            AgentState.STRESSING_DEVICE: self._decide_during_stress,
            AgentState.DENSE_MONITORING: self._decide_during_dense_monitoring,
            AgentState.RUNNING_CONFIRMATORY_CHECK: self._decide_after_confirmatory,
            AgentState.CHECKING_CONTROL_DEVICE: self._decide_after_control_check,
            AgentState.COMPARING_NEIGHBORS: self._decide_after_neighbor_inspection,
        }
        handler = dispatch.get(ctx.agent_state)
        if handler is None:
            return PolicyDecision(
                action=AgentAction.ADVANCE_TO_NEXT_DEVICE,
                reason="No handler for current state; advancing.",
            )
        return handler(ctx)

    # -----------------------------------------------------------------------
    # State-specific decision methods
    # -----------------------------------------------------------------------

    def _decide_after_health_check(self, ctx: PolicyContext) -> PolicyDecision:
        """
        Decide what to do immediately after the initial health-check measurement.
        """
        m = ctx.latest_metrics
        if m is None:
            return PolicyDecision(
                action=AgentAction.SKIP_DEVICE,
                reason="No metrics available from health check — skipping device.",
            )

        status = ctx.latest_status

        # --- Shorted device: immediate skip ---
        if status == DeviceStatus.SHORTED:
            return PolicyDecision(
                action=AgentAction.SKIP_DEVICE,
                reason=(
                    f"Device is shorted (R_est = {m.estimated_resistance_ohm:.2e} Ohm). "
                    f"Skipping durability testing."
                ),
                note=(
                    f"**Shorted device detected.** I(1V) = {m.leakage_at_1v_A:.2e} A, "
                    f"R_est = {m.estimated_resistance_ohm:.2e} Ohm. "
                    f"Pre-existing short hypothesis supported."
                ),
            )

        # --- Contact issue: retry once ---
        if status == DeviceStatus.CONTACT_ISSUE:
            if ctx.device.confirmatory_count < 1:
                return PolicyDecision(
                    action=AgentAction.REPEAT_MEASUREMENT,
                    reason=(
                        f"Near-zero current (I_max = {m.leakage_at_vmax_A:.2e} A) "
                        f"suggests bad probe contact. Retrying once."
                    ),
                    note=(
                        f"**Contact issue on first health check.** "
                        f"I(Vmax) = {m.leakage_at_vmax_A:.2e} A. Scheduling retry."
                    ),
                )
            else:
                return PolicyDecision(
                    action=AgentAction.SKIP_DEVICE,
                    reason=(
                        "Contact issue persists after retry. "
                        "Logging as CONTACT_ISSUE and moving on."
                    ),
                    note=(
                        f"**Persistent contact issue after {ctx.device.confirmatory_count} attempts.** "
                        f"Marking as CONTACT_ISSUE. Consider probe inspection."
                    ),
                    severity_hint=2,
                )

        # --- Failed device: skip stress ---
        if status == DeviceStatus.FAILED:
            return PolicyDecision(
                action=AgentAction.SKIP_DEVICE,
                reason=(
                    f"Device already failed at health check "
                    f"(I(1V) = {m.leakage_at_1v_A:.2e} A > threshold "
                    f"{self.thresholds.max_leakage_degraded_A:.2e} A). Skipping stress."
                ),
                note=(
                    f"**Device failed at initial health check.** "
                    f"I(1V) = {m.leakage_at_1v_A:.2e} A. "
                    f"True device degradation or pre-existing defect suspected."
                ),
            )

        # --- Near-failure: run confirmatory before stressing ---
        if status == DeviceStatus.NEAR_FAILURE:
            return PolicyDecision(
                action=AgentAction.RUN_CONFIRMATORY_CHECK,
                reason=(
                    f"Near-failure signature at health check "
                    f"(compliance hit at {m.breakdown_voltage_V:.1f} V). "
                    f"Running confirmatory check before deciding."
                ),
                note=(
                    f"**Near-failure at health check.** "
                    f"Compliance hit at V = {m.breakdown_voltage_V} V. "
                    f"Confirmatory measurement scheduled."
                ),
            )

        # --- Suspicious suspicion level from context ---
        if ctx.suspicion_result and ctx.suspicion_result.level in (
            SuspicionLevel.HIGH, SuspicionLevel.CRITICAL
        ):
            return PolicyDecision(
                action=AgentAction.RUN_CONFIRMATORY_CHECK,
                reason=(
                    f"Suspicion level = {ctx.suspicion_result.level.value} "
                    f"despite apparently OK health check metrics. "
                    f"Running confirmatory check."
                ),
                note=(
                    f"**High suspicion despite OK metrics.** "
                    f"Reasons: {'; '.join(ctx.suspicion_result.reasons[:2])}. "
                    f"Confirmatory check scheduled."
                ),
            )

        # --- Degrading: proceed but note the elevated leakage ---
        if status == DeviceStatus.DEGRADING:
            return PolicyDecision(
                action=AgentAction.START_STRESS,
                reason=(
                    f"Device shows elevated leakage (I(1V) = {m.leakage_at_1v_A:.2e} A) "
                    f"but is within degrading range. Proceeding with stress in dense mode."
                ),
                note=(
                    f"**Degraded but testable.** I(1V) = {m.leakage_at_1v_A:.2e} A. "
                    f"Starting stress in dense monitoring mode."
                ),
                new_protocol=ProtocolMode.DENSE_MONITORING.value,
            )

        # --- Healthy: start normal stress ---
        return PolicyDecision(
            action=AgentAction.START_STRESS,
            reason=(
                f"Device is healthy (I(1V) = {m.leakage_at_1v_A:.2e} A, "
                f"no breakdown in health check). Starting normal stress testing."
            ),
            note=(
                f"**Healthy device.** I(1V) = {m.leakage_at_1v_A:.2e} A. "
                f"Normal stress protocol initiated."
            ),
        )

    def _decide_classification(self, ctx: PolicyContext) -> PolicyDecision:
        """Alias to health check decision (same logic, called after retry)."""
        return self._decide_after_health_check(ctx)

    def _decide_during_stress(self, ctx: PolicyContext) -> PolicyDecision:
        """
        Decide what to do after each stress batch completes.

        Called once per batch during the normal stress protocol.
        """
        tf = ctx.trend_features
        m = ctx.latest_metrics
        sr = ctx.suspicion_result
        thr = self.thresholds
        batch = ctx.stress_batch_index

        # --- Device failed during stress (compliance hit = breakdown) ---
        if m and m.compliance_hit and m.breakdown_voltage_V is not None:
            if m.breakdown_voltage_V < 4.0:
                return PolicyDecision(
                    action=AgentAction.STOP_STRESS,
                    reason=(
                        f"Breakdown at {m.breakdown_voltage_V:.1f} V during stress batch {batch+1}. "
                        f"Device has failed. Stopping stress."
                    ),
                    note=(
                        f"**Breakdown during stress (batch {batch+1}).** "
                        f"V_bd = {m.breakdown_voltage_V:.1f} V. Device marked FAILED."
                    ),
                    severity_hint=2,
                )
            # Borderline breakdown: switch to dense monitoring
            return PolicyDecision(
                action=AgentAction.SWITCH_TO_DENSE_MONITORING,
                reason=(
                    f"Compliance hit at {m.breakdown_voltage_V:.1f} V during stress batch {batch+1}. "
                    f"Switching to dense monitoring."
                ),
                note=(
                    f"**Compliance hit during stress (batch {batch+1}).** "
                    f"V_bd = {m.breakdown_voltage_V:.1f} V. Dense monitoring activated."
                ),
            )

        # --- Rapid degradation detected ---
        if tf and tf.trend_state in (TrendState.RAPIDLY_WORSENING, TrendState.NEAR_BREAKDOWN):
            if not ctx.neighbors_inspected:
                return PolicyDecision(
                    action=AgentAction.INSPECT_NEIGHBORS,
                    reason=(
                        f"Rapid degradation detected (trend = {tf.trend_state.value}). "
                        f"Inspecting neighbours before switching protocol."
                    ),
                )
            return PolicyDecision(
                action=AgentAction.SWITCH_TO_DENSE_MONITORING,
                reason=(
                    f"Rapid degradation confirmed (slope = {tf.leakage_trend_slope:.2f} dec/batch, "
                    f"worsening rate = {tf.worsening_rate:.2f}). Switching to dense monitoring."
                ),
                note=(
                    f"**Rapid degradation — switching to dense monitoring** (batch {batch+1}). "
                    f"Leakage ratio first→last: {tf.leakage_ratio_first_last:.1f}×."
                ),
            )

        # --- High suspicion: check control device ---
        if sr and sr.should_check_control and not ctx.control_checked_this_pass:
            return PolicyDecision(
                action=AgentAction.CHECK_CONTROL_DEVICE,
                reason=(
                    f"Suspicion level = {sr.level.value} during stress testing. "
                    f"Checking control device to rule out setup issues."
                ),
            )

        # --- Escalation threshold exceeded ---
        if sr and sr.should_escalate:
            return PolicyDecision(
                action=AgentAction.ESCALATE_AND_CONTINUE,
                reason=sr.escalation_reason or "Suspicion threshold exceeded during stress.",
                severity_hint=3,
            )

        # --- Max batches reached: finish device ---
        if batch + 1 >= thr.max_stress_batches_per_device:
            status = ctx.latest_status
            return PolicyDecision(
                action=AgentAction.FINISH_DEVICE,
                reason=(
                    f"Reached maximum stress batches ({thr.max_stress_batches_per_device}). "
                    f"Final status: {status.value if status else 'unknown'}."
                ),
                note=(
                    f"**Stress testing complete** ({batch+1} batches). "
                    f"Device status: {status.value if status else 'unknown'}."
                ),
            )

        # --- Continue stress ---
        return PolicyDecision(
            action=AgentAction.CONTINUE_STRESS,
            reason=(
                f"Stress batch {batch+1} complete. "
                f"Trend = {tf.trend_state.value if tf else 'unknown'}. Continuing."
            ),
        )

    def _decide_during_dense_monitoring(self, ctx: PolicyContext) -> PolicyDecision:
        """
        Decide what to do after each dense-monitoring batch.

        Dense monitoring uses shorter sweeps and more frequent checks.
        """
        tf = ctx.trend_features
        m = ctx.latest_metrics
        batch = ctx.stress_batch_index
        thr = self.thresholds

        # --- Catastrophic failure during dense monitoring ---
        if m and m.compliance_hit:
            return PolicyDecision(
                action=AgentAction.STOP_STRESS,
                reason=(
                    f"Compliance hit during dense monitoring (batch {batch+1}). "
                    f"Device has failed."
                ),
                note=(
                    f"**Device failed during dense monitoring** (batch {batch+1}). "
                    f"V_bd = {m.breakdown_voltage_V} V."
                ),
                severity_hint=2,
            )

        # --- Still rapidly worsening ---
        if tf and tf.trend_state in (TrendState.RAPIDLY_WORSENING, TrendState.NEAR_BREAKDOWN):
            if batch + 1 >= thr.stress_batches_dense_mode:
                return PolicyDecision(
                    action=AgentAction.STOP_STRESS,
                    reason=(
                        f"Device remains in {tf.trend_state.value} state after "
                        f"{batch+1} dense monitoring batches. Marking as failed."
                    ),
                    note=(
                        f"**Dense monitoring exhausted** — device is still degrading rapidly. "
                        f"Marking FAILED."
                    ),
                    severity_hint=2,
                )

        # --- Stabilised: can reduce monitoring ---
        if tf and tf.trend_state == TrendState.STABLE and batch >= 2:
            return PolicyDecision(
                action=AgentAction.FINISH_DEVICE,
                reason=(
                    f"Device stabilised after {batch+1} dense monitoring batches. "
                    f"Ending stress testing."
                ),
                note=(
                    f"**Dense monitoring: device stabilised** after {batch+1} batches."
                ),
            )

        # --- Max dense monitoring batches ---
        if batch + 1 >= thr.stress_batches_dense_mode:
            return PolicyDecision(
                action=AgentAction.FINISH_DEVICE,
                reason=(
                    f"Reached maximum dense monitoring batches ({thr.stress_batches_dense_mode})."
                ),
            )

        return PolicyDecision(
            action=AgentAction.CONTINUE_STRESS,
            reason=f"Dense monitoring batch {batch+1} complete. Continuing.",
        )

    def _decide_after_confirmatory(self, ctx: PolicyContext) -> PolicyDecision:
        """
        Decide after running confirmatory (repeated) measurements.

        Inconsistency between repeats → high suspicion.
        Consistent near-failure → skip.
        Consistent healthy → proceed with stress.
        """
        m = ctx.latest_metrics
        device = ctx.device

        if device.inconsistent_confirmatory_count >= self.thresholds.confirmatory_inconsistency_count:
            return PolicyDecision(
                action=AgentAction.CHECK_CONTROL_DEVICE,
                reason=(
                    f"{device.inconsistent_confirmatory_count} inconsistent confirmatory results. "
                    f"Checking control device to distinguish device vs setup issue."
                ),
                note=(
                    f"**Inconsistent confirmatory measurements** on {device.device_id}. "
                    f"Control device check scheduled."
                ),
                severity_hint=2,
            )

        if m and (m.is_open_circuit or m.compliance_hit):
            return PolicyDecision(
                action=AgentAction.SKIP_DEVICE,
                reason=(
                    "Confirmatory check confirms device issue. Skipping stress."
                ),
                note=(
                    f"**Confirmatory check confirms issue** on {device.device_id}. "
                    f"Skipping durability testing."
                ),
            )

        # Confirmed healthy / recoverable
        return PolicyDecision(
            action=AgentAction.START_STRESS,
            reason="Confirmatory check passed. Proceeding with stress testing.",
            note=(
                f"**Confirmatory check passed** on {device.device_id}. "
                f"Stress testing initiated."
            ),
        )

    def _decide_after_control_check(self, ctx: PolicyContext) -> PolicyDecision:
        """
        Decide after measuring the designated control device out-of-sequence.
        """
        healthy = ctx.run_state.control_device_healthy if ctx.run_state else None

        if healthy is False:
            # Control device shows problems → escalate, consider pause
            n_failures = ctx.run_state.consecutive_failures if ctx.run_state else 0
            severity = 4 if n_failures >= self.thresholds.consecutive_failures_escalation else 3
            return PolicyDecision(
                action=AgentAction.ESCALATE_AND_PAUSE if severity == 4 else AgentAction.ESCALATE_AND_CONTINUE,
                reason=(
                    "Control device is also showing degraded behaviour. "
                    "Setup or instrument instability suspected. "
                    "Human operator intervention required."
                ),
                note=(
                    "**Control device degraded** — possible instrument or setup issue. "
                    "SETUP_DRIFT hypothesis strongly supported. "
                    "Escalating to operator."
                ),
                severity_hint=severity,
            )

        # Control is healthy → local device/process issue
        return PolicyDecision(
            action=AgentAction.CONTINUE_STRESS,
            reason=(
                "Control device is healthy. "
                "Observed issues are likely real device/process behaviour. "
                "Resuming normal operation."
            ),
            note=(
                "**Control device check passed.** "
                "Setup appears stable. Observed failures are device-level. "
                "CONTACT_DEGRADATION or LOCAL_SPATIAL_DEFECT hypothesis supported."
            ),
        )

    def _decide_after_neighbor_inspection(self, ctx: PolicyContext) -> PolicyDecision:
        """
        Decide after comparing a device to its spatial neighbours.
        """
        nc = ctx.neighbor_comparison

        if nc and (nc.is_outlier_high or nc.same_row_anomaly or nc.same_col_anomaly):
            return PolicyDecision(
                action=AgentAction.SWITCH_TO_DENSE_MONITORING,
                reason=(
                    f"Device is an outlier among neighbours "
                    f"(leakage ratio = {nc.leakage_ratio:.1f}×). "
                    f"Switching to dense monitoring."
                ),
                note=(
                    f"**Spatial outlier confirmed** for {nc.device_id}. "
                    f"Leakage {nc.leakage_ratio:.1f}× above neighbour median. "
                    f"Dense monitoring activated."
                ),
            )

        if nc and nc.is_in_cluster:
            return PolicyDecision(
                action=AgentAction.ESCALATE_AND_CONTINUE,
                reason=(
                    f"Device is part of a spatial cluster of anomalies. "
                    f"Likely local fabrication defect."
                ),
                severity_hint=3,
            )

        # No spatial anomaly found → return to stress
        return PolicyDecision(
            action=AgentAction.CONTINUE_STRESS,
            reason=(
                "No significant spatial anomaly detected. "
                "Resuming stress testing."
            ),
        )
