import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from hot_mess_lights import db
from hot_mess_lights.fixtures import Fixture
from hot_mess_lights.lights import Lights
from hot_mess_lights.playback import PlaybackController


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(db, "DB_PATH", os.path.join(self.tmp.name, "test.db"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_manual_snapshot_and_preset_round_trip(self):
        lights = Lights()
        first = Fixture("Wash", "RGB Wash", 1)
        second = Fixture("Par", "RGBWAUS Par", 4)
        lights.preview_channels({1: 17, 2: 80, 3: 120, 4: 5, 5: 10, 6: 15, 7: 20, 8: 25, 9: 30, 10: 0})

        swatches = {
            fixture.address: lights.fixture_swatch(fixture, f"Look - {fixture.name}")
            for fixture in (first, second)
        }
        self.assertEqual(swatches[1].levels(), (17, 80, 120, 0, 0, 0, 255))
        self.assertEqual(swatches[4].levels(), (5, 10, 15, 20, 25, 30, 0))
        db.add_color(swatches[4])
        db.capture_static_preset("Look", swatches)
        palette = db.load_palette()
        _, name, assignments = db.load_static_presets()[0]
        self.assertEqual(name, "Look")
        for fixture in (first, second):
            slot = assignments[fixture.address]
            self.assertIsNotNone(slot)
            self.assertEqual(fixture.levels(palette[slot].levels()), fixture.levels(swatches[fixture.address].levels()))
        self.assertEqual(sum(s.levels() == swatches[4].levels() for s in palette.values()), 1)

    def test_paused_fade_capture_uses_interpolated_preview(self):
        lights = Lights()
        fixture = Fixture("Par", "RGBWAUS Par", 1)
        tab = PlaybackController(lights)
        tab.fixtures = [fixture]
        tab.row_colors = [[(0, 0, 0, 0, 0, 0, 0), (200, 100, 40, 80, 0, 0, 200)]]
        tab.steps = 2
        tab.position = 0.0
        tab._last_tick = 10.0
        tab.playing = True
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10.5):
            tab.tick()
        tab.toggle_pause()
        snapshot = lights.fixture_swatch(fixture, "Paused")
        self.assertEqual(snapshot.levels(), (100, 50, 20, 40, 0, 0, 100))
        with patch("hot_mess_lights.playback.time.monotonic", return_value=50):
            tab.tick()
        self.assertEqual(lights.fixture_swatch(fixture, "Paused"), snapshot)

    def test_failed_output_does_not_change_tracked_state(self):
        lights = Lights()
        controller = MagicMock()
        lights._dmx = controller
        lights.preview_channels({1: 12})
        controller.set_channel.side_effect = OSError("port failed")
        with self.assertRaises(OSError):
            lights.set_channel(1, 200)
        self.assertEqual(lights.channel_value(1), 12)


if __name__ == "__main__":
    unittest.main()
