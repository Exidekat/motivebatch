"""A small terminal progress bar.

Writes to stderr with carriage returns so stdout stays a clean list of output
paths, and disables itself when not attached to a terminal so redirected output
does not fill up with control characters.
"""

import sys
import time

_BLOCKS = ("█", "░")   # full block, light shade
_ASCII = ("#", ".")

#: Redraws per second.  Frequent enough to look smooth, rare enough that the
#: drawing never becomes a measurable share of the export time.
_REDRAW_HZ = 20.0


def _supports_unicode(stream):
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return False
    try:
        for glyph in _BLOCKS:
            glyph.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False   # e.g. cp1252; note cp437 does carry both glyphs
    return True


class Progress(object):
    """Determinate when a total is known, an animated pulse when it is not."""

    def __init__(self, label="", stream=None, enabled=None, width=28):
        self.stream = stream or sys.stderr
        self.label = label
        self.width = width
        if enabled is None:
            enabled = bool(getattr(self.stream, "isatty", lambda: False)())
        self.enabled = enabled
        self.full, self.empty = _BLOCKS if _supports_unicode(self.stream) else _ASCII
        self.total = None
        self.done = 0
        self._last_draw = 0.0
        self._pulse = 0
        self._started = None
        self._dirty = False

    # -- lifecycle ------------------------------------------------------------

    def start(self, total=None):
        self.total = total if (total or 0) > 0 else None
        self.done = 0
        self._started = time.time()
        self._draw(force=True)
        return self

    def update(self, done, total=None):
        if total is not None and total > 0:
            self.total = total
        self.done = done
        self._draw()

    def advance(self, n=1):
        self.update(self.done + n)

    def pulse(self):
        """Advance the indeterminate animation."""
        self._pulse += 1
        self._draw()

    def finish(self, message=None):
        if not self.enabled:
            return
        if self.total:
            self.done = self.total
        self._draw(force=True, final=True)
        if self._dirty:
            self.stream.write("\n")
            self.stream.flush()
            self._dirty = False
        if message:
            self.stream.write(message + "\n")
            self.stream.flush()

    # So a failed export cannot leave a half-drawn bar on screen.
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.finish()
        else:
            self.clear()
        return False

    def clear(self):
        if self.enabled and self._dirty:
            self.stream.write("\r" + " " * self._line_width() + "\r")
            self.stream.flush()
            self._dirty = False

    # -- rendering ------------------------------------------------------------

    def _line_width(self):
        return self.width + len(self.label) + 40

    def _draw(self, force=False, final=False):
        if not self.enabled:
            return
        now = time.time()
        if not force and (now - self._last_draw) < (1.0 / _REDRAW_HZ):
            return
        self._last_draw = now

        if self.total:
            frac = min(1.0, max(0.0, float(self.done) / self.total))
            filled = int(round(frac * self.width))
            bar = self.full * filled + self.empty * (self.width - filled)
            tail = "{:3.0f}%  {:,}/{:,}".format(frac * 100.0, self.done, self.total)
        else:
            # No total: sweep a short block back and forth instead of faking a
            # percentage we do not actually know.
            span = max(1, self.width // 4)
            cycle = max(1, (self.width - span) * 2)
            pos = self._pulse % cycle
            if pos > (self.width - span):
                pos = cycle - pos
            bar = (self.empty * pos + self.full * span
                   + self.empty * (self.width - span - pos))
            tail = "working" if not final else "done"
            if final:
                bar = self.full * self.width

        line = "  {} [{}] {}".format(self.label, bar, tail) if self.label \
            else "  [{}] {}".format(bar, tail)
        self.stream.write("\r" + line.ljust(self._line_width())[:self._line_width()])
        self.stream.flush()
        self._dirty = True


def run_with_pulse(fn, bar, interval=0.08):
    """Run ``fn`` on a worker thread while animating an indeterminate bar.

    NMotive's Export is a single opaque call with no progress callback, so the
    only honest feedback is "still working" rather than a invented percentage.
    """
    import threading

    outcome = {}

    def worker():
        try:
            outcome["value"] = fn()
        except BaseException as exc:      # re-raised on the calling thread
            outcome["error"] = exc

    thread = threading.Thread(target=worker)
    thread.daemon = True
    bar.start(None)
    thread.start()
    while thread.is_alive():
        bar.pulse()
        thread.join(interval)
    if "error" in outcome:
        bar.clear()
        raise outcome["error"]
    bar.finish()
    return outcome.get("value")


class NullProgress(object):
    """Stand-in used when progress display is off."""

    enabled = False

    def start(self, total=None):
        return self

    def update(self, done, total=None):
        pass

    def advance(self, n=1):
        pass

    def pulse(self):
        pass

    def finish(self, message=None):
        pass

    def clear(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
