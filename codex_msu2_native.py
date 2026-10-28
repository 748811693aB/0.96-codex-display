#!/usr/bin/env python3
"""Show Codex usage and DeepSeek balance on the MSU2_MINI USB screen.

The screen alternates between two pages every 30 seconds by default. Both
pages use the firmware's native drawing commands, and the logo on the left
switches with the page (Codex flower / DeepSeek whale).
"""

from __future__ import annotations

import argparse
import datetime as dt
import signal
import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol, Sequence

try:
    from .codex_msu2_display import (
        FONT_5X7,
        Canvas565,
        CodexUsageClient,
        MSU2Mini,
        UsageSnapshot,
        format_snapshot,
        rgb565,
        save_png,
    )
    from .deepseek_balance import (
        DeepSeekAuthError,
        DeepSeekBalance,
        DeepSeekBalanceClient,
        DeepSeekError,
        DeepSeekPrice,
        currency_symbol,
        current_api_price,
        discover_credential,
        format_money,
        format_price_multiple,
        summarize,
        summarize_price,
    )
except ImportError:  # executed as a script
    from codex_msu2_display import (  # type: ignore[no-redef]
        FONT_5X7,
        Canvas565,
        CodexUsageClient,
        MSU2Mini,
        UsageSnapshot,
        format_snapshot,
        rgb565,
        save_png,
    )
    from deepseek_balance import (  # type: ignore[no-redef]
        DeepSeekAuthError,
        DeepSeekBalance,
        DeepSeekBalanceClient,
        DeepSeekError,
        DeepSeekPrice,
        currency_symbol,
        current_api_price,
        discover_credential,
        format_money,
        format_price_multiple,
        summarize,
        summarize_price,
    )


SCREEN_WIDTH = 160
SCREEN_HEIGHT = 80
DISPLAY_BRIGHTNESS = 0.82

LOGO_RESERVED_WIDTH = 64
CONTENT_HEIGHT = 59
CONTENT_X = LOGO_RESERVED_WIDTH
CONTENT_WIDTH = SCREEN_WIDTH - LOGO_RESERVED_WIDTH

CODEX_PAGE = "codex"
DEEPSEEK_PAGE = "deepseek"
PAGES = (CODEX_PAGE, DEEPSEEK_PAGE)

# DeepSeek page states.
STATUS_LOADING = "loading"
STATUS_OK = "ok"
STATUS_NO_KEY = "nokey"
STATUS_ERROR = "error"


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
WARNING = display_color(255, 190, 52)
MUTED = display_color(150, 170, 205)
LOGO_LIGHT = display_color(98, 112, 255)
LOGO_DARK = display_color(40, 60, 212)

# DeepSeek palette: brand blue, a darker edge tone for antialiased cells, and
# the light belly/eye tone.
DEEPSEEK_BLUE = display_color(77, 107, 254)
DEEPSEEK_EDGE = display_color(38, 56, 158)
DEEPSEEK_WHITE = display_color(240, 245, 255)
DEEPSEEK_ACCENT = display_color(140, 164, 255)

# Price colors run from green (cheap) through the DeepSeek blue baseline to
# red (expensive). The same color is used by the whale and its multiplier.
PRICE_GREEN_RGB = (62, 220, 132)
PRICE_BLUE_RGB = (77, 107, 254)
PRICE_RED_RGB = (255, 78, 92)


def _blend_rgb(start: tuple[int, int, int], end: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return tuple(round(a + (b - a) * amount) for a, b in zip(start, end))


def deepseek_price_rgb(price: DeepSeekPrice) -> tuple[int, int, int]:
    multiple = float(price.multiple_of_average)
    # The published valley/peak rates are 2/3× and 4/3× of their mean, so
    # those two observed endpoints map to saturated green and red.
    if multiple <= 1.0:
        return _blend_rgb(PRICE_GREEN_RGB, PRICE_BLUE_RGB, (multiple - (2 / 3)) / (1 / 3))
    return _blend_rgb(PRICE_BLUE_RGB, PRICE_RED_RGB, (multiple - 1.0) / (1 / 3))


def deepseek_price_color(price: DeepSeekPrice) -> int:
    return display_color(*deepseek_price_rgb(price))


def deepseek_price_edge_color(price: DeepSeekPrice) -> int:
    red, green, blue = deepseek_price_rgb(price)
    return display_color(round(red * 0.45), round(green * 0.45), round(blue * 0.45))


# ---------------------------------------------------------------------------
# Codex logo: a 24 x 24 source reduction of the official app mark.
# ---------------------------------------------------------------------------

LOGO_SOURCE_INSET = 2
LOGO_SOURCE_SIZE = 20
LOGO_SIZE = 51
LOGO_X = (LOGO_RESERVED_WIDTH - LOGO_SIZE) // 2
LOGO_Y = (CONTENT_HEIGHT - LOGO_SIZE) // 2

# L and D are the light and dark halves of its blue flower, W the white prompt.
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

# ---------------------------------------------------------------------------
# DeepSeek whale: a 40 x 30 pixel reduction of the official app mark.
# L = blue body, l = darker antialiased edge, W = white belly and eye.
# ---------------------------------------------------------------------------

WHALE_LOGO = (
    "                   l       Ll           ",
    "                lLLLL      LL           ",
    "       lLLLLLLLLLLLL      lLLL         l",
    "     LLLLLLLLLLLLLLL      lLLLLl      LL",
    "    LLLLLLLLLLLLLLLLl     lLLLLL  LLLLLL",
    "   LLLLLLLLLLLLLLLLLLL     LLLLLLLLLLLLL",
    "  LLLLLLLLLLLLLLLLLLLLL    LLLLLLLLLLLLl",
    " lLLLLLLLLLLLLLLLLLLLLLL   lLLLLLLLLLLL ",
    " LLLLLLLLLLLLLLLLLLLLLLLL   lLLLLLLLLL  ",
    "lLLLLLLLLLLLLLLLLLLLLLLLLL   lLLLLLLl   ",
    "LLLLLLLLLLLLLLLLLLLLLLLLLLLl lLLLL      ",
    "LLLWWWWWWLLLLLLLLLLLLLLLLLLLLLLLLL      ",
    "LLLWWWWWWWWLLLLLLLLLLWWWLLLLLLLLLl      ",
    "LLLWWWWWWWWWWLLLLLLLLLWWWLLLLLLLLl      ",
    "LLLWWWWWWWWWWWLLLLLLLWLWWLLLLLLLL       ",
    "LLLWWWWWWWWWWWWLLLLLLLLWWWLLLLLLL       ",
    "LLLlWWWWWWWWWWWWLLLLLLLWWWlLLLLLL       ",
    "LLLLWWWWWWWWWWWWWLLLLLLLLLLLLLLL        ",
    "lLLLWWWWWWWWWWWWWLLLLLLLLLLLLLLL        ",
    " LLLLWWWWWWWWWWWWWLLLLLLLLLLLLLl        ",
    " LLLLWWWWWWWWWWWWWWLLLLLLLLLLLL         ",
    "  LLLLWWWWWWWWWWWWWLLLLLLLLLLL          ",
    "  LLLLLWWWWWWLLWWWWWLLLLLLLLLl          ",
    "   LLLLLWWWWWLLLLWWWWLLLLLLLl           ",
    "    LLLLLWWWWWLLLLWWWWLLLLLLLl          ",
    "     LLLLLLlWLLLLLLWWWWLLLLLLLLl        ",
    "      LLLLLLLLLLLLLLLLWWLLLLLLLL        ",
    "       LLLLLLLLLLLLLLLLL  llLll         ",
    "         LLLLLLLLLLLLLl                 ",
    "           lLLLLLLLLl                   ",
)

WHALE_LOGO_WIDTH = 58
WHALE_LOGO_HEIGHT = 43
WHALE_LOGO_X = (LOGO_RESERVED_WIDTH - WHALE_LOGO_WIDTH) // 2
# Reserve the lower 14 px of the logo column for the large price multiple.
WHALE_LOGO_Y = 1


def vector_text_width(text: str, scale: int) -> int:
    return max(0, len(text) * 6 * scale - scale)


def _grid_runs(art: Sequence[str]) -> list[tuple[int, int, int, str]]:
    """Return horizontal single-color runs of an ASCII art grid."""
    runs: list[tuple[int, int, int, str]] = []
    for y, row in enumerate(art):
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


def logo_runs() -> list[tuple[int, int, int, str]]:
    """Return horizontal color runs for efficiently drawing the Codex logo."""
    return _grid_runs(CODEX_LOGO_24)


def scaled_logo_runs() -> list[tuple[int, int, int, int, str]]:
    """Scale Codex logo runs to the exact requested size without pixel gaps."""
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


def whale_logo_runs() -> list[tuple[int, int, int, int, str]]:
    """Scale the whale art to its target box without introducing gaps."""
    source_width = len(WHALE_LOGO[0])
    source_height = len(WHALE_LOGO)
    scaled: list[tuple[int, int, int, int, str]] = []
    for x, y, width, color_key in _grid_runs(WHALE_LOGO):
        left = WHALE_LOGO_X + x * WHALE_LOGO_WIDTH // source_width
        right = WHALE_LOGO_X + (x + width) * WHALE_LOGO_WIDTH // source_width
        top = WHALE_LOGO_Y + y * WHALE_LOGO_HEIGHT // source_height
        bottom = WHALE_LOGO_Y + (y + 1) * WHALE_LOGO_HEIGHT // source_height
        scaled.append((left, top, right - left, bottom - top, color_key))
    return scaled


# ---------------------------------------------------------------------------
# Surfaces: the native command writer and an in-memory canvas for previews.
# ---------------------------------------------------------------------------


class Surface(Protocol):
    def fill_region(self, x: int, y: int, width: int, height: int, color: int) -> None: ...

    def flush(self) -> None: ...

    def reset(self) -> None: ...

    def keep_display_active(self) -> None: ...


class MSU2Surface:
    """Firmware-native fill commands over the serial transport.

    Every fill costs three short commands, so writing each one and then waiting
    for its acknowledgement made a full page take several seconds. Fills are
    now queued and sent in small batches, with the acknowledgement drain shared
    by the whole batch.
    """

    BATCH_SIZE = 4
    # The firmware acknowledges every fill command. A re-enumerated or wedged
    # USB session keeps accepting writes without ever answering, so silence is
    # used as the liveness signal that triggers a reconnect.
    SILENT_FLUSH_LIMIT = 5

    def __init__(self, display: MSU2Mini, batch_size: int = BATCH_SIZE) -> None:
        self.display = display
        self.batch_size = max(1, batch_size)
        self._batch = bytearray()
        self._pending = 0
        self.silent_flushes = 0

    def _command(self, x: int, y: int, width: int, height: int, color: int) -> bytes:
        return (
            bytes((2, 0)) + x.to_bytes(2, "big") + y.to_bytes(2, "big")
            + bytes((2, 1)) + width.to_bytes(2, "big") + height.to_bytes(2, "big")
            + bytes((2, 3, 11)) + color.to_bytes(2, "big") + b"\0"
        )

    def fill_region(self, x: int, y: int, width: int, height: int, color: int) -> None:
        if width <= 0 or height <= 0:
            return
        self._batch.extend(self._command(x, y, width, height, color))
        self._pending += 1
        if self._pending >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        if not self._batch:
            return
        serial = self.display.serial
        payload = bytes(self._batch)
        self._batch.clear()
        self._pending = 0
        if serial is None:
            return
        serial.write_all(payload)
        response = serial.read_until_quiet(timeout=0.02, quiet=0.002)
        if response:
            self.silent_flushes = 0
        else:
            self.silent_flushes += 1
            if self.silent_flushes >= self.SILENT_FLUSH_LIMIT:
                self.silent_flushes = 0
                raise RuntimeError("MSU2 stopped acknowledging display writes; reconnecting")

    def reset(self) -> None:
        """Drop queued commands after a transport error or reconnect."""
        self._batch.clear()
        self._pending = 0
        self.silent_flushes = 0

    def keep_display_active(self) -> None:
        self.flush()
        self.fill_region(SCREEN_WIDTH - 1, SCREEN_HEIGHT - 1, 1, 1, BACKGROUND)
        self.flush()


class CanvasSurface:
    """In-memory surface used by ``--preview-dir``."""

    def __init__(self) -> None:
        self.canvas = Canvas565(SCREEN_WIDTH, SCREEN_HEIGHT, BACKGROUND)

    def fill_region(self, x: int, y: int, width: int, height: int, color: int) -> None:
        self.canvas.fill_rect(x, y, width, height, color)

    def flush(self) -> None:
        pass

    def reset(self) -> None:
        pass

    def keep_display_active(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


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


def other_page(page: str) -> str:
    """Return the page shown after ``page`` in the rotation."""
    return DEEPSEEK_PAGE if page == CODEX_PAGE else CODEX_PAGE


class NativeDashboard:
    def __init__(self, surface: Surface) -> None:
        self.surface = surface

    # -- primitives ---------------------------------------------------------

    def fill_region(self, x: int, y: int, width: int, height: int, color: int) -> None:
        self.surface.fill_region(x, y, width, height, color)

    def clear(self) -> None:
        self.fill_region(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, BACKGROUND)

    def clear_content(self) -> None:
        self.fill_region(CONTENT_X, 0, CONTENT_WIDTH, CONTENT_HEIGHT, BACKGROUND)

    def clear_footer(self) -> None:
        self.fill_region(0, CONTENT_HEIGHT, SCREEN_WIDTH, SCREEN_HEIGHT - CONTENT_HEIGHT, BACKGROUND)

    def draw_vector_text(self, x: int, y: int, text: str, color: int, scale: int = 1) -> None:
        for character_index, character in enumerate(text.upper()):
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

    # -- logos --------------------------------------------------------------

    def draw_codex_logo(self) -> None:
        colors = {"L": LOGO_LIGHT, "D": LOGO_DARK, "W": FOREGROUND}
        for x, y, width, height, color_key in scaled_logo_runs():
            self.fill_region(x, y, width, height, colors[color_key])

    def draw_whale_logo(self, price: DeepSeekPrice | None = None) -> None:
        if price is None:
            colors = {"L": DEEPSEEK_BLUE, "l": DEEPSEEK_EDGE, "W": DEEPSEEK_WHITE}
        else:
            colors = {
                "L": deepseek_price_color(price),
                "l": deepseek_price_edge_color(price),
                "W": DEEPSEEK_WHITE,
            }
        for x, y, width, height, color_key in whale_logo_runs():
            self.fill_region(x, y, width, height, colors[color_key])

    def draw_price_badge(self, price: DeepSeekPrice) -> None:
        """Draw the large multiplier in the reserved strip below the whale."""
        text = format_price_multiple(price.multiple_of_average).upper()
        scale = 2
        width = vector_text_width(text, scale)
        x = max(0, (LOGO_RESERVED_WIDTH - width) // 2)
        y = CONTENT_HEIGHT - 7 * scale
        self.draw_vector_text(x, y, text, deepseek_price_color(price), scale=scale)

    def draw_logo(self, page: str, price: DeepSeekPrice | None = None) -> None:
        self.fill_region(0, 0, LOGO_RESERVED_WIDTH, CONTENT_HEIGHT, BACKGROUND)
        if page == DEEPSEEK_PAGE:
            self.draw_whale_logo(price)
            if price is not None:
                self.draw_price_badge(price)
        else:
            self.draw_codex_logo()

    # -- Codex page ---------------------------------------------------------

    def draw_usage_rows(self, snapshot: UsageSnapshot | None) -> None:
        rows = (
            (1, "5H", remaining_text(None if snapshot is None else snapshot.remaining_percent)),
            (31, "7D", remaining_text(None if snapshot is None else snapshot.secondary_remaining_percent)),
        )
        for y, label, value in rows:
            label_width = vector_text_width(label, 2)
            value_width = vector_text_width(value, 3)
            percent_width = vector_text_width("%", 2)
            full_width = label_width + 4 + value_width + 2 + percent_width
            start_x = CONTENT_X + max(0, (CONTENT_WIDTH - full_width) // 2)
            value_x = start_x + label_width + 4
            percent_x = value_x + value_width + 2
            self.draw_vector_text(start_x, y + 3, label, FOREGROUND, scale=2)
            self.draw_vector_text(value_x, y, value, ACCENT, scale=3)
            self.draw_vector_text(percent_x, y + 3, "%", ACCENT, scale=2)

    def draw_footer_text(self, text: str, color: int = FOREGROUND) -> None:
        scale = 2
        if vector_text_width(text, scale) > SCREEN_WIDTH - 4:
            scale = 1
        self.clear_footer()
        width = vector_text_width(text, scale)
        x = max(0, (SCREEN_WIDTH - width) // 2)
        y = CONTENT_HEIGHT + max(0, (SCREEN_HEIGHT - CONTENT_HEIGHT - 7 * scale) // 2)
        self.draw_vector_text(x, y, text, color, scale=scale)

    def draw_footer_parts(self, label: str, value: str, label_color: int = MUTED) -> None:
        scale = 2
        gap = 6 * scale
        total = vector_text_width(label, scale) + gap + vector_text_width(value, scale)
        if total > SCREEN_WIDTH - 4:
            scale = 1
            gap = 6 * scale
            total = vector_text_width(label, scale) + gap + vector_text_width(value, scale)
        self.clear_footer()
        x = max(0, (SCREEN_WIDTH - total) // 2)
        y = CONTENT_HEIGHT + max(0, (SCREEN_HEIGHT - CONTENT_HEIGHT - 7 * scale) // 2)
        self.draw_vector_text(x, y, label, label_color, scale=scale)
        self.draw_vector_text(x + vector_text_width(label, scale) + gap, y, value, FOREGROUND, scale=scale)

    def draw_footer_parts_right(self, label: str, value: str, label_color: int = MUTED) -> None:
        """Place a readable footer item against the lower-right edge."""
        scale = 2
        gap = 8
        total = vector_text_width(label, scale) + gap + vector_text_width(value, scale)
        if total > SCREEN_WIDTH - 4:
            scale = 1
            gap = 4
            total = vector_text_width(label, scale) + gap + vector_text_width(value, scale)
        self.clear_footer()
        x = max(0, SCREEN_WIDTH - total - 2)
        y = CONTENT_HEIGHT + max(0, (SCREEN_HEIGHT - CONTENT_HEIGHT - 7 * scale) // 2)
        self.draw_vector_text(x, y, label, label_color, scale=scale)
        self.draw_vector_text(x + vector_text_width(label, scale) + gap, y, value, FOREGROUND, scale=scale)

    def draw_codex_content(self, snapshot: UsageSnapshot | None) -> None:
        self.clear_content()
        self.draw_usage_rows(snapshot)
        if snapshot is None:
            self.draw_footer_text("NO DATA", WARNING)
        else:
            self.draw_footer_text(reset_time_label(snapshot))

    # -- DeepSeek page ------------------------------------------------------

    def _amount_layout(
        self,
        label: str | None,
        symbol: str | None,
        value: str,
        max_scale: int,
    ) -> tuple[int, int, int]:
        """Pick font scales that fit the amount beside the logo."""
        width = 0
        for value_scale in range(max_scale, 0, -1):
            for label_scale in (2, 1):
                symbol_scale = max(2, value_scale)
                width = 0
                if label:
                    width += vector_text_width(label, label_scale) + 6
                if symbol:
                    width += vector_text_width(symbol, symbol_scale) + 3
                width += vector_text_width(value, value_scale)
                if width <= CONTENT_WIDTH:
                    return value_scale, label_scale, width
        return 1, 1, width

    def draw_amount_row(
        self,
        y: int,
        label: str | None,
        symbol: str | None,
        value: str,
        max_scale: int,
        color: int,
        label_color: int = MUTED,
    ) -> None:
        value_scale, label_scale, width = self._amount_layout(label, symbol, value, max_scale)
        cursor = CONTENT_X + max(0, (CONTENT_WIDTH - width) // 2)
        if label:
            label_y = y + (7 * value_scale - 7 * label_scale) // 2
            self.draw_vector_text(cursor, label_y, label, label_color, scale=label_scale)
            cursor += vector_text_width(label, label_scale) + 6
        if symbol:
            symbol_scale = max(2, value_scale)
            symbol_y = y + (7 * value_scale - 7 * symbol_scale) // 2
            self.draw_vector_text(cursor, symbol_y, symbol, color, scale=symbol_scale)
            cursor += vector_text_width(symbol, symbol_scale) + 3
        self.draw_vector_text(cursor, y, value, color, scale=value_scale)

    def draw_deepseek_content(
        self,
        balance: DeepSeekBalance | None,
        status: str,
        price: DeepSeekPrice | None = None,
    ) -> None:
        self.clear_content()
        if status == STATUS_OK and balance is not None:
            symbol = currency_symbol(balance.currency)
            self.draw_amount_row(1, None, symbol, format_money(balance.total), 3, DEEPSEEK_ACCENT)
            if balance.topped_up is not None:
                self.draw_amount_row(31, "TOP", None, format_money(balance.topped_up), 2, FOREGROUND)
            self.draw_footer_parts_right("GFT", f"{symbol}{format_money(balance.granted)}")
            return

        if status == STATUS_NO_KEY:
            message, hint, color = "NO KEY", "ADD API KEY", WARNING
        elif status == STATUS_LOADING:
            message, hint, color = "--", "LOADING", FOREGROUND
        else:
            message, hint, color = "ERROR", "RETRYING", WARNING
        scale = 2
        x = CONTENT_X + max(0, (CONTENT_WIDTH - vector_text_width(message, scale)) // 2)
        self.draw_vector_text(x, 16, message, color, scale=scale)
        self.draw_footer_text(hint, color)

    # -- pages --------------------------------------------------------------

    def draw_content(
        self,
        page: str,
        snapshot: UsageSnapshot | None,
        balance: DeepSeekBalance | None,
        status: str,
        price: DeepSeekPrice | None = None,
    ) -> None:
        if page == DEEPSEEK_PAGE:
            self.draw_deepseek_content(balance, status, price)
        else:
            self.draw_codex_content(snapshot)
        self.surface.flush()

    def draw_page(
        self,
        page: str,
        snapshot: UsageSnapshot | None,
        balance: DeepSeekBalance | None,
        status: str,
        price: DeepSeekPrice | None = None,
    ) -> None:
        self.draw_logo(page, price)
        self.draw_content(page, snapshot, balance, status, price)
        self.surface.flush()

    def keep_alive(self) -> None:
        self.surface.keep_display_active()


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------


@dataclass
class PageState:
    page: str = CODEX_PAGE
    codex_snapshot: UsageSnapshot | None = None
    deepseek_balance: DeepSeekBalance | None = None
    deepseek_price: DeepSeekPrice | None = None
    deepseek_status: str = STATUS_LOADING
    next_codex_refresh: float = 0.0
    next_deepseek_refresh: float = 0.0
    next_rotation: float = 0.0
    force_redraw: bool = True
    content_dirty: bool = True


def _refresh_codex(
    state: PageState,
    client: CodexUsageClient,
    interval: float,
    now: float,
) -> None:
    try:
        snapshot = client.read_usage()
        if snapshot != state.codex_snapshot:
            state.codex_snapshot = snapshot
            if state.page == CODEX_PAGE:
                state.content_dirty = True
        print(format_snapshot(snapshot), flush=True)
    except Exception as exc:  # noqa: BLE001 - the display must keep running
        print(f"Codex 用量查询失败：{exc}", flush=True)
        if state.codex_snapshot is None and state.page == CODEX_PAGE:
            state.content_dirty = True
    state.next_codex_refresh = now + max(5.0, interval)


def _refresh_deepseek(state: PageState, args: argparse.Namespace, now: float) -> None:
    try:
        price = current_api_price(args.deepseek_price_model)
        if price != state.deepseek_price:
            state.deepseek_price = price
            if state.page == DEEPSEEK_PAGE:
                state.content_dirty = True
    except DeepSeekError as exc:
        print(f"DeepSeek API 价格读取失败：{exc}", flush=True)

    credential = discover_credential(
        explicit_key=args.deepseek_key,
        explicit_key_file=args.deepseek_key_file,
        dsh_credentials=args.dsh_credentials,
        project_dir=Path(__file__).resolve().parent,
    )
    if credential is None:
        if state.deepseek_status != STATUS_NO_KEY:
            state.deepseek_status = STATUS_NO_KEY
            if state.page == DEEPSEEK_PAGE:
                state.content_dirty = True
            print(
                "未找到 DeepSeek 凭证：请设置 DEEPSEEK_API_KEY，或把 API Key 写入 "
                "~/.config/deepseek-display/api_key，或在 DeepSeek Harness 中登录账号。",
                flush=True,
            )
        state.next_deepseek_refresh = now + max(60.0, args.deepseek_interval)
        return

    try:
        balance = DeepSeekBalanceClient(credential).read()
    except DeepSeekAuthError as exc:
        state.deepseek_status = STATUS_OK if state.deepseek_balance is not None else STATUS_ERROR
        if state.page == DEEPSEEK_PAGE:
            state.content_dirty = True
        print(f"DeepSeek 余额读取失败：{exc}", flush=True)
        state.next_deepseek_refresh = now + 3600.0
        return
    except DeepSeekError as exc:
        state.deepseek_status = STATUS_OK if state.deepseek_balance is not None else STATUS_ERROR
        if state.page == DEEPSEEK_PAGE:
            state.content_dirty = True
        print(f"DeepSeek 余额读取失败：{exc}", flush=True)
        state.next_deepseek_refresh = now + max(30.0, min(60.0, args.deepseek_interval))
        return

    state.deepseek_balance = balance
    state.deepseek_status = STATUS_OK
    if state.page == DEEPSEEK_PAGE:
        state.content_dirty = True
    print(summarize(balance), flush=True)
    if state.deepseek_price is not None:
        print(summarize_price(state.deepseek_price), flush=True)
    state.next_deepseek_refresh = now + max(30.0, args.deepseek_interval)


def demo_snapshot() -> UsageSnapshot:
    now = int(time.time())
    return UsageSnapshot(
        used_percent=18,
        remaining_percent=82,
        resets_at=now + 2 * 3600,
        window_minutes=300,
        plan_type="plus",
        secondary_used_percent=64,
        secondary_remaining_percent=36,
        secondary_resets_at=now + 4 * 86400,
        secondary_window_minutes=10080,
    )


def demo_balance() -> DeepSeekBalance:
    return DeepSeekBalance(
        currency="CNY",
        total=Decimal("9.57"),
        topped_up=Decimal("3.69"),
        granted=Decimal("5.87"),
        is_available=True,
        fetched_at=time.time(),
        source="demo",
    )


def render_previews(args: argparse.Namespace, state: PageState) -> int:
    preview_dir = args.preview_dir
    assert preview_dir is not None
    preview_dir.mkdir(parents=True, exist_ok=True)
    for page in PAGES:
        surface = CanvasSurface()
        dashboard = NativeDashboard(surface)
        dashboard.clear()
        dashboard.draw_page(page, state.codex_snapshot, state.deepseek_balance, state.deepseek_status, state.deepseek_price)
        path = preview_dir / f"{page}.png"
        save_png(surface.canvas, path, scale=6)
        print(f"预览已写入 {path}", flush=True)
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-glob", default="/dev/cu.usbmodem*")
    parser.add_argument("--interval", type=float, default=60.0, help="Codex 用量查询间隔（秒）")
    parser.add_argument(
        "--deepseek-interval",
        type=float,
        default=300.0,
        help="DeepSeek 余额查询间隔（秒）",
    )
    parser.add_argument(
        "--rotate-interval",
        type=float,
        default=30.0,
        help="两个页面轮换显示的间隔（秒），设为 0 可关闭轮换",
    )
    parser.add_argument("--draw-interval", type=float, default=0.2, help="屏幕保活刷新间隔（秒）")
    parser.add_argument("--codex", dest="codex_path", help="Codex CLI 路径")
    parser.add_argument("--deepseek-key", help="DeepSeek API Key（默认读取环境变量或配置文件）")
    parser.add_argument(
        "--deepseek-price-model",
        default="deepseek-flash",
        help="用于峰谷价显示的 DeepSeek API 模型（默认 deepseek-flash）",
    )
    parser.add_argument("--deepseek-key-file", help="存放 DeepSeek API Key 的文件")
    parser.add_argument("--dsh-credentials", help="DeepSeek Harness 凭证文件路径")
    parser.add_argument(
        "--page",
        choices=("auto", CODEX_PAGE, DEEPSEEK_PAGE),
        default="auto",
        help="固定显示某一页，或 auto 轮换",
    )
    parser.add_argument("--preview-dir", type=Path, help="把两个页面渲染成 PNG 预览后退出")
    parser.add_argument("--demo", action="store_true", help="使用示例数据（不联网、不需要设备）")
    parser.add_argument("--once", action="store_true", help="只绘制一帧后退出")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    stop = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    state = PageState(page=CODEX_PAGE if args.page == "auto" else args.page)
    if args.demo:
        state.codex_snapshot = demo_snapshot()
        state.deepseek_balance = demo_balance()
        state.deepseek_price = current_api_price(args.deepseek_price_model)
        state.deepseek_status = STATUS_OK

    codex_client: CodexUsageClient | None = None
    if not args.demo:
        codex_client = CodexUsageClient(args.codex_path)
        now = time.monotonic()
        if args.page in ("auto", CODEX_PAGE):
            _refresh_codex(state, codex_client, args.interval, now)
        if args.page in ("auto", DEEPSEEK_PAGE):
            _refresh_deepseek(state, args, now)

    if args.preview_dir is not None:
        try:
            return render_previews(args, state)
        finally:
            if codex_client is not None:
                codex_client.close()

    display = MSU2Mini(args.device_glob, lcd_state=0)
    surface = MSU2Surface(display)
    dashboard = NativeDashboard(surface)
    state.next_rotation = time.monotonic() + max(1.0, args.rotate_interval)
    try:
        while not stop:
            started = time.monotonic()
            try:
                if args.page == "auto" and args.rotate_interval > 0 and started >= state.next_rotation:
                    state.page = other_page(state.page)
                    state.next_rotation = started + max(1.0, args.rotate_interval)
                    state.force_redraw = True

                if codex_client is not None:
                    if started >= state.next_codex_refresh:
                        _refresh_codex(state, codex_client, args.interval, started)
                    if started >= state.next_deepseek_refresh:
                        _refresh_deepseek(state, args, started)

                if display.serial is None:
                    display.connect()
                    surface.reset()
                    state.force_redraw = True

                if state.force_redraw:
                    dashboard.clear()
                    dashboard.draw_page(
                        state.page,
                        state.codex_snapshot,
                        state.deepseek_balance,
                        state.deepseek_status,
                        state.deepseek_price,
                    )
                    state.force_redraw = False
                    state.content_dirty = False
                elif state.content_dirty:
                    dashboard.draw_content(
                        state.page,
                        state.codex_snapshot,
                        state.deepseek_balance,
                        state.deepseek_status,
                        state.deepseek_price,
                    )
                    state.content_dirty = False
                dashboard.keep_alive()
            except Exception as exc:  # noqa: BLE001 - reconnect on any transport error
                print(f"显示刷新失败：{exc}", file=sys.stderr, flush=True)
                surface.reset()
                display.close()
                state.force_redraw = True
                state.content_dirty = True
                time.sleep(0.5)

            if args.once:
                break
            elapsed = time.monotonic() - started
            delay = max(0.0, args.draw_interval - elapsed)
            if delay:
                time.sleep(delay)
    finally:
        display.close()
        if codex_client is not None:
            codex_client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
