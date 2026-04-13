"""
Run summary writer.

Produces:
  - summary.md   — human-readable markdown summary of the full run
  - summary.json — machine-readable summary dict
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config.schema import AgentConfig
    from ..models.run_state import RunState


class SummaryWriter:
    """Generates the end-of-run summary in both markdown and JSON formats."""

    def __init__(self, config: "AgentConfig") -> None:
        self.config = config

    def save_summary(self, run_state: "RunState", output_dir: Path) -> None:
        self._save_markdown(run_state, output_dir)
        self._save_json(run_state, output_dir)

    # -----------------------------------------------------------------------
    # Markdown summary
    # -----------------------------------------------------------------------

    def _save_markdown(self, run_state: "RunState", output_dir: Path) -> None:
        lines = self._build_markdown(run_state)
        (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    def _build_markdown(self, run_state: "RunState") -> list[str]:
        rs = run_state
        cfg = self.config
        duration_str = ""
        if rs.start_time and rs.end_time:
            secs = (rs.end_time - rs.start_time).total_seconds()
            duration_str = f"{secs:.0f} s ({secs/60:.1f} min)"

        lines = [
            f"# IV-Agent Run Summary",
            f"",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Chip ID | `{rs.chip_id}` |",
            f"| Run ID | `{rs.run_id}` |",
            f"| Start | {rs.start_time.strftime('%Y-%m-%d %H:%M:%S') if rs.start_time else '—'} |",
            f"| End | {rs.end_time.strftime('%Y-%m-%d %H:%M:%S') if rs.end_time else '—'} |",
            f"| Duration | {duration_str} |",
            f"| Grid | {cfg.grid.nx} × {cfg.grid.ny} = {cfg.grid.n_devices} devices |",
            f"| Operator | {cfg.run.operator or '—'} |",
            f"| Mode | {'Simulation' if cfg.instruments.simulate else 'Real hardware'} |",
            f"",
            f"## Device Outcomes",
            f"",
            f"| Status | Count |",
            f"|--------|-------|",
            f"| ✅ Healthy | {rs.n_healthy} |",
            f"| ⚠️ Degrading | {rs.n_degrading} |",
            f"| ❌ Failed | {rs.n_failed} |",
            f"| ⛔ Shorted | {rs.n_shorted} |",
            f"| 🔌 Contact issue | {rs.n_contact_issue} |",
            f"| ⏭ Skipped | {rs.n_skipped} |",
            f"| **Total done** | **{rs.n_devices_done}** |",
            f"",
            f"Max consecutive failures: **{rs.max_consecutive_failures}**",
            f"",
            f"## Active Hypotheses",
            f"",
        ]

        active = sorted(
            [h for h in rs.hypotheses.values() if h.active],
            key=lambda h: h.support_level,
            reverse=True,
        )
        if active:
            lines.append("| Hypothesis | Support | Evidence |")
            lines.append("|-----------|---------|---------|")
            for h in active:
                ev = h.evidence_for[0] if h.evidence_for else "—"
                lines.append(
                    f"| {h.label} | {h.support_level:.2f} | {ev[:60]} |"
                )
        else:
            lines.append("_No active hypotheses._")
        lines.append("")

        # Alerts
        lines += [
            f"## Alerts ({len(rs.alerts)} total)",
            f"",
        ]
        for alert in rs.alerts:
            lines.append(
                f"- **SEV {alert.severity.value}** [{alert.timestamp.strftime('%H:%M:%S')}] "
                f"{alert.title}"
            )
        if not rs.alerts:
            lines.append("_No alerts raised._")
        lines.append("")

        # Selected notes
        lines += [
            f"## Experiment Notes (last 20)",
            f"",
        ]
        for note in rs.notes[-20:]:
            ts = note.timestamp.strftime("%H:%M:%S")
            dev_label = f" `{note.device_id}`" if note.device_id else ""
            lines.append(f"**[{ts}]{dev_label}** — {note.body}")
            lines.append("")

        # Device table
        lines += [
            f"## Device Summary Table",
            f"",
            f"| Device | [ix,iy] | Status | Trend | Suspicion | Leakage@1V | Batches |",
            f"|--------|---------|--------|-------|-----------|------------|---------|",
        ]
        for dev_id in rs.device_order:
            dev = rs.devices.get(dev_id)
            if not dev:
                continue
            leakage_str = (
                f"{dev.latest_leakage_at_1v_A:.2e}"
                if dev.latest_leakage_at_1v_A else "—"
            )
            lines.append(
                f"| {dev.device_id} | [{dev.ix},{dev.iy}] | "
                f"{dev.status.value} | {dev.trend_state.value} | "
                f"{dev.suspicion_level.value} ({dev.suspicion_score:.2f}) | "
                f"{leakage_str} | {dev.stress_batch_count} |"
            )

        lines += [
            f"",
            f"---",
            f"_Generated by IV-Agent v0.1.0 on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
        ]
        return lines

    # -----------------------------------------------------------------------
    # JSON summary
    # -----------------------------------------------------------------------

    def _save_json(self, run_state: "RunState", output_dir: Path) -> None:
        data = run_state.to_summary_dict()
        data["alerts"] = [a.to_dict() for a in run_state.alerts]
        data["notes_count"] = len(run_state.notes)
        (output_dir / "summary.json").write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8"
        )
