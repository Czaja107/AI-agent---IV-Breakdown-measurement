"""
Self-generated experiment notes writer.

The NotesWriter converts internal agent events into concise, factual,
lab-style notes.  Notes are written incrementally during the run and
saved as both markdown and JSON-lines.

Each note template is a function that receives context and returns a
string — no LLM involved, just structured string formatting.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..models.run_state import Note, RunState

if TYPE_CHECKING:
    from ..config.schema import AgentConfig


class NotesWriter:
    """
    Generates and persists self-written experiment notes.

    Notes are appended to notes.md (human-readable) and notes.jsonl
    (machine-readable) in the output directory.
    """

    def __init__(self, run_state: RunState, config: "AgentConfig") -> None:
        self.run_state = run_state
        self.config = config

    # -----------------------------------------------------------------------
    # Note templates (called directly by the agent or via storage.append_note)
    # -----------------------------------------------------------------------

    @staticmethod
    def note_healthy_device(device_id: str, leakage_A: float, n_batches: int) -> str:
        return (
            f"Device {device_id} completed {n_batches} stress batches without "
            f"anomalies. Final leakage at 1 V = {leakage_A:.2e} A. "
            f"Classified as HEALTHY."
        )

    @staticmethod
    def note_shorted_device(device_id: str, resistance_ohm: float) -> str:
        return (
            f"Device {device_id} detected as shorted at initial health check "
            f"(R_est = {resistance_ohm:.2e} Ohm). Durability testing skipped. "
            f"PRE_EXISTING_SHORT hypothesis supported."
        )

    @staticmethod
    def note_contact_issue(device_id: str, n_attempts: int) -> str:
        return (
            f"Device {device_id} showed near-zero current on {n_attempts} "
            f"consecutive measurement attempts, suggesting poor probe contact. "
            f"CONTACT_DEGRADATION hypothesis strengthened."
        )

    @staticmethod
    def note_degradation_trend(
        device_id: str, batch: int, ratio: float, trend: str
    ) -> str:
        return (
            f"Device {device_id}: leakage increased {ratio:.1f}× from baseline "
            f"by stress batch {batch}. Trend classification: {trend}. "
            f"TRUE_DEVICE_DEGRADATION hypothesis supported."
        )

    @staticmethod
    def note_breakdown_during_stress(
        device_id: str, batch: int, vbd_V: float
    ) -> str:
        return (
            f"Device {device_id}: compliance current hit during stress batch {batch} "
            f"(V_bd ≈ {vbd_V:.1f} V). Switching to dense monitoring. "
            f"TRUE_DEVICE_DEGRADATION hypothesis strongly supported."
        )

    @staticmethod
    def note_control_check_healthy(ctrl_id: str, triggering_id: str) -> str:
        return (
            f"Control device {ctrl_id} measured out-of-sequence (triggered by "
            f"activity on {triggering_id}) and found HEALTHY. "
            f"This suggests the issues seen recently are real device/process "
            f"behaviour rather than setup instability. "
            f"CONTACT_DEGRADATION or LOCAL_SPATIAL_DEFECT hypothesis strengthened; "
            f"SETUP_DRIFT hypothesis weakened."
        )

    @staticmethod
    def note_control_check_degraded(ctrl_id: str, triggering_id: str) -> str:
        return (
            f"Control device {ctrl_id} measured out-of-sequence (triggered by "
            f"activity on {triggering_id}) and found DEGRADED. "
            f"This is unexpected for a known-good device and suggests "
            f"instrument drift, probe-tip contamination, or setup instability. "
            f"SETUP_DRIFT hypothesis strongly supported. Escalation triggered."
        )

    @staticmethod
    def note_spatial_cluster(
        member_ids: list[str], region: str, n_members: int
    ) -> str:
        id_str = ", ".join(member_ids[:5])
        suffix = f" and {n_members - 5} more" if n_members > 5 else ""
        return (
            f"Spatial cluster of {n_members} anomalous devices detected in "
            f"{region} region: [{id_str}{suffix}]. "
            f"{'CORNER_EFFECT' if 'corner' in region or 'bottom' in region or 'top' in region else 'LOCAL_SPATIAL_DEFECT'} "
            f"hypothesis supported."
        )

    @staticmethod
    def note_consecutive_failures(n: int, hypothesis: str) -> str:
        return (
            f"{n} consecutive device failures or contact issues observed. "
            f"This pattern is inconsistent with random device-level failures "
            f"and strongly suggests {hypothesis}. "
            f"Operator attention may be required."
        )

    @staticmethod
    def note_hypothesis_update(hypothesis_label: str, support: float, reason: str) -> str:
        return (
            f"Hypothesis update — {hypothesis_label}: "
            f"support level now {support:.2f}/1.0. "
            f"Reason: {reason}."
        )
