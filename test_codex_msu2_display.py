import datetime as dt
import unittest

from codex_msu2_native import (
    CODEX_LOGO_24,
    DISPLAY_BRIGHTNESS,
    LOGO_SIZE,
    LOGO_RESERVED_WIDTH,
    logo_runs,
    remaining_text,
    reset_time_label,
    scaled_logo_runs,
    vector_text_width,
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


if __name__ == "__main__":
    unittest.main()
