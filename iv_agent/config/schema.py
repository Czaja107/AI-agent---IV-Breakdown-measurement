"""
Pydantic v2 configuration schema for the IV-agent experiment manager.

All user-configurable parameters are defined here and loaded from YAML.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, model_validator
import yaml


# ---------------------------------------------------------------------------
# Sub-configs
# ---------------------------------------------------------------------------

class GridConfig(BaseModel):
    """Defines the XY grid of capacitor devices on the chip."""
    nx: int = Field(ge=1, description="Number of columns (X direction)")
    ny: int = Field(ge=1, description="Number of rows (Y direction)")
    x_spacing_um: float = Field(gt=0, description="Column pitch in micrometres")
    y_spacing_um: float = Field(gt=0, description="Row pitch in micrometres")
    starting_device: list[int] = Field(
        default=[0, 0],
        description="[ix, iy] index of the device where probes are first landed manually",
    )
    row_major: bool = Field(
        default=True,
        description="If True, traverse row by row (row-major order)",
    )

    @model_validator(mode="after")
    def _validate_starting_device(self) -> "GridConfig":
        ix, iy = self.starting_device
        if ix < 0 or ix >= self.nx or iy < 0 or iy >= self.ny:
            raise ValueError(
                f"starting_device {self.starting_device} is outside grid "
                f"({self.nx}x{self.ny})"
            )
        return self

    @property
    def n_devices(self) -> int:
        return self.nx * self.ny

    def device_sequence(self) -> list[tuple[int, int]]:
        """Return ordered (ix, iy) pairs in traversal order."""
        if self.row_major:
            return [(ix, iy) for iy in range(self.ny) for ix in range(self.nx)]
        else:
            return [(ix, iy) for ix in range(self.nx) for iy in range(self.ny)]


class DeviceNamingConfig(BaseModel):
    """Controls how device IDs are generated from grid coordinates."""
    prefix: str = "CAP"
    scheme: str = Field(
        default="row_col",
        description="'row_col' → CAP_iy_ix | 'sequential' → CAP_N",
    )

    def format_id(self, iy: int, ix: int) -> str:
        if self.scheme == "row_col":
            return f"{self.prefix}_{iy:02d}_{ix:02d}"
        seq = iy * 1000 + ix
        return f"{self.prefix}_{seq:04d}"


class SimulationConfig(BaseModel):
    """Parameters that govern the built-in simulation backend."""
    seed: int = 42
    # Per-device type prior probabilities for random assignment
    p_healthy: float = 0.50
    p_slowly_degrading: float = 0.15
    p_abrupt_breakdown: float = 0.10
    p_pre_shorted: float = 0.05
    p_intermittent_contact: float = 0.05
    p_corner_weak: float = 0.15  # preferentially used for corner/edge devices
    # Scenario overrides (device_id -> SimDeviceType string)
    # Set by the demo config to create a deterministic interesting scenario
    device_type_overrides: dict[str, str] = Field(default_factory=dict)
    # Probe contact degradation: after this many devices contacted, add contact
    # noise to simulate probe-tip wear
    probe_degradation_after_n_devices: int = 999
    # Extra noise burst probability (setup drift simulation)
    noise_burst_probability: float = 0.03


class InstrumentConfig(BaseModel):
    """Specifies whether to use simulation or real hardware."""
    simulate: bool = True
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    # Real hardware connection strings (ignored when simulate=True)
    probe_station_address: str = ""
    keysight_visa_address: str = ""
    visa_timeout_ms: int = 5000
    settling_time_ms: int = 100


class ProtocolParams(BaseModel):
    """Parameters for a single measurement protocol variant."""
    v_start: float = 0.0
    v_stop: float = 5.0
    v_step: float = 0.25
    compliance_current_A: float = 1.0e-4
    # For stress/durability protocols
    n_cycles: int = 1
    # For confirmatory protocols
    n_repeats: int = 1


class ProtocolsConfig(BaseModel):
    """Collection of all protocol variants used by the agent."""
    health_check: ProtocolParams = Field(
        default_factory=lambda: ProtocolParams(
            v_start=0.0, v_stop=5.0, v_step=0.25, compliance_current_A=1e-4
        )
    )
    stress_batch: ProtocolParams = Field(
        default_factory=lambda: ProtocolParams(
            v_start=0.0, v_stop=12.0, v_step=0.5, compliance_current_A=1e-4, n_cycles=5
        )
    )
    dense_monitoring: ProtocolParams = Field(
        default_factory=lambda: ProtocolParams(
            v_start=0.0, v_stop=8.0, v_step=0.25, compliance_current_A=1e-4, n_cycles=3
        )
    )
    confirmatory: ProtocolParams = Field(
        default_factory=lambda: ProtocolParams(
            v_start=0.0, v_stop=5.0, v_step=0.25, compliance_current_A=1e-4, n_repeats=3
        )
    )
    low_stress_recheck: ProtocolParams = Field(
        default_factory=lambda: ProtocolParams(
            v_start=0.0, v_stop=3.0, v_step=0.25, compliance_current_A=1e-4
        )
    )
    control_check: ProtocolParams = Field(
        default_factory=lambda: ProtocolParams(
            v_start=0.0, v_stop=5.0, v_step=0.25, compliance_current_A=1e-4
        )
    )


class ThresholdConfig(BaseModel):
    """All numerical thresholds for classification, suspicion, and escalation."""

    # --- Health classification ---
    # Leakage current at 1 V used as the primary health indicator
    max_leakage_healthy_A: float = 5.0e-10       # < 500 pA → healthy
    max_leakage_degraded_A: float = 1.0e-7       # 500 pA–100 nA → degrading
    min_resistance_healthy_ohm: float = 1.0e10   # > 10 GΩ at 1 V → healthy
    # Short detection: if estimated R at 1 V is below this, device is shorted
    short_resistance_threshold_ohm: float = 1.0e4  # < 10 kΩ → shorted
    # Open-circuit / no-contact detection
    min_current_at_max_v_A: float = 1.0e-13      # if I(Vmax) < this, likely open

    # --- Suspicion triggers ---
    consecutive_failures_suspicion: int = 2
    consecutive_failures_escalation: int = 6
    confirmatory_inconsistency_count: int = 2     # inconsistent confirmatory repeats
    neighbor_leakage_ratio_suspicious: float = 8.0
    neighbor_leakage_ratio_critical: float = 30.0
    trend_worsening_rate_suspicious: float = 0.20  # ≥20% per batch
    trend_worsening_rate_critical: float = 0.40
    suspicion_score_for_control_check: float = 0.55
    suspicion_score_for_escalation: float = 0.80

    # --- Spatial analysis ---
    spatial_cluster_min_size: int = 3
    spatial_cluster_radius: int = 2

    # --- Stress testing ---
    max_stress_batches_per_device: int = 10
    stress_batches_dense_mode: int = 5

    # --- Control / sentinel device ---
    control_device_leakage_increase_threshold: float = 5.0  # > 5× baseline → bad


class EmailConfig(BaseModel):
    """SMTP settings for automated alert emails."""
    enabled: bool = False
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    use_tls: bool = True
    sender: str = ""
    password: str = ""
    recipients: list[str] = Field(default_factory=list)
    send_on_severity_3_plus: bool = True
    pause_on_severity_4: bool = True


class RunConfig(BaseModel):
    """Top-level run identification and output settings."""
    chip_id: str
    run_id: str
    output_dir: Path
    description: str = ""
    operator: str = ""


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------

class AgentConfig(BaseModel):
    """Root configuration loaded from a YAML file."""

    run: RunConfig
    grid: GridConfig
    device_naming: DeviceNamingConfig = Field(default_factory=DeviceNamingConfig)
    control_devices: list[list[int]] = Field(
        default_factory=list,
        description="List of [ix, iy] pairs that are known healthy control devices",
    )
    instruments: InstrumentConfig = Field(default_factory=InstrumentConfig)
    protocols: ProtocolsConfig = Field(default_factory=ProtocolsConfig)
    thresholds: ThresholdConfig = Field(default_factory=ThresholdConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AgentConfig":
        """Load and validate config from a YAML file."""
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls.model_validate(data)

    def is_control_device(self, ix: int, iy: int) -> bool:
        return [ix, iy] in self.control_devices

    def output_path(self) -> Path:
        p = self.run.output_dir / self.run.run_id
        p.mkdir(parents=True, exist_ok=True)
        return p
