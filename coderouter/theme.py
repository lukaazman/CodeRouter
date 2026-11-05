"""Design tokens: palettes, diff tones and theme resolution.

Cool graphite (dark) and warm paper (light) grounds, never pure black or
white, one accent used for the
primary action, focus and state, hairlines at low contrast. Body text is at
least 7:1 against its ground, muted text at least 4.5:1.
"""

import os
import subprocess

THEMES = ("dark", "light", "system")

DARK = {
    "canvas": "#14161a",
    "surface": "#14161a",
    "surface_alt": "#1b1e23",
    "surface_raised": "#24282e",
    "terminal": "#171a1e",
    "border": "#272b31",
    "border_strong": "#383d45",
    "text": "#e8ebf0",
    "text_muted": "#a3a9b3",
    "text_subtle": "#818792",
    "accent": "#93b6ff",
    "accent_active": "#b5ccff",
    "accent_ink": "#0d1527",
    "success": "#7dcf9b",
    "warning": "#e6bc73",
    "danger": "#ef8b93",
    "focus": "#93b6ff",
}

LIGHT = {
    "canvas": "#faf9f7",
    "surface": "#faf9f7",
    "surface_alt": "#f2f1ee",
    "surface_raised": "#e9e7e3",
    "terminal": "#f4f3f0",
    "border": "#e2e0db",
    "border_strong": "#cdcac3",
    "text": "#1c1b19",
    "text_muted": "#53514b",
    "text_subtle": "#6c6962",
    "accent": "#2d5bcc",
    "accent_active": "#2249ad",
    "accent_ink": "#ffffff",
    "success": "#2c8452",
    "warning": "#9a6410",
    "danger": "#bf3446",
    "focus": "#2d5bcc",
}

DIFF_TONES = {
    "dark": {"add_bg": "#16301f", "add_fg": "#a6e3b8", "del_bg": "#3a1e24", "del_fg": "#f4b0b7", "hunk_fg": "#93b6ff"},
    "light": {"add_bg": "#e2f3e7", "add_fg": "#1f6b3f", "del_bg": "#fbe3e5", "del_fg": "#9d2535", "hunk_fg": "#2d5bcc"},
}

PALETTES = {"dark": DARK, "light": LIGHT}


def normalize_theme(value):
    value = str(value or "dark").strip().lower()
    return value if value in THEMES else "dark"


def system_prefers_light():
    """Best-effort OS light/dark detection; dark when unknown."""
    try:
        if os.name == "nt":
            import winreg  # noqa: PLC0415 - Windows only

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _type = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return bool(value)
        if os.uname().sysname == "Darwin":
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=2,
            )
            return "dark" not in result.stdout.lower()
        gtk = os.environ.get("GTK_THEME", "")
        if gtk:
            return "dark" not in gtk.lower()
    except Exception:
        return False
    return False


def resolve_theme(value):
    value = normalize_theme(value)
    if value == "system":
        return "light" if system_prefers_light() else "dark"
    return value


def palette_for(value):
    return dict(PALETTES[resolve_theme(value)])


def diff_tones_for(value):
    return dict(DIFF_TONES[resolve_theme(value)])


def _luminance(hex_color):
    channels = []
    for index in (1, 3, 5):
        c = int(hex_color[index:index + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _mix(a, b, amount):
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(ca, cb))


def with_accent(palette, accent):
    """Swap in a custom accent; derive hover and ink colours with safe contrast."""
    accent = str(accent or "").strip().lower()
    if len(accent) != 7 or not accent.startswith("#"):
        return palette
    try:
        int(accent[1:], 16)
    except ValueError:
        return palette
    result = dict(palette)
    dark_ground = _luminance(palette["canvas"]) < 0.2
    result["accent"] = accent
    result["focus"] = accent
    result["accent_active"] = _mix(accent, "#ffffff" if dark_ground else "#000000", 0.2)
    ink_dark, ink_light = "#0d1527", "#ffffff"
    result["accent_ink"] = ink_dark if contrast(ink_dark, accent) >= contrast(ink_light, accent) else ink_light
    return result
