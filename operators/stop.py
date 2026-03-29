# SPDX-FileCopyrightText: 2025
# SPDX-License-Identifier: GPL-3.0-or-later

import lichtfeld as lf
from lfs_plugins.types import Operator

from ..core.renderer import do_stop
from ..core.state import State


class TRAININGRENDER_OT_stop(Operator):
    label       = "Stop"
    description = "Stop saving renders"

    @classmethod
    def poll(cls, context) -> bool:
        return State.listening

    def execute(self, context) -> set:
        do_stop()
        return {"FINISHED"}
