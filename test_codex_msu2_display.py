import datetime as dt
import unittest

from codex_msu2_native import (
    CODEX_LOGO_24,
    DISPLAY_BRIGHTNESS,
    LOGO_SCALE,
    LOGO_RESERVED_WIDTH,
    logo_runs,
    native_percent_text,
    percent_layout_changed,
    percent_start_x,
    reset_date_label,
)

from codex_msu2_display import (
    HEIGHT,
    WIDTH,
    UsageSnapshot,
    encode_compressed_pixels,
    encode_raw_pixels,
    render_dashboard,
    render_test_pattern,
    rgb565,
)


class DisplayTests(unittest.TestCase):
    def test_reset_date_label(self):
        snapshot = UsageSnapshot(40, 60, 1787210118, 10080, "plus")
        self.assertRegex(reset_date_label(snapshot), r"^RESET \d{2}-\d{2}$")

    def test_codex_logo_bitmap(self):
        self.assertEqual(len(CODEX_LOGO_24), 24)
        self.assertTrue(all(len(row) == 24 for row in CODEX_LOGO_24))
        self.assertEqual(set("".join(CODEX_LOGO_24)), {" ", "D", "L", "W"})
        self.assertTrue(logo_runs())
        self.assertEqual(LOGO_SCALE, 3)

    def test_percent_reserves_logo_area(self):
        self.assertEqual(percent_start_x("100%"), LOGO_RESERVED_WIDTH)
        self.assertEqual(percent_start_x("74%"), LOGO_RESERVED_WIDTH)
        self.assertEqual(percent_start_x("9%"), 80)
        self.assertEqual(native_percent_text("100%"), "100")
        self.assertFalse(percent_layout_changed("51%", "50%"))
        self.assertTrue(percent_layout_changed("10%", "9%"))

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
