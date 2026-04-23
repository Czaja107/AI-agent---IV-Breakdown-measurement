"""
ScientificReasoner — the main LLM reasoning module.

Takes a ScientificReasoningContext, calls the LLM client, parses and
validates the structured JSON output, and returns an LLMReasoningResult.

Failure handling
----------------
If the LLM call fails, returns an empty string, or produces invalid JSON,
the method returns None and logs the error.  The caller must fall back to
deterministic behaviour in that case.  This is by design: the LLM is an
advisory layer and must never block the experiment.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import ValidationError

from .client import LLMClient
from .schemas import ScientificReasoningContext, LLMReasoningResult
from .prompts import hypothesis_prompt

logger = logging.getLogger(__name__)


class ScientificReasoner:
    """
    Advisory LLM reasoning module.

    Wraps an LLMClient, formats prompts, parses structured responses, and
    exposes a single high-level method: reason().

    The reasoner is stateless — it does not accumulate history.  All context
    must be supplied in the ScientificReasoningContext argument.
    """

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def reason(
        self, context: ScientificReasoningContext
    ) -> Optional[LLMReasoningResult]:
        """
        Run one round of scientific reasoning for a device decision point.

        Returns an LLMReasoningResult on success, or None if the LLM is
        disabled / the response could not be parsed.
        """
        if self.client.is_noop:
            return None

        system_prompt, user_content = hypothesis_prompt(context.to_prompt_dict())

        try:
            raw = self.client.complete(system_prompt, user_content)
        except Exception as exc:
            logger.error("LLM complete() raised an exception: %s", exc)
            return None

        if not raw or not raw.strip():
            logger.debug("LLM returned an empty response for %s", context.device_id)
            return None

        return self._parse(raw, context)

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _parse(
        self, raw: str, context: ScientificReasoningContext
    ) -> Optional[LLMReasoningResult]:
        """Parse and validate the LLM JSON response."""
        # Strip markdown code fences if the LLM wrapped the JSON
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # drop first line (```json or ```) and last line (```)
            text = "\n".join(lines[1:-1]).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning(
                "LLM response for %s is not valid JSON: %s | raw=%r",
                context.device_id, exc, raw[:200],
            )
            return LLMReasoningResult.fallback(raw=raw, reason=f"JSON parse error: {exc}")

        try:
            result = LLMReasoningResult.model_validate(data)
        except ValidationError as exc:
            logger.warning(
                "LLM response for %s failed schema validation: %s",
                context.device_id, exc,
            )
            return LLMReasoningResult.fallback(raw=raw, reason=f"Schema validation error: {exc}")

        result.raw_response = raw

        # Guard: recommended_action must be in allowed_actions
        if result.recommended_action and result.recommended_action not in context.allowed_actions:
            logger.warning(
                "LLM recommended action %r for %s is not in allowed_actions %s; clearing.",
                result.recommended_action, context.device_id, context.allowed_actions,
            )
            result.recommended_action = ""
            result.recommended_action_reason = "(action cleared by guard — not in allowed set)"

        return result
