"""
Explicit state machine states and actions for the experiment agent.

These are the first-class building blocks of the policy layer.  Using named
enums (rather than strings or booleans) makes every decision auditable and
testable in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models.device import DeviceRecord, DeviceStatus, SuspicionLevel
    from ..models.measurement import IVMetrics
    from ..models.run_state import RunState
    from ..analysis.trends import TrendFeatures
    from ..analysis.neighbors import NeighborComparison
    from ..analysis.suspicion import SuspicionResult


# ---------------------------------------------------------------------------
# Agent state machine states
# ---------------------------------------------------------------------------

class AgentState(str, Enum):
    """
    The state the experiment manager is currently in for a given device.

    The agent transitions between states based on measurement results and
    policy decisions.
    """
    IDLE = "idle"
    MEASURING_INITIAL_HEALTH = "measuring_initial_health"
    CLASSIFYING_DEVICE = "classifying_device"
    STRESSING_DEVICE = "stressing_device"
    DENSE_MONITORING = "dense_monitoring"
    RUNNING_CONFIRMATORY_CHECK = "running_confirmatory_check"
    CHECKING_CONTROL_DEVICE = "checking_control_device"
    COMPARING_NEIGHBORS = "comparing_neighbors"
    ESCALATING = "escalating"
    PAUSED_FOR_HUMAN = "paused_for_human"
    DEVICE_COMPLETE = "device_complete"
    RUN_COMPLETE = "complete"


# ---------------------------------------------------------------------------
# Actions the policy engine can produce
# ---------------------------------------------------------------------------

class AgentAction(str, Enum):
    """
    Discrete actions the policy engine returns.

    The orchestration layer maps each action to a concrete sequence of steps.
    Using named actions (rather than scattered if-statements) makes the
    decision logic inspectable and unit-testable.
    """
    # Device-level actions
    START_STRESS = "start_stress"
    CONTINUE_STRESS = "continue_stress"
    STOP_STRESS = "stop_stress"
    SKIP_DEVICE = "skip_device"
    FINISH_DEVICE = "finish_device"

    # Measurement modification actions
    REPEAT_MEASUREMENT = "repeat_measurement"
    RUN_CONFIRMATORY_CHECK = "run_confirmatory_check"
    SWITCH_TO_DENSE_MONITORING = "switch_to_dense_monitoring"
    RUN_LOW_STRESS_RECHECK = "run_low_stress_recheck"

    # Inter-device actions
    CHECK_CONTROL_DEVICE = "check_control_device"
    INSPECT_NEIGHBORS = "inspect_neighbors"

    # Escalation actions
    ESCALATE_AND_CONTINUE = "escalate_and_continue"
    ESCALATE_AND_PAUSE = "escalate_and_pause"

    # Transition actions
    ADVANCE_TO_NEXT_DEVICE = "advance_to_next_device"


# ---------------------------------------------------------------------------
# Context and Decision dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PolicyContext:
    """
    Snapshot of all information available to the policy engine at decision time.

    Created by the orchestration layer and passed to PolicyEngine.decide().
    """
    # Current machine state
    agent_state: "AgentState"

    # Device being processed
    device: "DeviceRecord"

    # Latest measurement results
    latest_metrics: Optional["IVMetrics"] = None
    latest_status: Optional["DeviceStatus"] = None

    # Analysis results
    trend_features: Optional["TrendFeatures"] = None
    neighbor_comparison: Optional["NeighborComparison"] = None
    suspicion_result: Optional["SuspicionResult"] = None

    # Run-level context
    run_state: Optional["RunState"] = None

    # Stress tracking for current device
    stress_batch_index: int = 0
    max_stress_batches: int = 10
    confirmatory_index: int = 0

    # Flags from prior steps in the same device pass
    control_checked_this_pass: bool = False
    neighbors_inspected: bool = False

    # Additional context
    extra: dict = field(default_factory=dict)


@dataclass
class PolicyDecision:
    """
    Output of the policy engine for a single decision step.

    Includes the recommended action, an explanation, and any notes that
    the notes writer should record.
    """
    action: "AgentAction"
    reason: str              # concise explanation for logging / notes
    note: str = ""           # longer note text for the experiment log
    severity_hint: int = 1   # 1–4, for the alert system
    new_protocol: Optional[str] = None  # if action changes the protocol mode
