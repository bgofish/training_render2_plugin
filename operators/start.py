# SPDX-FileCopyrightText: 2025
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import lichtfeld as lf
from lfs_plugins.types import Operator

from ..core.state import State
from ..core.handler import ensure_post_step_hook_registered
from ..core import renderer as _renderer


class TRAININGRENDER_OT_start(Operator):
    label       = "Start Listening"
    description = "Start saving renders every N training iterations"

    @classmethod
    def poll(cls, context) -> bool:
        return not State.listening

    def execute(self, context) -> set:
        out = Path(State.output_dir)
        try:
            out.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            lf.log.error(f"Training Render: cannot create output dir – {exc}")
            return {"CANCELLED"}

        State.snap_count           = 0
        State.listening            = True
        _renderer._collate_started = False

        ensure_post_step_hook_registered()
        lf.log.info(
            f"Training Render: listening every {State.render_every} iters → {out}"
        )
        return {"FINISHED"}
