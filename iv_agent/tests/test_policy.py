"""
Unit tests for the policy engine.

Tests verify that the correct action is returned for each combination of
device status, trend, and suspicion level.  The policy engine is a pure
function so these tests are deterministic and require no file I/O.
"""
from __future__ import annotations

import pytest

from ..config.schema import AgentConfig, ThresholdConfig
from ..models.device import (
    DeviceRecord, DeviceStatus, GridPosition, ProtocolMode,
    SuspicionLevel, TrendState,
)
from ..models.measurement import IVMetrics, MeasurementStatus
from ..models.run_state import RunState
from ..analysis.suspicion import SuspicionResult
from ..policy.engine import PolicyEngine
from ..policy.states import AgentAction, AgentState, PolicyContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_config(tmp_path) -> AgentConfig:
    """Minimal valid config for policy engine tests (simulation mode)."""
    cfg_path = tmp_path / "test.yaml"
    cfg_path.write_text("""
run:
  chip_id: TEST_CHIP
  run_id: RUN_TEST
  output_dir: /tmp/test_output

grid:
  nx: 3
  ny: 3
  x_spacing_um: 100
  y_spacing_um: 100
""")
    return AgentConfig.from_yaml(cfg_path)


@pytest.fixture
def engine(minimal_config) -> PolicyEngine:
    return PolicyEngine(minimal_config)


def _make_device(
    status: DeviceStatus = DeviceStatus.HEALTHY,
    trend: TrendState = TrendState.STABLE,
    suspicion: SuspicionLevel = SuspicionLevel.NONE,
    confirmatory_count: int = 0,
    inconsistent_confirmatory: int = 0,
) -> DeviceRecord:
    dev = DeviceRecord(
        device_id="TEST_00_00",
        ix=0, iy=0,
        grid_position=GridPosition.CORNER,
    )
    dev.status = status
    dev.trend_state = trend
    dev.suspicion_level = suspicion
    dev.confirmatory_count = confirmatory_count
    dev.inconsistent_confirmatory_count = inconsistent_confirmatory
    return dev


def _make_metrics(
    leakage_1v: float = 1e-12,
    is_shorted: bool = False,
    is_open: bool = False,
    compliance_hit: bool = False,
    breakdown_v: float | None = None,
    status: MeasurementStatus = MeasurementStatus.VALID,
) -> IVMetrics:
    return IVMetrics(
        device_id="TEST_00_00",
        protocol_name="health_check",
        measurement_status=status,
        leakage_at_1v_A=leakage_1v,
        leakage_at_vmax_A=leakage_1v * 10,
        estimated_resistance_ohm=1.0 / leakage_1v if leakage_1v > 0 else 1e15,
        is_shorted=is_shorted,
        is_open_circuit=is_open,
        compliance_hit=compliance_hit,
        breakdown_voltage_V=breakdown_v,
        looks_healthy=(leakage_1v < 5e-10 and not is_shorted and not is_open),
        looks_degraded=(5e-10 <= leakage_1v <= 1e-7),
        looks_failed=(leakage_1v > 1e-7 or is_shorted),
    )


def _make_run_state(consecutive_failures: int = 0) -> RunState:
    rs = RunState(chip_id="TEST_CHIP", run_id="RUN_TEST")
    rs.consecutive_failures = consecutive_failures
    rs.n_healthy = max(0, 5 - consecutive_failures)
    rs.n_devices_done = 5
    return rs


# ---------------------------------------------------------------------------
# Health-check decision tests
# ---------------------------------------------------------------------------

class TestHealthCheckDecisions:

    def test_shorted_device_is_skipped(self, engine):
        dev = _make_device(status=DeviceStatus.SHORTED)
        metrics = _make_metrics(leakage_1v=1e-1, is_shorted=True)
        ctx = PolicyContext(
            agent_state=AgentState.MEASURING_INITIAL_HEALTH,
            device=dev,
            latest_metrics=metrics,
            latest_status=DeviceStatus.SHORTED,
            run_state=_make_run_state(),
        )
        decision = engine.decide(ctx)
        assert decision.action == AgentAction.SKIP_DEVICE

    def test_healthy_device_starts_stress(self, engine):
        dev = _make_device(status=DeviceStatus.HEALTHY)
        metrics = _make_metrics(leakage_1v=1e-12)
        ctx = PolicyContext(
            agent_state=AgentState.MEASURING_INITIAL_HEALTH,
            device=dev,
            latest_metrics=metrics,
            latest_status=DeviceStatus.HEALTHY,
            run_state=_make_run_state(),
        )
        decision = engine.decide(ctx)
        assert decision.action == AgentAction.START_STRESS

    def test_contact_issue_triggers_retry(self, engine):
        dev = _make_device(status=DeviceStatus.CONTACT_ISSUE)
        metrics = _make_metrics(leakage_1v=0.0, is_open=True)
        ctx = PolicyContext(
            agent_state=AgentState.MEASURING_INITIAL_HEALTH,
            device=dev,
            latest_metrics=metrics,
            latest_status=DeviceStatus.CONTACT_ISSUE,
            run_state=_make_run_state(),
        )
        decision = engine.decide(ctx)
        assert decision.action == AgentAction.REPEAT_MEASUREMENT

    def test_contact_issue_after_retry_skips(self, engine):
        dev = _make_device(status=DeviceStatus.CONTACT_ISSUE, confirmatory_count=1)
        metrics = _make_metrics(leakage_1v=0.0, is_open=True)
        ctx = PolicyContext(
            agent_state=AgentState.MEASURING_INITIAL_HEALTH,
            device=dev,
            latest_metrics=metrics,
            latest_status=DeviceStatus.CONTACT_ISSUE,
            run_state=_make_run_state(),
        )
        decision = engine.decide(ctx)
        assert decision.action == AgentAction.SKIP_DEVICE

    def test_failed_at_health_check_is_skipped(self, engine):
        dev = _make_device(status=DeviceStatus.FAILED)
        metrics = _make_metrics(leakage_1v=1e-5)  # way above threshold
        ctx = PolicyContext(
            agent_state=AgentState.MEASURING_INITIAL_HEALTH,
            device=dev,
            latest_metrics=metrics,
            latest_status=DeviceStatus.FAILED,
            run_state=_make_run_state(),
        )
        decision = engine.decide(ctx)
        assert decision.action == AgentAction.SKIP_DEVICE


# ---------------------------------------------------------------------------
# Stress decision tests
# ---------------------------------------------------------------------------

class TestStressDecisions:

    def test_continue_stress_when_all_ok(self, engine):
        dev = _make_device(status=DeviceStatus.HEALTHY, trend=TrendState.STABLE)
        metrics = _make_metrics(leakage_1v=2e-12)
        from ..analysis.trends import TrendFeatures
        tf = TrendFeatures(n_measurements=3, trend_state=TrendState.STABLE, worsening_rate=0.05)
        sr = SuspicionResult(device_id="TEST", score=0.0, level=SuspicionLevel.NONE)
        ctx = PolicyContext(
            agent_state=AgentState.STRESSING_DEVICE,
            device=dev,
            latest_metrics=metrics,
            latest_status=DeviceStatus.HEALTHY,
            trend_features=tf,
            suspicion_result=sr,
            run_state=_make_run_state(),
            stress_batch_index=2,
            max_stress_batches=10,
        )
        decision = engine.decide(ctx)
        assert decision.action == AgentAction.CONTINUE_STRESS

    def test_breakdown_during_stress_stops(self, engine):
        dev = _make_device(status=DeviceStatus.FAILED)
        metrics = _make_metrics(
            leakage_1v=1e-4, compliance_hit=True, breakdown_v=3.0
        )
        from ..analysis.trends import TrendFeatures
        tf = TrendFeatures(n_measurements=5, trend_state=TrendState.NEAR_BREAKDOWN,
                           worsening_rate=0.8, fraction_compliance_hit=0.8)
        sr = SuspicionResult(device_id="TEST", score=0.7, level=SuspicionLevel.HIGH)
        ctx = PolicyContext(
            agent_state=AgentState.STRESSING_DEVICE,
            device=dev,
            latest_metrics=metrics,
            latest_status=DeviceStatus.FAILED,
            trend_features=tf,
            suspicion_result=sr,
            run_state=_make_run_state(),
            stress_batch_index=3,
        )
        decision = engine.decide(ctx)
        assert decision.action in (AgentAction.STOP_STRESS, AgentAction.SWITCH_TO_DENSE_MONITORING)

    def test_max_batches_finishes_device(self, engine):
        dev = _make_device(status=DeviceStatus.HEALTHY, trend=TrendState.STABLE)
        metrics = _make_metrics(leakage_1v=1e-12)
        from ..analysis.trends import TrendFeatures
        tf = TrendFeatures(n_measurements=10, trend_state=TrendState.STABLE, worsening_rate=0.05)
        sr = SuspicionResult(device_id="TEST", score=0.0, level=SuspicionLevel.NONE)
        ctx = PolicyContext(
            agent_state=AgentState.STRESSING_DEVICE,
            device=dev,
            latest_metrics=metrics,
            latest_status=DeviceStatus.HEALTHY,
            trend_features=tf,
            suspicion_result=sr,
            run_state=_make_run_state(),
            stress_batch_index=9,  # last batch (0-indexed, max=10)
            max_stress_batches=10,
        )
        decision = engine.decide(ctx)
        assert decision.action == AgentAction.FINISH_DEVICE

    def test_rapid_degradation_triggers_dense_monitoring(self, engine):
        dev = _make_device(status=DeviceStatus.DEGRADING, trend=TrendState.RAPIDLY_WORSENING)
        metrics = _make_metrics(leakage_1v=5e-8)
        from ..analysis.trends import TrendFeatures
        tf = TrendFeatures(
            n_measurements=5,
            trend_state=TrendState.RAPIDLY_WORSENING,
            worsening_rate=0.7,
            leakage_trend_slope=0.5,
        )
        sr = SuspicionResult(
            device_id="TEST", score=0.55, level=SuspicionLevel.MEDIUM,
            recommended_actions=["switch_to_dense_monitoring"],
        )
        ctx = PolicyContext(
            agent_state=AgentState.STRESSING_DEVICE,
            device=dev,
            latest_metrics=metrics,
            latest_status=DeviceStatus.DEGRADING,
            trend_features=tf,
            suspicion_result=sr,
            run_state=_make_run_state(),
            stress_batch_index=4,
            neighbors_inspected=True,  # skip the inspect step
        )
        decision = engine.decide(ctx)
        assert decision.action in (
            AgentAction.SWITCH_TO_DENSE_MONITORING,
            AgentAction.INSPECT_NEIGHBORS,
            AgentAction.CHECK_CONTROL_DEVICE,
        )


# ---------------------------------------------------------------------------
# Control device check tests
# ---------------------------------------------------------------------------

class TestControlDeviceDecisions:

    def test_healthy_control_resumes_stress(self, engine):
        dev = _make_device()
        rs = _make_run_state()
        rs.control_device_healthy = True
        ctx = PolicyContext(
            agent_state=AgentState.CHECKING_CONTROL_DEVICE,
            device=dev,
            run_state=rs,
        )
        decision = engine.decide(ctx)
        assert decision.action == AgentAction.CONTINUE_STRESS

    def test_degraded_control_triggers_escalation(self, engine):
        dev = _make_device()
        rs = _make_run_state()
        rs.control_device_healthy = False
        rs.consecutive_failures = 3
        ctx = PolicyContext(
            agent_state=AgentState.CHECKING_CONTROL_DEVICE,
            device=dev,
            run_state=rs,
        )
        decision = engine.decide(ctx)
        assert decision.action in (
            AgentAction.ESCALATE_AND_CONTINUE,
            AgentAction.ESCALATE_AND_PAUSE,
        )
