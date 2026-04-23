"""
LLM client interface and backend implementations.

Three backends are available:

- NoOpLLMClient  — does nothing; always returns ""; used when LLM is disabled
- MockLLMClient  — deterministic mock that generates realistic structured
                   responses from the context without calling any API
- OpenAILikeClient — calls any OpenAI-compatible REST endpoint (OpenAI,
                     Ollama, vLLM, LM Studio, etc.)

All backends share the same one-method interface:

    client.complete(system_prompt: str, user_content: str) -> str

The returned string is expected to be a valid JSON object matching
LLMReasoningResult.  If it is not, ScientificReasoner handles the parse
failure and falls back to deterministic behaviour.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class LLMClient(ABC):
    """Abstract interface every LLM backend must implement."""

    @abstractmethod
    def complete(self, system_prompt: str, user_content: str) -> str:
        """
        Send a system prompt + user content to the LLM and return the
        raw string response (expected to be valid JSON).
        """

    @property
    def is_noop(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# No-op backend — used when llm.enabled = false
# ---------------------------------------------------------------------------

class NoOpLLMClient(LLMClient):
    """Returns empty string immediately; disables all LLM reasoning."""

    def complete(self, system_prompt: str, user_content: str) -> str:
        return ""

    @property
    def is_noop(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Mock backend — deterministic, context-aware, no API call required
# ---------------------------------------------------------------------------

class MockLLMClient(LLMClient):
    """
    A deterministic mock that generates realistic structured JSON responses.

    Parses the JSON-encoded ScientificReasoningContext and uses the
    suspicion score, suspicion reasons, grid position, control device
    status, and fabrication context to produce varied, evidence-grounded
    mock outputs.

    This is the default backend for the demo/test mode.
    """

    def complete(self, system_prompt: str, user_content: str) -> str:
        try:
            ctx = json.loads(user_content)
        except (json.JSONDecodeError, ValueError):
            return json.dumps(self._default_result())

        return json.dumps(self._generate(ctx))

    # -----------------------------------------------------------------------
    # Internal generation logic
    # -----------------------------------------------------------------------

    def _generate(self, ctx: dict) -> dict:
        suspicion_score: float = float(ctx.get("suspicion_score", 0.0))
        suspicion_reasons: list[str] = ctx.get("suspicion_reasons", [])
        active_hypotheses: list[dict] = ctx.get("active_hypotheses", [])
        allowed_actions: list[str] = ctx.get("allowed_actions", [])
        grid_info: dict = ctx.get("grid_position", {})
        grid_pos_label: str = grid_info.get("label", "center") if isinstance(grid_info, dict) else "center"
        device_id: str = ctx.get("device_id", "unknown")
        control_summary: dict = ctx.get("control_device_summary") or {}
        fab_ctx: dict = ctx.get("fabrication_context") or {}
        structure: dict = ctx.get("device_structure") or {}
        trend: dict = ctx.get("temporal_trend_summary") or {}
        neighborhood: dict = ctx.get("neighborhood_summary") or {}
        event_type: str = ctx.get("event_type", "")

        # --- Parse flags from context ---
        has_contact_issue = any(
            "contact" in r.lower() or "open" in r.lower() or "no current" in r.lower()
            for r in suspicion_reasons
        )
        has_rapid_degradation = any(
            "rapid" in r.lower() or "worsening" in r.lower() or "near_break" in r.lower()
            for r in suspicion_reasons
        )
        has_spatial_anomaly = any(
            "neighbor" in r.lower() or "spatial" in r.lower() or "outlier" in r.lower()
            for r in suspicion_reasons
        )
        is_corner_or_edge = grid_pos_label in ("corner", "edge")
        control_result = (control_summary.get("result") or "") if control_summary else ""
        control_failed = "degraded" in control_result or "failed" in control_result
        control_passed = "healthy" in control_result
        trend_state: str = trend.get("trend_state", "stable") if trend else "stable"
        dielectric_nm = structure.get("dielectric_thickness_nm")
        known_risks: list[str] = fab_ctx.get("known_fabrication_risks", [])
        process_split: str = fab_ctx.get("process_split", "")
        existing_hyp_names = [h.get("hypothesis", "") for h in active_hypotheses]

        hypotheses: list[str] = []
        evidence_for: list[str] = []
        evidence_against: list[str] = []
        structure_links: list[str] = []
        uncertainty_notes: list[str] = []

        # --- Determine primary hypothesis and evidence ---
        if control_failed:
            hypotheses = ["CONTACT_DEGRADATION", "SETUP_DRIFT"]
            evidence_for = [
                "Healthy control device is also degraded — this is inconsistent with a "
                "device-level failure and strongly suggests an instrument- or setup-level issue.",
                "Pattern affects both the device under test and the sentinel control device.",
            ]
            evidence_against = [
                "A true device degradation would not be expected to affect an unrelated control device."
            ]
            structure_links = [
                "Contact or setup issues are typically not structure-dependent — "
                "they affect all devices regardless of variant."
            ]
            uncertainty_notes = [
                "Cannot distinguish probe-tip contamination from instrument drift "
                "without further calibration checks."
            ]

        elif has_contact_issue:
            hypotheses = ["CONTACT_DEGRADATION"]
            evidence_for = [
                "Near-zero or anomalously low current traces are inconsistent with normal "
                "dielectric leakage behaviour.",
            ]
            evidence_against = [
                "The device may genuinely have very low leakage — an open-circuit signature "
                "is ambiguous without a repeat measurement."
            ]
            if control_passed:
                evidence_for.append(
                    "Control device remains healthy — instrument-wide setup instability "
                    "is less likely; a local probe contact issue is more probable."
                )
            else:
                uncertainty_notes.append(
                    "Control device has not been checked yet — "
                    "cannot distinguish local probe issue from setup drift."
                )
            if process_split:
                uncertainty_notes.append(
                    f"Device belongs to process split {process_split}; "
                    "an unusually thin or contaminated electrode could also cause "
                    "poor probe contact — worth noting in fab records."
                )

        elif has_rapid_degradation and is_corner_or_edge:
            hypotheses = ["CORNER_EFFECT", "TRUE_DEVICE_DEGRADATION"]
            evidence_for = [
                f"Device at grid position {grid_pos_label} shows rapid degradation "
                f"(trend state: {trend_state}).",
                "Corner and edge devices are subject to non-uniform electric field distribution "
                "due to fringing effects.",
            ]
            if known_risks:
                hypotheses.append("FABRICATION_INDUCED_DIELECTRIC_WEAKNESS")
                structure_links.append(
                    f"Fabrication note: {known_risks[0]}"
                )
            if dielectric_nm:
                structure_links.append(
                    f"Dielectric thickness {dielectric_nm} nm; thinner dielectrics are "
                    "more susceptible to corner-enhanced field stress."
                )
            if process_split:
                structure_links.append(
                    f"Process split {process_split} — check whether corner/edge device "
                    "performance varies systematically across splits."
                )
            uncertainty_notes = [
                "Corner effect and true device degradation are not mutually exclusive; "
                "both may be contributing."
            ]
            if control_passed:
                evidence_for.append(
                    "Control device (centre position) is healthy — the spatial localisation "
                    "of degradation to corner/edge devices supports a layout- or field-stress-dependent effect."
                )

        elif has_rapid_degradation:
            hypotheses = ["TRUE_DEVICE_DEGRADATION"]
            evidence_for = [
                f"Leakage trend state is '{trend_state}', indicating consistent degradation.",
            ]
            if control_passed:
                evidence_for.append(
                    "Control device is healthy — this confirms the degradation is local "
                    "to this device rather than a setup artefact."
                )
            if has_spatial_anomaly:
                hypotheses.append("LOCAL_SPATIAL_DEFECT")
                evidence_for.append(
                    "Device leakage is significantly elevated relative to its neighbours, "
                    "suggesting a localised defect rather than a uniform process shift."
                )
            uncertainty_notes = [
                "Evidence is consistent with intrinsic dielectric breakdown progression; "
                "however pre-existing microscopic defects cannot be ruled out without "
                "post-failure physical analysis."
            ]

        elif has_spatial_anomaly:
            hypotheses = ["LOCAL_SPATIAL_DEFECT"]
            if is_corner_or_edge:
                hypotheses = ["CORNER_EFFECT", "LOCAL_SPATIAL_DEFECT"]
            evidence_for = [
                "Leakage current is significantly elevated compared to spatial neighbours."
            ]
            if process_split:
                hypotheses.append("PROCESS_SPLIT_WEAKNESS")
                structure_links.append(
                    f"Process split {process_split}: spatial clustering within a split "
                    "may indicate a process-linked yield weakness."
                )
            uncertainty_notes = [
                "Spatial anomaly alone is insufficient to distinguish a true device defect "
                "from a probe alignment issue — a control device check is recommended."
            ]

        elif process_split and suspicion_score > 0.3:
            hypotheses = ["PROCESS_SPLIT_WEAKNESS", "TRUE_DEVICE_DEGRADATION"]
            evidence_for = [
                f"Device belongs to process split {process_split} and shows elevated suspicion."
            ]
            structure_links = [
                f"Process split {process_split} may have structural or compositional "
                "differences that affect reliability; compare with devices from other splits."
            ]
            if known_risks:
                structure_links.append(f"Known risk: {known_risks[0]}")
            uncertainty_notes = [
                "A single device is insufficient to conclude a split-level weakness; "
                "a systematic comparison across all splits is needed."
            ]

        else:
            hypotheses = ["TRUE_DEVICE_DEGRADATION"]
            evidence_for = [
                "Measured leakage trend is consistent with progressive dielectric degradation."
            ]
            uncertainty_notes = [
                "Suspicion level is low; current evidence is not sufficient for a "
                "definitive conclusion."
            ]

        if not structure and not fab_ctx:
            uncertainty_notes.append(
                "No device structure or fabrication metadata was provided; "
                "structure- and process-based reasoning is not possible for this device."
            )

        # Deduplicate while preserving order
        hypotheses = list(dict.fromkeys(hypotheses))

        # --- Choose action ---
        action, action_reason = self._choose_action(
            allowed_actions=allowed_actions,
            control_failed=control_failed,
            has_contact_issue=has_contact_issue,
            has_rapid_degradation=has_rapid_degradation,
            suspicion_score=suspicion_score,
            control_summary=control_summary,
        )

        # --- Build note text ---
        hyp_str = " and ".join(hypotheses[:2]) if hypotheses else "no specific failure mode identified"
        fab_note = f" Fabrication note: {known_risks[0]}." if known_risks else ""
        ctrl_note = (
            f" Control device result: {control_result}." if control_result else ""
        )
        note_text = (
            f"LLM analysis [{event_type}] for {device_id}: "
            f"Primary evidence supports {hyp_str}.{fab_note}{ctrl_note} "
            f"Trend state: {trend_state}. "
            + (
                "Evidence strength is moderate; additional measurements are "
                "recommended before drawing firm conclusions."
                if suspicion_score < 0.65
                else "Evidence is consistent with a meaningful device-level event."
            )
        )

        return {
            "primary_hypotheses": hypotheses[:3],
            "evidence_for": evidence_for[:4],
            "evidence_against": evidence_against[:2],
            "uncertainty_notes": uncertainty_notes[:3],
            "structure_or_process_links": structure_links[:3],
            "recommended_action": action,
            "recommended_action_reason": action_reason,
            "note_text": note_text,
        }

    @staticmethod
    def _choose_action(
        allowed_actions: list[str],
        control_failed: bool,
        has_contact_issue: bool,
        has_rapid_degradation: bool,
        suspicion_score: float,
        control_summary: dict,
    ) -> tuple[str, str]:
        def pick(preferred: list[str], fallback: str = "CONTINUE_STRESS") -> tuple[str, str]:
            for a in preferred:
                if a in allowed_actions:
                    return a, ""
            return (
                allowed_actions[0] if allowed_actions else fallback,
                "Default action from allowed set.",
            )

        if control_failed:
            a, _ = pick(["escalate_and_pause", "escalate_and_continue"])
            return a, (
                "Control device failure indicates setup instability; "
                "human intervention is required before further stressing devices."
            )

        control_checked = bool(control_summary)
        if has_contact_issue and not control_checked:
            a, _ = pick(["check_control_device"])
            return a, (
                "Contact issue detected; verifying via control device is the most "
                "diagnostic next step before concluding on probe wear."
            )

        if has_rapid_degradation:
            a, _ = pick(["switch_to_dense_monitoring", "continue_stress"])
            return a, (
                "Rapid degradation trend detected; increasing measurement density "
                "to track breakdown approach more accurately."
            )

        if suspicion_score > 0.55 and not control_checked:
            a, _ = pick(["check_control_device", "continue_stress"])
            return a, (
                "Elevated suspicion with no control check performed yet; "
                "a control device check would disambiguate device vs. setup issues."
            )

        a, _ = pick(["continue_stress"])
        return a, (
            "No immediate diagnostic concern; proceeding with standard stress protocol."
        )

    @staticmethod
    def _default_result() -> dict:
        return {
            "primary_hypotheses": ["TRUE_DEVICE_DEGRADATION"],
            "evidence_for": ["Insufficient context to evaluate."],
            "evidence_against": [],
            "uncertainty_notes": ["Context could not be parsed — using conservative default."],
            "structure_or_process_links": [],
            "recommended_action": "CONTINUE_STRESS",
            "recommended_action_reason": "Default safe action — context parsing failed.",
            "note_text": "LLM mock: context parsing failed; defaulting to conservative response.",
        }


# ---------------------------------------------------------------------------
# OpenAI-compatible REST backend
# ---------------------------------------------------------------------------

class OpenAILikeClient(LLMClient):
    """
    Calls any OpenAI-compatible REST API using only stdlib (urllib).

    Compatible with:
    - OpenAI API  (base_url = "https://api.openai.com/v1")
    - Ollama      (base_url = "http://localhost:11434/v1")
    - vLLM        (base_url = "http://localhost:8000/v1")
    - LM Studio   (base_url = "http://localhost:1234/v1")
    - Azure OpenAI (set base_url accordingly)
    """

    def __init__(
        self,
        api_key: str,
        model_name: str,
        base_url: str = "https://api.openai.com/v1",
        temperature: float = 0.2,
        max_tokens: int = 1024,
        timeout_s: int = 60,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s

    def complete(self, system_prompt: str, user_content: str) -> str:
        import urllib.request
        import urllib.error

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            logger.error("LLM HTTP error %s: %s", exc.code, body_text[:400])
            return ""
        except Exception as exc:
            logger.error("LLM request failed: %s", exc)
            return ""


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------

def build_client(mode: str, **kwargs) -> LLMClient:
    """
    Build an LLMClient from a mode string.

    mode options: "disabled" | "mock" | "openai_like"
    kwargs are forwarded to OpenAILikeClient when mode == "openai_like".
    """
    if mode == "disabled":
        return NoOpLLMClient()
    if mode == "mock":
        return MockLLMClient()
    if mode == "openai_like":
        return OpenAILikeClient(**kwargs)
    logger.warning("Unknown LLM mode %r; falling back to mock.", mode)
    return MockLLMClient()
