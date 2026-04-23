"""
Data schemas for the LLM reasoning layer.

All objects are Pydantic v2 models or plain dataclasses so they serialise
cleanly to JSON for both prompting and storage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Device structure and fabrication metadata
# ---------------------------------------------------------------------------

class DeviceStructureMetadata(BaseModel):
    """
    Physical/geometric description of the capacitor under test.

    Values are optional — only include what is actually known.  The LLM
    must NOT invent values not present here.
    """
    capacitor_type: str = ""               # e.g. "MIM", "MOS", "PIP"
    area_um2: Optional[float] = None       # device area in µm²
    dielectric_material: str = ""          # e.g. "SiO2", "HfO2", "Al2O3"
    dielectric_thickness_nm: Optional[float] = None
    top_electrode_material: str = ""       # e.g. "TiN", "Pt", "W"
    bottom_electrode_material: str = ""
    edge_shape: str = ""                   # e.g. "square", "circular", "rounded"
    design_notes: str = ""

    def is_populated(self) -> bool:
        return bool(
            self.capacitor_type or self.dielectric_material
            or self.top_electrode_material or self.design_notes
        )

    def to_prompt_dict(self) -> dict:
        d = {k: v for k, v in self.model_dump().items() if v not in (None, "")}
        return d


class FabricationContext(BaseModel):
    """
    Process and fabrication details for the device batch.

    Values are optional — only include what is actually known.
    """
    fab_run_id: str = ""
    process_split: str = ""                # e.g. "SPLIT_A", "SPLIT_B"
    deposition_method: str = ""            # e.g. "ALD", "CVD", "PVD"
    anneal_notes: str = ""
    etch_notes: str = ""
    cleaning_notes: str = ""
    known_fabrication_risks: list[str] = Field(default_factory=list)
    operator_comments: str = ""

    def is_populated(self) -> bool:
        return bool(
            self.fab_run_id or self.process_split
            or self.known_fabrication_risks or self.operator_comments
        )

    def to_prompt_dict(self) -> dict:
        d = {k: v for k, v in self.model_dump().items() if v not in (None, "", [])}
        return d


# ---------------------------------------------------------------------------
# Scientific reasoning context
# ---------------------------------------------------------------------------

@dataclass
class ScientificReasoningContext:
    """
    A structured snapshot of all evidence available at a decision point.

    Built by ContextBuilder from the agent's live state and passed to the LLM.
    All fields are plain Python types so the object serialises directly to JSON.
    """

    # Run / chip / device identity
    run_id: str
    chip_id: str
    device_id: str
    grid_x: int
    grid_y: int
    grid_position: str                    # "corner" | "edge" | "center"
    event_type: str                       # "health_check" | "stress_batch" | "escalation"

    # Optional device metadata (may be empty dicts if not configured)
    variant_id: str = ""
    device_structure: dict = field(default_factory=dict)
    fabrication_context: dict = field(default_factory=dict)

    # Latest measurement evidence
    latest_measurement_summary: dict = field(default_factory=dict)
    temporal_trend_summary: dict = field(default_factory=dict)
    neighborhood_summary: dict = field(default_factory=dict)
    control_device_summary: dict = field(default_factory=dict)   # {} if not checked yet

    # Heuristic outputs
    suspicion_score: float = 0.0
    suspicion_reasons: list[str] = field(default_factory=list)
    active_hypotheses: list[dict] = field(default_factory=list)  # [{hypothesis, support_level}]
    recent_events: list[str] = field(default_factory=list)

    # Policy context
    allowed_actions: list[str] = field(default_factory=list)
    current_protocol_mode: str = ""

    def to_prompt_dict(self) -> dict:
        """Return a clean dict for JSON-encoding into the LLM prompt."""
        return {
            "run_id": self.run_id,
            "chip_id": self.chip_id,
            "device_id": self.device_id,
            "grid_position": {"x": self.grid_x, "y": self.grid_y, "label": self.grid_position},
            "event_type": self.event_type,
            "variant_id": self.variant_id or None,
            "device_structure": self.device_structure or None,
            "fabrication_context": self.fabrication_context or None,
            "latest_measurement_summary": self.latest_measurement_summary,
            "temporal_trend_summary": self.temporal_trend_summary,
            "neighborhood_summary": self.neighborhood_summary,
            "control_device_summary": self.control_device_summary or None,
            "suspicion_score": round(self.suspicion_score, 3),
            "suspicion_reasons": self.suspicion_reasons,
            "active_hypotheses": self.active_hypotheses,
            "recent_events": self.recent_events[-6:],
            "allowed_actions": self.allowed_actions,
            "current_protocol_mode": self.current_protocol_mode,
        }


# ---------------------------------------------------------------------------
# LLM output schema
# ---------------------------------------------------------------------------

class LLMReasoningResult(BaseModel):
    """
    Structured output from the LLM scientific reasoner.

    Validated by Pydantic.  If parsing fails the agent falls back to
    deterministic behaviour and logs the parse error.
    """
    primary_hypotheses: list[str] = Field(
        default_factory=list,
        description="Hypothesis type names the LLM considers most likely.",
    )
    evidence_for: list[str] = Field(
        default_factory=list,
        description="Observed evidence supporting primary hypotheses.",
    )
    evidence_against: list[str] = Field(
        default_factory=list,
        description="Observed evidence that conflicts with primary hypotheses.",
    )
    uncertainty_notes: list[str] = Field(
        default_factory=list,
        description="Explicit uncertainty statements.",
    )
    structure_or_process_links: list[str] = Field(
        default_factory=list,
        description="Connections between evidence and device structure / process details.",
    )
    recommended_action: str = Field(
        default="",
        description="One action name chosen from the allowed_actions list.",
    )
    recommended_action_reason: str = Field(
        default="",
        description="Concise justification for the recommended action.",
    )
    note_text: str = Field(
        default="",
        description="A short lab-note paragraph summarising the reasoning.",
    )

    # Internal bookkeeping — not sent to LLM
    raw_response: str = Field(default="", exclude=True)
    parsing_succeeded: bool = Field(default=True, exclude=True)

    @classmethod
    def fallback(cls, raw: str = "", reason: str = "") -> "LLMReasoningResult":
        """Return a minimal valid result to use when parsing fails."""
        return cls(
            uncertainty_notes=[f"LLM output could not be parsed: {reason}"],
            parsing_succeeded=False,
            raw_response=raw,
        )


# ---------------------------------------------------------------------------
# Reasoning record persisted to llm_reasoning.jsonl
# ---------------------------------------------------------------------------

@dataclass
class LLMReasoningRecord:
    """One entry in llm_reasoning.jsonl — one record per reasoning event."""

    timestamp: str
    device_id: str
    event_type: str                            # health_check | stress_batch | escalation
    context_snapshot: dict                     # to_prompt_dict() output
    llm_result: Optional[dict]                 # model_dump() of LLMReasoningResult
    heuristic_action: str                      # what the deterministic policy decided
    llm_recommendation: str                    # what the LLM recommended
    llm_recommendation_matched: bool           # did they agree?
    llm_action_applied: bool = False           # was the LLM recommendation actually used?

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "device_id": self.device_id,
            "event_type": self.event_type,
            "heuristic_action": self.heuristic_action,
            "llm_recommendation": self.llm_recommendation,
            "llm_recommendation_matched": self.llm_recommendation_matched,
            "llm_action_applied": self.llm_action_applied,
            "llm_result": self.llm_result,
            "context_snapshot": self.context_snapshot,
        }
