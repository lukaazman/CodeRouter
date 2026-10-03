"""Presentation helpers for the CodeRouter window.

Dependency-free: anti-aliased stroke icons rendered into Tk PhotoImages,
a single-loop tween animator, and colour helpers. Nothing here touches run
state; the app wires these into its existing widgets.
"""

import ctypes
import math
import os
import time
import tkinter as tk


def hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def mix(color_a, color_b, amount):
    """Blend color_a toward color_b by amount (0..1)."""
    a = hex_to_rgb(color_a)
    b = hex_to_rgb(color_b)
    return rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * amount for i in range(3)))


def ease_out(t):
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    return 4 * t * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2


def pulse(elapsed, period):
    """Smooth 0..1..0 wave for breathing indicators."""
    return (1 - math.cos(2 * math.pi * (elapsed % period) / period)) / 2


def path_point(points, distance):
    remaining = distance
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        length = math.hypot(bx - ax, by - ay)
        if remaining <= length and length:
            t = remaining / length
            return (ax + (bx - ax) * t, ay + (by - ay) * t)
        remaining -= length
    return points[-1]


def path_length(points):
    return sum(math.hypot(bx - ax, by - ay) for (ax, ay), (bx, by) in zip(points, points[1:]))


def path_slice(points, start, end):
    """Points of an orthogonal polyline between two distances along it."""
    start = max(0.0, start)
    end = min(path_length(points), end)
    if end <= start:
        return []
    sliced = [path_point(points, start)]
    walked = 0.0
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        walked += math.hypot(bx - ax, by - ay)
        if start < walked < end:
            sliced.append((bx, by))
    sliced.append(path_point(points, end))
    return sliced


def reduced_motion(preference="full"):
    """Resolve the motion preference: "full", "reduced", or "system".

    "system" follows the Windows 'Animation effects' setting. The default is
    full motion because that OS switch is often turned off for performance
    rather than comfort; the app exposes its own Reduce motion toggle.
    """
    if os.environ.get("CODEROUTER_REDUCED_MOTION", "").strip().lower() in {"1", "true", "yes"}:
        return True
    preference = str(preference or "full").strip().lower()
    if preference == "reduced":
        return True
    if preference != "system" or os.name != "nt":
        return False
    try:
        enabled = ctypes.c_int(1)
        # SPI_GETCLIENTAREAANIMATION
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return not bool(enabled.value)
    except (AttributeError, OSError):
        pass
    return False


# --- Icons -----------------------------------------------------------------
# Each icon is a list of primitives on a 24-unit grid:
#   ("line", [(x, y), ...])          open polyline
#   ("ring", cx, cy, r)              stroked circle
#   ("arc", cx, cy, r, a0, a1)       stroked arc, degrees, screen coordinates
#   ("dot", cx, cy, r)               filled circle
#   ("box", x0, y0, x1, y1)          filled rectangle
# A primitive may carry a trailing {"color": key} dict to use a second tone.

def _rect(x0, y0, x1, y1):
    return ("line", [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])


ICONS = {
    "folder": [("line", [(3.5, 6.5), (9.5, 6.5), (11.5, 8.5), (20.5, 8.5), (20.5, 18.5), (3.5, 18.5), (3.5, 6.5)])],
    "plus": [("line", [(12, 5), (12, 19)]), ("line", [(5, 12), (19, 12)])],
    "history": [("ring", 12, 12, 8.5), ("line", [(12, 7.5), (12, 12), (15.2, 14)])],
    "verify": [("ring", 12, 12, 8.5), ("line", [(8.3, 12.3), (11, 15), (15.8, 9.6)])],
    "activity": [("line", [(3, 12.5), (7, 12.5), (9.5, 6), (14, 18), (16.5, 12.5), (21, 12.5)])],
    "review": [_rect(3.5, 5, 20.5, 19), ("line", [(13.5, 5), (13.5, 19)])],
    "settings": [
        ("line", [(4, 7), (20, 7)]), ("line", [(4, 12), (20, 12)]), ("line", [(4, 17), (20, 17)]),
        ("dot", 9, 7, 2.3), ("dot", 15.5, 12, 2.3), ("dot", 7.5, 17, 2.3),
    ],
    "search": [("ring", 10.5, 10.5, 6), ("line", [(15, 15), (20, 20)])],
    "send": [("line", [(12, 19), (12, 5.5)]), ("line", [(6.5, 11), (12, 5.5), (17.5, 11)])],
    "stop": [("box", 7, 7, 17, 17)],
    "file_plus": [
        ("line", [(6, 3.5), (14, 3.5), (18, 7.5), (18, 20.5), (6, 20.5), (6, 3.5)]),
        ("line", [(12, 10.5), (12, 16.5)]), ("line", [(9, 13.5), (15, 13.5)]),
    ],
    "refresh": [("arc", 12, 12, 7.5, -40, 250), ("line", [(17.9, 3.4), (17.75, 7.18), (13.9, 7.4)])],
    "chevron_down": [("line", [(8, 10), (12, 14), (16, 10)])],
    "chevron_right": [("line", [(10, 7.5), (14.5, 12), (10, 16.5)])],
    "chevron_left": [("line", [(14, 7.5), (9.5, 12), (14, 16.5)])],
    "chip": [
        _rect(7, 7, 17, 17),
        ("line", [(10, 3.5), (10, 7)]), ("line", [(14, 3.5), (14, 7)]),
        ("line", [(10, 17), (10, 20.5)]), ("line", [(14, 17), (14, 20.5)]),
        ("line", [(3.5, 10), (7, 10)]), ("line", [(3.5, 14), (7, 14)]),
        ("line", [(17, 10), (20.5, 10)]), ("line", [(17, 14), (20.5, 14)]),
    ],
    "check": [("line", [(5, 12.5), (10, 17.5), (19, 7)])],
    "check_list": [
        ("line", [(11, 7), (20, 7)]), ("line", [(11, 12), (20, 12)]), ("line", [(11, 17), (20, 17)]),
        ("line", [(3.5, 7), (5.2, 8.7), (8, 5.5)]), ("line", [(3.5, 12), (5.2, 13.7), (8, 10.5)]),
    ],
    "close": [("line", [(6.5, 6.5), (17.5, 17.5)]), ("line", [(17.5, 6.5), (6.5, 17.5)])],
    "undo": [
        ("line", [(8.5, 4.5), (4, 9), (8.5, 13.5)]),
        ("line", [(4, 9), (14, 9)]),
        ("arc", 14, 14, 5, -90, 90),
        ("line", [(14, 19), (8, 19)]),
    ],
    "export": [
        ("line", [(12, 14.5), (12, 3.5)]), ("line", [(7.5, 8), (12, 3.5), (16.5, 8)]),
        ("line", [(4.5, 12), (4.5, 20.5), (19.5, 20.5), (19.5, 12)]),
    ],
    "bug": [
        ("ring", 12, 13.5, 5),
        ("line", [(12, 8.5), (12, 18.5)]),
        ("line", [(4.5, 10.5), (7.3, 11.5)]), ("line", [(4.5, 16.5), (7.2, 15.6)]),
        ("line", [(19.5, 10.5), (16.7, 11.5)]), ("line", [(19.5, 16.5), (16.8, 15.6)]),
        ("line", [(10, 8.8), (8.8, 5.5)]), ("line", [(14, 8.8), (15.2, 5.5)]),
    ],
    "flask": [
        ("line", [(9.5, 3.5), (9.5, 9.5), (4.5, 19.5), (19.5, 19.5), (14.5, 9.5), (14.5, 3.5)]),
        ("line", [(8, 3.5), (16, 3.5)]), ("line", [(7, 14.5), (17, 14.5)]),
    ],
    "branch": [
        ("ring", 6.5, 5.5, 2.2), ("ring", 6.5, 18.5, 2.2), ("ring", 17.5, 7.5, 2.2),
        ("line", [(6.5, 7.7), (6.5, 16.3)]),
        ("line", [(17.5, 9.7), (17.2, 11.8), (15.8, 13.4), (8.5, 16.6)]),
    ],
    "doc": [
        ("line", [(6, 3.5), (14, 3.5), (18, 7.5), (18, 20.5), (6, 20.5), (6, 3.5)]),
        ("line", [(9, 10.5), (15, 10.5)]), ("line", [(9, 14), (15, 14)]), ("line", [(9, 17.5), (12.5, 17.5)]),
    ],
    "panel_close": [_rect(3.5, 5, 20.5, 19), ("line", [(14.5, 5), (14.5, 19)]), ("line", [(7.5, 9.5), (10, 12), (7.5, 14.5)])],
    "panel_open": [_rect(3.5, 5, 20.5, 19), ("line", [(14.5, 5), (14.5, 19)]), ("line", [(10, 9.5), (7.5, 12), (10, 14.5)])],
    "terminal": [_rect(3.5, 5, 20.5, 19), ("line", [(7, 9.5), (9.5, 12), (7, 14.5)]), ("line", [(11.5, 14.5), (16, 14.5)])],
}


def _segment_distance(px, py, ax, ay, bx, by):
    dx = bx - ax
    dy = by - ay
    length = dx * dx + dy * dy
    if not length:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _arc_distance(px, py, cx, cy, r, a0, a1):
    angle = math.degrees(math.atan2(py - cy, px - cx))
    span = (a1 - a0) % 360 or 360
    if (angle - a0) % 360 <= span:
        return abs(math.hypot(px - cx, py - cy) - r)
    best = float("inf")
    for a in (a0, a1):
        ex = cx + r * math.cos(math.radians(a))
        ey = cy + r * math.sin(math.radians(a))
        best = min(best, math.hypot(px - ex, py - ey))
    return best


def _coverage(primitive, px, py, half_stroke):
    kind = primitive[0]
    if kind == "line":
        points = primitive[1]
        if len(points) == 1:
            distance = math.hypot(px - points[0][0], py - points[0][1])
        else:
            distance = min(
                _segment_distance(px, py, *points[i], *points[i + 1])
                for i in range(len(points) - 1)
            )
        return half_stroke + 0.5 - distance
    if kind == "ring":
        _, cx, cy, r = primitive[:4]
        return half_stroke + 0.5 - abs(math.hypot(px - cx, py - cy) - r)
    if kind == "arc":
        _, cx, cy, r, a0, a1 = primitive[:6]
        return half_stroke + 0.5 - _arc_distance(px, py, cx, cy, r, a0, a1)
    if kind == "dot":
        _, cx, cy, r = primitive[:4]
        return r + 0.5 - math.hypot(px - cx, py - cy)
    if kind == "box":
        _, x0, y0, x1, y1 = primitive[:5]
        inside_x = min(px - x0, x1 - px)
        inside_y = min(py - y0, y1 - py)
        return min(inside_x, inside_y) + 0.5
    return 0.0


def render_primitives(master, primitives, size, color, background, stroke=1.7, tones=None, grid=24.0):
    """Rasterise primitives into an opaque PhotoImage blended over background."""
    scale = size / grid
    half_stroke = (stroke * scale) / 2.0
    bg = hex_to_rgb(background)
    tones = tones or {}
    compiled = []
    for primitive in primitives:
        tone = color
        if isinstance(primitive[-1], dict):
            tone = tones.get(primitive[-1].get("color"), color)
            primitive = primitive[:-1]
        kind = primitive[0]
        if kind == "line":
            scaled = ("line", [(x * scale, y * scale) for x, y in primitive[1]])
        elif kind in {"ring", "dot"}:
            scaled = (kind, primitive[1] * scale, primitive[2] * scale, primitive[3] * scale)
        elif kind == "arc":
            scaled = ("arc", primitive[1] * scale, primitive[2] * scale, primitive[3] * scale, primitive[4], primitive[5])
        else:
            scaled = ("box",) + tuple(value * scale for value in primitive[1:5])
        compiled.append((scaled, hex_to_rgb(tone)))
    image = tk.PhotoImage(master=master, width=size, height=size)
    rows = []
    for y in range(size):
        row = []
        py = y + 0.5
        for x in range(size):
            px = x + 0.5
            pixel = bg
            for shape, rgb in compiled:
                alpha = _coverage(shape, px, py, half_stroke)
                if alpha <= 0:
                    continue
                alpha = min(1.0, alpha)
                pixel = tuple(pixel[i] + (rgb[i] - pixel[i]) * alpha for i in range(3))
            row.append(rgb_to_hex(pixel))
        rows.append("{" + " ".join(row) + "}")
    image.put(" ".join(rows), to=(0, 0))
    return image


class IconFactory:
    """Caches anti-aliased icon images by (name, size, colour, background)."""

    def __init__(self, master, scale=1.0):
        self.master = master
        self.scale = scale
        self._cache = {}

    def px(self, value):
        return max(1, int(round(value * self.scale)))

    def get(self, name, size, color, background, stroke=1.7):
        pixels = self.px(size)
        key = (name, pixels, color, background, stroke)
        image = self._cache.get(key)
        if image is None:
            image = render_primitives(self.master, ICONS[name], pixels, color, background, stroke=stroke)
            self._cache[key] = image
        return image

    def custom(self, key, primitives, size, color, background, stroke=1.7, tones=None, grid=24.0):
        pixels = self.px(size)
        cache_key = ("custom", key, pixels, color, background, stroke)
        image = self._cache.get(cache_key)
        if image is None:
            image = render_primitives(
                self.master, primitives, pixels, color, background,
                stroke=stroke, tones=tones, grid=grid,
            )
            self._cache[cache_key] = image
        return image


# --- Animation ---------------------------------------------------------------

class Animator:
    """One after() loop drives every tween and continuous effect.

    Tweens call `apply(value)` with an eased 0..1 progress. Loops call
    `step(elapsed_seconds)` each frame until they return False. The loop
    sleeps when nothing is active, so an idle window costs nothing.
    """

    FRAME_MS = 16

    def __init__(self, root, reduce=None):
        self.root = root
        self.reduce = reduced_motion() if reduce is None else bool(reduce)
        self._tweens = {}
        self._loops = {}
        self._after_id = None
        self.closed = False

    def tween(self, key, duration, apply, easing=ease_out, done=None):
        if self.closed:
            return
        if self.reduce or duration <= 0:
            self._tweens.pop(key, None)
            self._safe(apply, 1.0)
            if done:
                self._safe(done)
            return
        self._tweens[key] = (time.perf_counter(), duration, apply, easing, done)
        self._wake()

    def loop(self, key, step):
        if self.closed or key in self._loops:
            return
        self._loops[key] = (time.perf_counter(), step)
        self._wake()

    def stop(self, key):
        self._tweens.pop(key, None)
        self._loops.pop(key, None)

    def running(self, key):
        return key in self._loops or key in self._tweens

    def close(self):
        self.closed = True
        self._tweens.clear()
        self._loops.clear()
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except (tk.TclError, RuntimeError):
                pass
            self._after_id = None

    @staticmethod
    def _safe(callback, *args):
        try:
            return callback(*args)
        except (tk.TclError, RuntimeError):
            return False

    def _wake(self):
        if self._after_id is None and not self.closed:
            try:
                self._after_id = self.root.after(self.FRAME_MS, self._frame)
            except (tk.TclError, RuntimeError):
                self._after_id = None

    def _frame(self):
        self._after_id = None
        if self.closed:
            return
        now = time.perf_counter()
        for key, (start, duration, apply, easing, done) in list(self._tweens.items()):
            progress = min(1.0, (now - start) / duration)
            self._safe(apply, easing(progress))
            if progress >= 1.0 and self._tweens.get(key, (None,))[0] == start:
                self._tweens.pop(key, None)
                if done:
                    self._safe(done)
        for key, (start, step) in list(self._loops.items()):
            if self._safe(step, now - start) is False and self._loops.get(key, (None,))[0] == start:
                self._loops.pop(key, None)
        if self._tweens or self._loops:
            self._wake()
