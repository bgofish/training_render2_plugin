# SPDX-FileCopyrightText: 2025
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path


class State:
    listening:    bool  = False
    snap_count:   int   = 0
    render_every: int   = 10
    max_iters:    int   = 0
    output_dir:   str   = str(Path.home() / "lfs_training_renders10")
    width:        int   = 1280
    height:       int   = 720
    fov:          float = 45.0

    # Camera track
    track_path:    str   = ""
    arc_per_snap:  float = 1.0
    use_track_fov: bool  = True   # True = FoV from JSON, False = panel FoV
    track_loop:    bool  = True
    track_loaded:  bool  = False
    _track_player         = None  # TrackPlayer instance, not serialised

    # Camera track 2 (multi-segment)
    active_track:   str   = "none"  # "none" | "track1" | "track2" | "track3"
    track2_path:    str   = ""
    dist_per_snap:  float = 0.1     # metres per snapshot
    track2_loop:    bool  = True
    track2_loaded:  bool  = False
    _track2_player        = None    # MultiSegmentTrackPlayer instance, not serialised

    # Camera track 3 (LFS camera path)
    track3_path:    str   = ""
    secs_per_snap:  float = 0.5     # seconds of animation per snapshot
    track3_loop:    bool  = True
    track3_loaded:  bool  = False
    _track3_player        = None    # LFSPathPlayer instance, not serialised

    # Video collation
    create_video:  bool = False
    video_fps:     int  = 24
    video_encoder: str  = "pyav"   # "pyav" | "ffmpeg"
    video_status:  str  = ""   # "", "encoding…", "✓ …", "✗ …"
