"""
Simulated instrument backend.

Generates synthetic I-V curves for a population of capacitor devices with
varied, physically-motivated failure modes.  The simulation is deterministic
given a fixed seed and is designed to trigger all of the agent's agentic
decision pathways.

Physical model (simplified Poole-Frenkel / trap-assisted tunneling):
    I_leak(V) = I0 * exp(V / V_char)

Breakdown: when I_leak > compliance OR V >= V_bd

Degradation under stress:
    I0_eff = I0 * exp(degradation_rate_i0 * N_stress_cycles)
    V_bd_eff = V_bd * exp(-degradation_rate_vbd * N_stress_cycles)
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import numpy as np

from ..config.schema import AgentConfig, ProtocolParams
from ..models.measurement import IVCurve, MeasurementStatus, StressBatch
from .base import InstrumentBackend


# ---------------------------------------------------------------------------
# Simulated device types
# ---------------------------------------------------------------------------

class SimDeviceType(str, Enum):
    HEALTHY_STABLE = "healthy_stable"
    SLOWLY_DEGRADING = "slowly_degrading"
    ABRUPT_BREAKDOWN = "abrupt_breakdown"
    PRE_SHORTED = "pre_shorted"
    INTERMITTENT_CONTACT = "intermittent_contact"
    CORNER_WEAK = "corner_weak"
    CONTROL_DEVICE = "control_device"


# Default electrical parameters per device type
_TYPE_DEFAULTS: dict[SimDeviceType, dict] = {
    SimDeviceType.HEALTHY_STABLE: dict(
        I0=1.0e-12, V_char=3.0, V_bd=16.0,
        deg_rate_i0=0.01, deg_rate_vbd=0.003,
        noise_rel=0.05, noise_floor=1.0e-14,
    ),
    SimDeviceType.SLOWLY_DEGRADING: dict(
        I0=3.0e-12, V_char=2.8, V_bd=13.0,
        deg_rate_i0=0.12, deg_rate_vbd=0.018,
        noise_rel=0.08, noise_floor=1.0e-14,
    ),
    SimDeviceType.ABRUPT_BREAKDOWN: dict(
        I0=5.0e-12, V_char=2.5, V_bd=10.5,
        deg_rate_i0=0.08, deg_rate_vbd=0.045,
        noise_rel=0.06, noise_floor=1.0e-14,
    ),
    SimDeviceType.PRE_SHORTED: dict(
        I0=0.0, V_char=1.0, V_bd=0.0,
        R_short=800.0,   # Ω
        deg_rate_i0=0.0, deg_rate_vbd=0.0,
        noise_rel=0.02, noise_floor=1.0e-14,
    ),
    SimDeviceType.INTERMITTENT_CONTACT: dict(
        I0=1.5e-12, V_char=3.0, V_bd=14.0,
        contact_fail_prob=0.65,
        R_contact_bad=5.0e7,  # Ω when contact fails
        deg_rate_i0=0.01, deg_rate_vbd=0.004,
        noise_rel=0.05, noise_floor=1.0e-14,
    ),
    SimDeviceType.CORNER_WEAK: dict(
        I0=8.0e-12, V_char=2.6, V_bd=9.5,
        deg_rate_i0=0.10, deg_rate_vbd=0.030,
        noise_rel=0.10, noise_floor=1.0e-14,
    ),
    SimDeviceType.CONTROL_DEVICE: dict(
        I0=0.8e-12, V_char=3.2, V_bd=18.0,
        deg_rate_i0=0.002, deg_rate_vbd=0.001,
        noise_rel=0.04, noise_floor=1.0e-14,
    ),
}


@dataclass
class SimDeviceParams:
    """True (hidden) parameters of a simulated device."""
    device_id: str
    device_type: SimDeviceType
    I0: float = 1.0e-12
    V_char: float = 3.0
    V_bd: float = 16.0
    deg_rate_i0: float = 0.01
    deg_rate_vbd: float = 0.003
    R_short: Optional[float] = None
    contact_fail_prob: float = 0.0
    R_contact_bad: float = 5.0e7
    noise_rel: float = 0.05
    noise_floor: float = 1.0e-14
    stress_cycles: int = 0        # accumulated by simulator calls

    # Extra variability per device
    i0_scatter: float = 1.0       # multiplicative scatter factor (set at init)
    vbd_scatter: float = 1.0

    @classmethod
    def from_type(
        cls,
        device_id: str,
        device_type: SimDeviceType,
        rng: np.random.Generator,
    ) -> "SimDeviceParams":
        defaults = dict(_TYPE_DEFAULTS[device_type])
        R_short = defaults.pop("R_short", None)
        contact_fail_prob = defaults.pop("contact_fail_prob", 0.0)
        R_contact_bad = defaults.pop("R_contact_bad", 5.0e7)

        # Per-device scatter: ±30% on I0, ±10% on V_bd
        i0_scatter = float(rng.lognormal(0, 0.25))
        vbd_scatter = float(rng.uniform(0.92, 1.08))

        return cls(
            device_id=device_id,
            device_type=device_type,
            R_short=R_short,
            contact_fail_prob=contact_fail_prob,
            R_contact_bad=R_contact_bad,
            i0_scatter=i0_scatter,
            vbd_scatter=vbd_scatter,
            **defaults,
        )


# ---------------------------------------------------------------------------
# Core I-V simulation function
# ---------------------------------------------------------------------------

def _simulate_iv_curve(
    params: SimDeviceParams,
    voltages: np.ndarray,
    compliance_A: float,
    rng: np.random.Generator,
    extra_noise_factor: float = 1.0,
) -> tuple[np.ndarray, bool, Optional[int]]:
    """
    Generate a synthetic current array for a given voltage sweep.

    Returns (currents, compliance_hit, compliance_hit_index).
    """
    n = len(voltages)
    currents = np.zeros(n)
    compliance_hit = False
    compliance_hit_index: Optional[int] = None

    # --- Pre-shorted device ---
    if params.R_short is not None:
        for k, v in enumerate(voltages):
            noise = rng.normal(0, max(params.noise_floor, abs(v / params.R_short) * params.noise_rel))
            I = v / params.R_short + noise
            currents[k] = I
            if abs(I) >= compliance_A and not compliance_hit:
                compliance_hit = True
                compliance_hit_index = k
        return currents, compliance_hit, compliance_hit_index

    # --- Contact failure ---
    contact_failed = (
        params.contact_fail_prob > 0
        and rng.random() < params.contact_fail_prob
    )
    if contact_failed:
        # Probe not making contact — current is noise floor level only
        for k, v in enumerate(voltages):
            currents[k] = rng.normal(0, params.noise_floor * 10)
        return currents, False, None

    # --- Normal dielectric / degraded device ---
    # Effective parameters after accumulated stress
    I0_eff = (
        params.I0
        * params.i0_scatter
        * np.exp(params.deg_rate_i0 * params.stress_cycles)
    )
    V_bd_eff = (
        params.V_bd
        * params.vbd_scatter
        * np.exp(-params.deg_rate_vbd * params.stress_cycles)
    )

    for k, v in enumerate(voltages):
        if v <= 0:
            I_leak = params.noise_floor
        elif v >= V_bd_eff:
            # Post-breakdown: current jumps to compliance (hard breakdown model)
            I_leak = compliance_A * 1.05  # just above compliance
        else:
            I_leak = I0_eff * np.exp(v / params.V_char)

        # Add noise: relative noise + absolute noise floor
        sigma = max(params.noise_floor, abs(I_leak) * params.noise_rel * extra_noise_factor)
        I_meas = I_leak + rng.normal(0, sigma)
        I_meas = max(0.0, I_meas)  # currents are non-negative in this model

        currents[k] = I_meas

        if I_meas >= compliance_A and not compliance_hit:
            compliance_hit = True
            compliance_hit_index = k
            # Clamp remaining points at compliance
            for j in range(k, n):
                currents[j] = compliance_A
            break

    return currents, compliance_hit, compliance_hit_index


# ---------------------------------------------------------------------------
# Simulated backend
# ---------------------------------------------------------------------------

class SimulatedBackend(InstrumentBackend):
    """
    Full simulated instrument backend.

    Assigns a hidden device type to every grid position at construction time,
    then generates synthetic I-V curves on demand.
    """

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        sim_cfg = config.instruments.simulation
        self._rng = np.random.default_rng(sim_cfg.seed)
        self._py_rng = random.Random(sim_cfg.seed)

        self._current_ix: int = config.grid.starting_device[0]
        self._current_iy: int = config.grid.starting_device[1]
        self._is_connected = False
        self._devices_contacted: int = 0  # for probe-tip degradation model

        # Global noise burst (simulates sudden setup drift)
        self._global_noise_factor: float = 1.0

        # Build device parameter map keyed by device_id
        self._device_params: dict[str, SimDeviceParams] = {}
        self._init_device_population()

    # --- Lifecycle ---

    def connect(self) -> None:
        self._is_connected = True

    def disconnect(self) -> None:
        self._is_connected = False

    def pause(self) -> None:
        pass  # No-op in simulation

    def resume(self) -> None:
        pass

    # --- Motion ---

    def move_to_grid_position(self, ix: int, iy: int) -> None:
        self._current_ix = ix
        self._current_iy = iy
        self._devices_contacted += 1
        # Optionally apply probe-tip degradation after many contacts
        sim_cfg = self.config.instruments.simulation
        if self._devices_contacted >= sim_cfg.probe_degradation_after_n_devices:
            # Probe tip is worn — add extra noise to all measurements
            self._global_noise_factor = 2.5

    def get_current_position(self) -> tuple[int, int]:
        return (self._current_ix, self._current_iy)

    # --- Measurement ---

    def run_iv_sweep(
        self,
        device_id: str,
        protocol: ProtocolParams,
        sweep_index: int = 0,
    ) -> IVCurve:
        params = self._get_params(device_id)
        voltages = np.arange(
            protocol.v_start, protocol.v_stop + protocol.v_step / 2, protocol.v_step
        )

        # Occasional global noise burst
        sim_cfg = self.config.instruments.simulation
        noise_burst = (
            self._py_rng.random() < sim_cfg.noise_burst_probability
        )
        local_noise = self._global_noise_factor * (3.0 if noise_burst else 1.0)

        currents, compliance_hit, compliance_idx = _simulate_iv_curve(
            params, voltages, protocol.compliance_current_A, self._rng, local_noise
        )

        return IVCurve(
            device_id=device_id,
            protocol_name=self._guess_protocol_name(protocol),
            sweep_index=sweep_index,
            voltages_V=voltages.tolist(),
            currents_A=currents.tolist(),
            compliance_hit=compliance_hit,
            compliance_hit_at_index=compliance_idx,
            timestamp=datetime.now(),
        )

    def run_stress_batch(
        self,
        device_id: str,
        protocol: ProtocolParams,
        batch_index: int,
    ) -> StressBatch:
        params = self._get_params(device_id)
        batch = StressBatch(
            device_id=device_id,
            batch_index=batch_index,
            protocol_name=self._guess_protocol_name(protocol),
        )

        from ..analysis.features import extract_iv_metrics
        from ..config.schema import ThresholdConfig
        thresholds = self.config.thresholds

        for cycle in range(protocol.n_cycles):
            curve = self.run_iv_sweep(device_id, protocol, sweep_index=cycle)
            metrics = extract_iv_metrics(curve, thresholds)
            batch.curves.append(curve)
            batch.metrics.append(metrics)
            # Apply one stress cycle worth of degradation after each sweep
            params.stress_cycles += 1

        batch.finalise()
        return batch

    # --- Internal helpers ---

    def _get_params(self, device_id: str) -> SimDeviceParams:
        if device_id not in self._device_params:
            # Unknown device — return a default healthy device
            return SimDeviceParams(
                device_id=device_id,
                device_type=SimDeviceType.HEALTHY_STABLE,
            )
        return self._device_params[device_id]

    @staticmethod
    def _guess_protocol_name(protocol: ProtocolParams) -> str:
        if protocol.v_stop <= 6.0:
            return "health_check"
        if protocol.v_stop <= 9.0:
            return "dense_monitoring"
        return "stress_batch"

    def _init_device_population(self) -> None:
        """Assign device types to all grid positions."""
        cfg = self.config
        sim_cfg = cfg.instruments.simulation
        grid = cfg.grid
        naming = cfg.device_naming

        # Build coordinate → device_type map
        overrides: dict[str, SimDeviceType] = {}
        for dev_id_str, type_str in sim_cfg.device_type_overrides.items():
            try:
                overrides[dev_id_str] = SimDeviceType(type_str)
            except ValueError:
                pass

        for iy in range(grid.ny):
            for ix in range(grid.nx):
                dev_id = naming.format_id(iy, ix)
                is_control = cfg.is_control_device(ix, iy)

                # Determine device type
                if dev_id in overrides:
                    dtype = overrides[dev_id]
                elif is_control:
                    dtype = SimDeviceType.CONTROL_DEVICE
                else:
                    dtype = self._sample_device_type(ix, iy, grid.nx, grid.ny, sim_cfg)

                self._device_params[dev_id] = SimDeviceParams.from_type(
                    dev_id, dtype, self._rng
                )

    def _sample_device_type(
        self, ix: int, iy: int, nx: int, ny: int, sim_cfg
    ) -> SimDeviceType:
        """Sample a device type, biasing corners/edges toward corner_weak."""
        is_corner = (ix in (0, nx - 1)) and (iy in (0, ny - 1))
        is_edge = (ix == 0 or ix == nx - 1 or iy == 0 or iy == ny - 1) and not is_corner

        if is_corner and self._py_rng.random() < 0.55:
            return SimDeviceType.CORNER_WEAK
        if is_edge and self._py_rng.random() < 0.25:
            return SimDeviceType.CORNER_WEAK

        weights = [
            sim_cfg.p_healthy,
            sim_cfg.p_slowly_degrading,
            sim_cfg.p_abrupt_breakdown,
            sim_cfg.p_pre_shorted,
            sim_cfg.p_intermittent_contact,
            sim_cfg.p_corner_weak,
        ]
        types = [
            SimDeviceType.HEALTHY_STABLE,
            SimDeviceType.SLOWLY_DEGRADING,
            SimDeviceType.ABRUPT_BREAKDOWN,
            SimDeviceType.PRE_SHORTED,
            SimDeviceType.INTERMITTENT_CONTACT,
            SimDeviceType.CORNER_WEAK,
        ]
        return self._py_rng.choices(types, weights=weights, k=1)[0]

    def get_device_true_type(self, device_id: str) -> str:
        """Expose true device type (for evaluation/testing only)."""
        p = self._device_params.get(device_id)
        return p.device_type.value if p else "unknown"
