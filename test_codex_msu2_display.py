import datetime as dt
import unittest

from codex_msu2_native import reset_date_label

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
