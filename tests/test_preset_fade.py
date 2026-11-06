import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from hot_mess_lights import db
from hot_mess_lights.fixtures import Fixture
from hot_mess_lights.lights import Lights
from hot_mess_lights.sequencer_ui import SequencerTab


class PresetFadeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = patch.object(db, "DB_PATH", os.path.join(tmp.name, "test.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.lights = Lights()
        self.tab = SequencerTab(self.lights)
        self.fixture = Fixture("Par", "RGBWAUS Par", 1)
        self.tab.fixtures = [self.fixture]
        self.tab.palette = db.load_palette()
        self.red = next(slot for slot, swatch in self.tab.palette.items() if swatch.name == "Red")
        self.blue = next(slot for slot, swatch in self.tab.palette.items() if swatch.name == "Blue")
        self.red_preset = db.save_static_preset("Red", {1: self.red})
        self.blue_preset = db.save_static_preset("Blue", {1: self.blue})
        self.tab.timer = MagicMock()
        self.tab.play_button = MagicMock()
        self.tab.pause_button = MagicMock()
        self.tab.preview_els = [MagicMock()]
        self.tab.refresh = MagicMock()

    def test_fades_without_blackout_then_reaches_target(self):
        self.lights.preview_channels({1: 20, 2: 40, 3: 80, 4: 50, 5: 0, 6: 0, 7: 100})
        self.tab.playing = True
        self.tab.paused = True
        with patch("hot_mess_lights.sequencer_ui.time.monotonic", return_value=10):
            self.tab.apply_static_preset(self.red_preset)
        self.assertEqual(self.lights.channel_value(1), 20)
        self.assertFalse(self.tab.playing)
        with patch("hot_mess_lights.sequencer_ui.time.monotonic", return_value=10.5):
            self.tab._tick()
        self.assertEqual(
            tuple(self.lights.channel_value(i) for i in range(1, 8)),
            (138, 20, 40, 25, 0, 0, 178),
        )
        with patch("hot_mess_lights.sequencer_ui.time.monotonic", return_value=11):
            self.tab._tick()
        self.assertEqual(tuple(self.lights.channel_value(i) for i in range(1, 8)), (255, 0, 0, 0, 0, 0, 255))
        self.assertFalse(self.tab.timer.active)
        self.assertIsNone(self.tab._fade_start)

    def test_new_preset_starts_from_current_fade_output(self):
        with patch("hot_mess_lights.sequencer_ui.time.monotonic", return_value=10):
            self.tab.apply_static_preset(self.red_preset)
        with patch("hot_mess_lights.sequencer_ui.time.monotonic", return_value=10.5):
            self.tab._tick()
            self.tab.apply_static_preset(self.blue_preset)
        self.assertEqual(self.lights.channel_value(1), 128)
        with patch("hot_mess_lights.sequencer_ui.time.monotonic", return_value=11):
            self.tab._tick()
        self.assertEqual((self.lights.channel_value(1), self.lights.channel_value(3)), (64, 128))

    def test_manual_adjustment_cancels_fade(self):
        with patch("hot_mess_lights.sequencer_ui.time.monotonic", return_value=10):
            self.tab.apply_static_preset(self.red_preset)
        self.lights.preview_channels({1: 99})
        self.tab.manual_adjusted()
        with patch("hot_mess_lights.sequencer_ui.time.monotonic", return_value=11):
            self.tab._tick()
        self.assertEqual(self.lights.channel_value(1), 99)
        self.assertFalse(self.tab.timer.active)

    def test_output_failure_cancels_fade_without_updating_preview(self):
        controller = MagicMock()
        controller.set_channel.side_effect = OSError("disconnected")
        self.lights._dmx = controller
        with patch("hot_mess_lights.sequencer_ui.time.monotonic", return_value=10):
            self.tab.apply_static_preset(self.red_preset)
        with patch("hot_mess_lights.sequencer_ui.time.monotonic", return_value=10.5), patch(
            "hot_mess_lights.sequencer_ui.ui.notify"
        ) as notify:
            self.tab._tick()
        notify.assert_called_once()
        self.assertIsNone(self.tab._fade_start)
        self.assertIsNone(self.tab.static_preset_id)
        self.assertFalse(self.tab.timer.active)
        self.tab.preview_els[0].style.assert_not_called()


if __name__ == "__main__":
    unittest.main()
