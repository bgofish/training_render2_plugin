# SPDX-FileCopyrightText: 2025
# SPDX-License-Identifier: GPL-3.0-or-later

import lichtfeld as lf

from .state import State
from .renderer import render_and_save, do_stop


_hook_registered: bool = False
_warned_bad_iteration: bool = False


def ensure_post_step_hook_registered() -> None:
    global _hook_registered
    if _hook_registered:
        return
    lf.on_post_step(on_post_step)
    _hook_registered = True


def on_post_step(ctx=None):
    """Called by LFS after every training step.

    LichtFeld may pass the current training context as an argument.
    """
    if not State.listening:
        return

    if ctx is None:
        ctx = lf.context()

    # LichtFeld may pass either a context object (with `.iteration`) or a dict
    # with some variant of an iteration key.
    iteration = None
    if isinstance(ctx, dict):
        for key in ("iteration", "iter", "step", "global_step", "train_step"):
            if key in ctx:
                iteration = ctx.get(key)
                break
    else:
        for attr in ("iteration", "iter", "step", "global_step", "train_step"):
            if hasattr(ctx, attr):
                iteration = getattr(ctx, attr)
                break

    if iteration is None:
        gctx = lf.context()
        for attr in ("iteration", "iter", "step", "global_step", "train_step"):
            if hasattr(gctx, attr):
                iteration = getattr(gctx, attr)
                break

    try:
        iteration = int(iteration)
    except Exception:
        iteration = 0

    global _warned_bad_iteration
    if iteration <= 0:
        if not _warned_bad_iteration:
            _warned_bad_iteration = True
            lf.log.error(
                "Training Render: could not read a valid training iteration from context; "
                "filenames will use snapshot index to avoid overwriting."
            )
        return  # skip – no valid iteration, would produce a blank frame

    # ── Rate schedule mode ───────────────────────────────────────────────────
    if getattr(State, "rate_mode", "fixed") == "schedule":
        schedule = getattr(State, "rate_schedule", [])
        if schedule:
            # Find the active row — highest start_iter <= current iteration
            active_every = schedule[0][1]  # default to first row
            for start_iter, every in schedule:
                if iteration >= start_iter:
                    active_every = every
                else:
                    break

            # STOP row reached — stop immediately, no render
            if active_every == "STOP":
                do_stop()
                return

            if iteration % active_every != 0 and iteration != 1:
                return
            render_and_save(iteration, State.snap_count)
            return

    # ── Fixed mode (original behaviour) ──────────────────────────────────────
    if State.max_iters > 0 and iteration >= State.max_iters:
        render_and_save(iteration, State.snap_count)
        do_stop()
        return

    if iteration % State.render_every != 0 and iteration != 1:
        return

    render_and_save(iteration, State.snap_count)