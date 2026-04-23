"""
LLMNoteWriter — produces richer experiment notes using LLM reasoning output.

The writer combines:
- The heuristic-generated note text (from NotesWriter)
- The structured LLMReasoningResult
- The ScientificReasoningContext

to produce a single enriched note that includes observed evidence,
hypotheses, structure/process links, uncertainty statements, and the
recommended action.

When the LLM is disabled or reasoning failed, the writer falls back to
returning the heuristic note unchanged.
"""
from __future__ import annotations

from typing import Optional

from .schemas import LLMReasoningResult, ScientificReasoningContext


class LLMNoteWriter:
    """
    Formats enriched laboratory notes from LLM reasoning results.

    Stateless — call write() as many times as needed.
    """

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def write(
        self,
        heuristic_note: str,
        llm_result: Optional[LLMReasoningResult],
        context: Optional[ScientificReasoningContext] = None,
    ) -> str:
        """
        Return an enriched note string.

        If llm_result is None or parsing failed, returns the heuristic note.
        Otherwise returns an enriched version that incorporates LLM reasoning.
        """
        if llm_result is None or not llm_result.parsing_succeeded:
            return heuristic_note

        parts: list[str] = []

        # Observed evidence section
        if llm_result.evidence_for:
            obs_items = "; ".join(llm_result.evidence_for[:3])
            parts.append(f"**Observed evidence**: {obs_items}.")

        # Hypotheses section
        if llm_result.primary_hypotheses:
            hyp_str = ", ".join(llm_result.primary_hypotheses)
            parts.append(f"**Working hypotheses** [LLM]: {hyp_str}.")

        # Structure / process links
        if llm_result.structure_or_process_links:
            link_str = "; ".join(llm_result.structure_or_process_links[:2])
            parts.append(f"**Structure/process context**: {link_str}.")

        # Conflicting evidence
        if llm_result.evidence_against:
            against_str = "; ".join(llm_result.evidence_against[:2])
            parts.append(f"**Conflicting evidence**: {against_str}.")

        # Uncertainty
        if llm_result.uncertainty_notes:
            unc_str = " ".join(llm_result.uncertainty_notes[:2])
            parts.append(f"**Uncertainty**: {unc_str}")

        # Recommended action
        if llm_result.recommended_action and llm_result.recommended_action_reason:
            parts.append(
                f"**LLM recommended action**: {llm_result.recommended_action} — "
                f"{llm_result.recommended_action_reason}"
            )

        if not parts:
            return heuristic_note

        # Prepend heuristic note as the base observation
        enriched = heuristic_note.rstrip()
        if enriched:
            enriched += "  \n"
        enriched += "  \n".join(parts)
        return enriched

    def write_from_llm_text(
        self,
        heuristic_note: str,
        llm_result: Optional[LLMReasoningResult],
    ) -> str:
        """
        Use the LLM's own note_text field if available, otherwise fall back
        to the structured enrichment from write().
        """
        if llm_result is None or not llm_result.parsing_succeeded:
            return heuristic_note

        if llm_result.note_text:
            # Append heuristic note as a secondary context block
            combined = llm_result.note_text.strip()
            if heuristic_note:
                combined = heuristic_note.strip() + "  \n[LLM] " + combined
            return combined

        return self.write(heuristic_note, llm_result)
