#!/usr/bin/env python3
"""Show Codex remaining usage with the MSU2 firmware's native font commands."""

from __future__ import annotations

import argparse
import datetime as dt
import signal
import time

from codex_msu2_display import (
    FONT_5X7,
    CodexUsageClient,
    MSU2Mini,
    UsageSnapshot,
    format_snapshot,
    rgb565,
)


ASCII_FONT_PAGE = 3651
SCREEN_WIDTH = 160
SCREEN_HEIGHT = 80
DISPLAY_BRIGHTNESS = 0.82
LOGO_X = 2
LOGO_Y = 2
LOGO_SCALE = 3
LOGO_SOURCE_INSET = 2
LOGO_RESERVED_WIDTH = 64


def display_color(red: int, green: int, blue: int) -> int:
    """Convert an RGB color to the slightly dimmed display palette."""
    return rgb565(
        round(red * DISPLAY_BRIGHTNESS),
        round(green * DISPLAY_BRIGHTNESS),
        round(blue * DISPLAY_BRIGHTNESS),
    )


BACKGROUND = rgb565(0, 0, 0)
ACCENT = display_color(39, 220, 143)
FOREGROUND = display_color(236, 244, 255)
LOGO_LIGHT = display_color(98, 112, 255)
LOGO_DARK = display_color(40, 60, 212)

# A 24 x 24 source reduction of the official Codex app mark. The non-empty
# 20 x 20 center is drawn at 3x for a visible 60 x 60 logo. L and D are the
# light and dark halves of its blue flower, while W draws the white prompt.
CODEX_LOGO_24 = (
    "                        ",
    "                        ",
    "        LLLLL           ",
    "       LLLLLLLLLLL      ",
    "      LLLLLLLLLLLLL     ",
    "     LLLLLLLLLLLLLLL    ",
    "    LLLLLLLLLLLLLLLL    ",
    "   LLLLLLLLLLLLLLLLLL   ",
    "  LLLLLWLLLLLLLLLLLLL   ",
    "  LLLLLWWLLLLLLLLLLLL   ",
    "  LLLLLWWLLLLLLLLLLLL   ",
    "  LLLLLLWWLLLLLLLLLLLL  ",
    "  LLLLLLWWLLLLLLLLLLLL  ",
    "   LLLLWWLLLLLLLLLLLLL  ",
    "   LLLLWLLLLWWWWWLLLLL  ",
    "   LLLLLLLLLLLLLLLLLLL  ",
    "   LDDDDLLLLLLLLLLLLL   ",
    "   LDDDDDDDLLLLLLLLL    ",
    "    LDDDDDDDDDDLLL      ",
    "     LDDDDDDDDDDLL      ",
    "       LLLLDDDDDL       ",
    "           LLLLL        ",
    "                        ",
    "                        ",
)


def logo_runs() -> list[tuple[int, int, int, str]]:
    """Return horizontal color runs for efficiently drawing the logo."""
    runs: list[tuple[int, int, int, str]] = []
    for y, row in enumerate(CODEX_LOGO_24):
        x = 0
        while x < len(row):
            color_key = row[x]
            if color_key == " ":
                x += 1
                continue
            start = x
            while x < len(row) and row[x] == color_key:
                x += 1
            runs.append((start, y, x - start, color_key))
    return runs


def percent_start_x(percent_text: str) -> int:
    """Center the native percentage in the area to the right of the logo."""
    display_text = native_percent_text(percent_text)
    available_width = SCREEN_WIDTH - LOGO_RESERVED_WIDTH
    return LOGO_RESERVED_WIDTH + max(0, (available_width - len(display_text) * 32) // 2)


def native_percent_text(percent_text: str) -> str:
    """Keep the percentage within the three native glyph cells beside the logo."""
    return "100" if percent_text == "100%" else percent_text[:3]


def percent_layout_changed(previous: str, current: str) -> bool:
    """Return whether old glyph cells must be cleared before redrawing."""
    return percent_start_x(previous) != percent_start_x(current)


def reset_date_label(snapshot: UsageSnapshot) -> str:
    if not snapshot.resets_at:
        return "RESET -- --"
    reset = dt.datetime.fromtimestamp(snapshot.resets_at).astimezone()
    return "RESET " + reset.strftime("%m-%d")


class NativeDashboard:
    def __init__(self, display: MSU2Mini) -> None:
        self.display = display

    def _send_no_wait(self, command: bytes) -> None:
        assert self.display.serial is not None
        self.display.serial.write_all(command)

    def _send_wait(self, command: bytes) -> None:
        assert self.display.serial is not None
        self.display.serial.read_until_quiet(timeout=0.01, quiet=0.002)
        self.display.serial.write_all(command)
        response = self.display.serial.read_until_quiet(timeout=0.25, quiet=0.002)
        if response and command[:2] not in response:
            raise RuntimeError(f"Unexpected MSU2 response: {response.hex()}")

    def _set_xy(self, x: int, y: int) -> None:
        self._send_no_wait(bytes((2, 0)) + x.to_bytes(2, "big") + y.to_bytes(2, "big"))

    def _set_size(self, width: int, height: int) -> None:
        self._send_no_wait(bytes((2, 1)) + width.to_bytes(2, "big") + height.to_bytes(2, "big"))

    def _set_color(self, foreground: int, background: int) -> None:
        self._send_no_wait(bytes((2, 2)) + foreground.to_bytes(2, "big") + background.to_bytes(2, "big"))

    def clear(self, color: int) -> None:
        self.fill_region(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, color)

    def fill_region(self, x: int, y: int, width: int, height: int, color: int) -> None:
        self._set_xy(x, y)
        self._set_size(width, height)
        self._send_wait(bytes((2, 3, 11)) + color.to_bytes(2, "big") + b"\0")

    def draw_ascii(self, x: int, y: int, character: str, foreground: int, background: int) -> None:
        self._set_xy(x, y)
        self._set_color(foreground, background)
        self._send_wait(bytes((2, 3, 2, ord(character))) + ASCII_FONT_PAGE.to_bytes(2, "big"))

    def draw_percent(self, percent_text: str) -> None:
        percent_text = native_percent_text(percent_text)
        percent_x = percent_start_x(percent_text)
        for index, character in enumerate(percent_text):
            self.draw_ascii(percent_x + index * 32, 0, character, ACCENT, BACKGROUND)

    def clear_percent_area(self) -> None:
        self.fill_region(LOGO_RESERVED_WIDTH, 0, SCREEN_WIDTH - LOGO_RESERVED_WIDTH, 64, BACKGROUND)

    def draw_codex_logo(self) -> None:
        colors = {"L": LOGO_LIGHT, "D": LOGO_DARK, "W": FOREGROUND}
        for x, y, width, color_key in logo_runs():
            self.fill_region(
                LOGO_X + (x - LOGO_SOURCE_INSET) * LOGO_SCALE,
                LOGO_Y + (y - LOGO_SOURCE_INSET) * LOGO_SCALE,
                width * LOGO_SCALE,
                LOGO_SCALE,
                colors[color_key],
            )

    def draw_small_text(self, text: str) -> None:
        scale = 2
        text = text.upper()[:13]
        width = max(0, len(text) * 6 * scale - scale)
        start_x = max(0, (SCREEN_WIDTH - width) // 2)
        start_y = 65
        self.fill_region(0, 64, SCREEN_WIDTH, 16, BACKGROUND)
        for character_index, character in enumerate(text):
            glyph = FONT_5X7.get(character, FONT_5X7[" "])
            glyph_x = start_x + character_index * 6 * scale
            for row_index, row in enumerate(glyph):
                column = 0
                while column < 5:
                    if row[column] == "0":
                        column += 1
                        continue
                    run_start = column
                    while column < 5 and row[column] == "1":
                        column += 1
                    self.fill_region(
                        glyph_x + run_start * scale,
                        start_y + row_index * scale,
                        (column - run_start) * scale,
                        scale,
                        FOREGROUND,
                    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-glob", default="/dev/cu.usbmodem*")
    parser.add_argument("--interval", type=float, default=60.0, help="Codex usage query interval")
    parser.add_argument("--draw-interval", type=float, default=0.2, help="Native glyph redraw interval")
    parser.add_argument("--codex", dest="codex_path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stop = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    usage_client = CodexUsageClient(args.codex_path)
    display = MSU2Mini(args.device_glob, lcd_state=0)
    dashboard = NativeDashboard(display)
    snapshot: UsageSnapshot | None = None
    next_usage_refresh = 0.0
    needs_clear = True
    date_dirty = True
    last_percent_text: str | None = None
    try:
        while not stop:
            started = time.monotonic()
            try:
                if snapshot is None or started >= next_usage_refresh:
                    snapshot = usage_client.read_usage()
                    next_usage_refresh = started + max(1.0, args.interval)
                    date_dirty = True
                    print(format_snapshot(snapshot), flush=True)

                if display.serial is None:
                    display.connect()
                    needs_clear = True
                percent_text = f"{snapshot.remaining_percent}%"
                if needs_clear:
                    dashboard.clear(BACKGROUND)
                    dashboard.draw_codex_logo()
                    needs_clear = False
                    date_dirty = True
                elif last_percent_text is not None and percent_layout_changed(last_percent_text, percent_text):
                    # Only clear when the glyph count changes and the centered
                    # text moves. Clearing every 0.2 s makes the LCD flicker.
                    dashboard.clear_percent_area()
                last_percent_text = percent_text
                dashboard.draw_percent(percent_text)
                if date_dirty:
                    dashboard.draw_small_text(reset_date_label(snapshot))
                    date_dirty = False
            except Exception as exc:
                print(f"Native display refresh failed: {exc}", flush=True)
                display.close()
                needs_clear = True
                date_dirty = True
                last_percent_text = None
                time.sleep(0.5)

            elapsed = time.monotonic() - started
            delay = max(0.0, args.draw_interval - elapsed)
            if delay:
                time.sleep(delay)
    finally:
        display.close()
        usage_client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
