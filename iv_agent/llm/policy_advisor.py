"""
PolicyAdvisor — bounded LLM policy advice with deterministic guard.

Architecture
------------
1. The deterministic policy engine computes a PolicyDecision with an
   allowed_actions set.
2. The PolicyAdvisor asks the LLM to recommend ONE action from that set.
3. The guard validates the LLM recommendation:
   - Must be in allowed_actions.
   - Must not be less safe than the deterministic decision (e.g. LLM cannot
     downgrade ESCALATE_AND_PAUSE to CONTINUE_STRESS).
4. If the recommendation passes the guard, it optionally replaces the
   deterministic action (only when advisory_mode = "advisory_with_bounded_override").
5. The deterministic policy remains the final authority.

Safety invariants
-----------------
- ESCALATE_AND_PAUSE can never be overridden to a lower-severity action.
- ESCALATE_AND_CONTINUE can never be overridden to CONTINUE_STRESS.
- Actions not in allowed_actions are always rejected.
"""
from __future__ import annotations

import logging
from typing import Optional

from .schemas import LLMReasoningResult, ScientificReasoningContext

logger = logging.getLogger(__name__)


# Safety order: higher index = more conservative/safe; LLM may not override
# a higher-index action with a lower-index one.
_SAFETY_ORDER: list[str] = [
    "continue_stress",
    "switch_to_dense_monitoring",
    "run_low_stress_recheck",
    "repeat_measurement",
    "run_confirmatory_check",
    "inspect_neighbors",
    "check_control_device",
    "stop_stress",
    "skip_device",
    "finish_device",
    "escalate_and_continue",
    "escalate_and_pause",
]


def _safety_level(action: str) -> int:
    try:
        return _SAFETY_ORDER.index(action)
    except ValueError:
        return 0


class PolicyAdvisor:
    """
    Advisory LLM policy layer with a deterministic safety guard.

    Parameters
    ----------
    advisory_mode : str
        "advisory_only" — log LLM recommendation but always use deterministic.
        "advisory_with_bounded_override" — apply LLM recommendation if it
            passes the safety guard.
    """

    def __init__(self, advisory_mode: str = "advisory_only") -> None:
        self.advisory_mode = advisory_mode

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def apply_advice(
        self,
        heuristic_action: str,
        llm_result: Optional[LLMReasoningResult],
        allowed_actions: list[str],
        context: Optional[ScientificReasoningContext] = None,
    ) -> tuple[str, str, bool]:
        """
        Validate LLM advice and optionally override the heuristic action.

        Parameters
        ----------
        heuristic_action : str
            The action chosen by the deterministic policy engine.
        llm_result : LLMReasoningResult | None
            Output from the ScientificReasoner.
        allowed_actions : list[str]
            Actions the policy engine has declared legal.
        context : ScientificReasoningContext | None
            For logging.

        Returns
        -------
        (final_action, final_reason, llm_was_applied)
        """
        device_id = context.device_id if context else "unknown"

        if llm_result is None or not llm_result.parsing_succeeded:
            return heuristic_action, "", False

        llm_action = llm_result.recommended_action
        if not llm_action:
            return heuristic_action, "", False

        # --- Guard 1: must be in allowed_actions ---
        if llm_action not in allowed_actions:
            logger.info(
                "PolicyAdvisor GUARD: LLM action %r for %s not in allowed set %s.",
                llm_action, device_id, allowed_actions,
            )
            return heuristic_action, "", False

        # --- Guard 2: must not decrease safety level ---
        if _safety_level(llm_action) < _safety_level(heuristic_action):
            logger.info(
                "PolicyAdvisor GUARD: LLM action %r for %s is less safe than "
                "heuristic %r; rejecting.",
                llm_action, device_id, heuristic_action,
            )
            return heuristic_action, "", False

        # --- Guard 3: mode check ---
        if self.advisory_mode == "advisory_only":
            logger.debug(
                "PolicyAdvisor [advisory_only]: LLM recommends %r for %s "
                "(heuristic: %r); not overriding.",
                llm_action, device_id, heuristic_action,
            )
            return heuristic_action, llm_result.recommended_action_reason, False

        # advisory_with_bounded_override — safe to apply
        if llm_action != heuristic_action:
            logger.info(
                "PolicyAdvisor OVERRIDE: %s heuristic=%r -> llm=%r (%s)",
                device_id, heuristic_action, llm_action,
                llm_result.recommended_action_reason[:80],
            )

        return llm_action, llm_result.recommended_action_reason, (llm_action != heuristic_action)
