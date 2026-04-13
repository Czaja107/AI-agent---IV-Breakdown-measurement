"""
Abstract interfaces that all instrument backends must implement.

Real hardware adapters (Keysight + Cascade Microtech) will subclass these.
The simulated backend also subclasses them, so the orchestration layer is
completely decoupled from the underlying hardware.

SAFETY NOTE: These interfaces must be validated against real hardware before
use in a production environment.  Contact / touchdown is assumed to have been
manually initialized by the operator before the agent starts.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..config.schema import AgentConfig, ProtocolParams
from ..models.measurement import IVCurve, StressBatch


class ProbeStationInterface(ABC):
    """
    Abstract interface to the probe station (Cascade Microtech eVue III or similar).

    The agent only moves between grid positions — it does NOT perform initial
    touchdown or visual alignment.  Those must be done manually by the operator.
    """

    @abstractmethod
    def connect(self) -> None:
        """Open connection to the probe station controller."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection to the probe station controller."""

    @abstractmethod
    def move_to_grid_position(self, ix: int, iy: int) -> None:
        """
        Move the stage to grid position (ix, iy) using the pre-configured
        X/Y spacing from the config.

        The first device position is assumed to be set manually.
        """

    @abstractmethod
    def get_current_position(self) -> tuple[int, int]:
        """Return the current (ix, iy) grid index."""

    @abstractmethod
    def pause(self) -> None:
        """Pause automated stepping (e.g. while awaiting human intervention)."""

    @abstractmethod
    def resume(self) -> None:
        """Resume automated stepping after a pause."""


class MeasurementBackend(ABC):
    """
    Abstract interface to the Keysight measurement stack.

    Responsible for running I-V sweeps and stress sequences.
    """

    @abstractmethod
    def connect(self) -> None:
        """Open VISA connection to the instrument."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection and return instrument to safe state."""

    @abstractmethod
    def run_iv_sweep(
        self, device_id: str, protocol: ProtocolParams, sweep_index: int = 0
    ) -> IVCurve:
        """
        Perform a single voltage sweep and return the raw I-V curve.

        Args:
            device_id: Identifier of the device currently under probe.
            protocol:  Protocol parameters (voltage range, step, compliance).
            sweep_index: Index within a larger batch (0-based).
        """

    @abstractmethod
    def run_stress_batch(
        self, device_id: str, protocol: ProtocolParams, batch_index: int
    ) -> StressBatch:
        """
        Run n_cycles consecutive I-V sweeps as a stress / durability batch.

        Args:
            device_id:   Device identifier.
            protocol:    Stress protocol parameters including n_cycles.
            batch_index: Which batch number this is (0-based).
        """


class InstrumentBackend(ABC):
    """
    Combined probe-station + measurement backend.

    Concrete implementations unify both interfaces so the orchestration layer
    only needs to keep a reference to a single backend object.
    """

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def move_to_grid_position(self, ix: int, iy: int) -> None: ...

    @abstractmethod
    def get_current_position(self) -> tuple[int, int]: ...

    @abstractmethod
    def run_iv_sweep(
        self, device_id: str, protocol: ProtocolParams, sweep_index: int = 0
    ) -> IVCurve: ...

    @abstractmethod
    def run_stress_batch(
        self, device_id: str, protocol: ProtocolParams, batch_index: int
    ) -> StressBatch: ...

    @abstractmethod
    def pause(self) -> None: ...

    @abstractmethod
    def resume(self) -> None: ...

    @classmethod
    def from_config(cls, config: AgentConfig) -> "InstrumentBackend":
        """Factory: return the right backend based on config.instruments.simulate."""
        from .simulator import SimulatedBackend
        if config.instruments.simulate:
            return SimulatedBackend(config)
        # Future: return KeysightRealBackend(config)
        raise NotImplementedError(
            "Real hardware backend not yet implemented. "
            "Set instruments.simulate: true in config."
        )
