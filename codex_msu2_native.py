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


SCREEN_WIDTH = 160
SCREEN_HEIGHT = 80
DISPLAY_BRIGHTNESS = 0.82
LOGO_SOURCE_INSET = 2
LOGO_SOURCE_SIZE = 20
LOGO_SIZE = 51
LOGO_RESERVED_WIDTH = 64
CONTENT_HEIGHT = 59
LOGO_X = (LOGO_RESERVED_WIDTH - LOGO_SIZE) // 2
LOGO_Y = (CONTENT_HEIGHT - LOGO_SIZE) // 2


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
# 20 x 20 center is drawn at 51 x 51 (85% of the former 60 x 60 logo).
# L and D are the
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


def scaled_logo_runs() -> list[tuple[int, int, int, int, str]]:
    """Scale logo runs to the exact requested size without pixel gaps."""
    scaled: list[tuple[int, int, int, int, str]] = []
    for x, y, width, color_key in logo_runs():
        source_x = x - LOGO_SOURCE_INSET
        source_y = y - LOGO_SOURCE_INSET
        left = source_x * LOGO_SIZE // LOGO_SOURCE_SIZE
        right = (source_x + width) * LOGO_SIZE // LOGO_SOURCE_SIZE
        top = source_y * LOGO_SIZE // LOGO_SOURCE_SIZE
        bottom = (source_y + 1) * LOGO_SIZE // LOGO_SOURCE_SIZE
        scaled.append((LOGO_X + left, LOGO_Y + top, right - left, bottom - top, color_key))
    return scaled


def reset_time_label(snapshot: UsageSnapshot) -> str:
    def clock(timestamp: int | None) -> str:
        if timestamp is None:
            return "--:--"
        return dt.datetime.fromtimestamp(timestamp).astimezone().strftime("%H:%M")

    def month_day(timestamp: int | None) -> str:
        if timestamp is None:
            return "-- --"
        return dt.datetime.fromtimestamp(timestamp).astimezone().strftime("%m-%d")

    return f"{clock(snapshot.resets_at)}/{month_day(snapshot.secondary_resets_at)}"


def remaining_text(percent: int | None) -> str:
    return "--" if percent is None else str(percent)


def vector_text_width(text: str, scale: int) -> int:
    return max(0, len(text) * 6 * scale - scale)


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

    def clear(self, color: int) -> None:
        self.fill_region(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, color)

    def fill_region(self, x: int, y: int, width: int, height: int, color: int) -> None:
        self._set_xy(x, y)
        self._set_size(width, height)
        self._send_wait(bytes((2, 3, 11)) + color.to_bytes(2, "big") + b"\0")

    def clear_usage_area(self) -> None:
        self.fill_region(LOGO_RESERVED_WIDTH, 0, SCREEN_WIDTH - LOGO_RESERVED_WIDTH, CONTENT_HEIGHT, BACKGROUND)

    def draw_codex_logo(self) -> None:
        colors = {"L": LOGO_LIGHT, "D": LOGO_DARK, "W": FOREGROUND}
        for x, y, width, height, color_key in scaled_logo_runs():
            self.fill_region(x, y, width, height, colors[color_key])

    def draw_vector_text(self, x: int, y: int, text: str, color: int, scale: int = 1) -> None:
        for character_index, character in enumerate(text):
            glyph = FONT_5X7.get(character, FONT_5X7[" "])
            glyph_x = x + character_index * 6 * scale
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
                        y + row_index * scale,
                        (column - run_start) * scale,
                        scale,
                        color,
                    )

    def draw_usage_rows(self, snapshot: UsageSnapshot) -> None:
        rows = (
            (1, "5H", remaining_text(snapshot.remaining_percent)),
            (31, "7D", remaining_text(snapshot.secondary_remaining_percent)),
        )
        for y, label, value in rows:
            label_width = vector_text_width(label, 2)
            value_width = vector_text_width(value, 3)
            percent_width = vector_text_width("%", 2)
            full_width = label_width + 4 + value_width + 2 + percent_width
            start_x = LOGO_RESERVED_WIDTH + max(0, (SCREEN_WIDTH - LOGO_RESERVED_WIDTH - full_width) // 2)
            value_x = start_x + label_width + 4
            percent_x = value_x + value_width + 2
            self.draw_vector_text(start_x, y + 3, label, FOREGROUND, scale=2)
            self.draw_vector_text(value_x, y, value, ACCENT, scale=3)
            self.draw_vector_text(percent_x, y + 3, "%", ACCENT, scale=2)

    def draw_reset_times(self, snapshot: UsageSnapshot) -> None:
        text = reset_time_label(snapshot)
        width = vector_text_width(text, 2)
        start_x = max(0, (SCREEN_WIDTH - width) // 2)
        self.fill_region(0, CONTENT_HEIGHT, SCREEN_WIDTH, SCREEN_HEIGHT - CONTENT_HEIGHT, BACKGROUND)
        self.draw_vector_text(start_x, 63, text, FOREGROUND, scale=2)

    def keep_display_active(self) -> None:
        self.fill_region(SCREEN_WIDTH - 1, SCREEN_HEIGHT - 1, 1, 1, BACKGROUND)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-glob", default="/dev/cu.usbmodem*")
    parser.add_argument("--interval", type=float, default=60.0, help="Codex usage query interval")
    parser.add_argument("--draw-interval", type=float, default=0.2, help="Display keep-alive interval")
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
    usage_dirty = True
    try:
        while not stop:
            started = time.monotonic()
            try:
                if snapshot is None or started >= next_usage_refresh:
                    snapshot = usage_client.read_usage()
                    next_usage_refresh = started + max(1.0, args.interval)
                    usage_dirty = True
                    print(format_snapshot(snapshot), flush=True)

                if display.serial is None:
                    display.connect()
                    needs_clear = True
                if needs_clear:
                    dashboard.clear(BACKGROUND)
                    dashboard.draw_codex_logo()
                    needs_clear = False
                    usage_dirty = True
                if usage_dirty:
                    dashboard.clear_usage_area()
                    dashboard.draw_usage_rows(snapshot)
                    dashboard.draw_reset_times(snapshot)
                    usage_dirty = False
                dashboard.keep_display_active()
            except Exception as exc:
                print(f"Native display refresh failed: {exc}", flush=True)
                display.close()
                needs_clear = True
                usage_dirty = True
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
