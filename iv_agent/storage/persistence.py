"""
Storage manager — JSON / CSV persistence and checkpointing.

All run outputs are written to the output directory defined in the config.
File layout:
  <output_dir>/<run_id>/
      run_state.json         — full run state summary
      devices.json           — all device records
      alerts.json            — all alerts
      hypotheses.json        — all hypotheses
      chip_map.csv           — per-device metric table
      notes.md               — all experiment notes (markdown)
      notes.jsonl            — all experiment notes (JSON-lines)
      summary.md             — human-readable summary
      summary.json           — machine-readable summary
      checkpoint.json        — latest checkpoint (overwritten each time)
      plots/                 — all generated figures
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config.schema import AgentConfig
    from ..models.run_state import RunState, Note


class StorageManager:
    """
    Handles all file I/O for the agent.

    All methods are safe to call multiple times (idempotent writes).
    """

    def __init__(self, config: "AgentConfig") -> None:
        self.config = config

    # -----------------------------------------------------------------------
    # Device data
    # -----------------------------------------------------------------------

    def save_devices(self, run_state: "RunState", output_dir: Path) -> None:
        """Write devices.json with all DeviceRecord data."""
        data = [
            run_state.devices[dev_id].to_dict()
            for dev_id in run_state.device_order
            if dev_id in run_state.devices
        ]
        self._write_json(output_dir / "devices.json", data)

    # -----------------------------------------------------------------------
    # Alerts and hypotheses
    # -----------------------------------------------------------------------

    def save_alerts(self, run_state: "RunState", output_dir: Path) -> None:
        data = [a.to_dict() for a in run_state.alerts]
        self._write_json(output_dir / "alerts.json", data)

    def save_hypotheses(self, run_state: "RunState", output_dir: Path) -> None:
        data = {k: v.to_dict() for k, v in run_state.hypotheses.items()}
        self._write_json(output_dir / "hypotheses.json", data)

    # -----------------------------------------------------------------------
    # Notes (incremental — appended during run)
    # -----------------------------------------------------------------------

    def append_note(self, note: "Note", output_dir: Path) -> None:
        """Append a single note to notes.md and notes.jsonl."""
        md_path = output_dir / "notes.md"
        jsonl_path = output_dir / "notes.jsonl"

        ts = note.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        dev_label = f" `{note.device_id}`" if note.device_id else ""
        md_line = f"\n**[{ts}]{dev_label}** _{note.category}_ — {note.body}\n"

        with open(md_path, "a", encoding="utf-8") as fh:
            fh.write(md_line)

        with open(jsonl_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(note.to_dict(), default=str) + "\n")

    # -----------------------------------------------------------------------
    # Run state
    # -----------------------------------------------------------------------

    def save_run_state(self, run_state: "RunState", output_dir: Path) -> None:
        """Write the final run_state.json."""
        self._write_json(output_dir / "run_state.json", run_state.to_summary_dict())

    # -----------------------------------------------------------------------
    # Checkpointing
    # -----------------------------------------------------------------------

    def checkpoint(self, run_state: "RunState", output_dir: Path) -> None:
        """
        Write a lightweight checkpoint.json with the current run state.

        Called periodically so a run can be inspected while it is still going.
        """
        data = {
            "checkpoint_time": datetime.now().isoformat(),
            "n_devices_done": run_state.n_devices_done,
            "n_devices_total": run_state.n_devices_total,
            "n_healthy": run_state.n_healthy,
            "n_failed": run_state.n_failed,
            "n_shorted": run_state.n_shorted,
            "n_contact_issue": run_state.n_contact_issue,
            "consecutive_failures": run_state.consecutive_failures,
            "global_suspicion_score": round(run_state.global_suspicion_score, 3),
            "n_alerts": len(run_state.alerts),
            "n_notes": len(run_state.notes),
            "hypotheses": {
                k: round(v.support_level, 3)
                for k, v in run_state.hypotheses.items()
                if v.support_level > 0.05
            },
        }
        self._write_json(output_dir / "checkpoint.json", data)

    # -----------------------------------------------------------------------
    # Utilities
    # -----------------------------------------------------------------------

    @staticmethod
    def _write_json(path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )
