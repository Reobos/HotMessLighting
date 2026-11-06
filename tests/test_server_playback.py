import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from hot_mess_lights import db
from hot_mess_lights.fixtures import Fixture
from hot_mess_lights.lights import Lights
from hot_mess_lights.playback import PlaybackController
from hot_mess_lights.sequencer_ui import SequencerTab


class ServerPlaybackTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        patcher = patch.object(db, "DB_PATH", os.path.join(temp.name, "test.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        db.save_fixtures([Fixture("Wash", "RGB Wash", 1)])
        palette = db.load_palette()
        self.red = next(slot for slot, swatch in palette.items() if swatch.name == "Red")
        self.blue = next(slot for slot, swatch in palette.items() if swatch.name == "Blue")
        db.set_cell(1, 0, self.red)
        db.set_cell(1, 1, self.blue)
        db.set_setting("steps", 2)
        self.lights = Lights()
        self.controller = PlaybackController(self.lights)

    def test_playback_continues_without_views_and_new_views_share_state(self):
        first = SequencerTab(self.controller)
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10):
            self.controller.start()
        del first
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10.5):
            self.controller.tick()
        self.assertEqual(self.lights.channel_value(1), 128)
        self.assertEqual(self.lights.channel_value(3), 128)
        second = SequencerTab(self.controller)
        self.assertTrue(second.playing)
        self.assertEqual(second.controller.position, 0.5)
        self.controller.toggle_pause()
        third = SequencerTab(self.controller)
        self.assertTrue(third.paused)
        with patch("hot_mess_lights.playback.time.monotonic", return_value=20):
            self.controller.tick()
        self.assertEqual(self.controller.position, 0.5)

    def test_static_fade_completes_without_views(self):
        preset = db.save_static_preset("Red", {1: self.red})
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10):
            self.controller.apply_static_preset(preset)
        with patch("hot_mess_lights.playback.time.monotonic", return_value=11):
            self.controller.tick()
        self.assertEqual(self.lights.channel_value(1), 255)
        self.assertIsNone(self.controller._fade_start)
        view = SequencerTab(self.controller)
        self.assertEqual(view.controller.static_preset_id, preset)
        self.assertEqual(self.lights.channel_value(1), 255)

    def test_connected_output_continues_after_view_is_discarded(self):
        interface = MagicMock()
        self.lights._dmx = interface
        view = SequencerTab(self.controller)
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10):
            self.controller.start()
        del view
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10.5):
            self.controller.tick()
        interface.set_channel.assert_any_call(1, 128, submit_after=False)
        interface.set_channel.assert_any_call(3, 128, submit_after=False)
        interface.submit.assert_called_once()
        interface.close.assert_not_called()
        self.assertTrue(self.lights.connected)


if __name__ == "__main__":
    unittest.main()
