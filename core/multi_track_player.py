# SPDX-FileCopyrightText: 2025
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import math
from pathlib import Path

import lichtfeld as lf

# ── Version detection ─────────────────────────────────────────────────────────
def _parse_version(v: str) -> tuple:
    import re
    parts = v.lstrip("v").split(".")[:3]
    return tuple(int(re.match(r"\d+", x).group()) for x in parts)

Y_UP = _parse_version(lf.__version__) >= (0, 5, 1)


class MultiSegmentTrackPlayer:
    """Loads a multi-segment camera_track.json (linear + orbit) exported by
    360_record and provides camera transforms stepped by distance (metres)."""

    def __init__(self, path: str, dist_per_snap: float = 0.1):
        data     = json.loads(Path(path).read_text(encoding="utf-8"))
        settings = data.get("settings", {})

        up_axis_idx  = int(settings.get("up_axis_idx", 0))
        # 360_record index: 0=Z, 1=Y, 2=X  (matches UP_AXIS_ITEMS in linear_path_panel.py)
        _UP_AXIS_MAP = {0: "z", 1: "y", 2: "x"}
        self.up_axis = _UP_AXIS_MAP.get(up_axis_idx, "z")
        self.fov     = float(settings.get("fov", 45.0))

        # Linear-segment elevation offset (matches 360_record LinearPath._get_elevation_offset)
        # Orbit segments have their own per-segment elevation; this only applies to linear.
        raw_elev     = float(settings.get("elevation", 0.0))
        invert_elev  = bool(settings.get("invert_elevation", False))
        elev_scalar  = -raw_elev if invert_elev else raw_elev
        if self.up_axis == "y":
            self._linear_elev_offset = (0.0, elev_scalar, 0.0)
        elif self.up_axis == "x":
            self._linear_elev_offset = (elev_scalar, 0.0, 0.0)
        else:  # z
            self._linear_elev_offset = (0.0, 0.0, elev_scalar)

        self._segments = self._build_segments(data.get("segments", []))
        self.total_length = sum(s["length"] for s in self._segments)
        self._dist_per_snap = dist_per_snap   # stored for info only

    # ── public ────────────────────────────────────────────────────────────────

    def get_camera_at_snap(self, snap_index: int, dist_per_snap: float, loop: bool):
        """Return (eye, target, up, fov) for the given snapshot index."""
        travel = snap_index * dist_per_snap

        if loop and self.total_length > 0:
            travel = travel % self.total_length
        else:
            travel = min(travel, self.total_length)

        eye, target, seg = self._position_at(travel)

        # Use per-segment orbit_axis for orbit segments (matches 360_record get_up_vector)
        axis = seg.get("orbit_axis", self.up_axis) if seg["type"] == "orbit" else self.up_axis
        if axis == "y":
            up = (0.0, 1.0, 0.0)
        elif axis == "x":
            up = (1.0, 0.0, 0.0)
        else:
            up = (0.0, 0.0, 1.0)

        return eye, target, up, self.fov

    @property
    def segment_count(self) -> int:
        return len(self._segments)

    def info(self, dist_per_snap: float) -> str:
        n_snaps = math.ceil(self.total_length / dist_per_snap) if dist_per_snap > 0 else 0
        return (
            f"{self.segment_count} segment(s)  "
            f"total={self.total_length:.3f}m  "
            f"fov={self.fov:.1f}\u00b0  "
            f"~{n_snaps} snaps @ {dist_per_snap:.3f}m"
        )

    # ── private ───────────────────────────────────────────────────────────────

    def _build_segments(self, raw_segments: list) -> list:
        segments  = []
        cumulative = 0.0
        for seg in raw_segments:
            seg_type = str(seg.get("type", "")).lower()
            if seg_type == "linear":
                start  = tuple(seg["start"])
                end    = tuple(seg["end"])
                poi    = tuple(seg.get("poi", end))
                length = math.dist(start, end)
                segments.append({
                    "type":       "linear",
                    "start":      start,
                    "end":        end,
                    "poi":        poi,
                    "length":     length,
                    "cum_start":  cumulative,
                })
            elif seg_type in ("orbit", "circular"):
                poi        = tuple(seg.get("poi") or seg.get("center"))
                radius     = float(seg["radius"])
                elevation  = float(seg.get("elevation", 0.0))
                start_angle = float(seg.get("start_angle", seg.get("arc_start", 0.0)))
                arc_deg    = float(seg.get("arc_degrees",
                                 seg.get("arc_end", 360.0) - start_angle))
                orbit_axis = str(seg.get("orbit_axis", seg.get("up_axis", "y"))).lower()
                invert     = bool(seg.get("invert_direction", False))
                length     = radius * math.radians(abs(arc_deg))
                segments.append({
                    "type":         "orbit",
                    "poi":          poi,
                    "radius":       radius,
                    "elevation":    elevation,
                    "start_angle":  start_angle,
                    "arc_degrees":  arc_deg,
                    "orbit_axis":   orbit_axis,
                    "invert":       invert,
                    "length":       length,
                    "cum_start":    cumulative,
                })
            else:
                continue   # skip unknown segment types
            cumulative += segments[-1]["length"]
        return segments

    def _position_at(self, travel: float):
        """Return (eye, look_at, segment) for travel distance along the full path."""
        for seg in reversed(self._segments):
            if travel >= seg["cum_start"]:
                sub = travel - seg["cum_start"]
                t   = sub / seg["length"] if seg["length"] > 0 else 0.0
                t   = max(0.0, min(1.0, t))
                return self._eval_segment(seg, t)
        # Fallback: start of first segment
        return self._eval_segment(self._segments[0], 0.0)

    def _eval_segment(self, seg: dict, t: float):
        if seg["type"] == "linear":
            base   = _lerp3(seg["start"], seg["end"], t)
            dx, dy, dz = self._linear_elev_offset
            eye    = (base[0] + dx, base[1] + dy, base[2] + dz)
            target = seg["poi"]
        else:  # orbit
            angle  = seg["start_angle"] + t * seg["arc_degrees"]
            if seg["invert"]:
                angle = seg["start_angle"] - t * seg["arc_degrees"]
            eye    = _orbit_pos(seg["poi"], seg["radius"], seg["elevation"],
                                angle, seg["orbit_axis"])
            target = seg["poi"]
        return eye, target, seg


# ── helpers ───────────────────────────────────────────────────────────────────

def _lerp3(a, b, t):
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def _orbit_pos(poi, radius, elevation, angle_deg, up_axis):
    theta = math.radians(angle_deg)
    cx, cy, cz = poi
    r, e = radius, elevation
    if up_axis == "y":
        # +Y-up: Z axis is negated relative to -Y-up
        return (cx + r * math.cos(theta), cy + e, cz + r * (-math.sin(theta) if Y_UP else math.sin(theta)))
    else:
        return (cx + r * math.cos(theta), cy + r * math.sin(theta), cz + e)
