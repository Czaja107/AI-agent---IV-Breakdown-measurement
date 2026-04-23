"""
LLMAlertWriter — produces enriched escalation alert explanations.

For each escalation event the writer combines:
- The heuristic trigger reason (from PolicyDecision.reason)
- The LLMReasoningResult (if available)
- The ScientificReasoningContext (for device/process context)

to produce an explanation that:
- States what triggered the alert in evidence-grounded language.
- Links to active hypotheses with their supporting evidence.
- References device structure / fabrication context when available.
- Explicitly states uncertainty.
- Tells the operator what to check next.

When the LLM is disabled or reasoning failed, returns the heuristic
explanation unchanged.
"""
from __future__ import annotations

from typing import Optional

from .schemas import LLMReasoningResult, ScientificReasoningContext


class LLMAlertWriter:
    """
    Formats enriched escalation alert explanations from LLM reasoning.

    Stateless — call write() as many times as needed.
    """

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def write(
        self,
        heuristic_explanation: str,
        llm_result: Optional[LLMReasoningResult],
        context: Optional[ScientificReasoningContext] = None,
        severity: int = 2,
    ) -> tuple[str, str]:
        """
        Return (enriched_explanation, operator_recommendation).

        Parameters
        ----------
        heuristic_explanation : str
            The original explanation produced by deterministic logic.
        llm_result : LLMReasoningResult | None
            LLM output for this decision point.  If None, returns the
            heuristic explanation unchanged.
        context : ScientificReasoningContext | None
            The reasoning context.  Used to reference structural/process info.
        severity : int
            Alert severity (1-4).  Higher severity → more explicit action.

        Returns
        -------
        (explanation, operator_action)
        """
        if llm_result is None or not llm_result.parsing_succeeded:
            return heuristic_explanation, self._default_operator_action(severity)

        parts: list[str] = [heuristic_explanation.strip()]

        # Add active hypotheses with evidence
        if llm_result.primary_hypotheses:
            hyp_str = ", ".join(llm_result.primary_hypotheses)
            parts.append(
                f"Active working hypotheses: {hyp_str}."
            )

        if llm_result.evidence_for:
            ev_str = "; ".join(llm_result.evidence_for[:3])
            parts.append(f"Supporting evidence: {ev_str}.")

        if llm_result.evidence_against:
            ag_str = "; ".join(llm_result.evidence_against[:2])
            parts.append(f"Conflicting evidence: {ag_str}.")

        # Structure / process context
        if llm_result.structure_or_process_links:
            link_str = "; ".join(llm_result.structure_or_process_links[:2])
            parts.append(f"Structure/process context: {link_str}.")

        # Control device context
        if context and context.control_device_summary:
            ctrl_result = context.control_device_summary.get("result", "")
            if ctrl_result == "healthy":
                parts.append(
                    "Note: the healthy control device remains unaffected, "
                    "which localises the issue to this device or its immediate region "
                    "rather than a system-wide setup problem."
                )
            elif ctrl_result == "degraded":
                parts.append(
                    "Note: the control device is also degraded — "
                    "this raises the possibility of a setup-level issue rather than "
                    "a true device-level failure."
                )

        # Uncertainty
        if llm_result.uncertainty_notes:
            unc_str = " ".join(llm_result.uncertainty_notes[:2])
            parts.append(f"Uncertainty: {unc_str}")

        explanation = "  ".join(p for p in parts if p)

        # Operator action
        op_action = (
            llm_result.recommended_action_reason.strip()
            or self._default_operator_action(severity)
        )
        if llm_result.recommended_action:
            op_action = (
                f"Suggested next step: {llm_result.recommended_action}. "
                + op_action
            )

        return explanation, op_action

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _default_operator_action(severity: int) -> str:
        if severity >= 4:
            return (
                "Inspect probe tips and connections, verify instrument calibration, "
                "and check the control device before resuming the run."
            )
        if severity == 3:
            return (
                "Review the measurement log, verify probe contact on the affected device, "
                "and confirm the control device is healthy."
            )
        return "Review the measurement log at your earliest convenience."
