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
        self.fill_region(0, 0, 160, 80, color)

    def fill_region(self, x: int, y: int, width: int, height: int, color: int) -> None:
        self._set_xy(x, y)
        self._set_size(width, height)
        self._send_wait(bytes((2, 3, 11)) + color.to_bytes(2, "big") + b"\0")

    def draw_ascii(self, x: int, y: int, character: str, foreground: int, background: int) -> None:
        self._set_xy(x, y)
        self._set_color(foreground, background)
        self._send_wait(bytes((2, 3, 2, ord(character))) + ASCII_FONT_PAGE.to_bytes(2, "big"))

    def draw_percent(self, percent_text: str) -> None:
        black = rgb565(0, 0, 0)
        green = rgb565(39, 220, 143)
        percent_text = percent_text[:5]
        percent_x = max(0, (160 - len(percent_text) * 32) // 2)
        for index, character in enumerate(percent_text):
            self.draw_ascii(percent_x + index * 32, 0, character, green, black)

    def draw_small_text(self, text: str) -> None:
        black = rgb565(0, 0, 0)
        white = rgb565(236, 244, 255)
        scale = 2
        text = text.upper()[:13]
        width = max(0, len(text) * 6 * scale - scale)
        start_x = max(0, (160 - width) // 2)
        start_y = 65
        self.fill_region(0, 64, 160, 16, black)
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
                        white,
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
                if needs_clear:
                    dashboard.clear(rgb565(0, 0, 0))
                    needs_clear = False
                    date_dirty = True
                dashboard.draw_percent(f"{snapshot.remaining_percent}%")
                if date_dirty:
                    dashboard.draw_small_text(reset_date_label(snapshot))
                    date_dirty = False
            except Exception as exc:
                print(f"Native display refresh failed: {exc}", flush=True)
                display.close()
                needs_clear = True
                date_dirty = True
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
