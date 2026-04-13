"""
Integration-level tests for the simulation backend.

Verifies that the simulator produces physically reasonable I-V data,
that different device types produce distinguishable signatures,
and that stress degradation is correctly modelled.
"""
from __future__ import annotations

import pytest
import numpy as np

from ..config.schema import AgentConfig, ThresholdConfig
from ..instruments.simulator import SimulatedBackend, SimDeviceType
from ..analysis.features import extract_iv_metrics


@pytest.fixture
def small_config(tmp_path) -> AgentConfig:
    cfg_path = tmp_path / "test.yaml"
    cfg_path.write_text("""
run:
  chip_id: SIM_TEST
  run_id: RUN_SIM
  output_dir: /tmp/sim_test_output

grid:
  nx: 3
  ny: 3
  x_spacing_um: 100
  y_spacing_um: 100

control_devices:
  - [1, 1]

instruments:
  simulate: true
  simulation:
    seed: 42
    device_type_overrides:
      CAP_00_00: healthy_stable
      CAP_00_01: pre_shorted
      CAP_00_02: intermittent_contact
      CAP_01_00: slowly_degrading
      CAP_01_01: control_device
      CAP_01_02: abrupt_breakdown
      CAP_02_00: corner_weak
""")
    return AgentConfig.from_yaml(cfg_path)


@pytest.fixture
def backend(small_config) -> SimulatedBackend:
    b = SimulatedBackend(small_config)
    b.connect()
    return b


@pytest.fixture
def thresholds() -> ThresholdConfig:
    return ThresholdConfig()


class TestSimulatorBasics:

    def test_connect_and_get_position(self, backend, small_config):
        ix, iy = backend.get_current_position()
        assert ix == small_config.grid.starting_device[0]
        assert iy == small_config.grid.starting_device[1]

    def test_move_updates_position(self, backend):
        backend.move_to_grid_position(2, 1)
        ix, iy = backend.get_current_position()
        assert ix == 2 and iy == 1

    def test_iv_sweep_returns_correct_shape(self, backend, small_config):
        from ..config.schema import ProtocolParams
        protocol = ProtocolParams(v_start=0.0, v_stop=5.0, v_step=0.5)
        curve = backend.run_iv_sweep("CAP_00_00", protocol)
        assert len(curve.voltages_V) == len(curve.currents_A)
        assert len(curve.voltages_V) == 11  # 0, 0.5, ..., 5.0
        assert curve.voltages_V[0] == pytest.approx(0.0)
        assert curve.voltages_V[-1] == pytest.approx(5.0)

    def test_currents_are_non_negative(self, backend, small_config):
        from ..config.schema import ProtocolParams
        protocol = ProtocolParams(v_start=0.0, v_stop=5.0, v_step=0.5)
        curve = backend.run_iv_sweep("CAP_00_00", protocol)
        assert all(i >= 0 for i in curve.currents_A)


class TestDeviceTypeDifferentiation:

    def test_healthy_device_low_leakage(self, backend, thresholds):
        from ..config.schema import ProtocolParams
        protocol = ProtocolParams(v_start=0.0, v_stop=5.0, v_step=0.5)
        curve = backend.run_iv_sweep("CAP_00_00", protocol)
        metrics = extract_iv_metrics(curve, thresholds)
        assert metrics.leakage_at_1v_A < thresholds.max_leakage_healthy_A, (
            f"Healthy device leakage too high: {metrics.leakage_at_1v_A:.2e}"
        )
        assert not metrics.is_shorted
        assert not metrics.is_open_circuit

    def test_shorted_device_detected(self, backend, thresholds):
        from ..config.schema import ProtocolParams
        protocol = ProtocolParams(v_start=0.0, v_stop=5.0, v_step=0.5, compliance_current_A=1e-3)
        curve = backend.run_iv_sweep("CAP_00_01", protocol)  # pre_shorted
        metrics = extract_iv_metrics(curve, thresholds)
        assert metrics.is_shorted, (
            f"Pre-shorted device not detected. R_est = {metrics.estimated_resistance_ohm:.2e}"
        )

    def test_control_device_stays_healthy(self, backend, thresholds):
        from ..config.schema import ProtocolParams
        protocol = ProtocolParams(v_start=0.0, v_stop=5.0, v_step=0.5)
        # Measure control device after many stress cycles on other devices
        for _ in range(5):
            backend.run_stress_batch(
                "CAP_01_00",
                ProtocolParams(v_start=0.0, v_stop=12.0, v_step=0.5, n_cycles=5),
                batch_index=_,
            )
        curve = backend.run_iv_sweep("CAP_01_01", protocol)  # control_device
        metrics = extract_iv_metrics(curve, thresholds)
        assert not metrics.is_shorted
        assert metrics.leakage_at_1v_A < thresholds.max_leakage_degraded_A

    def test_slowly_degrading_leakage_increases(self, backend, thresholds):
        """Leakage should increase after stress cycles for a degrading device."""
        from ..config.schema import ProtocolParams
        health_protocol = ProtocolParams(v_start=0.0, v_stop=5.0, v_step=0.5)
        stress_protocol = ProtocolParams(v_start=0.0, v_stop=12.0, v_step=0.5, n_cycles=5)

        # Measure before stress
        curve_before = backend.run_iv_sweep("CAP_01_00", health_protocol)
        metrics_before = extract_iv_metrics(curve_before, thresholds)

        # Apply many stress cycles
        for i in range(8):
            backend.run_stress_batch("CAP_01_00", stress_protocol, batch_index=i)

        # Measure after stress
        curve_after = backend.run_iv_sweep("CAP_01_00", health_protocol)
        metrics_after = extract_iv_metrics(curve_after, thresholds)

        assert metrics_after.leakage_at_1v_A >= metrics_before.leakage_at_1v_A, (
            f"Leakage should not decrease after stress: "
            f"before={metrics_before.leakage_at_1v_A:.2e}, "
            f"after={metrics_after.leakage_at_1v_A:.2e}"
        )

    def test_stress_batch_applies_degradation(self, backend, thresholds):
        """Running a stress batch should increase device stress_cycles counter."""
        from ..config.schema import ProtocolParams
        stress_protocol = ProtocolParams(v_start=0.0, v_stop=12.0, v_step=0.5, n_cycles=3)
        params_before = backend._device_params.get("CAP_01_00")
        cycles_before = params_before.stress_cycles if params_before else 0

        backend.run_stress_batch("CAP_01_00", stress_protocol, batch_index=0)

        params_after = backend._device_params.get("CAP_01_00")
        cycles_after = params_after.stress_cycles if params_after else 0
        assert cycles_after == cycles_before + 3
