"""Persistent Kaleido renderer for PNG export.

kaleido's default fig.to_image()/write_image() spins up a fresh headless
Chromium instance and tears it down on every single call (~8-12s each,
verified). This keeps one browser open for the lifetime of the process,
driven by a dedicated background thread's event loop, so exports after the
first only cost the actual render (~0.5s) instead of a full browser
cold-start. Calling code stays synchronous (Dash callbacks aren't async).
"""
from __future__ import annotations

import asyncio
import threading

import kaleido


class PngExporter:
    def __init__(self, n: int = 1):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._kaleido = kaleido.Kaleido(n=n)
        self._submit(self._kaleido.open()).result(timeout=60)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def render_png(self, fig_dict: dict, width: int, height: int, scale: float) -> bytes:
        coro = self._kaleido.calc_fig(fig_dict, opts=dict(format="png", width=width, height=height, scale=scale))
        return self._submit(coro).result(timeout=30)


_exporter: PngExporter | None = None


def get_exporter() -> PngExporter:
    global _exporter
    if _exporter is None:
        _exporter = PngExporter()
    return _exporter
