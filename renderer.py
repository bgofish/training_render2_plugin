# SPDX-FileCopyrightText: 2025
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path
import datetime
import subprocess
import threading

import lichtfeld as lf

from .state import State


def render_and_save(iteration: int, snap_index: int = 0) -> None:
    if not State.listening:
        return
    try:
        # ── Camera position ───────────────────────────────────────────────────
        if State.active_track == "track3" and State.track3_loaded and State._track3_player:
            eye, target, up, fov = State._track3_player.get_camera_at_snap(
                snap_index, State.secs_per_snap, State.track3_loop
            )
            if not State.use_track_fov:
                fov = State.fov
        elif State.active_track == "track2" and State.track2_loaded and State._track2_player:
            eye, target, up, fov = State._track2_player.get_camera_at_snap(
                snap_index, State.dist_per_snap, State.track2_loop
            )
            if not State.use_track_fov:
                fov = State.fov
            lf.log.info(
                f"Training Render [track2] snap={snap_index}  "
                f"dist={State.dist_per_snap:.3f}m  "
                f"travel={snap_index * State.dist_per_snap:.3f}m  "
                f"eye=({eye[0]:.3f},{eye[1]:.3f},{eye[2]:.3f})"
            )
        elif State.active_track == "track1" and State.track_loaded and State._track_player:
            eye, target, up, fov = State._track_player.get_camera_at_snap(
                snap_index, State.arc_per_snap, State.track_loop
            )
            if not State.use_track_fov:
                fov = State.fov
        else:
            cam    = lf.get_camera()
            eye    = cam.eye
            target = cam.target
            up     = cam.up
            fov    = State.fov

        tensor = lf.render_at(eye, target, State.width, State.height, fov, up)

        # Abort if Stop was pressed while the render was in-flight
        if not State.listening:
            return

        # ── File name ─────────────────────────────────────────────────────────
        if isinstance(iteration, int) and iteration > 0:
            name = f"iter_{iteration:07d}.png"
        else:
            name = f"snap_{snap_index + 1:07d}.png"

        out_path = Path(State.output_dir) / name
        lf.io.save_image(str(out_path), tensor)

        State.snap_count += 1
        lf.log.info(
            f"Training Render: saved {out_path.name} ({State.snap_count} total)"
        )
    except Exception as exc:
        lf.log.error(f"Training Render: render failed at iter {iteration} \u2013 {exc}")


_collate_started = False


def do_stop() -> None:
    global _collate_started
    State.listening = False
    if _collate_started:
        return
    _collate_started = True
    lf.log.info(f"Training Render: stopped after {State.snap_count} snapshots.")
    if State.create_video and State.snap_count > 0:
        threading.Thread(target=_collate_video, daemon=True).start()


def create_video_now() -> None:
    """Trigger video collation immediately, regardless of create_video flag."""
    threading.Thread(target=_collate_video, daemon=True).start()


# ── Video collation ────────────────────────────────────────────────────────────

def _collate_video() -> None:
    if State.video_encoder == "ffmpeg":
        _collate_ffmpeg()
    else:
        _collate_pyav()


def _collate_pyav() -> None:
    """Encode PNGs → MKV using PyAV (in-process, no external binary needed)."""
    State.video_status = "encoding\u2026"
    out_dir  = Path(State.output_dir)
    ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"training_render_{ts}.mkv"

    pngs = sorted(out_dir.glob("*.png"))
    if not pngs:
        State.video_status = "\u2717 No PNG files found in output folder"
        lf.log.error("Training Render: video collation \u2013 no PNGs found")
        return

    try:
        import io
        import av

        # Probe dimensions from first frame
        with av.open(pngs[0].as_posix()) as probe:
            first = next(probe.decode(video=0))
            w, h = first.width, first.height

        # yuv420p requires even dimensions
        w += w % 2
        h += h % 2

        # Encode into BytesIO (matroska is a streaming format — no seeking needed)
        for codec in ("libx264", "mpeg4"):
            try:
                buf = io.BytesIO()
                with av.open(buf, mode="w", format="matroska") as container:
                    stream = container.add_stream(codec, rate=State.video_fps)
                    stream.width   = w
                    stream.height  = h
                    stream.pix_fmt = "yuv420p"
                    if codec == "libx264":
                        stream.codec_context.options = {"crf": "18", "preset": "fast"}

                    frame_idx = 0
                    for png_path in pngs:
                        with av.open(png_path.as_posix()) as src:
                            for frame in src.decode(video=0):
                                frame = frame.reformat(width=w, height=h, format="yuv420p")
                                frame.pts = frame_idx
                                frame_idx += 1
                                for pkt in stream.encode(frame):
                                    container.mux(pkt)

                    for pkt in stream.encode():
                        container.mux(pkt)

                out_file.write_bytes(buf.getvalue())
                break
            except Exception as codec_exc:
                lf.log.error(f"Training Render: PyAV codec {codec} failed \u2013 {codec_exc}")
                if codec == "mpeg4":
                    raise

        State.video_status = f"\u2713 Saved: {out_file.name}"
        lf.log.info(f"Training Render: video saved to {out_file}")

    except ImportError:
        State.video_status = "\u2717 PyAV not installed \u2013 run: pip install av"
        lf.log.error("Training Render: PyAV (av) not found \u2013 pip install av")
    except Exception as exc:
        State.video_status = f"\u2717 Error: {exc}"
        lf.log.error(f"Training Render: video collation error \u2013 {exc}")


def _collate_ffmpeg() -> None:
    """Encode PNGs → MP4 using an external ffmpeg binary."""
    import tempfile, shutil

    State.video_status = "encoding\u2026"
    out_dir  = Path(State.output_dir)
    ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"training_render_{ts}.mp4"

    pngs = sorted(out_dir.glob("*.png"))
    if not pngs:
        State.video_status = "\u2717 No PNG files found in output folder"
        lf.log.error("Training Render: video collation \u2013 no PNGs found")
        return

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        State.video_status = "\u2717 ffmpeg not found in PATH"
        lf.log.error("Training Render: ffmpeg not found in PATH")
        return

    try:
        flist_path = None
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False, encoding="utf-8") as flist:
            flist_path = flist.name
            for p in pngs:
                flist.write(f"file '{p.as_posix()}'\n")
                flist.write(f"duration {1.0 / State.video_fps}\n")

        cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", flist_path,
            "-vf", f"fps={State.video_fps}",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            str(out_file),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-500:])

        State.video_status = f"\u2713 Saved: {out_file.name}"
        lf.log.info(f"Training Render: video saved to {out_file}")

    except Exception as exc:
        State.video_status = f"\u2717 Error: {exc}"
        lf.log.error(f"Training Render: ffmpeg collation error \u2013 {exc}")
    finally:
        if flist_path:
            try:
                Path(flist_path).unlink()
            except OSError:
                pass
