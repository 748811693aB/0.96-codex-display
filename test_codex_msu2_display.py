import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_msu2_native import (
    CODEX_LOGO_24,
    CONTENT_HEIGHT,
    CONTENT_WIDTH,
    DISPLAY_BRIGHTNESS,
    DEEPSEEK_BLUE,
    LOGO_SIZE,
    LOGO_RESERVED_WIDTH,
    MSU2Surface,
    STATUS_NO_KEY,
    STATUS_OK,
    WHALE_LOGO,
    WHALE_LOGO_HEIGHT,
    WHALE_LOGO_WIDTH,
    CanvasSurface,
    NativeDashboard,
    demo_balance,
    demo_snapshot,
    other_page,
    logo_runs,
    remaining_text,
    reset_time_label,
    scaled_logo_runs,
    vector_text_width,
    whale_logo_runs,
)

from deepseek_balance import (
    current_api_price,
    discover_credential,
    format_money,
    parse_api_balance,
    parse_platform_balance,
    read_api_key_file,
    read_dsh_grant,
)

from codex_msu2_display import (
    HEIGHT,
    WIDTH,
    UsageSnapshot,
    encode_compressed_pixels,
    encode_raw_pixels,
    parse_usage_snapshot,
    render_dashboard,
    render_test_pattern,
    rgb565,
)


class DisplayTests(unittest.TestCase):
    def test_reset_time_label(self):
        snapshot = UsageSnapshot(40, 60, 1787210118, 300, "plus", 25, 75, 1787814918, 10080)
        self.assertRegex(reset_time_label(snapshot), r"^\d{2}:\d{2}/\d{2}-\d{2}$")
        self.assertEqual(reset_time_label(UsageSnapshot(40, 60, None, 300, "plus")), "--:--/-- --")
        self.assertLessEqual(vector_text_width(reset_time_label(snapshot), 2), 160)

    def test_parse_both_usage_windows(self):
        snapshot = parse_usage_snapshot({
            "rateLimitsByLimitId": {
                "codex": {
                    "planType": "plus",
                    "primary": {"usedPercent": 40, "resetsAt": 1000, "windowDurationMins": 300},
                    "secondary": {"usedPercent": 25, "resetsAt": 2000, "windowDurationMins": 10080},
                }
            }
        })
        self.assertEqual((snapshot.remaining_percent, snapshot.window_minutes), (60, 300))
        self.assertEqual((snapshot.secondary_remaining_percent, snapshot.secondary_window_minutes), (75, 10080))

    def test_codex_logo_bitmap(self):
        self.assertEqual(len(CODEX_LOGO_24), 24)
        self.assertTrue(all(len(row) == 24 for row in CODEX_LOGO_24))
        self.assertEqual(set("".join(CODEX_LOGO_24)), {" ", "D", "L", "W"})
        self.assertTrue(logo_runs())
        scaled_runs = scaled_logo_runs()
        self.assertEqual(LOGO_SIZE, 51)
        self.assertEqual(max(x + width for x, _, width, _, _ in scaled_runs) - min(x for x, _, _, _, _ in scaled_runs), 51)
        self.assertEqual(max(y + height for _, y, _, height, _ in scaled_runs) - min(y for _, y, _, _, _ in scaled_runs), 51)

    def test_two_usage_rows_fit_beside_logo(self):
        available_width = 160 - LOGO_RESERVED_WIDTH
        for percent in (None, 0, 9, 74, 100):
            row_width = (
                vector_text_width("5H", 2)
                + 4
                + vector_text_width(remaining_text(percent), 3)
                + 2
                + vector_text_width("%", 2)
            )
            self.assertLessEqual(row_width, available_width)

    def test_native_palette_is_slightly_dimmed(self):
        self.assertGreater(DISPLAY_BRIGHTNESS, 0.75)
        self.assertLess(DISPLAY_BRIGHTNESS, 1.0)

    def test_rgb565_primaries(self):
        self.assertEqual(rgb565(255, 0, 0), 0xF800)
        self.assertEqual(rgb565(0, 255, 0), 0x07E0)
        self.assertEqual(rgb565(0, 0, 255), 0x001F)

    def test_dashboard_size(self):
        snapshot = UsageSnapshot(26, 74, 1787210118, 10080, "plus")
        canvas = render_dashboard(snapshot, dt.datetime(2026, 8, 17, 12, 0))
        self.assertEqual((canvas.width, canvas.height), (WIDTH, HEIGHT))
        self.assertEqual(len(canvas.pixels), WIDTH * HEIGHT)

    def test_uniform_block_compression(self):
        pixels = [0x1234] * 128
        payload = encode_compressed_pixels(pixels)
        self.assertEqual(payload, bytes((2, 4, 0x12, 0x34, 0x12, 0x34, 2, 3, 8, 1, 0, 0)))

    def test_pattern_size(self):
        canvas = render_test_pattern()
        self.assertEqual(len(canvas.pixels), WIDTH * HEIGHT)

    def test_changed_pair_encoding(self):
        pixels = [0x0000] * 128
        pixels[4] = 0xF800
        pixels[5] = 0x07E0
        payload = encode_compressed_pixels(pixels)
        self.assertIn(bytes((4, 2, 0xF8, 0x00, 0x07, 0xE0)), payload)

    def test_raw_frame_packetization(self):
        pixels = [0x1234] * 128
        payload = encode_raw_pixels(pixels)
        self.assertEqual(len(payload), 390)
        self.assertEqual(payload[:6], bytes((4, 0, 0x12, 0x34, 0x12, 0x34)))
        self.assertEqual(payload[-6:], bytes((2, 3, 8, 1, 0, 0)))


class WhaleAndDeepSeekTests(unittest.TestCase):
    def test_whale_logo_bitmap(self):
        self.assertEqual(len(WHALE_LOGO), 30)
        self.assertTrue(all(len(row) == 40 for row in WHALE_LOGO))
        self.assertEqual(set("".join(WHALE_LOGO)), {" ", "L", "l", "W"})
        runs = whale_logo_runs()
        self.assertTrue(runs)
        self.assertGreaterEqual(min(x for x, _, _, _, _ in runs), 0)
        self.assertLessEqual(max(x + width for x, _, width, _, _ in runs), LOGO_RESERVED_WIDTH)
        self.assertGreaterEqual(min(y for _, y, _, _, _ in runs), 0)
        self.assertLessEqual(max(y + height for _, y, _, height, _ in runs), CONTENT_HEIGHT)
        self.assertEqual(WHALE_LOGO_WIDTH, 58)
        self.assertEqual(WHALE_LOGO_HEIGHT, 43)

    def test_deepseek_page_draws_whale_and_amounts(self):
        surface = CanvasSurface()
        dashboard = NativeDashboard(surface)
        dashboard.draw_page("deepseek", demo_snapshot(), demo_balance(), STATUS_OK)
        self.assertEqual(len(surface.canvas.pixels), 160 * 80)
        self.assertIn(DEEPSEEK_BLUE, surface.canvas.pixels)
        self.assertIn(0x0000, surface.canvas.pixels)

    def test_no_key_page_renders(self):
        surface = CanvasSurface()
        dashboard = NativeDashboard(surface)
        dashboard.draw_page("deepseek", None, None, STATUS_NO_KEY)
        self.assertEqual(len(surface.canvas.pixels), 160 * 80)

    def test_surface_batches_fill_commands(self):
        class FakeSerial:
            def __init__(self):
                self.writes = []
                self.drains = 0

            def write_all(self, data):
                self.writes.append(bytes(data))

            def read_until_quiet(self, timeout=0.5, quiet=0.04):
                self.drains += 1
                return b""

        class FakeDisplay:
            def __init__(self):
                self.serial = FakeSerial()

        display = FakeDisplay()
        surface = MSU2Surface(display, batch_size=2)
        surface.fill_region(1, 2, 3, 4, 0x1234)
        self.assertEqual(display.serial.writes, [])
        surface.fill_region(5, 6, 7, 8, 0x5678)
        self.assertEqual(len(display.serial.writes), 1)
        self.assertEqual(len(display.serial.writes[0]), 36)
        self.assertEqual(display.serial.writes[0][:18], bytes((2, 0, 0, 1, 0, 2, 2, 1, 0, 3, 0, 4, 2, 3, 11, 0x12, 0x34, 0)))
        surface.fill_region(9, 10, 11, 12, 0x9ABC)
        surface.flush()
        self.assertEqual(len(display.serial.writes), 2)
        self.assertEqual(len(display.serial.writes[1]), 18)

    def test_surface_reset_drops_pending_commands(self):
        class FakeSerial:
            def __init__(self):
                self.writes = []

            def write_all(self, data):
                self.writes.append(bytes(data))

            def read_until_quiet(self, timeout=0.5, quiet=0.04):
                return b""

        class FakeDisplay:
            def __init__(self):
                self.serial = FakeSerial()

        display = FakeDisplay()
        surface = MSU2Surface(display, batch_size=8)
        surface.fill_region(0, 0, 1, 1, 0)
        surface.reset()
        surface.flush()
        self.assertEqual(display.serial.writes, [])

    def test_surface_reconnects_after_silent_device(self):
        class SilentSerial:
            def __init__(self):
                self.writes = 0

            def write_all(self, data):
                self.writes += 1

            def read_until_quiet(self, timeout=0.5, quiet=0.04):
                return b""

        class FakeDisplay:
            def __init__(self):
                self.serial = SilentSerial()

        display = FakeDisplay()
        surface = MSU2Surface(display, batch_size=1)
        for _ in range(4):
            surface.fill_region(0, 0, 1, 1, 0)
            surface.flush()
        with self.assertRaises(RuntimeError):
            surface.fill_region(0, 0, 1, 1, 0)

    def test_surface_stays_connected_when_device_acks(self):
        class AckSerial:
            def write_all(self, data):
                pass

            def read_until_quiet(self, timeout=0.5, quiet=0.04):
                return bytes((2, 3, 11, 0, 0, 0))

        class FakeDisplay:
            def __init__(self):
                self.serial = AckSerial()

        surface = MSU2Surface(FakeDisplay(), batch_size=2)
        for _ in range(10):
            surface.fill_region(0, 0, 1, 1, 0)
            surface.flush()
        self.assertEqual(surface.silent_flushes, 0)

    def test_page_rotation_alternates(self):
        self.assertEqual(other_page("codex"), "deepseek")
        self.assertEqual(other_page("deepseek"), "codex")
        self.assertEqual(other_page(other_page("codex")), "codex")

    def test_deepseek_amounts_fit_beside_logo(self):
        surface = CanvasSurface()
        dashboard = NativeDashboard(surface)
        for value in ("0.00", "9.57", "99.99", "999.99", "9999.99", "123456.78"):
            _, _, width = dashboard._amount_layout(None, "¥", value, 3)
            self.assertLessEqual(width, CONTENT_WIDTH)
            _, _, width = dashboard._amount_layout("TOP", None, value, 2)
            self.assertLessEqual(width, CONTENT_WIDTH)

    def test_api_price_peak_and_valley_multiples(self):
        peak = current_api_price("pro", now=dt.datetime(2026, 10, 28, 2, tzinfo=dt.timezone.utc))
        valley = current_api_price("pro", now=dt.datetime(2026, 10, 28, 12, tzinfo=dt.timezone.utc))
        self.assertTrue(peak.is_peak)
        self.assertFalse(valley.is_peak)
        self.assertAlmostEqual(float(peak.multiple_of_average), 4 / 3, places=8)
        self.assertAlmostEqual(float(valley.multiple_of_average), 2 / 3, places=8)
        self.assertEqual(str(peak.price_per_million), "3.96")
        self.assertEqual(str(valley.price_per_million), "1.98")

    def test_parse_api_balance(self):
        balance = parse_api_balance({
            "is_available": True,
            "balance_infos": [
                {"currency": "USD", "total_balance": "1.00", "granted_balance": "0.00", "topped_up_balance": "1.00"},
                {"currency": "CNY", "total_balance": "110.00", "granted_balance": "10.00", "topped_up_balance": "100.00"},
            ],
        })
        self.assertEqual((balance.currency, str(balance.total)), ("CNY", "110.00"))
        self.assertEqual(format_money(balance.total), "110.00")
        self.assertTrue(balance.is_available)

    def test_parse_platform_balance_sums_wallets(self):
        balance = parse_platform_balance({
            "code": 0,
            "msg": "",
            "data": {
                "biz_code": 0,
                "biz_msg": "",
                "biz_data": {
                    "normal_wallets": [{"currency": "CNY", "balance": "3.6930024400000000"}],
                    "bonus_wallets": [{"currency": "CNY", "balance": "5.8749065200000000"}],
                },
            },
        })
        self.assertEqual(balance.currency, "CNY")
        self.assertEqual(format_money(balance.total), "9.57")
        self.assertEqual(format_money(balance.topped_up), "3.69")
        self.assertEqual(format_money(balance.granted), "5.87")

    def test_platform_error_raises(self):
        from deepseek_balance import DeepSeekError

        with self.assertRaises(DeepSeekError):
            parse_platform_balance({"code": 40003, "msg": "unauthorized"})
        with self.assertRaises(DeepSeekError):
            parse_platform_balance({"code": 0, "data": {"biz_code": 1, "biz_data": {}}})

    def test_format_money(self):
        self.assertEqual(format_money(None), "--")
        self.assertEqual(format_money(demo_balance().total), "9.57")
        self.assertEqual(format_money(demo_balance().granted), "5.87")

    def test_read_dsh_grant(self):
        document = """
version: 1
records:
  client-connection/browser-session:
    kind: grant
    payload:
      secret: abc
  deepseek-account-platform/default:
    kind: grant
    payload:
      version: 1
      token: tok+/en==
      issuer: https://platform.deepseek.com
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".credentials.yaml"
            path.write_text(document, encoding="utf-8")
            self.assertEqual(read_dsh_grant(path), ("tok+/en==", "https://platform.deepseek.com"))

    def test_read_dsh_grant_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(read_dsh_grant(Path(directory) / "missing.yaml"))

    def test_read_api_key_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api_key"
            path.write_text("# comment\n\nsk-test-123\n", encoding="utf-8")
            self.assertEqual(read_api_key_file(path), "sk-test-123")

    def test_discover_credential_prefers_explicit_key(self):
        credential = discover_credential("sk-explicit")
        self.assertEqual(credential.kind, "api_key")
        self.assertEqual(credential.secret, "sk-explicit")

    def test_discover_credential_uses_project_key_file(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / ".deepseek_api_key").write_text("sk-project\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "", "DSH_HOME": str(project)}):
                credential = discover_credential(project_dir=project)
                self.assertIsNotNone(credential)
                self.assertEqual(credential.kind, "api_key")
                self.assertEqual(credential.secret, "sk-project")


if __name__ == "__main__":
    unittest.main()
