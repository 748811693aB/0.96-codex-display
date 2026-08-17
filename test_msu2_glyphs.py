#!/usr/bin/env python3
"""Exercise the MSU2 firmware's native fill and 32x64 ASCII glyph commands."""

from __future__ import annotations

import argparse
import signal
import time

from codex_msu2_display import MSU2Mini, rgb565


FONT_PAGE = 3651


def send_no_wait(display: MSU2Mini, command: bytes) -> None:
    assert display.serial is not None
    display.serial.write_all(command)


def send_wait(display: MSU2Mini, command: bytes) -> None:
    assert display.serial is not None
    display.serial.read_until_quiet(timeout=0.01, quiet=0.002)
    display.serial.write_all(command)
    response = display.serial.read_until_quiet(timeout=0.25, quiet=0.002)
    if response and command[:2] not in response:
        raise RuntimeError(f"Unexpected command response: {response.hex()}")


def set_xy(display: MSU2Mini, x: int, y: int) -> None:
    send_no_wait(display, bytes((2, 0)) + x.to_bytes(2, "big") + y.to_bytes(2, "big"))


def set_size(display: MSU2Mini, width: int, height: int) -> None:
    send_no_wait(display, bytes((2, 1)) + width.to_bytes(2, "big") + height.to_bytes(2, "big"))


def set_color(display: MSU2Mini, foreground: int, background: int) -> None:
    send_no_wait(display, bytes((2, 2)) + foreground.to_bytes(2, "big") + background.to_bytes(2, "big"))


def fill(display: MSU2Mini, color: int) -> None:
    set_xy(display, 0, 0)
    set_size(display, 160, 80)
    send_wait(display, bytes((2, 3, 11)) + color.to_bytes(2, "big") + b"\0")


def draw_ascii(display: MSU2Mini, x: int, y: int, character: str, foreground: int, background: int) -> None:
    set_xy(display, x, y)
    set_color(display, foreground, background)
    send_wait(
        display,
        bytes((2, 3, 2, ord(character))) + FONT_PAGE.to_bytes(2, "big"),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device-glob", default="/dev/cu.usbmodem01234567891")
    parser.add_argument("--text", default="67%")
    args = parser.parse_args()

    stop = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    display = MSU2Mini(args.device_glob, lcd_state=0)
    black = rgb565(0, 0, 0)
    green = rgb565(39, 220, 143)
    try:
        display.connect()
        text = args.text[:4]
        start_x = max(0, (160 - len(text) * 32) // 2)
        while not stop:
            fill(display, black)
            for index, character in enumerate(text):
                draw_ascii(display, start_x + index * 32, 8, character, green, black)
            time.sleep(0.02)
    finally:
        display.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
