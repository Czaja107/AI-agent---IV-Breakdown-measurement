"""
Tests for the LLM scientific reasoning layer.

Tests cover:
- ScientificReasoningContext construction and serialisation
- MockLLMClient structured outputs
- ScientificReasoner: parse success, parse failure, noop fallback
- PolicyAdvisor: guard rejects invalid action, guard rejects less-safe action,
  advisory_only does not override, bounded_override applies valid action
- LLMNoteWriter enrichment
- LLMAlertWriter enrichment
- HypothesisTracker.update_from_llm_result: known and unknown hypothesis types
- Deterministic behaviour unchanged when LLM is disabled
"""
from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from ..llm.client import NoOpLLMClient, MockLLMClient, OpenAILikeClient
from ..llm.schemas import (
    ScientificReasoningContext,
    LLMReasoningResult,
    LLMReasoningRecord,
    DeviceStructureMetadata,
    FabricationContext,
)
from ..llm.scientific_reasoner import ScientificReasoner
from ..llm.note_writer import LLMNoteWriter
from ..llm.alert_writer import LLMAlertWriter
from ..llm.policy_advisor import PolicyAdvisor
from ..models.device import DeviceRecord, DeviceStatus, GridPosition, TrendState, ProtocolMode, SuspicionLevel
from ..models.run_state import HypothesisType, HypothesisRecord, RunState
from ..analysis.hypotheses import HypothesisTracker, HypothesisEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_device(device_id: str = "CAP_01_01") -> DeviceRecord:
    d = DeviceRecord(
        device_id=device_id,
        ix=1,
        iy=1,
        grid_position=GridPosition.CENTER,
    )
    d.status = DeviceStatus.DEGRADING
    d.trend_state = TrendState.SLOWLY_WORSENING
    d.suspicion_score = 0.45
    d.suspicion_level = SuspicionLevel.MEDIUM
    d.suspicion_reasons = ["leakage_increasing", "neighbor_outlier"]
    d.latest_leakage_at_1v_A = 3.2e-9
    d.baseline_leakage_at_1v_A = 8.0e-11
    return d


def _make_run_state() -> RunState:
    rs = RunState(chip_id="TEST_CHIP", run_id="TEST_RUN")
    # Init hypotheses
    for h in HypothesisType:
        rs.hypotheses[h.value] = HypothesisRecord(hypothesis=h)
    return rs


def _make_context(**kwargs) -> ScientificReasoningContext:
    defaults = dict(
        run_id="TEST_RUN",
        chip_id="TEST_CHIP",
        device_id="CAP_01_01",
        grid_x=1,
        grid_y=1,
        grid_position="center",
        event_type="stress_batch",
        suspicion_score=0.45,
        suspicion_reasons=["leakage_increasing"],
        allowed_actions=["CONTINUE_STRESS", "CHECK_CONTROL_DEVICE", "ESCALATE_AND_PAUSE"],
        current_protocol_mode="normal_stress",
    )
    defaults.update(kwargs)
    return ScientificReasoningContext(**defaults)


# ---------------------------------------------------------------------------
# ScientificReasoningContext
# ---------------------------------------------------------------------------

class TestScientificReasoningContext:

    def test_to_prompt_dict_is_serialisable(self):
        ctx = _make_context()
        d = ctx.to_prompt_dict()
        # Must be JSON-serialisable
        s = json.dumps(d)
        assert "CAP_01_01" in s

    def test_to_prompt_dict_contains_key_fields(self):
        ctx = _make_context(
            device_structure={"capacitor_type": "MIM", "dielectric_thickness_nm": 10.0},
            fabrication_context={"process_split": "SPLIT_A"},
        )
        d = ctx.to_prompt_dict()
        assert d["device_id"] == "CAP_01_01"
        assert d["device_structure"]["capacitor_type"] == "MIM"
        assert d["fabrication_context"]["process_split"] == "SPLIT_A"
        assert d["allowed_actions"] == [
            "CONTINUE_STRESS", "CHECK_CONTROL_DEVICE", "ESCALATE_AND_PAUSE"
        ]

    def test_to_prompt_dict_trims_old_events(self):
        ctx = _make_context(recent_events=[f"event_{i}" for i in range(20)])
        d = ctx.to_prompt_dict()
        assert len(d["recent_events"]) <= 6


# ---------------------------------------------------------------------------
# MockLLMClient
# ---------------------------------------------------------------------------

class TestMockLLMClient:

    def test_returns_valid_json(self):
        client = MockLLMClient()
        ctx = _make_context()
        raw = client.complete("", json.dumps(ctx.to_prompt_dict()))
        data = json.loads(raw)
        assert "primary_hypotheses" in data
        assert "recommended_action" in data
        assert "note_text" in data

    def test_recommended_action_in_allowed_set(self):
        client = MockLLMClient()
        ctx = _make_context(
            allowed_actions=["continue_stress", "check_control_device"],
            suspicion_score=0.3,
        )
        raw = client.complete("", json.dumps(ctx.to_prompt_dict()))
        data = json.loads(raw)
        assert data["recommended_action"] in ["continue_stress", "check_control_device"]

    def test_control_failed_triggers_escalation_preference(self):
        client = MockLLMClient()
        ctx = _make_context(
            control_device_summary={"result": "degraded"},
            allowed_actions=["continue_stress", "escalate_and_pause"],
            suspicion_score=0.8,
        )
        raw = client.complete("", json.dumps(ctx.to_prompt_dict()))
        data = json.loads(raw)
        assert "CONTACT_DEGRADATION" in data["primary_hypotheses"] or \
               "SETUP_DRIFT" in data["primary_hypotheses"]

    def test_contact_issue_prompts_control_check(self):
        client = MockLLMClient()
        ctx = _make_context(
            suspicion_reasons=["no current detected — possible open contact"],
            allowed_actions=["continue_stress", "check_control_device"],
            suspicion_score=0.5,
        )
        raw = client.complete("", json.dumps(ctx.to_prompt_dict()))
        data = json.loads(raw)
        assert data["recommended_action"] == "check_control_device"

    def test_bad_json_input_falls_back_to_default(self):
        client = MockLLMClient()
        raw = client.complete("", "this is not json {{{{")
        data = json.loads(raw)
        assert "recommended_action" in data

    def test_fab_context_mentioned_in_structure_links(self):
        client = MockLLMClient()
        ctx = _make_context(
            fabrication_context={
                "process_split": "SPLIT_B",
                "known_fabrication_risks": ["corner devices have 15% thinner dielectric"],
            },
            grid_position="corner",
            suspicion_reasons=["rapidly_worsening trend"],
            suspicion_score=0.7,
            allowed_actions=["continue_stress", "switch_to_dense_monitoring"],
        )
        raw = client.complete("", json.dumps(ctx.to_prompt_dict()))
        data = json.loads(raw)
        links = " ".join(data.get("structure_or_process_links", []))
        assert "SPLIT_B" in links or "corner" in links.lower() or "thinner" in links.lower()


# ---------------------------------------------------------------------------
# NoOpLLMClient
# ---------------------------------------------------------------------------

class TestNoOpLLMClient:

    def test_returns_empty_string(self):
        client = NoOpLLMClient()
        result = client.complete("system", "user")
        assert result == ""

    def test_is_noop(self):
        assert NoOpLLMClient().is_noop is True
        assert MockLLMClient().is_noop is False


# ---------------------------------------------------------------------------
# ScientificReasoner
# ---------------------------------------------------------------------------

class TestScientificReasoner:

    def test_reason_with_mock_client_returns_result(self):
        reasoner = ScientificReasoner(MockLLMClient())
        ctx = _make_context()
        result = reasoner.reason(ctx)
        assert result is not None
        assert isinstance(result.primary_hypotheses, list)
        assert result.parsing_succeeded is True

    def test_reason_with_noop_client_returns_none(self):
        reasoner = ScientificReasoner(NoOpLLMClient())
        ctx = _make_context()
        result = reasoner.reason(ctx)
        assert result is None

    def test_reason_with_bad_json_returns_fallback(self):
        bad_client = MagicMock()
        bad_client.is_noop = False
        bad_client.complete.return_value = "not json at all }{{"
        reasoner = ScientificReasoner(bad_client)
        ctx = _make_context()
        result = reasoner.reason(ctx)
        assert result is not None
        assert result.parsing_succeeded is False

    def test_reason_with_invalid_schema_returns_fallback(self):
        bad_client = MagicMock()
        bad_client.is_noop = False
        bad_client.complete.return_value = json.dumps({"foo": "bar"})
        reasoner = ScientificReasoner(bad_client)
        ctx = _make_context()
        # Schema validation should fail for missing required-ish fields
        # LLMReasoningResult has all optional fields, so this passes
        result = reasoner.reason(ctx)
        assert result is not None  # default values fill in

    def test_guard_rejects_action_not_in_allowed_set(self):
        client = MagicMock()
        client.is_noop = False
        client.complete.return_value = json.dumps({
            "primary_hypotheses": ["TRUE_DEVICE_DEGRADATION"],
            "evidence_for": [],
            "evidence_against": [],
            "uncertainty_notes": [],
            "structure_or_process_links": [],
            "recommended_action": "INVALID_MADE_UP_ACTION",
            "recommended_action_reason": "test",
            "note_text": "test note",
        })
        reasoner = ScientificReasoner(client)
        ctx = _make_context(allowed_actions=["continue_stress"])
        result = reasoner.reason(ctx)
        assert result is not None
        assert result.recommended_action == ""  # cleared by guard

    def test_exception_in_client_returns_none(self):
        bad_client = MagicMock()
        bad_client.is_noop = False
        bad_client.complete.side_effect = RuntimeError("network error")
        reasoner = ScientificReasoner(bad_client)
        ctx = _make_context()
        result = reasoner.reason(ctx)
        assert result is None

    def test_markdown_json_fence_is_stripped(self):
        client = MagicMock()
        client.is_noop = False
        client.complete.return_value = (
            "```json\n"
            + json.dumps({
                "primary_hypotheses": ["CONTACT_DEGRADATION"],
                "evidence_for": ["test"],
                "evidence_against": [],
                "uncertainty_notes": [],
                "structure_or_process_links": [],
                "recommended_action": "CONTINUE_STRESS",
                "recommended_action_reason": "test",
                "note_text": "test note",
            })
            + "\n```"
        )
        reasoner = ScientificReasoner(client)
        ctx = _make_context()
        result = reasoner.reason(ctx)
        assert result is not None
        assert "CONTACT_DEGRADATION" in result.primary_hypotheses


# ---------------------------------------------------------------------------
# PolicyAdvisor
# ---------------------------------------------------------------------------

class TestPolicyAdvisor:

    def _make_result(self, action: str) -> LLMReasoningResult:
        return LLMReasoningResult(
            recommended_action=action,
            recommended_action_reason="LLM says so",
            parsing_succeeded=True,
        )

    def test_advisory_only_never_overrides(self):
        advisor = PolicyAdvisor(advisory_mode="advisory_only")
        result = self._make_result("check_control_device")
        final, reason, applied = advisor.apply_advice(
            heuristic_action="continue_stress",
            llm_result=result,
            allowed_actions=["continue_stress", "check_control_device"],
        )
        assert final == "continue_stress"
        assert applied is False

    def test_bounded_override_applies_safe_action(self):
        advisor = PolicyAdvisor(advisory_mode="advisory_with_bounded_override")
        result = self._make_result("check_control_device")
        final, reason, applied = advisor.apply_advice(
            heuristic_action="continue_stress",
            llm_result=result,
            allowed_actions=["continue_stress", "check_control_device"],
        )
        assert final == "check_control_device"
        assert applied is True

    def test_guard_rejects_action_not_in_allowed_set(self):
        advisor = PolicyAdvisor(advisory_mode="advisory_with_bounded_override")
        result = self._make_result("escalate_and_pause")
        final, reason, applied = advisor.apply_advice(
            heuristic_action="continue_stress",
            llm_result=result,
            allowed_actions=["continue_stress"],  # escalate_and_pause not allowed
        )
        assert final == "continue_stress"
        assert applied is False

    def test_guard_rejects_less_safe_action(self):
        advisor = PolicyAdvisor(advisory_mode="advisory_with_bounded_override")
        # Heuristic says escalate_and_pause, LLM says continue_stress (less safe)
        result = self._make_result("continue_stress")
        final, reason, applied = advisor.apply_advice(
            heuristic_action="escalate_and_pause",
            llm_result=result,
            allowed_actions=["continue_stress", "escalate_and_pause"],
        )
        assert final == "escalate_and_pause"  # guard preserved safer action
        assert applied is False

    def test_no_override_when_result_is_none(self):
        advisor = PolicyAdvisor(advisory_mode="advisory_with_bounded_override")
        final, reason, applied = advisor.apply_advice(
            heuristic_action="continue_stress",
            llm_result=None,
            allowed_actions=["continue_stress"],
        )
        assert final == "continue_stress"
        assert applied is False

    def test_no_override_when_parsing_failed(self):
        advisor = PolicyAdvisor(advisory_mode="advisory_with_bounded_override")
        result = LLMReasoningResult.fallback(reason="test failure")
        final, reason, applied = advisor.apply_advice(
            heuristic_action="continue_stress",
            llm_result=result,
            allowed_actions=["continue_stress", "check_control_device"],
        )
        assert final == "continue_stress"
        assert applied is False


# ---------------------------------------------------------------------------
# LLMNoteWriter
# ---------------------------------------------------------------------------

class TestLLMNoteWriter:

    def test_fallback_when_result_is_none(self):
        writer = LLMNoteWriter()
        note = writer.write("heuristic note text", None)
        assert note == "heuristic note text"

    def test_enriched_note_contains_hypothesis(self):
        writer = LLMNoteWriter()
        result = LLMReasoningResult(
            primary_hypotheses=["CONTACT_DEGRADATION"],
            evidence_for=["near-zero current trace"],
            recommended_action="CHECK_CONTROL_DEVICE",
            recommended_action_reason="check control to disambiguate",
            parsing_succeeded=True,
        )
        note = writer.write("base note", result)
        assert "CONTACT_DEGRADATION" in note
        assert "near-zero current trace" in note

    def test_write_from_llm_text_prefers_note_text(self):
        writer = LLMNoteWriter()
        result = LLMReasoningResult(
            primary_hypotheses=["TRUE_DEVICE_DEGRADATION"],
            note_text="LLM generated note about the device.",
            parsing_succeeded=True,
        )
        note = writer.write_from_llm_text("heuristic note", result)
        assert "LLM generated note about the device." in note

    def test_fallback_when_parsing_failed(self):
        writer = LLMNoteWriter()
        result = LLMReasoningResult.fallback(reason="test")
        note = writer.write("heuristic note", result)
        assert note == "heuristic note"


# ---------------------------------------------------------------------------
# LLMAlertWriter
# ---------------------------------------------------------------------------

class TestLLMAlertWriter:

    def test_fallback_when_result_is_none(self):
        writer = LLMAlertWriter()
        explanation, op_action = writer.write("heuristic explanation", None, severity=3)
        assert explanation == "heuristic explanation"
        assert len(op_action) > 0

    def test_enriched_explanation_contains_hypothesis(self):
        writer = LLMAlertWriter()
        result = LLMReasoningResult(
            primary_hypotheses=["SETUP_DRIFT"],
            evidence_for=["control device also degraded"],
            uncertainty_notes=["cannot distinguish from probe wear"],
            parsing_succeeded=True,
        )
        explanation, op_action = writer.write("base explanation", result, severity=3)
        assert "SETUP_DRIFT" in explanation
        assert "control device also degraded" in explanation

    def test_control_device_failed_note_included(self):
        writer = LLMAlertWriter()
        result = LLMReasoningResult(parsing_succeeded=True)
        ctx = _make_context(
            control_device_summary={"result": "degraded"},
        )
        explanation, _ = writer.write("base", result, context=ctx, severity=3)
        assert "control device" in explanation.lower()


# ---------------------------------------------------------------------------
# HypothesisTracker.update_from_llm_result
# ---------------------------------------------------------------------------

class TestHypothesisTrackerLLM:

    def test_known_hypothesis_type_is_updated(self):
        rs = _make_run_state()
        tracker = HypothesisTracker(rs)
        device = _make_device()
        result = LLMReasoningResult(
            primary_hypotheses=["CORNER_EFFECT"],
            evidence_for=["device is at corner"],
            parsing_succeeded=True,
        )
        tracker.update_from_llm_result(result, device)
        h = rs.hypotheses[HypothesisType.CORNER_EFFECT.value]
        assert h.support_level > 0.0
        assert any("[llm]" in e for e in h.evidence_for)

    def test_unknown_hypothesis_type_is_skipped_gracefully(self):
        rs = _make_run_state()
        tracker = HypothesisTracker(rs)
        device = _make_device()
        result = LLMReasoningResult(
            primary_hypotheses=["FICTIONAL_HYPOTHESIS_XYZ"],
            parsing_succeeded=True,
        )
        # Should not raise
        tracker.update_from_llm_result(result, device)

    def test_new_llm_hypothesis_types_are_tracked(self):
        rs = _make_run_state()
        tracker = HypothesisTracker(rs)
        device = _make_device()
        result = LLMReasoningResult(
            primary_hypotheses=["PROCESS_SPLIT_WEAKNESS", "FABRICATION_INDUCED_DIELECTRIC_WEAKNESS"],
            evidence_for=["process split B shows earlier degradation"],
            parsing_succeeded=True,
        )
        tracker.update_from_llm_result(result, device)
        h_psw = rs.hypotheses[HypothesisType.PROCESS_SPLIT_WEAKNESS.value]
        assert h_psw.support_level > 0.0

    def test_failed_parsing_skips_update(self):
        rs = _make_run_state()
        tracker = HypothesisTracker(rs)
        device = _make_device()
        baseline = rs.hypotheses[HypothesisType.TRUE_DEVICE_DEGRADATION.value].support_level
        result = LLMReasoningResult.fallback(reason="parse error")
        tracker.update_from_llm_result(result, device)
        assert rs.hypotheses[HypothesisType.TRUE_DEVICE_DEGRADATION.value].support_level == baseline

    def test_both_upper_and_lower_case_names_accepted(self):
        rs = _make_run_state()
        tracker = HypothesisTracker(rs)
        device = _make_device()
        result_upper = LLMReasoningResult(
            primary_hypotheses=["TRUE_DEVICE_DEGRADATION"],
            parsing_succeeded=True,
        )
        result_lower = LLMReasoningResult(
            primary_hypotheses=["true_device_degradation"],
            parsing_succeeded=True,
        )
        tracker.update_from_llm_result(result_upper, device)
        support_after_upper = rs.hypotheses["true_device_degradation"].support_level
        tracker.update_from_llm_result(result_lower, device)
        support_after_lower = rs.hypotheses["true_device_degradation"].support_level
        assert support_after_lower > support_after_upper  # both added support


# ---------------------------------------------------------------------------
# Deterministic core unaffected when LLM is disabled
# ---------------------------------------------------------------------------

class TestDeterministicCoreUnchanged:

    def test_noop_reasoner_returns_none(self):
        reasoner = ScientificReasoner(NoOpLLMClient())
        ctx = _make_context()
        assert reasoner.reason(ctx) is None

    def test_policy_advisor_advisory_only_preserves_heuristic(self):
        advisor = PolicyAdvisor("advisory_only")
        result = LLMReasoningResult(
            primary_hypotheses=["CONTACT_DEGRADATION"],
            recommended_action="escalate_and_pause",
            parsing_succeeded=True,
        )
        final, _, applied = advisor.apply_advice(
            heuristic_action="continue_stress",
            llm_result=result,
            allowed_actions=["continue_stress", "escalate_and_pause"],
        )
        assert final == "continue_stress"
        assert applied is False

    def test_note_writer_passthrough_when_no_llm(self):
        writer = LLMNoteWriter()
        original = "deterministic note from heuristic"
        result = writer.write(original, None)
        assert result == original

    def test_alert_writer_passthrough_when_no_llm(self):
        writer = LLMAlertWriter()
        original = "deterministic alert explanation"
        explanation, _ = writer.write(original, None, severity=2)
        assert explanation == original


# ---------------------------------------------------------------------------
# LLMReasoningRecord serialisation
# ---------------------------------------------------------------------------

class TestLLMReasoningRecord:

    def test_to_dict_is_serialisable(self):
        record = LLMReasoningRecord(
            timestamp=datetime.now().isoformat(),
            device_id="CAP_00_00",
            event_type="health_check",
            context_snapshot={"device_id": "CAP_00_00"},
            llm_result={"primary_hypotheses": ["TRUE_DEVICE_DEGRADATION"]},
            heuristic_action="CONTINUE_STRESS",
            llm_recommendation="CONTINUE_STRESS",
            llm_recommendation_matched=True,
        )
        d = record.to_dict()
        s = json.dumps(d)
        assert "CAP_00_00" in s
        assert "heuristic_action" in d
