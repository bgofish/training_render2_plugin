# SPDX-FileCopyrightText: 2025
# SPDX-License-Identifier: GPL-3.0-or-later

"""LFSPathPlayer — plays back a LightField Studio camera_path.json file.

Updated with Catmull-Rom Spline interpolation for smooth (Blue Line) paths
and support for easing modes (Linear, Ease In, Ease Out, Ease In-Out).
"""

import json
import math
from pathlib import Path

import lichtfeld as lf

# ── Version detection ─────────────────────────────────────────────────────────
# v0.5.0.x = -Y-up   v0.5.1+ = +Y-up
def _parse_version(v: str) -> tuple:
    import re
    parts = v.lstrip("v").split(".")[:3]
    return tuple(int(re.match(r"\d+", x).group()) for x in parts)

Y_UP = _parse_version(lf.__version__) >= (0, 5, 1)


# ── Pure-Python helpers ───────────────────────────────────────────────────────

def _focal_to_fov(focal_mm: float, sensor_h: float = 24.0) -> float:
    """Convert focal length (mm) to vertical FoV (degrees)."""
    if focal_mm <= 0:
        return 60.0
    return math.degrees(2.0 * math.atan(sensor_h / (2.0 * focal_mm)))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _catmull_rom_3(p0, p1, p2, p3, t: float):
    """Centripetal Catmull-Rom spline for smooth 3D position interpolation."""
    t2 = t * t
    t3 = t2 * t

    def _calc(v0, v1, v2, v3):
        return 0.5 * ((2 * v1) +
                     (-v0 + v2) * t +
                     (2 * v0 - 5 * v1 + 4 * v2 - v3) * t2 +
                     (-v0 + 3 * v1 - 3 * v2 + v3) * t3)

    return (
        _calc(p0[0], p1[0], p2[0], p3[0]),
        _calc(p0[1], p1[1], p2[1], p3[1]),
        _calc(p0[2], p1[2], p2[2], p3[2])
    )


def _apply_easing(t: float, mode: int) -> float:
    """Reshapes alpha based on easing mode from Blender."""
    if mode == 1:    # Ease In
        return t * t
    elif mode == 2:  # Ease Out
        return t * (2.0 - t)
    elif mode == 3:  # Ease In-Out (Smoothstep)
        return t * t * (3.0 - 2.0 * t)
    return t         # Linear (0)


def _dot4(q1, q2) -> float:
    return q1[0]*q2[0] + q1[1]*q2[1] + q1[2]*q2[2] + q1[3]*q2[3]


def _slerp(q1, q2, t: float):
    """Spherical linear interpolation between two unit quaternions [w,x,y,z]."""
    dot = _dot4(q1, q2)
    if dot < 0.0:
        q2 = (-q2[0], -q2[1], -q2[2], -q2[3])
        dot = -dot
    if dot > 0.9995:
        r = (q1[0] + t * (q2[0] - q1[0]), q1[1] + t * (q2[1] - q1[1]),
             q1[2] + t * (q2[2] - q1[2]), q1[3] + t * (q2[3] - q1[3]))
        n = math.sqrt(r[0]**2 + r[1]**2 + r[2]**2 + r[3]**2)
        return (r[0]/n, r[1]/n, r[2]/n, r[3]/n) if n > 0 else r
    theta_0 = math.acos(max(-1.0, min(1.0, dot)))
    theta   = theta_0 * t
    sin0    = math.sin(theta_0)
    sin_t   = math.sin(theta)
    s1 = math.cos(theta) - dot * sin_t / sin0
    s2 = sin_t / sin0
    return (s1*q1[0] + s2*q2[0], s1*q1[1] + s2*q2[1], s1*q1[2] + s2*q2[2], s1*q1[3] + s2*q2[3])


def _quat_rotate(q, v):
    """Rotate vector v = (x,y,z) by unit quaternion q = (w,x,y,z)."""
    qw, qx, qy, qz = q
    vx, vy, vz     = v
    tx = 2.0 * (qy * vz - qz * vy)
    ty = 2.0 * (qz * vx - qx * vz)
    tz = 2.0 * (qx * vy - qy * vx)
    return (vx + qw * tx + (qy * tz - qz * ty),
            vy + qw * ty + (qz * tx - qx * tz),
            vz + qw * tz + (qx * ty - qy * tx))


# ── Player ────────────────────────────────────────────────────────────────────

class LFSPathPlayer:
    """Interpolates smooth position/orientation from a LFS camera_path.json."""

    def __init__(self, path: str):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        raw  = data.get("keyframes", [])
        if not raw:
            raise ValueError("No keyframes found in camera_path.json")

        self._keyframes = sorted(
            [
                {
                    "time": float(kf["time"]),
                    "pos":  tuple(float(v) for v in kf["position"]),
                    "rot":  tuple(float(v) for v in kf["rotation"]),
                    "fov":  _focal_to_fov(float(kf.get("focal_length_mm", 35.0))),
                    "easing": int(kf.get("easing", 0)),
                }
                for kf in raw
            ],
            key=lambda k: k["time"],
        )

        self.total_duration: float = self._keyframes[-1]["time"]
        self.n_keyframes: int      = len(self._keyframes)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_camera_at_snap(self, snap_index: int, secs_per_snap: float, loop: bool):
        """Return (eye, target, up, fov) for the given snapshot index."""
        t = snap_index * secs_per_snap
        if self.total_duration > 0:
            if loop:
                t = t % self.total_duration
            else:
                t = min(t, self.total_duration)

        pos, rot, fov = self._interpolate(t, loop=loop)

        # +Y-up: forward=(0,0,-1), up=(0,1,0)
        # -Y-up: forward=(0,0, 1), up=(0,1,0)
        if Y_UP:
            forward = _quat_rotate(rot, (0.0,  0.0, -1.0))
        else:
            forward = _quat_rotate(rot, (0.0,  0.0,  1.0))
        up_vec  = _quat_rotate(rot, (0.0,  1.0,  0.0))
        target  = (pos[0] + forward[0], pos[1] + forward[1], pos[2] + forward[2])

        return pos, target, up_vec, fov

    def info(self, secs_per_snap: float) -> str:
        snaps = (int(self.total_duration / secs_per_snap) if secs_per_snap > 0 else 0)
        avg_fov = sum(kf["fov"] for kf in self._keyframes) / self.n_keyframes
        return (f"{self.n_keyframes} keyframes | duration={self.total_duration:.1f}s | "
                f"fov\u2248{avg_fov:.1f}\u00b0 | ~{snaps} snaps @ {secs_per_snap}s")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _interpolate(self, t: float, loop: bool = False):
        kfs = self._keyframes
        n = self.n_keyframes

        if not loop:
            if t <= kfs[0]["time"]: return kfs[0]["pos"], kfs[0]["rot"], kfs[0]["fov"]
            if t >= kfs[-1]["time"]: return kfs[-1]["pos"], kfs[-1]["rot"], kfs[-1]["fov"]

        for i in range(n - 1):
            a, b = kfs[i], kfs[i + 1]
            if a["time"] <= t <= b["time"]:
                span = b["time"] - a["time"]
                alpha = (t - a["time"]) / span if span > 0 else 0.0
                
                # Apply easing to alpha before interpolation
                alpha = _apply_easing(alpha, a["easing"])

                # Spline Points
                p1 = a["pos"]
                p2 = b["pos"]
                
                if loop:
                    p0 = kfs[(i - 1) % n]["pos"]
                    p3 = kfs[(i + 2) % n]["pos"]
                else:
                    p0 = kfs[max(0, i - 1)]["pos"]
                    p3 = kfs[min(n - 1, i + 2)]["pos"]

                pos = _catmull_rom_3(p0, p1, p2, p3, alpha)
                rot = _slerp(a["rot"], b["rot"], alpha)
                fov = _lerp(a["fov"], b["fov"], alpha)
                
                return pos, rot, fov

        # Wraparound case for loop: last keyframe back to first
        if loop:
            a, b = kfs[-1], kfs[0]
            # Estimate a 1-second transition if no explicit duration exists
            alpha = min(1.0, (t - a["time"]) / 1.0) if t > a["time"] else 0.0
            pos = _catmull_rom_3(kfs[-2]["pos"], a["pos"], b["pos"], kfs[1]["pos"], alpha)
            return pos, _slerp(a["rot"], b["rot"], alpha), _lerp(a["fov"], b["fov"], alpha)

        return kfs[-1]["pos"], kfs[-1]["rot"], kfs[-1]["fov"]
