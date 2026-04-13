"""
Plotting utilities for the IV-agent.

Generates:
  - Per-device overlaid I-V curves
  - Chip heatmaps (status, leakage, suspicion score)
  - Degradation trend plots (leakage over stress batches)

All plots are saved as PNG to the output directory.
Matplotlib is used in non-interactive (Agg) backend mode.
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING

warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — safe for server/headless use
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import matplotlib.lines as mlines
import numpy as np

if TYPE_CHECKING:
    from ..config.schema import AgentConfig
    from ..models.run_state import RunState
    from ..models.device import DeviceRecord


_STATUS_COLOURS = {
    "healthy": "#2ecc71",
    "degrading": "#f39c12",
    "near_failure": "#e67e22",
    "failed": "#e74c3c",
    "shorted": "#8e44ad",
    "contact_issue": "#3498db",
    "suspicious": "#f1c40f",
    "unknown": "#95a5a6",
    "skipped": "#bdc3c7",
}


class PlotGenerator:
    """Generates and saves all run-level and device-level plots."""

    def __init__(self, config: "AgentConfig") -> None:
        self.config = config

    # -----------------------------------------------------------------------
    # Chip heatmaps
    # -----------------------------------------------------------------------

    def plot_chip_heatmaps(self, run_state: "RunState", output_dir: Path) -> None:
        """
        Generate chip heatmaps for:
        - Device status (categorical colour map)
        - Leakage at 1 V (log scale)
        - Suspicion score (0–1)
        """
        plot_dir = output_dir / "plots"
        plot_dir.mkdir(exist_ok=True)

        devices = list(run_state.devices.values())
        grid = self.config.grid
        nx, ny = grid.nx, grid.ny

        # Build 2D arrays
        status_grid = np.full((ny, nx), "unknown", dtype=object)
        leakage_grid = np.full((ny, nx), np.nan)
        suspicion_grid = np.full((ny, nx), 0.0)

        for dev in devices:
            if 0 <= dev.iy < ny and 0 <= dev.ix < nx:
                status_grid[dev.iy, dev.ix] = dev.status.value
                if dev.latest_leakage_at_1v_A and dev.latest_leakage_at_1v_A > 0:
                    leakage_grid[dev.iy, dev.ix] = np.log10(dev.latest_leakage_at_1v_A)
                suspicion_grid[dev.iy, dev.ix] = dev.suspicion_score

        self._plot_status_heatmap(status_grid, nx, ny, plot_dir)
        self._plot_scalar_heatmap(
            leakage_grid, nx, ny, plot_dir,
            title="Leakage at 1 V (log₁₀ A)",
            filename="heatmap_leakage.png",
            cmap="RdYlGn_r",
        )
        self._plot_scalar_heatmap(
            suspicion_grid, nx, ny, plot_dir,
            title="Suspicion Score",
            filename="heatmap_suspicion.png",
            cmap="YlOrRd",
            vmin=0, vmax=1,
        )

    def _plot_status_heatmap(
        self, status_grid: np.ndarray, nx: int, ny: int, plot_dir: Path
    ) -> None:
        fig, ax = plt.subplots(figsize=(max(6, nx * 1.2), max(4, ny * 1.0)))
        ax.set_xlim(-0.5, nx - 0.5)
        ax.set_ylim(-0.5, ny - 0.5)
        ax.set_xlabel("Column (ix)", fontsize=11)
        ax.set_ylabel("Row (iy)", fontsize=11)
        ax.set_title(
            f"Chip Status Map — {self.config.run.chip_id} / {self.config.run.run_id}",
            fontsize=13,
        )

        for iy in range(ny):
            for ix in range(nx):
                status_val = status_grid[iy, ix]
                colour = _STATUS_COLOURS.get(status_val, "#95a5a6")
                rect = plt.Rectangle(
                    (ix - 0.45, iy - 0.45), 0.9, 0.9,
                    facecolor=colour, edgecolor="white", linewidth=1.5,
                )
                ax.add_patch(rect)
                ax.text(
                    ix, iy, status_val[:3].upper(),
                    ha="center", va="center", fontsize=7, color="white",
                    fontweight="bold",
                )

        # Legend
        legend_elements = [
            mpatches.Patch(facecolor=col, label=label)
            for label, col in _STATUS_COLOURS.items()
        ]
        ax.legend(
            handles=legend_elements, loc="upper left",
            bbox_to_anchor=(1.01, 1), borderaxespad=0, fontsize=8,
        )
        ax.set_xticks(range(nx))
        ax.set_yticks(range(ny))
        plt.tight_layout()
        fig.savefig(plot_dir / "heatmap_status.png", dpi=120, bbox_inches="tight")
        plt.close(fig)

    def _plot_scalar_heatmap(
        self,
        data: np.ndarray,
        nx: int,
        ny: int,
        plot_dir: Path,
        title: str,
        filename: str,
        cmap: str = "RdYlGn_r",
        vmin: float | None = None,
        vmax: float | None = None,
    ) -> None:
        fig, ax = plt.subplots(figsize=(max(6, nx * 1.2), max(4, ny * 1.0)))
        im = ax.imshow(
            data, cmap=cmap, origin="lower",
            vmin=vmin, vmax=vmax,
            aspect="auto",
        )
        plt.colorbar(im, ax=ax, label=title)
        ax.set_xlabel("Column (ix)")
        ax.set_ylabel("Row (iy)")
        ax.set_title(f"{title} — {self.config.run.chip_id}")
        ax.set_xticks(range(nx))
        ax.set_yticks(range(ny))
        plt.tight_layout()
        fig.savefig(plot_dir / filename, dpi=120, bbox_inches="tight")
        plt.close(fig)

    # -----------------------------------------------------------------------
    # I-V curve plots
    # -----------------------------------------------------------------------

    def plot_device_iv_curves(
        self, run_state: "RunState", output_dir: Path, max_devices: int = 20
    ) -> None:
        """
        Plot overlaid I-V curves for all devices (up to max_devices).

        Saves one figure with all health-check curves overlaid, coloured by status.
        """
        plot_dir = output_dir / "plots"
        plot_dir.mkdir(exist_ok=True)

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.set_xlabel("Voltage (V)")
        ax.set_ylabel("Current (A) — log scale")
        ax.set_yscale("log")
        ax.set_title(
            f"Health-Check I-V Curves — {self.config.run.chip_id} / {self.config.run.run_id}"
        )
        ax.set_ylim(1e-14, 1e-3)

        count = 0
        for dev in list(run_state.devices.values())[:max_devices]:
            if not dev.iv_curves:
                continue
            # Use first health-check curve
            first_curve = dev.iv_curves[0]
            v = np.array(first_curve.voltages_V)
            i = np.array(first_curve.currents_A)
            i_clipped = np.where(i > 1e-14, i, 1e-14)
            colour = _STATUS_COLOURS.get(dev.status.value, "#95a5a6")
            alpha = 0.7 if not dev.is_control_device else 1.0
            lw = 1.0 if not dev.is_control_device else 2.0
            ls = "-" if not dev.is_control_device else "--"
            ax.plot(v, i_clipped, color=colour, alpha=alpha, linewidth=lw, linestyle=ls,
                    label=dev.device_id if dev.is_control_device else None)
            count += 1

        # Legend for status colours
        legend_elements = [
            mlines.Line2D([0], [0], color=col, linewidth=2, label=label)
            for label, col in _STATUS_COLOURS.items()
            if any(d.status.value == label for d in run_state.devices.values())
        ]
        ax.legend(handles=legend_elements, fontsize=8, loc="upper left")
        ax.grid(True, which="both", alpha=0.3)
        plt.tight_layout()
        fig.savefig(plot_dir / "iv_curves_health_check.png", dpi=120)
        plt.close(fig)

    # -----------------------------------------------------------------------
    # Degradation trend plots
    # -----------------------------------------------------------------------

    def plot_degradation_trends(
        self, run_state: "RunState", output_dir: Path
    ) -> None:
        """
        Plot leakage-at-1V vs measurement index for each device that has
        stress history.
        """
        plot_dir = output_dir / "plots"
        plot_dir.mkdir(exist_ok=True)

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.set_xlabel("Measurement index")
        ax.set_ylabel("Leakage at 1 V (A) — log scale")
        ax.set_yscale("log")
        ax.set_title(
            f"Degradation Trends — {self.config.run.chip_id} / {self.config.run.run_id}"
        )
        ax.set_ylim(1e-14, 1e-3)

        for dev in run_state.devices.values():
            if len(dev.metrics_history) < 3:
                continue
            leakages = [m.leakage_at_1v_A for m in dev.metrics_history]
            leakages = [max(l, 1e-14) for l in leakages]
            colour = _STATUS_COLOURS.get(dev.status.value, "#95a5a6")
            ax.plot(
                range(len(leakages)), leakages,
                color=colour, alpha=0.7, linewidth=1.2,
                marker="o", markersize=3,
                label=dev.device_id if dev.is_control_device else None,
            )

        ax.grid(True, which="both", alpha=0.3)
        if any(d.is_control_device for d in run_state.devices.values()):
            ax.legend(fontsize=8)
        plt.tight_layout()
        fig.savefig(plot_dir / "degradation_trends.png", dpi=120)
        plt.close(fig)
