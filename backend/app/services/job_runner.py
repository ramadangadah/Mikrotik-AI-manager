"""
Fire-and-forget background task launcher. asyncio.create_task() results
must be kept referenced somewhere or they can be garbage-collected mid-run;
this module is that somewhere.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)
_background_tasks: set[asyncio.Task] = set()


def launch(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)

    def _done(t: asyncio.Task):
        _background_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logger.exception("background job failed", exc_info=exc)

    task.add_done_callback(_done)
    return task
