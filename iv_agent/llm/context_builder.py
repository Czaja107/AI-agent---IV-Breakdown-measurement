"""
ContextBuilder — assembles a ScientificReasoningContext from live agent state.

Called by the orchestration layer after heuristic analysis is complete.
Pulls together device metrics, trends, neighbours, hypotheses, control-device
status, and optional variant metadata into a single serialisable object that
can be JSON-encoded for the LLM prompt.
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from .schemas import ScientificReasoningContext

if TYPE_CHECKING:
    from ..models.device import DeviceRecord
    from ..models.run_state import RunState
    from ..models.measurement import IVMetrics
    from ..analysis.trends import TrendFeatures
    from ..analysis.neighbors import NeighborComparison
    from ..analysis.suspicion import SuspicionResult
    from ..config.schema import AgentConfig


class ContextBuilder:
    """
    Builds a ScientificReasoningContext suitable for LLM prompting.

    The builder is stateless — call build() multiple times with different
    arguments.
    """

    def __init__(self, config: "AgentConfig") -> None:
        self.config = config
        # Build variant lookup: device_id -> (variant_id, structure_dict, fab_dict)
        self._variant_map: dict[str, tuple[str, dict, dict]] = {}
        self._build_variant_map()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def build(
        self,
        device: "DeviceRecord",
        run_state: "RunState",
        event_type: str,
        allowed_actions: list[str],
        metrics: Optional["IVMetrics"] = None,
        trend_features: Optional["TrendFeatures"] = None,
        neighbor_comparison: Optional["NeighborComparison"] = None,
        suspicion_result: Optional["SuspicionResult"] = None,
    ) -> ScientificReasoningContext:
        """Assemble and return a ScientificReasoningContext."""

        variant_id, structure_dict, fab_dict = self._variant_map.get(
            device.device_id, ("", {}, {})
        )

        return ScientificReasoningContext(
            run_id=self.config.run.run_id,
            chip_id=self.config.run.chip_id,
            device_id=device.device_id,
            grid_x=device.ix,
            grid_y=device.iy,
            grid_position=device.grid_position.value,
            event_type=event_type,
            variant_id=variant_id,
            device_structure=structure_dict,
            fabrication_context=fab_dict,
            latest_measurement_summary=self._measurement_summary(device, metrics),
            temporal_trend_summary=self._trend_summary(device, trend_features),
            neighborhood_summary=self._neighbor_summary(device, neighbor_comparison),
            control_device_summary=self._control_summary(run_state),
            suspicion_score=device.suspicion_score,
            suspicion_reasons=list(device.suspicion_reasons),
            active_hypotheses=self._active_hypotheses(run_state),
            recent_events=self._recent_events(device, run_state),
            allowed_actions=allowed_actions,
            current_protocol_mode=device.protocol_mode.value,
        )

    # -----------------------------------------------------------------------
    # Summary builders (each returns a plain dict for JSON encoding)
    # -----------------------------------------------------------------------

    @staticmethod
    def _measurement_summary(
        device: "DeviceRecord", metrics: Optional["IVMetrics"]
    ) -> dict:
        d: dict = {
            "status": device.status.value,
            "n_measurements_total": len(device.metrics_history),
            "stress_batch_count": device.stress_batch_count,
            "breakdown_events": device.breakdown_events,
        }
        if metrics is not None:
            d["leakage_at_1v_A"] = _fmt(metrics.leakage_at_1v_A)
            d["breakdown_voltage_V"] = metrics.breakdown_voltage_V
            d["compliance_hit"] = metrics.compliance_hit
            d["looks_healthy"] = metrics.looks_healthy
            d["noise_std_A"] = _fmt(metrics.noise_std_A)
        if device.baseline_leakage_at_1v_A:
            d["baseline_leakage_at_1v_A"] = _fmt(device.baseline_leakage_at_1v_A)
        ratio = device.leakage_ratio_vs_baseline()
        if ratio is not None:
            d["leakage_ratio_vs_baseline"] = round(ratio, 2)
        return d

    @staticmethod
    def _trend_summary(
        device: "DeviceRecord", tf: Optional["TrendFeatures"]
    ) -> dict:
        d: dict = {"trend_state": device.trend_state.value}
        if tf is not None:
            d["worsening_rate"] = round(tf.worsening_rate, 4)
            d["leakage_trend_slope"] = round(tf.leakage_trend_slope, 6)
            d["leakage_acceleration"] = round(tf.leakage_acceleration, 6)
            d["n_measurements"] = tf.n_measurements
            d["leakage_ratio_first_last"] = round(tf.leakage_ratio_first_last, 3)
            d["fraction_compliance_hit"] = round(tf.fraction_compliance_hit, 3)
        return d

    @staticmethod
    def _neighbor_summary(
        device: "DeviceRecord", nc: Optional["NeighborComparison"]
    ) -> dict:
        if nc is None:
            return {}
        return {
            "n_neighbors_found": nc.n_neighbors_found,
            "neighbor_median_leakage_A": _fmt(nc.neighbor_median_leakage_A)
            if nc.neighbor_median_leakage_A else None,
            "leakage_ratio_vs_neighbors": round(nc.leakage_ratio, 2),
            "is_outlier_high": nc.is_outlier_high,
            "is_outlier_low": nc.is_outlier_low,
            "is_in_cluster": nc.is_in_cluster,
        }

    @staticmethod
    def _control_summary(run_state: "RunState") -> dict:
        if run_state.control_device_last_checked is None:
            return {}
        return {
            "result": "healthy" if run_state.control_device_healthy else "degraded",
            "last_checked": run_state.control_device_last_checked.isoformat()
            if run_state.control_device_last_checked else None,
        }

    @staticmethod
    def _active_hypotheses(run_state: "RunState") -> list[dict]:
        return [
            {
                "hypothesis": h.hypothesis.value,
                "support_level": round(h.support_level, 3),
                "active": h.active,
                "top_evidence": h.evidence_for[:2],
            }
            for h in sorted(
                run_state.hypotheses.values(),
                key=lambda x: x.support_level,
                reverse=True,
            )
            if h.support_level > 0.05
        ][:6]

    @staticmethod
    def _recent_events(device: "DeviceRecord", run_state: "RunState") -> list[str]:
        events: list[str] = []
        # Last few device notes
        for note in device.device_notes[-3:]:
            events.append(f"[device_note] {note[:120]}")
        # Last few global notes
        for note in run_state.notes[-4:]:
            if not note.device_id or note.device_id == device.device_id:
                events.append(f"[{note.category}] {note.body[:120]}")
        return events[-8:]

    # -----------------------------------------------------------------------
    # Variant map
    # -----------------------------------------------------------------------

    def _build_variant_map(self) -> None:
        """Pre-compute device_id -> (variant_id, structure_dict, fab_dict) mapping."""
        variants = getattr(self.config, "variants", []) or []
        chip_fab = getattr(self.config, "chip_fabrication_context", None)
        chip_fab_dict = chip_fab.to_prompt_dict() if chip_fab else {}

        for variant in variants:
            v_id: str = getattr(variant, "variant_id", "")
            structure = getattr(variant, "device_structure", None)
            fab = getattr(variant, "fabrication_context", None)
            s_dict = structure.to_prompt_dict() if structure else {}
            f_dict = fab.to_prompt_dict() if fab else {}

            # Merge chip-level fab context as a fallback
            merged_fab = {**chip_fab_dict, **f_dict}

            for dev_id in getattr(variant, "device_ids", []):
                self._variant_map[dev_id] = (v_id, s_dict, merged_fab)

        # For devices not in any variant, still attach chip-level fab context
        self._chip_fab_dict = chip_fab_dict

    def get_variant_info(self, device_id: str) -> tuple[str, dict, dict]:
        """Return (variant_id, structure_dict, fab_dict) for a device ID."""
        if device_id in self._variant_map:
            return self._variant_map[device_id]
        return ("", {}, self._chip_fab_dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(v: Optional[float]) -> Optional[str]:
    """Format a float in scientific notation for readability."""
    if v is None:
        return None
    return f"{v:.3e}"
