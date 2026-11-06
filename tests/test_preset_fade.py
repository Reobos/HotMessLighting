import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from hot_mess_lights import db
from hot_mess_lights.fixtures import Fixture
from hot_mess_lights.lights import Lights
from hot_mess_lights.playback import PlaybackController


class PresetFadeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = patch.object(db, "DB_PATH", os.path.join(tmp.name, "test.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.lights = Lights()
        self.tab = PlaybackController(self.lights)
        self.fixture = Fixture("Par", "RGBWAUS Par", 1)
        self.tab.fixtures = [self.fixture]
        self.tab.palette = db.load_palette()
        self.red = next(slot for slot, swatch in self.tab.palette.items() if swatch.name == "Red")
        self.blue = next(slot for slot, swatch in self.tab.palette.items() if swatch.name == "Blue")
        self.red_preset = db.save_static_preset("Red", {1: self.red})
        self.blue_preset = db.save_static_preset("Blue", {1: self.blue})

    def test_fades_without_blackout_then_reaches_target(self):
        self.lights.preview_channels({1: 20, 2: 40, 3: 80, 4: 50, 5: 0, 6: 0, 7: 100})
        self.tab.playing = True
        self.tab.paused = True
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10):
            self.tab.apply_static_preset(self.red_preset)
        self.assertEqual(self.lights.channel_value(1), 20)
        self.assertFalse(self.tab.playing)
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10.5):
            self.tab.tick()
        self.assertEqual(
            tuple(self.lights.channel_value(i) for i in range(1, 8)),
            (138, 20, 40, 25, 0, 0, 178),
        )
        with patch("hot_mess_lights.playback.time.monotonic", return_value=11):
            self.tab.tick()
        self.assertEqual(tuple(self.lights.channel_value(i) for i in range(1, 8)), (255, 0, 0, 0, 0, 0, 255))
        self.assertIsNone(self.tab._fade_start)

    def test_new_preset_starts_from_current_fade_output(self):
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10):
            self.tab.apply_static_preset(self.red_preset)
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10.5):
            self.tab.tick()
            self.tab.apply_static_preset(self.blue_preset)
        self.assertEqual(self.lights.channel_value(1), 128)
        with patch("hot_mess_lights.playback.time.monotonic", return_value=11):
            self.tab.tick()
        self.assertEqual((self.lights.channel_value(1), self.lights.channel_value(3)), (64, 128))

    def test_manual_adjustment_cancels_fade(self):
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10):
            self.tab.apply_static_preset(self.red_preset)
        self.lights.preview_channels({1: 99})
        self.tab.manual_adjusted()
        with patch("hot_mess_lights.playback.time.monotonic", return_value=11):
            self.tab.tick()
        self.assertEqual(self.lights.channel_value(1), 99)
        self.assertIsNone(self.tab._fade_start)

    def test_output_failure_cancels_fade_without_updating_preview(self):
        controller = MagicMock()
        controller.set_channel.side_effect = OSError("disconnected")
        self.lights._dmx = controller
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10):
            self.tab.apply_static_preset(self.red_preset)
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10.5), self.assertLogs(
            "hot_mess_lights.playback", level="ERROR"
        ):
            self.tab.tick()
        self.assertEqual(self.tab.error, "disconnected")
        self.assertIsNone(self.tab._fade_start)
        self.assertIsNone(self.tab.static_preset_id)
        self.assertFalse(self.tab.playing)


if __name__ == "__main__":
    unittest.main()
