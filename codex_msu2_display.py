#!/usr/bin/env python3
"""Show Codex account rate-limit status on an MSU2_MINI USB screen.

The MSU2 protocol in this file was reconstructed from the user-supplied
MSU2_MINI_DemoV1.6 Windows application. It writes directly to LCD RAM and
does not erase or program the P25D80 flash.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import os
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


WIDTH = 160
HEIGHT = 80
BAUD = termios.B19200
DEFAULT_DEVICE_GLOB = "/dev/cu.usbmodem*"


FONT_5X7: dict[str, tuple[str, ...]] = {
    " ": ("00000",) * 7,
    "%": ("11001", "11010", "00100", "01000", "10110", "00110", "00000"),
    "/": ("00001", "00010", "00100", "00100", "01000", "10000", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ":": ("00000", "00100", "00100", "00000", "00100", "00100", "00000"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
}


def rgb565(red: int, green: int, blue: int) -> int:
    return ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)


def rgb565_to_rgb888(value: int) -> tuple[int, int, int]:
    red = (value >> 11) & 0x1F
    green = (value >> 5) & 0x3F
    blue = value & 0x1F
    return (
        (red << 3) | (red >> 2),
        (green << 2) | (green >> 4),
        (blue << 3) | (blue >> 2),
    )


@dataclass(frozen=True)
class UsageSnapshot:
    used_percent: int
    remaining_percent: int
    resets_at: int | None
    window_minutes: int | None
    plan_type: str | None
    secondary_used_percent: int | None = None
    secondary_remaining_percent: int | None = None
    secondary_resets_at: int | None = None
    secondary_window_minutes: int | None = None


def parse_usage_snapshot(result: dict) -> UsageSnapshot:
    """Extract the 5-hour primary and weekly secondary Codex limits."""
    rate_limits = result.get("rateLimitsByLimitId") or {}
    bucket = rate_limits.get("codex") or result.get("rateLimits") or {}
    primary = bucket.get("primary") or {}
    secondary = bucket.get("secondary") or {}

    def used_percent(window: dict) -> int | None:
        value = window.get("usedPercent")
        if value is None:
            return None
        return min(100, max(0, int(value)))

    primary_used = used_percent(primary)
    secondary_used = used_percent(secondary)
    return UsageSnapshot(
        used_percent=primary_used or 0,
        remaining_percent=100 - primary_used if primary_used is not None else 100,
        resets_at=primary.get("resetsAt"),
        window_minutes=primary.get("windowDurationMins"),
        plan_type=bucket.get("planType"),
        secondary_used_percent=secondary_used,
        secondary_remaining_percent=100 - secondary_used if secondary_used is not None else None,
        secondary_resets_at=secondary.get("resetsAt"),
        secondary_window_minutes=secondary.get("windowDurationMins"),
    )


class CodexUsageClient:
    """Small JSON-lines client for the local Codex app-server."""

    def __init__(self, codex_path: str | None = None, timeout: float = 20.0) -> None:
        discovered = codex_path or shutil.which("codex")
        self.codex_path = discovered or "/opt/homebrew/bin/codex"
        self.timeout = timeout
        self.process: subprocess.Popen[str] | None = None
        self.request_id = 0

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self.close()
        self.process = subprocess.Popen(
            [self.codex_path, "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        result = self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex-msu2-display",
                    "title": "Codex MSU2 Display",
                    "version": "1.0.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        if not isinstance(result, dict) or "codexHome" not in result:
            raise RuntimeError("Codex app-server initialization returned an unexpected response")
        self._send({"method": "initialized"})

    def read_usage(self) -> UsageSnapshot:
        self.start()
        try:
            result = self._request("account/rateLimits/read", None)
        except Exception:
            self.close()
            self.start()
            result = self._request("account/rateLimits/read", None)

        return parse_usage_snapshot(result)

    def _request(self, method: str, params: object) -> dict:
        self.request_id += 1
        request_id = self.request_id
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            message = self._read_message(deadline)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"Codex app-server error: {message['error']}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(f"Unexpected Codex response for {method}")
            return result

    def _send(self, message: dict) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("Codex app-server is not running")
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def _read_message(self, deadline: float) -> dict:
        if self.process is None or self.process.stdout is None:
            raise RuntimeError("Codex app-server is not running")
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for Codex usage data")
            ready, _, _ = select.select([self.process.stdout], [], [], remaining)
            if not ready:
                raise TimeoutError("Timed out waiting for Codex usage data")
            line = self.process.stdout.readline()
            if not line:
                code = self.process.poll()
                raise RuntimeError(f"Codex app-server exited unexpectedly ({code})")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                return message

    def close(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.process = None


class Canvas565:
    def __init__(self, width: int, height: int, background: int) -> None:
        self.width = width
        self.height = height
        self.pixels = [background] * (width * height)

    def fill_rect(self, x: int, y: int, width: int, height: int, color: int) -> None:
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.width, x + width)
        y1 = min(self.height, y + height)
        for row in range(y0, y1):
            start = row * self.width + x0
            self.pixels[start : start + (x1 - x0)] = [color] * (x1 - x0)

    def draw_text(self, x: int, y: int, text: str, color: int, scale: int = 1) -> None:
        cursor = x
        for character in text.upper():
            glyph = FONT_5X7.get(character, FONT_5X7[" "])
            for gy, row in enumerate(glyph):
                for gx, bit in enumerate(row):
                    if bit == "1":
                        self.fill_rect(cursor + gx * scale, y + gy * scale, scale, scale, color)
            cursor += 6 * scale


def text_width(text: str, scale: int) -> int:
    return max(0, len(text) * 6 * scale - scale)


def render_dashboard(snapshot: UsageSnapshot, now: dt.datetime | None = None) -> Canvas565:
    background = rgb565(5, 10, 22)
    panel = rgb565(16, 27, 48)
    white = rgb565(236, 244, 255)
    muted = rgb565(122, 148, 177)
    if snapshot.remaining_percent >= 50:
        accent = rgb565(39, 220, 143)
    elif snapshot.remaining_percent >= 20:
        accent = rgb565(255, 190, 52)
    else:
        accent = rgb565(255, 78, 92)

    canvas = Canvas565(WIDTH, HEIGHT, background)
    canvas.draw_text(4, 0, f"5H{snapshot.remaining_percent}%", accent, scale=3)
    weekly = "--" if snapshot.secondary_remaining_percent is None else str(snapshot.secondary_remaining_percent)
    canvas.draw_text(4, 25, f"7D{weekly}%", accent, scale=3)

    bar_x, bar_y, bar_width, bar_height = 4, 50, 152, 8
    canvas.fill_rect(bar_x, bar_y, bar_width, bar_height, panel)
    inner_width = bar_width - 4
    filled = round(inner_width * snapshot.remaining_percent / 100)
    if filled:
        canvas.fill_rect(bar_x + 2, bar_y + 2, filled, bar_height - 4, accent)

    def reset_clock(timestamp: int | None) -> str:
        if timestamp is None:
            return "--:--"
        return dt.datetime.fromtimestamp(timestamp).astimezone().strftime("%H:%M")

    def reset_month_day(timestamp: int | None) -> str:
        if timestamp is None:
            return "-- --"
        return dt.datetime.fromtimestamp(timestamp).astimezone().strftime("%m-%d")

    footer = f"{reset_clock(snapshot.resets_at)}/{reset_month_day(snapshot.secondary_resets_at)}"
    footer_x = (WIDTH - text_width(footer, 2)) // 2
    canvas.draw_text(footer_x, 63, footer, muted, scale=2)
    return canvas


def render_test_pattern() -> Canvas565:
    """Render large color bands for diagnosing LCD state and transfer issues."""
    canvas = Canvas565(WIDTH, HEIGHT, rgb565(255, 255, 255))
    canvas.fill_rect(0, 0, WIDTH, 20, rgb565(255, 0, 0))
    canvas.fill_rect(0, 20, WIDTH, 20, rgb565(0, 255, 0))
    canvas.fill_rect(0, 40, WIDTH, 20, rgb565(0, 0, 255))
    canvas.fill_rect(0, 60, WIDTH, 20, rgb565(255, 255, 255))
    canvas.draw_text(50, 64, "TEST", rgb565(0, 0, 0), scale=2)
    return canvas


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def save_png(canvas: Canvas565, path: Path, scale: int = 4) -> None:
    raw_rows = bytearray()
    for source_y in range(canvas.height):
        expanded = bytearray()
        for source_x in range(canvas.width):
            color = canvas.pixels[source_y * canvas.width + source_x]
            expanded.extend(rgb565_to_rgb888(color) * scale)
        row = b"\x00" + bytes(expanded)
        for _ in range(scale):
            raw_rows.extend(row)
    width = canvas.width * scale
    height = canvas.height * scale
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
    png.extend(png_chunk(b"IDAT", zlib.compress(bytes(raw_rows), level=9)))
    png.extend(png_chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def encode_compressed_pixels(pixels: Sequence[int]) -> bytes:
    """Encode RGB565 pixels using the MSU2 demo application's LCD-RAM codec."""
    if len(pixels) % 128:
        raise ValueError("Pixel count must be a multiple of 128")
    output = bytearray()
    for offset in range(0, len(pixels), 128):
        block = pixels[offset : offset + 128]
        words = [(block[index] << 16) | block[index + 1] for index in range(0, 128, 2)]
        dominant = collections.Counter(words).most_common(1)[0][0]
        output.extend((2, 4))
        output.extend(dominant.to_bytes(4, "big"))
        for index, word in enumerate(words):
            if word == dominant:
                continue
            output.extend((4, index))
            output.extend(word.to_bytes(4, "big"))
        output.extend((2, 3, 8, 1, 0, 0))
    return bytes(output)


def encode_raw_pixels(pixels: Sequence[int]) -> bytes:
    """Encode RGB565 pixels with the firmware's reliable 256-byte chunk protocol."""
    if len(pixels) % 128:
        raise ValueError("Pixel count must be a multiple of 128")
    output = bytearray()
    for offset in range(0, len(pixels), 128):
        block = pixels[offset : offset + 128]
        raw = bytearray()
        for pixel in block:
            raw.extend(pixel.to_bytes(2, "big"))
        for index in range(64):
            output.extend((4, index))
            output.extend(raw[index * 4 : index * 4 + 4])
        output.extend((2, 3, 8, 1, 0, 0))
    return bytes(output)


class RawSerial:
    def __init__(self, path: str) -> None:
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attributes = termios.tcgetattr(self.fd)
        attributes[0] = 0
        attributes[1] = 0
        attributes[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attributes[3] = 0
        attributes[4] = BAUD
        attributes[5] = BAUD
        attributes[6][termios.VMIN] = 0
        attributes[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, attributes)
        termios.tcflush(self.fd, termios.TCIOFLUSH)

    def write_all(self, data: bytes, timeout: float = 30.0) -> None:
        view = memoryview(data)
        deadline = time.monotonic() + timeout
        while view:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out writing to {self.path}")
            _, writable, _ = select.select([], [self.fd], [], remaining)
            if not writable:
                continue
            written = os.write(self.fd, view)
            view = view[written:]

    def read_until_quiet(self, timeout: float = 0.5, quiet: float = 0.04) -> bytes:
        deadline = time.monotonic() + timeout
        data = bytearray()
        while time.monotonic() < deadline:
            wait = min(quiet, deadline - time.monotonic())
            readable, _, _ = select.select([self.fd], [], [], max(0, wait))
            if not readable:
                if data:
                    break
                continue
            chunk = os.read(self.fd, 4096)
            if chunk:
                data.extend(chunk)
        return bytes(data)

    def drain(self) -> None:
        termios.tcdrain(self.fd)

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


class MSU2Mini:
    def __init__(
        self,
        device_glob: str = DEFAULT_DEVICE_GLOB,
        lcd_state: int = 0,
        packet_delay: float = 0.01,
    ) -> None:
        self.device_glob = device_glob
        self.lcd_state = lcd_state
        self.packet_delay = packet_delay
        self.serial: RawSerial | None = None
        self.window_size: tuple[int, int] | None = None

    def connect(self) -> str:
        self.close()
        candidates = sorted(glob.glob(self.device_glob))
        if not candidates:
            raise FileNotFoundError(f"No serial device matched {self.device_glob}")
        errors: list[str] = []
        for path in candidates:
            port: RawSerial | None = None
            try:
                port = RawSerial(path)
                time.sleep(0.35)
                greeting = port.read_until_quiet(timeout=0.5)
                port.write_all(b"\x00MSNCN")
                time.sleep(0.25)
                response = port.read_until_quiet(timeout=0.5)
                # The device does not always repeat its greeting after a host
                # process reconnects. The reference cross-platform client also
                # treats MSNCN as a wake-up signal and proceeds without making
                # the greeting mandatory.
                self.serial = port
                # The official host application sends LCD_State immediately
                # after connecting. Without this, the controller can keep the
                # startup/flash page active and ignore LCD-RAM frames.
                self._set_lcd_state(self.lcd_state)
                return path
            except Exception as exc:
                errors.append(f"{path}: {exc}")
                if port is not None:
                    port.close()
        raise RuntimeError("Could not connect to MSU2_MINI: " + "; ".join(errors))

    def show(self, canvas: Canvas565) -> int:
        payload = encode_compressed_pixels(canvas.pixels)
        return self.show_payload(payload, canvas.width, canvas.height)

    def show_payload(self, payload: bytes, width: int, height: int) -> int:
        if self.serial is None:
            self.connect()
        assert self.serial is not None
        # Start every draw with a fresh window command and preserve the
        # firmware's 390-byte packet boundaries. This is the reliable path
        # used by the cross-platform MSU Mini implementation.
        self._set_window(0, 0, width, height)
        self.window_size = (width, height)
        for offset in range(0, len(payload), 390):
            self.serial.write_all(payload[offset : offset + 390], timeout=5.0)
            self.serial.drain()
            time.sleep(self.packet_delay)
        return len(payload)

    def _set_window(self, x: int, y: int, width: int, height: int) -> None:
        assert self.serial is not None
        self.serial.read_until_quiet(timeout=0.05)
        self.serial.write_all(bytes((2, 0)) + x.to_bytes(2, "big") + y.to_bytes(2, "big"))
        self.serial.write_all(bytes((2, 1)) + width.to_bytes(2, "big") + height.to_bytes(2, "big"))
        start = bytes((2, 3, 7, 0, 0, 0))
        self.serial.write_all(start)
        reply = self.serial.read_until_quiet(timeout=1.0)
        if reply and start[:2] not in reply:
            raise RuntimeError(f"Unexpected LCD start acknowledgement: {reply.hex()}")

    def _set_lcd_state(self, state: int) -> None:
        assert self.serial is not None
        command = bytes((2, 3, 10, state, 0, 0))
        self.serial.write_all(command)
        time.sleep(0.01)
        reply = self.serial.read_until_quiet(timeout=0.5)
        if reply and command[:2] not in reply:
            raise RuntimeError(f"Unexpected LCD state acknowledgement: {reply.hex()}")

    def close(self) -> None:
        if self.serial is not None:
            self.serial.close()
            self.serial = None
        self.window_size = None


def format_snapshot(snapshot: UsageSnapshot) -> str:
    def describe(remaining: int | None, resets_at: int | None) -> str:
        value = "unknown" if remaining is None else f"{remaining}% remaining"
        if resets_at:
            reset = dt.datetime.fromtimestamp(resets_at).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        else:
            reset = "unknown"
        return f"{value}, resets {reset}"

    return (
        f"Codex {snapshot.plan_type or 'unknown'}: "
        f"5h {describe(snapshot.remaining_percent, snapshot.resets_at)}; "
        f"weekly {describe(snapshot.secondary_remaining_percent, snapshot.secondary_resets_at)}"
    )


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Refresh once and exit")
    parser.add_argument("--interval", type=float, default=60.0, help="Refresh interval in seconds")
    parser.add_argument(
        "--hold-interval",
        type=float,
        default=5.0,
        help="Seconds between cached LCD frames used to suppress the offline animation",
    )
    parser.add_argument("--device-glob", default=DEFAULT_DEVICE_GLOB, help="Serial device glob")
    parser.add_argument("--lcd-state", type=int, choices=(0, 1), default=0, help="MSU2 LCD orientation")
    parser.add_argument(
        "--packet-delay",
        type=float,
        default=0.01,
        help="Seconds to let the controller process each 256-byte LCD chunk",
    )
    parser.add_argument("--codex", dest="codex_path", help="Path to the Codex CLI")
    parser.add_argument("--preview", type=Path, help="Write a scaled PNG preview")
    parser.add_argument("--no-device", action="store_true", help="Do not write to the USB screen")
    parser.add_argument("--test-pattern", action="store_true", help="Show an RGB diagnostic pattern")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    stop = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    usage_client = CodexUsageClient(args.codex_path)
    display = MSU2Mini(args.device_glob, args.lcd_state, max(0.0, args.packet_delay))
    canvas: Canvas565 | None = None
    frame_payload: bytes | None = None
    snapshot: UsageSnapshot | None = None
    next_usage_refresh = 0.0
    try:
        while not stop:
            started = time.monotonic()
            refreshed = False
            try:
                now = time.monotonic()
                if canvas is None or (not args.test_pattern and now >= next_usage_refresh):
                    snapshot = None if args.test_pattern else usage_client.read_usage()
                    canvas = render_test_pattern() if args.test_pattern else render_dashboard(snapshot)
                    frame_payload = encode_raw_pixels(canvas.pixels)
                    next_usage_refresh = now + max(1.0, args.interval)
                    refreshed = True
                    if args.preview:
                        save_png(canvas, args.preview)

                assert canvas is not None and frame_payload is not None
                if args.no_device:
                    if refreshed:
                        print("MSU2 RGB test pattern" if snapshot is None else format_snapshot(snapshot), flush=True)
                else:
                    try:
                        payload_size = display.show_payload(frame_payload, canvas.width, canvas.height)
                    except Exception as first_error:
                        display.close()
                        try:
                            payload_size = display.show_payload(frame_payload, canvas.width, canvas.height)
                        except Exception as retry_error:
                            raise RuntimeError(f"LCD write failed ({first_error}); retry failed ({retry_error})") from retry_error
                    if refreshed:
                        status = "MSU2 RGB test pattern" if snapshot is None else format_snapshot(snapshot)
                        print(f"{status}; holding {payload_size}-byte LCD frame", flush=True)
            except Exception as exc:
                print(f"Refresh failed: {exc}", file=sys.stderr, flush=True)
                if args.once:
                    return 1
            if args.once:
                break
            elapsed = time.monotonic() - started
            target_interval = args.interval if args.no_device else max(0.0, args.hold_interval)
            deadline = time.monotonic() + max(0.0, target_interval - elapsed)
            while not stop and time.monotonic() < deadline:
                time.sleep(min(0.05, deadline - time.monotonic()))
    finally:
        display.close()
        usage_client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
