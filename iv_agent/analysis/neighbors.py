"""
Neighbor-aware spatial analysis.

Compares a device's metrics to nearby devices on the chip grid.
Detects whether anomalies are isolated or part of a spatial cluster.
Also handles corner / edge / center categorisation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

import numpy as np

from ..config.schema import ThresholdConfig
from ..models.device import DeviceRecord, GridPosition

if TYPE_CHECKING:
    pass


@dataclass
class NeighborComparison:
    """Result of comparing a device to its spatial neighbours."""
    device_id: str
    n_neighbors_found: int = 0
    neighbor_ids: list[str] = field(default_factory=list)
    # Leakage comparison
    device_leakage_A: float = 0.0
    neighbor_median_leakage_A: float = 0.0
    leakage_ratio: float = 1.0         # device / neighbor_median
    # Flags
    is_outlier_high: bool = False      # device is much higher than neighbours
    is_outlier_low: bool = False       # device is much lower (contact issue?)
    same_row_anomaly: bool = False
    same_col_anomaly: bool = False
    # Spatial cluster membership
    is_in_cluster: bool = False
    cluster_description: str = ""


@dataclass
class SpatialCluster:
    """A group of spatially adjacent suspicious or failed devices."""
    member_ids: list[str] = field(default_factory=list)
    centroid_ix: float = 0.0
    centroid_iy: float = 0.0
    grid_position_label: str = ""   # "corner", "edge", "center"
    description: str = ""


class NeighborAnalyzer:
    """
    Spatial analysis utilities.

    Operates on the shared device dict from RunState.
    All positions are (ix, iy) = (column, row) zero-indexed.
    """

    def __init__(self, nx: int, ny: int, thresholds: ThresholdConfig) -> None:
        self.nx = nx
        self.ny = ny
        self.thresholds = thresholds

    def classify_grid_position(self, ix: int, iy: int) -> GridPosition:
        """Return corner / edge / center based on grid location."""
        is_x_edge = ix == 0 or ix == self.nx - 1
        is_y_edge = iy == 0 or iy == self.ny - 1
        if is_x_edge and is_y_edge:
            return GridPosition.CORNER
        if is_x_edge or is_y_edge:
            return GridPosition.EDGE
        return GridPosition.CENTER

    def get_neighbors(
        self,
        ix: int,
        iy: int,
        devices: dict[str, DeviceRecord],
        radius: int = 2,
    ) -> list[DeviceRecord]:
        """
        Return all DeviceRecords within Chebyshev distance `radius` that have
        at least one measurement (i.e. have been visited by the agent).
        """
        neighbors = []
        for dev in devices.values():
            if dev.ix == ix and dev.iy == iy:
                continue  # exclude self
            dx = abs(dev.ix - ix)
            dy = abs(dev.iy - iy)
            if max(dx, dy) <= radius and dev.latest_leakage_at_1v_A is not None:
                neighbors.append(dev)
        return neighbors

    def get_row_neighbors(
        self, ix: int, iy: int, devices: dict[str, DeviceRecord]
    ) -> list[DeviceRecord]:
        return [
            d for d in devices.values()
            if d.iy == iy and d.ix != ix and d.latest_leakage_at_1v_A is not None
        ]

    def get_col_neighbors(
        self, ix: int, iy: int, devices: dict[str, DeviceRecord]
    ) -> list[DeviceRecord]:
        return [
            d for d in devices.values()
            if d.ix == ix and d.iy != iy and d.latest_leakage_at_1v_A is not None
        ]

    def compare_to_neighbors(
        self,
        device: DeviceRecord,
        devices: dict[str, DeviceRecord],
        radius: int = 2,
    ) -> NeighborComparison:
        """
        Compare the current device's leakage to nearby measured devices.

        Returns a NeighborComparison with outlier flags set.
        """
        comparison = NeighborComparison(device_id=device.device_id)

        if device.latest_leakage_at_1v_A is None:
            return comparison

        comparison.device_leakage_A = device.latest_leakage_at_1v_A

        neighbors = self.get_neighbors(device.ix, device.iy, devices, radius)
        comparison.n_neighbors_found = len(neighbors)
        comparison.neighbor_ids = [n.device_id for n in neighbors]

        if not neighbors:
            return comparison

        neighbor_leakages = [
            n.latest_leakage_at_1v_A
            for n in neighbors
            if n.latest_leakage_at_1v_A is not None
        ]
        if not neighbor_leakages:
            return comparison

        median_leakage = float(np.median(neighbor_leakages))
        comparison.neighbor_median_leakage_A = median_leakage

        if median_leakage > 1.0e-15:
            ratio = comparison.device_leakage_A / median_leakage
        else:
            ratio = 1.0
        comparison.leakage_ratio = ratio

        thr = self.thresholds
        comparison.is_outlier_high = ratio >= thr.neighbor_leakage_ratio_suspicious
        comparison.is_outlier_low = ratio <= 1.0 / thr.neighbor_leakage_ratio_suspicious

        # Check row anomaly
        row_neighbors = self.get_row_neighbors(device.ix, device.iy, devices)
        if row_neighbors:
            row_leakages = [n.latest_leakage_at_1v_A for n in row_neighbors if n.latest_leakage_at_1v_A]
            if row_leakages:
                row_ratio = comparison.device_leakage_A / float(np.median(row_leakages))
                comparison.same_row_anomaly = row_ratio >= thr.neighbor_leakage_ratio_suspicious

        # Check column anomaly
        col_neighbors = self.get_col_neighbors(device.ix, device.iy, devices)
        if col_neighbors:
            col_leakages = [n.latest_leakage_at_1v_A for n in col_neighbors if n.latest_leakage_at_1v_A]
            if col_leakages:
                col_ratio = comparison.device_leakage_A / float(np.median(col_leakages))
                comparison.same_col_anomaly = col_ratio >= thr.neighbor_leakage_ratio_suspicious

        return comparison

    def detect_spatial_cluster(
        self,
        devices: dict[str, DeviceRecord],
        suspicious_statuses: set[str] | None = None,
    ) -> list[SpatialCluster]:
        """
        Find connected groups of suspicious / failed devices.

        Uses a simple flood-fill over the chip grid.
        Returns a list of SpatialCluster objects.
        """
        if suspicious_statuses is None:
            from ..models.device import DeviceStatus
            suspicious_statuses = {
                DeviceStatus.SUSPICIOUS.value,
                DeviceStatus.FAILED.value,
                DeviceStatus.NEAR_FAILURE.value,
                DeviceStatus.CONTACT_ISSUE.value,
            }

        flagged: dict[tuple[int, int], str] = {}  # (ix, iy) → device_id
        for dev in devices.values():
            if dev.status.value in suspicious_statuses:
                flagged[(dev.ix, dev.iy)] = dev.device_id

        if len(flagged) < self.thresholds.spatial_cluster_min_size:
            return []

        visited: set[tuple[int, int]] = set()
        clusters: list[SpatialCluster] = []

        for pos in flagged:
            if pos in visited:
                continue
            # BFS flood fill
            cluster_members: list[tuple[int, int]] = []
            queue = [pos]
            while queue:
                cur = queue.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                if cur in flagged:
                    cluster_members.append(cur)
                    # Check all 8-connected neighbours
                    cx, cy = cur
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            if dx == 0 and dy == 0:
                                continue
                            nb = (cx + dx, cy + dy)
                            if nb in flagged and nb not in visited:
                                queue.append(nb)

            if len(cluster_members) >= self.thresholds.spatial_cluster_min_size:
                member_ids = [flagged[p] for p in cluster_members]
                xs = [p[0] for p in cluster_members]
                ys = [p[1] for p in cluster_members]
                cx = float(np.mean(xs))
                cy = float(np.mean(ys))
                pos_label = self._cluster_position_label(xs, ys)
                clusters.append(SpatialCluster(
                    member_ids=member_ids,
                    centroid_ix=cx,
                    centroid_iy=cy,
                    grid_position_label=pos_label,
                    description=f"{len(member_ids)}-device cluster in {pos_label} region",
                ))

        return clusters

    def _cluster_position_label(self, xs: list[int], ys: list[int]) -> str:
        """Heuristically label a cluster's chip location."""
        cx = float(np.mean(xs))
        cy = float(np.mean(ys))
        nx_f = float(self.nx - 1)
        ny_f = float(self.ny - 1)
        x_norm = cx / max(nx_f, 1)
        y_norm = cy / max(ny_f, 1)
        # Determine coarse label
        x_label = "left" if x_norm < 0.35 else ("right" if x_norm > 0.65 else "center")
        y_label = "top" if y_norm < 0.35 else ("bottom" if y_norm > 0.65 else "center")
        if x_label == "center" and y_label == "center":
            return "center"
        return f"{y_label}-{x_label}"
