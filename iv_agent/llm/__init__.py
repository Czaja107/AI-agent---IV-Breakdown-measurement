"""
LLM-assisted scientific reasoning layer.

This package adds an optional advisory LLM layer on top of the existing
deterministic/heuristic orchestration core.  The LLM is used for high-level
evidence-grounded scientific reasoning only — it does NOT directly control
hardware, compute raw electrical metrics, or bypass safety checks.

Public surface
--------------
- LLMLayer        — high-level facade wiring all sub-modules together
- LLMClient       — abstract client (NoOp / Mock / OpenAILike backends)
- ScientificReasoner
- LLMNoteWriter
- LLMAlertWriter
- PolicyAdvisor
- ContextBuilder
"""
from .client import LLMClient, NoOpLLMClient, MockLLMClient, OpenAILikeClient
from .schemas import (
    ScientificReasoningContext,
    LLMReasoningResult,
    LLMReasoningRecord,
    DeviceStructureMetadata,
    FabricationContext,
)
from .scientific_reasoner import ScientificReasoner
from .note_writer import LLMNoteWriter
from .alert_writer import LLMAlertWriter
from .policy_advisor import PolicyAdvisor
from .context_builder import ContextBuilder

__all__ = [
    "LLMClient",
    "NoOpLLMClient",
    "MockLLMClient",
    "OpenAILikeClient",
    "ScientificReasoningContext",
    "LLMReasoningResult",
    "LLMReasoningRecord",
    "DeviceStructureMetadata",
    "FabricationContext",
    "ScientificReasoner",
    "LLMNoteWriter",
    "LLMAlertWriter",
    "PolicyAdvisor",
    "ContextBuilder",
]
