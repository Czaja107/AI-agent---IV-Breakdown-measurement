"""
Chip map generator.

Produces a CSV file with one row per device containing all key metrics,
suitable for further analysis in spreadsheet tools or pandas.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config.schema import AgentConfig
    from ..models.run_state import RunState


class ChipMapGenerator:
    """Writes chip_map.csv with per-device summary metrics."""

    COLUMNS = [
        "device_id", "ix", "iy", "grid_position",
        "status", "trend_state", "suspicion_level", "suspicion_score",
        "is_control_device",
        "baseline_leakage_at_1v_A", "latest_leakage_at_1v_A",
        "latest_breakdown_voltage_V", "leakage_ratio_vs_baseline",
        "stress_batch_count", "stress_cycles_total", "breakdown_events",
        "n_measurements", "confirmatory_count", "inconsistent_confirmatory_count",
        "suspicion_reasons",
    ]

    def __init__(self, config: "AgentConfig") -> None:
        self.config = config

    def save_csv(self, run_state: "RunState", output_dir: Path) -> Path:
        """Write chip_map.csv and return its path."""
        out_path = output_dir / "chip_map.csv"
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.COLUMNS)
            writer.writeheader()
            for dev_id in run_state.device_order:
                dev = run_state.devices.get(dev_id)
                if dev is None:
                    continue
                leakage_ratio = dev.leakage_ratio_vs_baseline()
                writer.writerow({
                    "device_id": dev.device_id,
                    "ix": dev.ix,
                    "iy": dev.iy,
                    "grid_position": dev.grid_position.value,
                    "status": dev.status.value,
                    "trend_state": dev.trend_state.value,
                    "suspicion_level": dev.suspicion_level.value,
                    "suspicion_score": round(dev.suspicion_score, 3),
                    "is_control_device": dev.is_control_device,
                    "baseline_leakage_at_1v_A": _fmt(dev.baseline_leakage_at_1v_A),
                    "latest_leakage_at_1v_A": _fmt(dev.latest_leakage_at_1v_A),
                    "latest_breakdown_voltage_V": _fmt(dev.latest_breakdown_voltage_V),
                    "leakage_ratio_vs_baseline": _fmt(leakage_ratio),
                    "stress_batch_count": dev.stress_batch_count,
                    "stress_cycles_total": dev.stress_cycles_total,
                    "breakdown_events": dev.breakdown_events,
                    "n_measurements": len(dev.iv_curves),
                    "confirmatory_count": dev.confirmatory_count,
                    "inconsistent_confirmatory_count": dev.inconsistent_confirmatory_count,
                    "suspicion_reasons": "; ".join(dev.suspicion_reasons[:3]),
                })
        return out_path


def _fmt(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float):
        return f"{val:.4e}"
    return str(val)
