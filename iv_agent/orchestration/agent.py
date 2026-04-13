"""
Main experiment agent loop.

ExperimentAgent orchestrates the full measurement run:
  1. Initialises devices, instruments, analysis engines, and reporting.
  2. Steps through the device grid in traversal order.
  3. For each device: runs the health check, applies policy decisions,
     executes stress / confirmatory / control / neighbor steps.
  4. After each action, updates run state, notes, and alerts.
  5. Periodically checkpoints to disk.
  6. Generates final reports at the end.

The agent is *not* a monolithic loop with scattered conditionals.
Decision logic lives exclusively in PolicyEngine; the agent loop
executes the action returned by the policy.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

from ..config.schema import AgentConfig, ProtocolParams
from ..models.device import (
    DeviceRecord, DeviceStatus, GridPosition, ProtocolMode,
    SuspicionLevel, TrendState,
)
from ..models.measurement import IVCurve, IVMetrics, StressBatch
from ..models.run_state import Alert, AlertSeverity, Note, RunState
from ..instruments.base import InstrumentBackend
from ..analysis.features import extract_iv_metrics
from ..analysis.health import classify_device_health, estimate_contact_quality
from ..analysis.trends import TrendAnalyzer, TrendFeatures
from ..analysis.neighbors import NeighborAnalyzer, NeighborComparison
from ..analysis.suspicion import SuspicionEngine, SuspicionContext, SuspicionResult
from ..analysis.hypotheses import HypothesisTracker, HypothesisEvent
from ..policy.engine import PolicyEngine
from ..policy.states import AgentAction, AgentState, PolicyContext, PolicyDecision


console = Console(force_terminal=True)


class ExperimentAgent:
    """
    Autonomous experiment manager for capacitor reliability characterisation.

    Initialise with a validated AgentConfig, then call run() to start the
    measurement run.  Uses InstrumentBackend.from_config() to get either the
    simulated or real hardware backend.
    """

    CHECKPOINT_EVERY_N_DEVICES = 3

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.backend: InstrumentBackend = InstrumentBackend.from_config(config)

        # Analysis engines
        self.trend_analyzer = TrendAnalyzer(config.thresholds)
        self.neighbor_analyzer = NeighborAnalyzer(
            config.grid.nx, config.grid.ny, config.thresholds
        )
        self.suspicion_engine = SuspicionEngine(config.thresholds)
        self.policy_engine = PolicyEngine(config)

        # Initialise run state
        self.run_state = RunState(
            chip_id=config.run.chip_id,
            run_id=config.run.run_id,
            n_devices_total=config.grid.n_devices,
        )

        # Hypothesis tracker wires itself into run_state
        self.hypothesis_tracker = HypothesisTracker(self.run_state)

        # Reporting / notifications (imported lazily to avoid circular imports)
        from ..reporting.notes import NotesWriter
        from ..notifications.alerts import AlertManager
        from ..storage.persistence import StorageManager
        self.notes_writer = NotesWriter(self.run_state, config)
        self.alert_manager = AlertManager(config)
        self.storage = StorageManager(config)

        # Output directory
        self.output_dir: Path = config.output_path()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def run(self) -> RunState:
        """Execute the full measurement run and return the final RunState."""
        console.print(Panel(
            f"[bold cyan]IV-Agent — Autonomous Capacitor Reliability Characterisation[/bold cyan]\n"
            f"Chip: [yellow]{self.config.run.chip_id}[/yellow]  "
            f"Run: [yellow]{self.config.run.run_id}[/yellow]  "
            f"Grid: {self.config.grid.nx}×{self.config.grid.ny} = "
            f"{self.config.grid.n_devices} devices",
            title="Experiment Start",
            border_style="cyan",
        ))

        self.backend.connect()
        self.run_state.start_time = datetime.now()

        try:
            self._initialise_devices()
            self._run_main_loop()
        except KeyboardInterrupt:
            console.print("\n[bold red]Run interrupted by user.[/bold red]")
        finally:
            self.run_state.end_time = datetime.now()
            self.run_state.is_complete = not self.run_state.is_paused
            self._generate_final_reports()
            self.backend.disconnect()

        return self.run_state

    # -----------------------------------------------------------------------
    # Initialisation
    # -----------------------------------------------------------------------

    def _initialise_devices(self) -> None:
        """Create DeviceRecord objects for all grid positions."""
        grid = self.config.grid
        naming = self.config.device_naming
        sequence = grid.device_sequence()

        for (ix, iy) in sequence:
            dev_id = naming.format_id(iy, ix)
            grid_pos = self.neighbor_analyzer.classify_grid_position(ix, iy)
            is_control = self.config.is_control_device(ix, iy)

            device = DeviceRecord(
                device_id=dev_id,
                ix=ix,
                iy=iy,
                grid_position=grid_pos,
                is_control_device=is_control,
            )
            self.run_state.devices[dev_id] = device
            self.run_state.device_order.append(dev_id)

            if is_control:
                self.run_state.control_device_ids.append(dev_id)

    # -----------------------------------------------------------------------
    # Main loop
    # -----------------------------------------------------------------------

    def _run_main_loop(self) -> None:
        """Step through every device in traversal order."""
        total = len(self.run_state.device_order)

        for i, dev_id in enumerate(self.run_state.device_order):
            device: DeviceRecord = self.run_state.devices[dev_id]

            if self.run_state.is_paused:
                console.print(
                    f"\n[bold red]Run paused.[/bold red] "
                    f"Reason: {self.run_state.pause_reason}\n"
                    f"Press [bold]Enter[/bold] to resume or Ctrl+C to abort."
                )
                input()
                self.run_state.is_paused = False
                self.run_state.pause_reason = None
                self.backend.resume()

            console.rule(
                f"[bold]Device {i+1}/{total}: {dev_id} "
                f"[{device.ix},{device.iy}] ({device.grid_position.value})[/bold]"
            )

            # Move probe to device
            self.backend.move_to_grid_position(device.ix, device.iy)
            device.measurement_start = datetime.now()

            self._process_device(device)

            device.measurement_end = datetime.now()
            device.is_done = True
            self.run_state.n_devices_done += 1
            self._update_run_counters(device)

            # Checkpoint periodically
            if (i + 1) % self.CHECKPOINT_EVERY_N_DEVICES == 0:
                self.storage.checkpoint(self.run_state, self.output_dir)

            # Post-device spatial analysis
            clusters = self.neighbor_analyzer.detect_spatial_cluster(
                self.run_state.devices
            )
            if clusters:
                for cluster in clusters:
                    self._handle_spatial_cluster(cluster)

    # -----------------------------------------------------------------------
    # Per-device processing
    # -----------------------------------------------------------------------

    def _process_device(self, device: DeviceRecord) -> None:
        """
        Run the full measurement and decision sequence for one device.

        State machine: HEALTH_CHECK → CLASSIFYING → (STRESS | SKIP | CONFIRMATORY)
        """
        # --- STEP 1: Initial health check ---
        self._log_state(AgentState.MEASURING_INITIAL_HEALTH, device)
        health_curve = self.backend.run_iv_sweep(
            device.device_id, self.config.protocols.health_check
        )
        health_metrics = extract_iv_metrics(health_curve, self.config.thresholds)
        self._record_measurement(device, health_curve, health_metrics)

        # Build context for policy engine
        ctx = self._build_context(
            device=device,
            state=AgentState.MEASURING_INITIAL_HEALTH,
            metrics=health_metrics,
        )
        decision = self.policy_engine.decide(ctx)
        self._log_decision(device, decision)

        if decision.note:
            self._write_note(device, decision.note, category="device")

        # --- STEP 2: Execute health-check decision ---
        if decision.action == AgentAction.SKIP_DEVICE:
            self._apply_skip(device, decision)
            return

        if decision.action == AgentAction.REPEAT_MEASUREMENT:
            device.confirmatory_count += 1
            # Retry health check
            health_curve2 = self.backend.run_iv_sweep(
                device.device_id, self.config.protocols.health_check
            )
            health_metrics2 = extract_iv_metrics(health_curve2, self.config.thresholds)
            self._record_measurement(device, health_curve2, health_metrics2)
            ctx = self._build_context(
                device=device,
                state=AgentState.MEASURING_INITIAL_HEALTH,
                metrics=health_metrics2,
            )
            decision = self.policy_engine.decide(ctx)
            self._log_decision(device, decision)
            if decision.note:
                self._write_note(device, decision.note, category="device")
            if decision.action == AgentAction.SKIP_DEVICE:
                self._apply_skip(device, decision)
                return

        if decision.action == AgentAction.RUN_CONFIRMATORY_CHECK:
            decision = self._run_confirmatory(device)
            if decision.action in (AgentAction.SKIP_DEVICE, AgentAction.FINISH_DEVICE):
                self._apply_skip(device, decision)
                return

        # --- STEP 3: Check if we need to check control device before stressing ---
        ctx = self._build_context(
            device=device, state=AgentState.MEASURING_INITIAL_HEALTH, metrics=health_metrics
        )
        if ctx.suspicion_result and ctx.suspicion_result.should_check_control:
            self._check_control_device(device)

        # --- STEP 4: Determine initial protocol mode ---
        protocol_mode = ProtocolMode.NORMAL_STRESS
        if decision.new_protocol == ProtocolMode.DENSE_MONITORING.value:
            protocol_mode = ProtocolMode.DENSE_MONITORING

        # --- STEP 5: Classify and set baseline ---
        health_status = classify_device_health(health_metrics, self.config.thresholds)
        device.status = health_status
        if device.baseline_leakage_at_1v_A is None and health_metrics.leakage_at_1v_A > 0:
            device.baseline_leakage_at_1v_A = health_metrics.leakage_at_1v_A

        # Update hypothesis tracker
        self.hypothesis_tracker.on_device_classified(
            device,
            HypothesisEvent("initial_classification", device.device_id,
                            f"Device classified as {health_status.value}"),
        )
        self.hypothesis_tracker.on_grid_position_effect(
            device,
            HypothesisEvent("grid_position", device.device_id,
                            f"Device is at grid position {device.grid_position.value}"),
        )

        # If control device, measure lightly and exit
        if device.is_control_device:
            self._log_state(AgentState.CHECKING_CONTROL_DEVICE, device)
            self._handle_control_device_result(device, health_metrics)
            return

        # --- STEP 6: Stress testing loop ---
        self._run_stress_loop(device, protocol_mode)

    def _run_stress_loop(
        self, device: DeviceRecord, initial_mode: ProtocolMode
    ) -> None:
        """
        Execute the stress / durability measurement loop for a device.

        Continues until: max batches reached | device fails | policy says stop.
        """
        mode = initial_mode
        thr = self.config.thresholds
        control_checked = False
        neighbors_inspected = False

        for batch_idx in range(thr.max_stress_batches_per_device):
            self._log_state(
                AgentState.STRESSING_DEVICE if mode == ProtocolMode.NORMAL_STRESS
                else AgentState.DENSE_MONITORING,
                device,
            )

            # Select protocol based on current mode
            protocol = self._protocol_for_mode(mode)
            device.protocol_mode = mode

            # Run stress batch
            batch = self.backend.run_stress_batch(
                device.device_id, protocol, batch_index=batch_idx
            )
            device.stress_batch_count += 1
            device.stress_cycles_total += protocol.n_cycles

            # Record all curves and metrics from the batch
            for curve, metrics in zip(batch.curves, batch.metrics):
                self._record_measurement(device, curve, metrics)

            # Use the last (worst) metrics from the batch for decision making
            last_metrics = batch.metrics[-1] if batch.metrics else None

            # Compliance hit = breakdown event
            if batch.any_compliance_hit:
                device.breakdown_events += 1

            # Trend analysis
            tf = self.trend_analyzer.analyse(device.metrics_history)
            device.trend_state = tf.trend_state

            # Neighbor comparison
            nc = self.neighbor_analyzer.compare_to_neighbors(
                device, self.run_state.devices
            )

            # Suspicion evaluation
            ctx_sus = SuspicionContext(
                device=device,
                latest_metrics=last_metrics,
                run_state=self.run_state,
                trend_features=tf,
                neighbor_comparison=nc,
                control_device_healthy=self.run_state.control_device_healthy,
            )
            sr = self.suspicion_engine.evaluate(ctx_sus)
            device.suspicion_score = sr.score
            device.suspicion_level = sr.level
            device.suspicion_reasons = sr.reasons

            # Classify current status
            current_status = classify_device_health(
                last_metrics, self.config.thresholds
            ) if last_metrics else device.status
            device.status = current_status

            # Update hypotheses
            if tf.trend_state in (TrendState.RAPIDLY_WORSENING, TrendState.NEAR_BREAKDOWN,
                                   TrendState.ABRUPT_FAILURE):
                self.hypothesis_tracker.on_rapid_degradation(
                    device, tf,
                    HypothesisEvent("rapid_degradation", device.device_id,
                                    f"trend={tf.trend_state.value}"),
                )

            # Build policy context
            agent_state = (
                AgentState.STRESSING_DEVICE
                if mode == ProtocolMode.NORMAL_STRESS
                else AgentState.DENSE_MONITORING
            )
            ctx = PolicyContext(
                agent_state=agent_state,
                device=device,
                latest_metrics=last_metrics,
                latest_status=current_status,
                trend_features=tf,
                neighbor_comparison=nc,
                suspicion_result=sr,
                run_state=self.run_state,
                stress_batch_index=batch_idx,
                max_stress_batches=thr.max_stress_batches_per_device,
                control_checked_this_pass=control_checked,
                neighbors_inspected=neighbors_inspected,
            )

            decision = self.policy_engine.decide(ctx)
            self._log_decision(device, decision)

            if decision.note:
                self._write_note(device, decision.note, category="trend")

            # --- Execute action ---
            if decision.action == AgentAction.STOP_STRESS:
                device.status = DeviceStatus.FAILED
                self._write_note(
                    device,
                    f"Device marked FAILED after {batch_idx+1} stress batches. "
                    f"Reason: {decision.reason}",
                    category="device",
                )
                break

            elif decision.action == AgentAction.FINISH_DEVICE:
                break

            elif decision.action == AgentAction.SWITCH_TO_DENSE_MONITORING:
                mode = ProtocolMode.DENSE_MONITORING
                self._write_note(
                    device,
                    f"Protocol switched to DENSE_MONITORING at batch {batch_idx+1}. "
                    f"Reason: {decision.reason}",
                    category="trend",
                )

            elif decision.action == AgentAction.CHECK_CONTROL_DEVICE:
                self._check_control_device(device)
                control_checked = True
                # Re-evaluate after control check
                ctx.control_checked_this_pass = True
                ctx.agent_state = AgentState.CHECKING_CONTROL_DEVICE
                post_control_decision = self.policy_engine.decide(ctx)
                if post_control_decision.action in (
                    AgentAction.ESCALATE_AND_PAUSE, AgentAction.ESCALATE_AND_CONTINUE
                ):
                    self._handle_escalation(device, post_control_decision)
                    if post_control_decision.action == AgentAction.ESCALATE_AND_PAUSE:
                        break

            elif decision.action == AgentAction.INSPECT_NEIGHBORS:
                nc = self.neighbor_analyzer.compare_to_neighbors(
                    device, self.run_state.devices, radius=self.config.thresholds.spatial_cluster_radius
                )
                neighbors_inspected = True
                ctx.neighbor_comparison = nc
                ctx.neighbors_inspected = True
                ctx.agent_state = AgentState.COMPARING_NEIGHBORS
                neighbor_decision = self.policy_engine.decide(ctx)
                if neighbor_decision.action == AgentAction.SWITCH_TO_DENSE_MONITORING:
                    mode = ProtocolMode.DENSE_MONITORING
                elif neighbor_decision.action in (
                    AgentAction.ESCALATE_AND_PAUSE, AgentAction.ESCALATE_AND_CONTINUE
                ):
                    self._handle_escalation(device, neighbor_decision)

            elif decision.action in (
                AgentAction.ESCALATE_AND_CONTINUE, AgentAction.ESCALATE_AND_PAUSE
            ):
                self._handle_escalation(device, decision)
                if decision.action == AgentAction.ESCALATE_AND_PAUSE:
                    break

            # For CONTINUE_STRESS: just go to next iteration

        # Final status update
        if device.status not in (DeviceStatus.FAILED, DeviceStatus.SKIPPED):
            tf_final = self.trend_analyzer.analyse(device.metrics_history)
            if tf_final.trend_state in (TrendState.RAPIDLY_WORSENING, TrendState.NEAR_BREAKDOWN):
                device.status = DeviceStatus.DEGRADING
            elif tf_final.worsening_rate > 0.3:
                device.status = DeviceStatus.DEGRADING
            else:
                if device.status not in (DeviceStatus.DEGRADING,):
                    device.status = DeviceStatus.HEALTHY

    # -----------------------------------------------------------------------
    # Action handlers
    # -----------------------------------------------------------------------

    def _run_confirmatory(self, device: DeviceRecord) -> PolicyDecision:
        """Run n_repeats confirmatory measurements and assess consistency."""
        self._log_state(AgentState.RUNNING_CONFIRMATORY_CHECK, device)
        protocol = self.config.protocols.confirmatory
        confirmatory_metrics: list[IVMetrics] = []

        for rep in range(protocol.n_repeats):
            curve = self.backend.run_iv_sweep(device.device_id, protocol, sweep_index=rep)
            metrics = extract_iv_metrics(curve, self.config.thresholds)
            self._record_measurement(device, curve, metrics)
            confirmatory_metrics.append(metrics)
            device.confirmatory_count += 1

        # Check consistency: do the repeats agree?
        if len(confirmatory_metrics) >= 2:
            leakages = [m.leakage_at_1v_A for m in confirmatory_metrics]
            max_l, min_l = max(leakages), min(leakages)
            if min_l > 0 and (max_l / min_l) > 10.0:
                device.inconsistent_confirmatory_count += 1
                self._write_note(
                    device,
                    f"**Inconsistent confirmatory measurements** "
                    f"(ratio max/min leakage = {max_l/min_l:.1f}×). "
                    f"Measurement noise or intermittent contact suspected.",
                    category="device",
                )
                self.hypothesis_tracker.on_noisy_measurements(
                    HypothesisEvent("inconsistent_confirmatory", device.device_id,
                                    f"leakage ratio {max_l/min_l:.1f}×")
                )

        ctx = PolicyContext(
            agent_state=AgentState.RUNNING_CONFIRMATORY_CHECK,
            device=device,
            latest_metrics=confirmatory_metrics[-1] if confirmatory_metrics else None,
            latest_status=classify_device_health(
                confirmatory_metrics[-1], self.config.thresholds
            ) if confirmatory_metrics else DeviceStatus.UNKNOWN,
            run_state=self.run_state,
            confirmatory_index=device.confirmatory_count,
        )
        decision = self.policy_engine.decide(ctx)
        if decision.note:
            self._write_note(device, decision.note, category="device")
        return decision

    def _check_control_device(self, triggering_device: DeviceRecord) -> None:
        """
        Measure the designated control device out of sequence.

        This is the sentinel mechanism: if the control device looks bad,
        suspect setup/instrument; if it looks fine, suspect real device issues.
        """
        if not self.run_state.control_device_ids:
            return

        ctrl_id = self.run_state.control_device_ids[0]
        ctrl_device: DeviceRecord = self.run_state.devices[ctrl_id]

        console.print(
            f"\n  [bold magenta][CTRL] Control check: {ctrl_id}[/bold magenta] "
            f"(triggered by {triggering_device.device_id})"
        )

        # Move to control device
        self.backend.move_to_grid_position(ctrl_device.ix, ctrl_device.iy)
        ctrl_curve = self.backend.run_iv_sweep(
            ctrl_id, self.config.protocols.control_check
        )
        ctrl_metrics = extract_iv_metrics(ctrl_curve, self.config.thresholds)
        self._record_measurement(ctrl_device, ctrl_curve, ctrl_metrics)

        # Compare to baseline if available
        ctrl_status = classify_device_health(ctrl_metrics, self.config.thresholds)
        control_healthy = ctrl_status in (DeviceStatus.HEALTHY, DeviceStatus.DEGRADING)

        # If we have a baseline, use a stricter check
        if ctrl_device.baseline_leakage_at_1v_A and ctrl_device.baseline_leakage_at_1v_A > 0:
            ratio = ctrl_metrics.leakage_at_1v_A / ctrl_device.baseline_leakage_at_1v_A
            thr_ratio = self.config.thresholds.control_device_leakage_increase_threshold
            if ratio > thr_ratio:
                control_healthy = False
        else:
            ctrl_device.baseline_leakage_at_1v_A = ctrl_metrics.leakage_at_1v_A

        self.run_state.control_device_healthy = control_healthy
        self.run_state.control_device_last_checked = datetime.now()
        self.run_state.out_of_sequence_checks.append(ctrl_id)

        status_str = "[green]HEALTHY[/green]" if control_healthy else "[red]DEGRADED[/red]"
        console.print(f"  Control device result: {status_str}")

        # Update hypotheses
        self.hypothesis_tracker.on_control_check_result(
            control_healthy,
            HypothesisEvent(
                "control_device_check",
                ctrl_id,
                f"Control device {ctrl_id} checked at request of {triggering_device.device_id}: "
                f"{'healthy' if control_healthy else 'degraded'}",
            ),
        )

        note_text = (
            f"**Control device check** ({ctrl_id}) triggered by activity on "
            f"{triggering_device.device_id}. "
            f"Result: {'HEALTHY ✓' if control_healthy else 'DEGRADED ✗'}. "
        )
        if control_healthy:
            note_text += (
                "Setup appears stable. Observed issues are likely real device/process behaviour. "
                "CONTACT_DEGRADATION or LOCAL_SPATIAL_DEFECT hypothesis strengthened."
            )
        else:
            note_text += (
                "Control device shows unexpected behaviour. "
                "Possible instrument drift or probe-tip contamination. "
                "SETUP_DRIFT hypothesis strongly supported. Escalating."
            )
        self._write_note(triggering_device, note_text, category="hypothesis")

        # Move back to original device
        self.backend.move_to_grid_position(triggering_device.ix, triggering_device.iy)

    def _handle_escalation(
        self, device: DeviceRecord, decision: PolicyDecision
    ) -> None:
        """Create and dispatch an alert based on the policy decision."""
        severity_int = decision.severity_hint
        severity = AlertSeverity(severity_int)

        # Collect evidence
        evidence = []
        if self.run_state.consecutive_failures > 0:
            evidence.append(
                f"{self.run_state.consecutive_failures} consecutive device failures"
            )
        active_hyps = self.hypothesis_tracker.get_active()
        for h in active_hyps[:2]:
            evidence.append(f"Active hypothesis: {h.label} (support = {h.support_level:.2f})")
        if device.suspicion_reasons:
            evidence.extend(device.suspicion_reasons[:3])

        recent_ctx = (
            f"Device {device.device_id} [{device.ix},{device.iy}], "
            f"status={device.status.value}, "
            f"suspicion={device.suspicion_level.value}, "
            f"trend={device.trend_state.value}."
        )

        hyp_labels = [h.hypothesis.value for h in active_hyps[:3]]

        alert = self.alert_manager.create_alert(
            run_state=self.run_state,
            device=device,
            severity=severity,
            title=f"[SEV {severity_int}] {decision.reason[:60]}",
            explanation=decision.reason,
            evidence=evidence,
            recent_context=recent_ctx,
            recommended_action=self._recommended_action_text(severity_int),
            hypotheses=hyp_labels,
        )
        self.run_state.record_alert(alert)

        colour = 'red' if severity_int >= 3 else 'yellow'
        console.print(
            f"\n  [bold {colour}]"
            f"[!] ALERT {alert.alert_id} (SEV {severity_int}): {decision.reason[:80]}[/bold {colour}]"
        )

        self.alert_manager.dispatch(alert)

        if severity == AlertSeverity.PAUSE:
            self.run_state.is_paused = True
            self.run_state.pause_reason = decision.reason
            self.backend.pause()

    def _handle_spatial_cluster(self, cluster) -> None:
        """React to a detected spatial cluster of anomalies."""
        note_text = (
            f"**Spatial cluster detected**: {cluster.description}. "
            f"Members: {', '.join(cluster.member_ids[:6])}{'...' if len(cluster.member_ids) > 6 else ''}. "
            f"Region: {cluster.grid_position_label}."
        )
        self._write_global_note(note_text, category="spatial")

        self.hypothesis_tracker.on_spatial_cluster_detected(
            cluster,
            HypothesisEvent(
                "spatial_cluster",
                description=cluster.description,
            ),
        )

        console.print(
            f"\n  [bold yellow][CLUSTER] Spatial cluster: {cluster.description}[/bold yellow]"
        )

    def _apply_skip(self, device: DeviceRecord, decision: PolicyDecision) -> None:
        """Mark a device as skipped and update run state counters."""
        if decision.note:
            self._write_note(device, decision.note, category="device")
        console.print(
            f"  [dim]-> SKIPPED: {decision.reason}[/dim]"
        )
        if device.status == DeviceStatus.UNKNOWN:
            # Determine skip reason
            if device.metrics_history:
                last_m = device.metrics_history[-1]
                device.status = classify_device_health(last_m, self.config.thresholds)
            else:
                device.status = DeviceStatus.SKIPPED

        # Update consecutive failure counter
        if device.status in (
            DeviceStatus.FAILED, DeviceStatus.SHORTED,
            DeviceStatus.CONTACT_ISSUE, DeviceStatus.NEAR_FAILURE,
        ):
            self.run_state.consecutive_failures += 1
            self.run_state.max_consecutive_failures = max(
                self.run_state.max_consecutive_failures,
                self.run_state.consecutive_failures,
            )
            # Hypothesis: consecutive contact failures
            if device.status == DeviceStatus.CONTACT_ISSUE:
                self.hypothesis_tracker.on_consecutive_contact_failures(
                    self.run_state.consecutive_failures,
                    HypothesisEvent(
                        "consecutive_contact_failures",
                        device.device_id,
                        f"{self.run_state.consecutive_failures} consecutive contact failures",
                    ),
                )
        else:
            self.run_state.consecutive_failures = 0

    # -----------------------------------------------------------------------
    # Measurement recording helpers
    # -----------------------------------------------------------------------

    def _record_measurement(
        self, device: DeviceRecord, curve: IVCurve, metrics: IVMetrics
    ) -> None:
        """Append a measurement to the device record and update summary scalars."""
        device.iv_curves.append(curve)
        device.metrics_history.append(metrics)
        device.latest_leakage_at_1v_A = metrics.leakage_at_1v_A
        if metrics.breakdown_voltage_V is not None:
            device.latest_breakdown_voltage_V = metrics.breakdown_voltage_V

    # -----------------------------------------------------------------------
    # Context builders
    # -----------------------------------------------------------------------

    def _build_context(
        self,
        device: DeviceRecord,
        state: AgentState,
        metrics: IVMetrics,
    ) -> PolicyContext:
        """Build a PolicyContext with all available analysis results."""
        tf = self.trend_analyzer.analyse(device.metrics_history)
        nc = self.neighbor_analyzer.compare_to_neighbors(
            device, self.run_state.devices
        )
        status = classify_device_health(metrics, self.config.thresholds)

        sus_ctx = SuspicionContext(
            device=device,
            latest_metrics=metrics,
            run_state=self.run_state,
            trend_features=tf,
            neighbor_comparison=nc,
            control_device_healthy=self.run_state.control_device_healthy,
        )
        sr = self.suspicion_engine.evaluate(sus_ctx)
        device.suspicion_score = sr.score
        device.suspicion_level = sr.level
        device.suspicion_reasons = sr.reasons

        return PolicyContext(
            agent_state=state,
            device=device,
            latest_metrics=metrics,
            latest_status=status,
            trend_features=tf,
            neighbor_comparison=nc,
            suspicion_result=sr,
            run_state=self.run_state,
        )

    # -----------------------------------------------------------------------
    # Notes and logging
    # -----------------------------------------------------------------------

    def _write_note(self, device: DeviceRecord, text: str, category: str) -> None:
        """Create a Note and record it in run state + device record."""
        note = Note(
            note_id=self.run_state.next_note_id(),
            category=category,
            device_id=device.device_id,
            body=text,
        )
        self.run_state.record_note(note)
        device.device_notes.append(text[:120])
        self.storage.append_note(note, self.output_dir)

    def _write_global_note(self, text: str, category: str) -> None:
        note = Note(
            note_id=self.run_state.next_note_id(),
            category=category,
            body=text,
        )
        self.run_state.record_note(note)
        self.storage.append_note(note, self.output_dir)

    def _log_state(self, state: AgentState, device: DeviceRecord) -> None:
        console.print(
            f"  [cyan]State:[/cyan] {state.value}  "
            f"[dim]({device.device_id} | "
            f"suspicion={device.suspicion_level.value} | "
            f"trend={device.trend_state.value})[/dim]"
        )

    def _log_decision(self, device: DeviceRecord, decision: PolicyDecision) -> None:
        colour = {
            AgentAction.SKIP_DEVICE: "red",
            AgentAction.STOP_STRESS: "red",
            AgentAction.ESCALATE_AND_PAUSE: "bold red",
            AgentAction.ESCALATE_AND_CONTINUE: "yellow",
            AgentAction.SWITCH_TO_DENSE_MONITORING: "magenta",
            AgentAction.CHECK_CONTROL_DEVICE: "magenta",
            AgentAction.CONTINUE_STRESS: "green",
            AgentAction.START_STRESS: "green",
            AgentAction.FINISH_DEVICE: "green",
        }.get(decision.action, "white")

        console.print(
            f"  [bold {colour}]-> {decision.action.value}[/bold {colour}]: "
            f"[{colour}]{decision.reason[:100]}[/{colour}]"
        )

    # -----------------------------------------------------------------------
    # Run-level helpers
    # -----------------------------------------------------------------------

    def _update_run_counters(self, device: DeviceRecord) -> None:
        """Update summary counters and consecutive failure streak."""
        status = device.status
        if status == DeviceStatus.HEALTHY:
            self.run_state.n_healthy += 1
            self.run_state.consecutive_failures = 0
        elif status == DeviceStatus.DEGRADING:
            self.run_state.n_degrading += 1
            self.run_state.consecutive_failures = 0
        elif status in (DeviceStatus.FAILED, DeviceStatus.NEAR_FAILURE):
            self.run_state.n_failed += 1
            self.run_state.consecutive_failures += 1
        elif status == DeviceStatus.SHORTED:
            self.run_state.n_shorted += 1
            self.run_state.consecutive_failures += 1
        elif status == DeviceStatus.CONTACT_ISSUE:
            self.run_state.n_contact_issue += 1
            self.run_state.consecutive_failures += 1
        else:
            self.run_state.n_skipped += 1

        self.run_state.max_consecutive_failures = max(
            self.run_state.max_consecutive_failures,
            self.run_state.consecutive_failures,
        )

    def _protocol_for_mode(self, mode: ProtocolMode) -> ProtocolParams:
        p = self.config.protocols
        return {
            ProtocolMode.NORMAL_STRESS: p.stress_batch,
            ProtocolMode.DENSE_MONITORING: p.dense_monitoring,
            ProtocolMode.CONFIRMATORY: p.confirmatory,
            ProtocolMode.LOW_STRESS_RECHECK: p.low_stress_recheck,
            ProtocolMode.CONTROL_CHECK: p.control_check,
        }.get(mode, p.stress_batch)

    def _recommended_action_text(self, severity: int) -> str:
        texts = {
            1: "No immediate action required. Monitor progress.",
            2: "Review end-of-run summary. Consider adjusting thresholds.",
            3: "Inspect recent measurement traces. Verify probe contact quality.",
            4: "Pause experiment. Inspect probe tip, check instrument connections, "
               "and verify probe station calibration before resuming.",
        }
        return texts.get(severity, "Review experiment log.")

    def _handle_control_device_result(
        self, device: DeviceRecord, metrics: IVMetrics
    ) -> None:
        """Record the result of a scheduled (in-sequence) control device measurement."""
        status = classify_device_health(metrics, self.config.thresholds)
        device.status = status
        if device.baseline_leakage_at_1v_A is None:
            device.baseline_leakage_at_1v_A = metrics.leakage_at_1v_A
        self.run_state.control_device_healthy = status in (
            DeviceStatus.HEALTHY, DeviceStatus.DEGRADING
        )
        self._write_note(
            device,
            f"**Scheduled control device measurement.** "
            f"Status: {status.value}. I(1V) = {metrics.leakage_at_1v_A:.2e} A.",
            category="device",
        )

    # -----------------------------------------------------------------------
    # Final reports
    # -----------------------------------------------------------------------

    def _generate_final_reports(self) -> None:
        """Generate all output files at the end of the run."""
        console.print("\n[bold cyan]Generating reports...[/bold cyan]")

        from ..reporting.chip_map import ChipMapGenerator
        from ..reporting.summary import SummaryWriter
        from ..reporting.plots import PlotGenerator

        # Save run state
        self.storage.save_run_state(self.run_state, self.output_dir)
        self.storage.save_devices(self.run_state, self.output_dir)
        self.storage.save_alerts(self.run_state, self.output_dir)
        self.storage.save_hypotheses(self.run_state, self.output_dir)

        # Chip map
        chip_map = ChipMapGenerator(self.config)
        chip_map.save_csv(self.run_state, self.output_dir)

        # Plots
        plotter = PlotGenerator(self.config)
        plotter.plot_chip_heatmaps(self.run_state, self.output_dir)
        plotter.plot_device_iv_curves(self.run_state, self.output_dir)
        plotter.plot_degradation_trends(self.run_state, self.output_dir)

        # Summary
        writer = SummaryWriter(self.config)
        writer.save_summary(self.run_state, self.output_dir)

        console.print(
            Panel(
                self._format_final_summary(),
                title="Run Complete",
                border_style="green",
            )
        )

    def _format_final_summary(self) -> str:
        rs = self.run_state
        duration = ""
        if rs.start_time and rs.end_time:
            secs = (rs.end_time - rs.start_time).total_seconds()
            duration = f"{secs:.0f}s"
        active_hyps = self.hypothesis_tracker.get_active()
        hyp_str = ", ".join(h.label for h in active_hyps[:3]) or "None"
        return (
            f"Chip: {rs.chip_id}  Run: {rs.run_id}  Duration: {duration}\n"
            f"Devices: {rs.n_devices_done}/{rs.n_devices_total} done | "
            f"Healthy: {rs.n_healthy} | Degrading: {rs.n_degrading} | "
            f"Failed: {rs.n_failed} | Shorted: {rs.n_shorted} | "
            f"Contact: {rs.n_contact_issue}\n"
            f"Alerts: {len(rs.alerts)} | Notes: {len(rs.notes)}\n"
            f"Active hypotheses: {hyp_str}\n"
            f"Output: {self.output_dir}"
        )
