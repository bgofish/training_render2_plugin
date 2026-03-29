# SPDX-FileCopyrightText: 2025
# SPDX-License-Identifier: GPL-3.0-or-later

"""Training Render Plugin for LichtFeld Studio 005."""

import lichtfeld as lf

from .panels.training_render import TrainingRenderPanel
from .operators.start import TRAININGRENDER_OT_start
from .operators.stop import TRAININGRENDER_OT_stop

_classes = [
    TrainingRenderPanel,
    TRAININGRENDER_OT_start,
    TRAININGRENDER_OT_stop,
]


def on_load():
    for cls in _classes:
        lf.register_class(cls)
    lf.log.info("Training Render plugin loaded")


def on_unload():
    for cls in reversed(_classes):
        lf.unregister_class(cls)
    lf.log.info("Training Render plugin unloaded")


__all__ = ["TrainingRenderPanel"]
