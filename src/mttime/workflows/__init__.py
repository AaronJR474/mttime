# SPDX-License-Identifier: LGPL-3.0-only
"""Additive high-level workflows for MTtime.

The workflow layer intentionally remains separate from :mod:`mttime.core` so the
upstream inversion API stays recognizable.  Import either helper module directly::

    from mttime.workflows import mttime_helpers, gf_helpers

PyFK is imported lazily by the functions that require it; Syngine workflows can
therefore be used when PyFK is not installed.

Use :func:`run_auto_cmt` to run the acquisition-through-inversion workflow.
"""

from .mttime_helpers import run_auto_cmt

__all__ = ["mttime_helpers", "gf_helpers", "run_auto_cmt"]
