# SPDX-FileCopyrightText: 2025
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import subprocess
import sys
import threading
import time as _time
import math as _math
from math import gcd
from pathlib import Path

import lichtfeld as lf

from ..core.state import State
from ..core.track_player import TrackPlayer
from ..core.multi_track_player import MultiSegmentTrackPlayer, _orbit_pos
from ..core.lfs_path_player import LFSPathPlayer


# ── Module-level preview state & draw handler ─────────────────────────────────

_show_preview            = False
_draw_handler_registered = False


def _ensure_draw_handler() -> None:
    global _draw_handler_registered
    if not _draw_handler_registered:
        try:
            lf.remove_draw_handler("training_render_preview")
        except Exception:
            pass
        lf.add_draw_handler("training_render_preview",
                            _training_render_draw_handler, "POST_VIEW")
        _draw_handler_registered = True


def _training_render_draw_handler(ctx) -> None:
    if not _show_preview:
        return

    # ── Track 1 – circular arc ────────────────────────────────────────────────
    if State.track_loaded and State._track_player is not None:
        tp  = State._track_player
        n   = max(24, int(abs(tp.arc_end - tp.arc_start) / 6))
        pts = [tp._orbit_position(tp.arc_start + i * (tp.arc_end - tp.arc_start) / n)
               for i in range(n + 1)]
        for i in range(len(pts) - 1):
            ctx.draw_line_3d(pts[i], pts[i + 1], (0.8, 0.4, 1.0, 0.8), 2.0)
        ctx.draw_point_3d(tp.center, (1.0, 0.2, 0.8, 1.0), 20.0)
        lbl = ctx.world_to_screen(tp.center)
        if lbl:
            ctx.draw_text_2d((lbl[0] + 10, lbl[1] - 8), "POI (T1)", (1.0, 0.2, 0.8, 1.0))
        ctx.draw_point_3d(pts[0],  (0.2, 1.0, 0.2, 1.0), 14.0)
        ctx.draw_point_3d(pts[-1], (1.0, 0.4, 0.2, 1.0), 14.0)
        ctx.draw_line_3d(tp.center, pts[0], (1.0, 0.2, 0.8, 0.25), 1.0)

    # ── Track 2 – multi-segment ───────────────────────────────────────────────
    if State.track2_loaded and State._track2_player is not None:
        mp   = State._track2_player
        segs = mp._segments
        dx, dy, dz = mp._linear_elev_offset

        for i, seg in enumerate(segs):
            if seg["type"] == "linear":
                s  = seg["start"];  e  = seg["end"]
                s2 = (s[0]+dx, s[1]+dy, s[2]+dz)
                e2 = (e[0]+dx, e[1]+dy, e[2]+dz)
                ctx.draw_line_3d(s2, e2, (0.2, 0.8, 1.0, 0.8), 2.0)
                ctx.draw_point_3d(s2, (0.2, 1.0, 0.2, 1.0), 14.0)
                ctx.draw_point_3d(e2, (1.0, 0.4, 0.2, 1.0), 14.0)
                lbl = ctx.world_to_screen(s2)
                if lbl:
                    ctx.draw_text_2d((lbl[0]+10, lbl[1]-8), f"S{i+1}", (0.2, 1.0, 0.2, 1.0))
                poi = seg.get("poi")
                if poi:
                    mid = ((s2[0]+e2[0])/2, (s2[1]+e2[1])/2, (s2[2]+e2[2])/2)
                    ctx.draw_line_3d(mid, poi, (1.0, 0.2, 0.8, 0.35), 1.0)
                    ctx.draw_point_3d(poi, (1.0, 0.2, 0.8, 1.0), 18.0)
            else:  # orbit
                poi  = seg["poi"];  r    = seg["radius"];  elev = seg["elevation"]
                axis = seg["orbit_axis"];  a0 = seg["start_angle"]
                arc  = seg["arc_degrees"]; inv = seg["invert"]
                n    = max(24, int(abs(arc) / 6))
                pts  = []
                for j in range(n + 1):
                    t     = j / n
                    angle = a0 - t * arc if inv else a0 + t * arc
                    pts.append(_orbit_pos(poi, r, elev, angle, axis))
                for j in range(len(pts) - 1):
                    ctx.draw_line_3d(pts[j], pts[j+1], (0.8, 0.4, 1.0, 0.8), 2.0)
                ctx.draw_point_3d(poi, (1.0, 0.2, 0.8, 1.0), 20.0)
                lbl = ctx.world_to_screen(poi)
                if lbl:
                    ctx.draw_text_2d((lbl[0]+10, lbl[1]-8), f"POI{i+1}", (1.0, 0.2, 0.8, 1.0))
                ctx.draw_point_3d(pts[0],  (0.2, 1.0, 0.2, 1.0), 14.0)
                ctx.draw_point_3d(pts[-1], (1.0, 0.4, 0.2, 1.0), 14.0)
                ctx.draw_line_3d(poi, pts[0], (1.0, 0.2, 0.8, 0.25), 1.0)

            # Transition dashes to next segment
            if i < len(segs) - 1:
                next_seg = segs[i + 1]
                if seg["type"] == "linear":
                    ce = seg["end"]
                    curr_end = (ce[0]+dx, ce[1]+dy, ce[2]+dz)
                else:
                    a_end = (seg["start_angle"] - seg["arc_degrees"] if seg["invert"]
                             else seg["start_angle"] + seg["arc_degrees"])
                    curr_end = _orbit_pos(seg["poi"], seg["radius"], seg["elevation"],
                                         a_end, seg["orbit_axis"])
                if next_seg["type"] == "linear":
                    ns = next_seg["start"]
                    next_start = (ns[0]+dx, ns[1]+dy, ns[2]+dz)
                else:
                    next_start = _orbit_pos(next_seg["poi"], next_seg["radius"],
                                            next_seg["elevation"], next_seg["start_angle"],
                                            next_seg["orbit_axis"])
                ctx.draw_line_3d(curr_end, next_start, (0.5, 0.5, 1.0, 0.4), 1.5)

    # ── Track 3 – LFS camera path ─────────────────────────────────────────────
    if State.track3_loaded and State._track3_player is not None:
        lp  = State._track3_player
        dur = lp.total_duration
        n   = 60
        pts = []
        for i in range(n + 1):
            t   = dur * i / n
            pos, rot, fov = lp._interpolate(t)
            pts.append(pos)
        for i in range(len(pts) - 1):
            ctx.draw_line_3d(pts[i], pts[i + 1], (0.4, 1.0, 0.6, 0.8), 2.0)
        ctx.draw_point_3d(pts[0],  (0.2, 1.0, 0.2, 1.0), 14.0)
        ctx.draw_point_3d(pts[-1], (1.0, 0.4, 0.2, 1.0), 14.0)
        lbl = ctx.world_to_screen(pts[0])
        if lbl:
            ctx.draw_text_2d((lbl[0] + 10, lbl[1] - 8), "LFS Path", (0.4, 1.0, 0.6, 1.0))


# ── Camera preview playback ───────────────────────────────────────────────────

_PREVIEW_SNAPS_PER_SEC   = 30.0
_PREVIEW_SPEEDS          = [0.5, 1.0, 2.0, 4.0]
_preview_active          = False
_preview_start_time      = 0.0
_preview_speed           = 1.0
_preview_handler_name    = "training_render_cam_preview"
_preview_original_camera = None  # (eye, target, up, fov)


def _start_path_preview() -> None:
    global _preview_active, _preview_start_time, _preview_original_camera
    try:
        cam = lf.get_camera()
        _preview_original_camera = (
            tuple(cam.eye), tuple(cam.target),
            tuple(cam.up), cam.fov,
        )
    except Exception:
        _preview_original_camera = None
    _preview_active     = True
    _preview_start_time = _time.time()
    try:
        lf.remove_draw_handler(_preview_handler_name)
    except Exception:
        pass
    lf.add_draw_handler(_preview_handler_name, _preview_camera_handler, "POST_VIEW")
    lf.ui.request_redraw()


def _stop_path_preview() -> None:
    global _preview_active
    _preview_active = False
    try:
        lf.remove_draw_handler(_preview_handler_name)
    except Exception:
        pass
    if _preview_original_camera is not None:
        eye, target, up, fov = _preview_original_camera
        try:
            lf.set_camera(eye, target, up)
            lf.set_camera_fov(fov)
        except Exception:
            pass
    lf.ui.request_redraw()


def _preview_camera_handler(ctx) -> None:
    global _preview_active
    if not _preview_active:
        return

    elapsed    = (_time.time() - _preview_start_time) * _preview_speed
    snap_index = int(elapsed * _PREVIEW_SNAPS_PER_SEC)

    if State.active_track == "track3" and State.track3_loaded and State._track3_player:
        loop        = State.track3_loop
        eye, target, up, fov = State._track3_player.get_camera_at_snap(
            snap_index, State.secs_per_snap, loop)
        total_snaps = (int(State._track3_player.total_duration / State.secs_per_snap)
                       if State.secs_per_snap > 0 else 1)
    elif State.active_track == "track2" and State.track2_loaded and State._track2_player:
        loop        = State.track2_loop
        eye, target, up, fov = State._track2_player.get_camera_at_snap(
            snap_index, State.dist_per_snap, loop)
        total_snaps = (_math.ceil(State._track2_player.total_length / State.dist_per_snap)
                       if State.dist_per_snap > 0 else 1)
    elif State.active_track == "track1" and State.track_loaded and State._track_player:
        loop        = State.track_loop
        eye, target, up, fov = State._track_player.get_camera_at_snap(
            snap_index, State.arc_per_snap, loop)
        arc_range   = abs(State._track_player.arc_end - State._track_player.arc_start)
        total_snaps = (int(arc_range / State.arc_per_snap)
                       if State.arc_per_snap > 0 else 1)
    else:
        _stop_path_preview()
        return

    try:
        lf.set_camera(eye, target, up)
        if State.use_track_fov:
            lf.set_camera_fov(fov)
    except Exception:
        pass

    if not loop and snap_index >= total_snaps:
        _stop_path_preview()
        return

    lf.ui.request_redraw()


# ── Module-level helpers ──────────────────────────────────────────────────────

def _open_folder(path: str) -> None:
    """Open *path* in Windows Explorer, creating it first if needed."""
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        lf.log.error(f"Training Render: could not create folder {path!r} – {exc}")
    try:
        subprocess.Popen(f'explorer "{path}"', shell=True)
    except Exception as exc:
        lf.log.error(f"Training Render: could not open folder – {exc}")


def _browse_folder(title: str, default_path: str) -> str | None:
    """Open a modern Explorer-style folder picker via PowerShell OpenFileDialog trick."""
    try:
        if sys.platform == "win32":
            initial_dir = default_path if os.path.isdir(default_path) else os.path.expanduser("~")
            initial_dir = initial_dir.replace(chr(92), chr(92) + chr(92))
            ps_script = f"""
                Add-Type -AssemblyName System.Windows.Forms
                $dialog = New-Object System.Windows.Forms.OpenFileDialog
                $dialog.Title = "{title}"
                $dialog.InitialDirectory = "{initial_dir}"
                $dialog.ValidateNames = $false
                $dialog.CheckFileExists = $false
                $dialog.CheckPathExists = $true
                $dialog.FileName = "Folder Selection."
                if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
                    Write-Output (Split-Path $dialog.FileName)
                }}
            """
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            path = result.stdout.strip()
            return path if path else None
    except Exception as exc:
        lf.log.error(f"Training Render: folder dialog error – {exc}")
    return None


def _browse_json_file(title: str, default_path: str) -> str | None:
    """Open a file picker filtered to .json files via PowerShell OpenFileDialog."""
    try:
        if sys.platform == "win32":
            initial_dir = default_path if os.path.isdir(default_path) else os.path.expanduser("~")
            initial_dir = initial_dir.replace(chr(92), chr(92) + chr(92))
            ps_script = f"""
                Add-Type -AssemblyName System.Windows.Forms
                $dialog = New-Object System.Windows.Forms.OpenFileDialog
                $dialog.Title = "{title}"
                $dialog.InitialDirectory = "{initial_dir}"
                $dialog.Filter = "Camera Track (*.json)|*.json|All Files (*.*)|*.*"
                $dialog.FilterIndex = 1
                if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
                    Write-Output $dialog.FileName
                }}
            """
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            path = result.stdout.strip()
            return path if path else None
    except Exception as exc:
        lf.log.error(f"Training Render: file dialog error – {exc}")
    return None


# ── Panel ─────────────────────────────────────────────────────────────────────

class TrainingRenderPanel(lf.ui.Panel):
    id                 = "training_render.main_panel"
    label              = "Training Render"
    space              = lf.ui.PanelSpace.MAIN_PANEL_TAB
    order              = 200
    template           = str(Path(__file__).resolve().with_name("training_render.rml"))
    height_mode        = lf.ui.PanelHeightMode.CONTENT
    update_interval_ms = 100
    poll_dependencies  = {lf.ui.PollDependency.TRAINING}

    _RESOLUTIONS = [
        (1280,  720),
        (1920, 1080),
        (2560, 1440),
        (3840, 2160),
    ]

    _OP_START = "lfs_plugins.training_render.operators.start.TRAININGRENDER_OT_start"
    _OP_STOP  = "lfs_plugins.training_render.operators.stop.TRAININGRENDER_OT_stop"

    def __init__(self):
        self._handle              = None
        self._resolution_idx      = 0
        self._pending_output_dir  = None  # written by browse thread, read in on_update
        self._pending_track_path  = None  # written by browse thread, read in on_update
        self._pending_track2_path = None
        self._pending_track3_path = None
        self._track1_expanded     = False
        self._track2_expanded     = False
        self._track3_expanded     = False
        self._preview_expanded    = False
        self._preview_speed_idx   = 1    # default 1×
        self._video_expanded      = False
        self._last_video_status   = ""
        self._last_preview_active = False
        # dirty-detection snapshots
        self._last_listening      = False
        self._last_trainer_state  = ""
        self._last_snap_count     = -1
        self._last_output_dir     = ""
        self._last_width          = 0
        self._last_height         = 0
        self._last_fov            = 0.0
        self._last_track_loaded   = False
        self._last_track_path     = ""
        self._last_track2_loaded  = False
        self._last_track2_path    = ""
        self._last_track3_loaded  = False
        self._last_track3_path    = ""
        self._last_active_track   = "none"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_bind_model(self, ctx):
        model = ctx.create_data_model("training_render")

        # Output
        model.bind_func("output_dir", lambda: State.output_dir)

        # Capture settings
        model.bind("render_every_str",
                   lambda: str(State.render_every),
                   lambda v: self._set_int_state("render_every", v, 1, 100_000))
        model.bind("max_iters_str",
                   lambda: str(State.max_iters),
                   lambda v: self._set_int_state("max_iters", v, 0, 1_000_000))

        # Resolution
        model.bind("resolution_idx",
                   lambda: str(self._resolution_idx),
                   self._set_resolution)
        model.bind_func("aspect_ratio_text", self._aspect_ratio_text)

        # FoV
        model.bind("fov_str",
                   lambda: f"{State.fov:.1f}",
                   self._set_fov)

        # Camera track collapsible state
        model.bind("track1_expanded",
                   lambda: self._track1_expanded,
                   lambda v: self._set_expand("_track1_expanded", v))
        model.bind_func("track1_arrow", lambda: "\u25bc" if self._track1_expanded else "\u25b6")
        model.bind("track2_expanded",
                   lambda: self._track2_expanded,
                   lambda v: self._set_expand("_track2_expanded", v))
        model.bind_func("track2_arrow", lambda: "\u25bc" if self._track2_expanded else "\u25b6")

        # Preview section collapsible state
        model.bind("preview_expanded",
                   lambda: self._preview_expanded,
                   lambda v: self._set_expand("_preview_expanded", v))
        model.bind_func("preview_arrow", lambda: "\u25bc" if self._preview_expanded else "\u25b6")

        # Camera track
        model.bind_func("track_path_display",  self._track_path_display)
        model.bind("arc_per_snap_str",
                   lambda: f"{State.arc_per_snap:.1f}",
                   lambda v: self._set_float_state("arc_per_snap", v, 0.0, 360.0))
        model.bind("fov_source",
                   lambda: "file" if State.use_track_fov else "panel",
                   self._set_fov_source)
        model.bind("track_loop",
                   lambda: State.track_loop,
                   lambda v: self._set_bool_state("track_loop", v))
        model.bind_func("track_status_text",  self._track_status_text)
        model.bind_func("track_status_class", self._track_status_class)

        # Active track + Camera track 2
        model.bind("active_track",
                   lambda: State.active_track,
                   lambda v: self._set_str_state("active_track", v))
        model.bind_func("track2_path_display",  self._track2_path_display)
        model.bind("dist_per_snap_str",
                   lambda: f"{State.dist_per_snap:.2f}",
                   lambda v: self._set_float_state("dist_per_snap", v, 0.001, 100.0))
        model.bind("track2_loop",
                   lambda: State.track2_loop,
                   lambda v: self._set_bool_state("track2_loop", v))
        model.bind_func("track2_status_text",  self._track2_status_text)
        model.bind_func("track2_status_class", self._track2_status_class)

        # Camera track 3 (LFS path) collapsible state
        model.bind("track3_expanded",
                   lambda: self._track3_expanded,
                   lambda v: self._set_expand("_track3_expanded", v))
        model.bind_func("track3_arrow", lambda: "\u25bc" if self._track3_expanded else "\u25b6")
        model.bind_func("track3_path_display",  self._track3_path_display)
        model.bind("secs_per_snap_str",
                   lambda: f"{State.secs_per_snap:.2f}",
                   lambda v: self._set_float_state("secs_per_snap", v, 0.01, 300.0))
        model.bind("track3_loop",
                   lambda: State.track3_loop,
                   lambda v: self._set_bool_state("track3_loop", v))
        model.bind_func("track3_status_text",  self._track3_status_text)
        model.bind_func("track3_status_class", self._track3_status_class)

        # Video output collapsible
        model.bind("video_expanded",
                   lambda: self._video_expanded,
                   lambda v: self._set_expand("_video_expanded", v))
        model.bind_func("video_arrow", lambda: "\u25bc" if self._video_expanded else "\u25b6")
        model.bind("create_video",
                   lambda: State.create_video,
                   lambda v: self._set_bool_state("create_video", v))
        model.bind("video_fps_str",
                   lambda: str(State.video_fps),
                   lambda v: self._set_int_state("video_fps", v, 1, 120))
        model.bind("video_encoder",
                   lambda: State.video_encoder,
                   lambda v: setattr(State, "video_encoder", v))
        model.bind_func("video_status_text",  self._video_status_text)
        model.bind_func("video_status_class", self._video_status_class)
        model.bind_event("do_create_video", self._on_do_create_video)

        # Controls / status
        model.bind_func("show_idle",            lambda: not State.listening)
        model.bind_func("show_listening",       lambda: State.listening)
        model.bind_func("show_start_training",  lambda: self._trainer_state() not in ("running", "paused"))
        model.bind_func("show_pause_training",  lambda: self._trainer_state() == "running")
        model.bind_func("show_resume_training", lambda: self._trainer_state() == "paused")
        model.bind_func("status_text",    self._status_text)

        # Path preview toggle
        model.bind("show_preview",
                   lambda: _show_preview,
                   self._set_show_preview)

        # Path preview playback
        model.bind("preview_speed_idx",
                   lambda: str(self._preview_speed_idx),
                   self._set_preview_speed)
        model.bind_func("preview_idle",          lambda: not _preview_active)
        model.bind_func("preview_active_state",  lambda: _preview_active)
        model.bind_func("preview_progress_text", self._preview_progress_text)

        # Events
        model.bind_event("do_start",          self._on_do_start)
        model.bind_event("do_stop",           self._on_do_stop)
        model.bind_event("do_start_training",  self._on_do_start_training)
        model.bind_event("do_pause_training",  self._on_do_pause_training)
        model.bind_event("do_resume_training", self._on_do_resume_training)
        model.bind_event("do_browse_folder",  self._on_do_browse_folder)
        model.bind_event("do_open_folder",    self._on_do_open_folder)
        model.bind_event("do_browse_track",   self._on_do_browse_track)
        model.bind_event("do_load_track",     self._on_do_load_track)
        model.bind_event("toggle_track1",     self._on_toggle_track1)
        model.bind_event("toggle_track2",     self._on_toggle_track2)
        model.bind_event("toggle_track3",     self._on_toggle_track3)
        model.bind_event("toggle_preview",    self._on_toggle_preview)
        model.bind_event("toggle_video",      self._on_toggle_video)
        model.bind_event("do_browse_track2",  self._on_do_browse_track2)
        model.bind_event("do_load_track2",    self._on_do_load_track2)
        model.bind_event("do_browse_track3",  self._on_do_browse_track3)
        model.bind_event("do_load_track3",    self._on_do_load_track3)
        model.bind_event("do_start_preview",  self._on_do_start_preview)
        model.bind_event("do_stop_preview",   self._on_do_stop_preview)
        model.bind_event("num_step",          self._on_num_step)

        self._handle = model.get_handle()
        _ensure_draw_handler()

    def on_update(self, doc):
        dirty = False

        # Apply pending output dir from browse thread
        if self._pending_output_dir is not None:
            State.output_dir = self._pending_output_dir
            self._pending_output_dir = None
            self._dirty("output_dir")
            dirty = True

        # Apply pending track path from browse thread
        if self._pending_track_path is not None:
            State.track_path = self._pending_track_path
            self._pending_track_path = None
            self._dirty("track_path_display")
            dirty = True

        # listening state
        if State.listening != self._last_listening:
            self._last_listening = State.listening
            self._dirty("show_idle", "show_listening", "status_text")
            dirty = True

        # trainer state (start/pause/resume button)
        ts = self._trainer_state()
        if ts != self._last_trainer_state:
            self._last_trainer_state = ts
            lf.log.info(f"Training Render: trainer_state={ts!r}")
            self._dirty("show_start_training", "show_pause_training", "show_resume_training")
            dirty = True

        # snap count
        if State.snap_count != self._last_snap_count:
            self._last_snap_count = State.snap_count
            self._dirty("status_text")
            dirty = True

        # output dir
        if State.output_dir != self._last_output_dir:
            self._last_output_dir = State.output_dir
            self._dirty("output_dir")
            dirty = True

        # resolution
        if State.width != self._last_width or State.height != self._last_height:
            self._last_width  = State.width
            self._last_height = State.height
            self._dirty("aspect_ratio_text")
            dirty = True

        # fov
        if State.fov != self._last_fov:
            self._last_fov = State.fov
            self._dirty("fov_str")
            dirty = True

        # track loaded / path
        if State.track_loaded != self._last_track_loaded:
            self._last_track_loaded = State.track_loaded
            self._dirty("track_status_text", "track_status_class", "track_path_display")
            dirty = True

        if State.track_path != self._last_track_path:
            self._last_track_path = State.track_path
            self._dirty("track_path_display")
            dirty = True

        # track2 loaded / path / active_track
        if self._pending_track2_path is not None:
            State.track2_path = self._pending_track2_path
            self._pending_track2_path = None
            self._dirty("track2_path_display")
            dirty = True

        if self._pending_track3_path is not None:
            State.track3_path = self._pending_track3_path
            self._pending_track3_path = None
            self._dirty("track3_path_display")
            dirty = True

        if State.track2_loaded != self._last_track2_loaded:
            self._last_track2_loaded = State.track2_loaded
            self._dirty("track2_status_text", "track2_status_class", "track2_path_display")
            dirty = True

        if State.track2_path != self._last_track2_path:
            self._last_track2_path = State.track2_path
            self._dirty("track2_path_display")
            dirty = True

        if State.track3_loaded != self._last_track3_loaded:
            self._last_track3_loaded = State.track3_loaded
            self._dirty("track3_status_text", "track3_status_class", "track3_path_display")
            dirty = True

        if State.track3_path != self._last_track3_path:
            self._last_track3_path = State.track3_path
            self._dirty("track3_path_display")
            dirty = True

        if State.active_track != self._last_active_track:
            self._last_active_track = State.active_track
            self._dirty("active_track")
            dirty = True

        # preview playback state
        if _preview_active != self._last_preview_active:
            self._last_preview_active = _preview_active
            self._dirty("preview_idle", "preview_active_state", "preview_progress_text")
            dirty = True
        if _preview_active:
            self._dirty("preview_progress_text")
            dirty = True

        # video encoding status
        if State.video_status != self._last_video_status:
            self._last_video_status = State.video_status
            self._dirty("video_status_text", "video_status_class")
            dirty = True

        return dirty

    def on_unmount(self, doc):
        global _draw_handler_registered
        _stop_path_preview()
        try:
            lf.remove_draw_handler("training_render_preview")
        except Exception:
            pass
        _draw_handler_registered = False
        doc.remove_data_model("training_render")
        self._handle = None

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_do_start(self, handle, event, args):
        lf.ui.ops.invoke(self._OP_START)

    def _on_do_stop(self, handle, event, args):
        lf.ui.ops.invoke(self._OP_STOP)

    def _trainer_state(self) -> str:
        """Return 'training', 'paused', or '' (idle/no trainer)."""
        try:
            has = lf.has_trainer()
            if has:
                raw = lf.trainer_state()
                s = str(raw).lower()
                return s
            return ""
        except Exception as exc:
            lf.log.error(f"Training Render: _trainer_state error – {type(exc).__name__}: {exc}")
            return ""

    def _on_do_create_video(self, handle, event, args):
        if not State.output_dir:
            return
        from ..core.renderer import create_video_now
        create_video_now()

    def _on_do_start_training(self, handle, event, args):
        try:
            lf.start_training()
        except Exception as exc:
            lf.log.error(f"Training Render: could not start training – {exc}")

    def _on_do_pause_training(self, handle, event, args):
        try:
            lf.pause_training()
        except Exception as exc:
            lf.log.error(f"Training Render: could not pause training – {exc}")

    def _on_do_resume_training(self, handle, event, args):
        try:
            lf.resume_training()
        except Exception as exc:
            lf.log.error(f"Training Render: could not resume training – {exc}")

    def _on_do_browse_folder(self, handle, event, args):
        current = State.output_dir
        def _browse():
            picked = _browse_folder("Select output folder", current)
            if picked:
                self._pending_output_dir = picked
        threading.Thread(target=_browse, daemon=True).start()

    def _on_do_open_folder(self, handle, event, args):
        _open_folder(State.output_dir)

    def _on_do_browse_track(self, handle, event, args):
        initial = str(Path(State.track_path).parent) if State.track_path else os.path.expanduser("~")
        def _browse():
            picked = _browse_json_file("Select camera_track.json", initial)
            if picked:
                self._pending_track_path = picked
        threading.Thread(target=_browse, daemon=True).start()

    def _on_do_load_track(self, handle, event, args):
        # Flush any pending path from the browse thread before loading
        if self._pending_track_path is not None:
            State.track_path = self._pending_track_path
            self._pending_track_path = None
            self._dirty("track_path_display")

        if not State.track_path:
            lf.log.error("Training Render: no track file selected.")
            return

        lf.log.info(f"Training Render: loading track from {State.track_path!r}")
        try:
            State._track_player = TrackPlayer(State.track_path)
            State.track_loaded  = True
            lf.log.info(f"Training Render: track loaded – {State._track_player.info}")
            self._dirty("track_status_text", "track_status_class", "track_path_display")
        except Exception as exc:
            State._track_player = None
            State.track_loaded  = False
            lf.log.error(f"Training Render: failed to load track – {exc}")
            self._dirty("track_status_text", "track_status_class")

    def _on_toggle_track1(self, handle, event, args):
        self._track1_expanded = not self._track1_expanded
        self._dirty("track1_expanded", "track1_arrow")

    def _on_toggle_track2(self, handle, event, args):
        self._track2_expanded = not self._track2_expanded
        self._dirty("track2_expanded", "track2_arrow")

    def _on_toggle_track3(self, handle, event, args):
        self._track3_expanded = not self._track3_expanded
        self._dirty("track3_expanded", "track3_arrow")

    def _on_toggle_preview(self, handle, event, args):
        self._preview_expanded = not self._preview_expanded
        self._dirty("preview_expanded", "preview_arrow")

    def _on_toggle_video(self, handle, event, args):
        self._video_expanded = not self._video_expanded
        self._dirty("video_expanded", "video_arrow")

    def _on_do_browse_track2(self, handle, event, args):
        initial = str(Path(State.track2_path).parent) if State.track2_path else os.path.expanduser("~")
        def _browse():
            picked = _browse_json_file("Select camera_track2.json", initial)
            if picked:
                self._pending_track2_path = picked
        threading.Thread(target=_browse, daemon=True).start()

    def _on_do_load_track2(self, handle, event, args):
        if self._pending_track2_path is not None:
            State.track2_path = self._pending_track2_path
            self._pending_track2_path = None
            self._dirty("track2_path_display")

        if not State.track2_path:
            lf.log.error("Training Render: no Track 2 file selected.")
            return

        lf.log.info(f"Training Render: loading Track 2 from {State.track2_path!r}")
        try:
            State._track2_player = MultiSegmentTrackPlayer(State.track2_path)
            State.track2_loaded  = True
            lf.log.info(f"Training Render: Track 2 loaded – {State._track2_player.info(State.dist_per_snap)}")
            self._dirty("track2_status_text", "track2_status_class", "track2_path_display")
        except Exception as exc:
            State._track2_player = None
            State.track2_loaded  = False
            lf.log.error(f"Training Render: failed to load Track 2 – {exc}")
            self._dirty("track2_status_text", "track2_status_class")

    def _on_do_browse_track3(self, handle, event, args):
        initial = str(Path(State.track3_path).parent) if State.track3_path else os.path.expanduser("~")
        def _browse():
            picked = _browse_json_file("Select camera_path.json", initial)
            if picked:
                self._pending_track3_path = picked
        threading.Thread(target=_browse, daemon=True).start()

    def _on_do_load_track3(self, handle, event, args):
        if self._pending_track3_path is not None:
            State.track3_path = self._pending_track3_path
            self._pending_track3_path = None
            self._dirty("track3_path_display")

        if not State.track3_path:
            lf.log.error("Training Render: no LFS path file selected.")
            return

        lf.log.info(f"Training Render: loading LFS path from {State.track3_path!r}")
        try:
            State._track3_player = LFSPathPlayer(State.track3_path)
            State.track3_loaded  = True
            lf.log.info(f"Training Render: LFS path loaded – {State._track3_player.info(State.secs_per_snap)}")
            self._dirty("track3_status_text", "track3_status_class", "track3_path_display")
        except Exception as exc:
            State._track3_player = None
            State.track3_loaded  = False
            lf.log.error(f"Training Render: failed to load LFS path – {exc}")
            self._dirty("track3_status_text", "track3_status_class")

    def _on_do_start_preview(self, handle, event, args):
        if State.active_track == "none":
            return
        _start_path_preview()
        self._dirty("preview_idle", "preview_active_state", "preview_progress_text")

    def _on_do_stop_preview(self, handle, event, args):
        _stop_path_preview()
        self._dirty("preview_idle", "preview_active_state", "preview_progress_text")

    def _on_num_step(self, handle, event, args):
        if not args or len(args) < 2:
            return
        field     = str(args[0])
        direction = int(args[1])
        # int fields
        int_steps  = {"render_every": 1, "max_iters": 100, "video_fps": 1}
        int_ranges = {"render_every": (1, 100_000), "max_iters": (0, 1_000_000), "video_fps": (1, 120)}
        # float fields
        flt_steps  = {"arc_per_snap": 1.0, "dist_per_snap": 0.01, "secs_per_snap": 0.1}
        flt_ranges = {"arc_per_snap": (0.0, 360.0), "dist_per_snap": (0.001, 100.0), "secs_per_snap": (0.01, 300.0)}

        if field in int_steps:
            step   = int_steps[field]
            lo, hi = int_ranges[field]
            current   = getattr(State, field, 0)
            new_val   = max(lo, min(hi, current + direction * step))
            if new_val != current:
                setattr(State, field, new_val)
                self._dirty(f"{field}_str")
        elif field in flt_steps:
            step   = flt_steps[field]
            lo, hi = flt_ranges[field]
            current = getattr(State, field, 0.0)
            decimals = 3 if field in ("dist_per_snap", "secs_per_snap") else 1
            new_val = round(max(lo, min(hi, current + direction * step)), decimals)
            if abs(new_val - current) > 1e-6:
                setattr(State, field, new_val)
                self._dirty(f"{field}_str")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _dirty(self, *fields):
        if not self._handle:
            return
        for f in fields:
            self._handle.dirty(f)

    def _set_int_state(self, attr: str, value, lo: int, hi: int):
        try:
            v = max(lo, min(hi, int(float(value))))
        except (TypeError, ValueError):
            return
        if v == getattr(State, attr):
            return
        setattr(State, attr, v)
        self._dirty(f"{attr}_str")

    def _set_float_state(self, attr: str, value, lo: float, hi: float):
        try:
            raw = float(value)
            decimals = 3 if attr == "dist_per_snap" else 1
            v = round(max(lo, min(hi, raw)), decimals)
        except (TypeError, ValueError):
            return
        if abs(v - getattr(State, attr, 0.0)) < 1e-9:
            return
        setattr(State, attr, v)
        self._dirty(f"{attr}_str")

    def _set_str_state(self, attr: str, value):
        setattr(State, attr, str(value))

    def _set_show_preview(self, value):
        global _show_preview
        if isinstance(value, str):
            _show_preview = value.lower() not in ("false", "0", "")
        else:
            _show_preview = bool(value)
        lf.ui.request_redraw()

    def _set_preview_speed(self, value):
        global _preview_speed
        try:
            idx = max(0, min(len(_PREVIEW_SPEEDS) - 1, int(value)))
        except (ValueError, TypeError):
            return
        self._preview_speed_idx = idx
        _preview_speed = _PREVIEW_SPEEDS[idx]

    def _preview_progress_text(self) -> str:
        if not _preview_active:
            return ""
        elapsed    = (_time.time() - _preview_start_time) * _preview_speed
        snap_index = int(elapsed * _PREVIEW_SNAPS_PER_SEC)
        if State.active_track == "track3" and State._track3_player and State.secs_per_snap > 0:
            total = int(State._track3_player.total_duration / State.secs_per_snap)
        elif State.active_track == "track2" and State._track2_player and State.dist_per_snap > 0:
            total = _math.ceil(State._track2_player.total_length / State.dist_per_snap)
        elif State.active_track == "track1" and State._track_player and State.arc_per_snap > 0:
            total = int(abs(State._track_player.arc_end - State._track_player.arc_start)
                        / State.arc_per_snap)
        else:
            return "Previewing\u2026"
        pct = min(100, int(snap_index / total * 100)) if total > 0 else 0
        return f"Preview: {pct}%  (snap {snap_index}/{total})"

    def _set_expand(self, attr: str, value):
        """Setter for collapsible bool — ignores external writes (toggle event owns state)."""
        pass  # state is managed exclusively by the toggle event handlers

    def _set_bool_state(self, attr: str, value):
        if isinstance(value, str):
            v = value.lower() not in ("false", "0", "")
        else:
            v = bool(value)
        setattr(State, attr, v)

    def _set_resolution(self, value):
        try:
            idx = int(value)
        except (TypeError, ValueError):
            return
        idx = max(0, min(len(self._RESOLUTIONS) - 1, idx))
        if idx == self._resolution_idx:
            return
        self._resolution_idx = idx
        State.width, State.height = self._RESOLUTIONS[idx]
        self._dirty("resolution_idx", "aspect_ratio_text")

    def _set_fov(self, value):
        try:
            v = max(5.0, min(170.0, float(value)))
        except (TypeError, ValueError):
            return
        if abs(v - State.fov) < 1e-4:
            return
        State.fov = v
        self._dirty("fov_str")

    def _set_fov_source(self, value):
        State.use_track_fov = (str(value) == "file")
        self._dirty("fov_source")

    def _aspect_ratio_text(self) -> str:
        divisor = gcd(State.width, State.height)
        ar_w = State.width  // divisor
        ar_h = State.height // divisor
        return f"Aspect ratio  {ar_w}:{ar_h}  ({State.width} \u00d7 {State.height})"

    def _track_path_display(self) -> str:
        if State.track_path:
            return Path(State.track_path).name
        return "No track file selected"

    def _track_status_text(self) -> str:
        if State.track_loaded and State._track_player is not None:
            return f"\u2713 Loaded \u2013 {State._track_player.info}"
        return "\u25cb Not loaded"

    def _track_status_class(self) -> str:
        return "text-accent" if State.track_loaded else "text-muted"

    def _track2_path_display(self) -> str:
        if State.track2_path:
            return Path(State.track2_path).name
        return "No track file selected"

    def _track2_status_text(self) -> str:
        if State.track2_loaded and State._track2_player is not None:
            return f"\u2713 Loaded \u2013 {State._track2_player.info(State.dist_per_snap)}"
        return "\u25cb Not loaded"

    def _track2_status_class(self) -> str:
        return "text-accent" if State.track2_loaded else "text-muted"

    def _track3_path_display(self) -> str:
        if State.track3_path:
            return Path(State.track3_path).name
        return "No path file selected"

    def _track3_status_text(self) -> str:
        if State.track3_loaded and State._track3_player is not None:
            return f"\u2713 Loaded \u2013 {State._track3_player.info(State.secs_per_snap)}"
        return "\u25cb Not loaded"

    def _track3_status_class(self) -> str:
        return "text-accent" if State.track3_loaded else "text-muted"

    def _video_status_text(self) -> str:
        return State.video_status if State.video_status else "\u25cb Idle"

    def _video_status_class(self) -> str:
        s = State.video_status
        if s.startswith("\u2713"):
            return "text-accent"
        if s.startswith("\u2717"):
            return "text-muted"
        return "text-muted"

    def _status_text(self) -> str:
        if State.listening:
            return f"\u25cf Listening  |  {State.snap_count} snapshot(s) saved"
        if State.snap_count > 0:
            return f"\u25ce Stopped  |  {State.snap_count} snapshot(s) saved"
        return "\u25cb Idle \u2013 press Start Listening"
