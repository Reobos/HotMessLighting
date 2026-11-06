import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from hot_mess_lights import db
from hot_mess_lights.fixtures import Fixture
from hot_mess_lights.lights import Lights
from hot_mess_lights.sequencer_ui import SequencerTab


class StopTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patcher = patch.object(db, "DB_PATH", os.path.join(temporary.name, "test.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.lights = Lights()
        self.fixture = Fixture("Par", "RGBWAUS Par", 1)
        self.tab = SequencerTab(self.lights)
        self.tab.fixtures = [self.fixture]
        self.tab.row_colors = [[(0, 0, 0, 0, 0, 0, 0), (200, 100, 40, 80, 0, 0, 200)]]
        self.tab.steps = 2
        self.tab._last_tick = 10
        self.tab.playing = True
        self.tab.preview_els = [MagicMock()]
        self.tab.cell_els = {(0, 0): MagicMock(), (0, 1): MagicMock()}
        self.tab.play_button = MagicMock()
        self.tab.pause_button = MagicMock()
        self.tab.timer = MagicMock()

    def test_stop_preserves_previewed_fade_and_position(self):
        with patch("hot_mess_lights.sequencer_ui.time.monotonic", return_value=10.5):
            self.tab._tick()
        snapshot = self.lights.fixture_swatch(self.fixture, "current")
        self.tab.preview_els[0].style.reset_mock()
        self.tab.stop()
        self.assertEqual(self.lights.fixture_swatch(self.fixture, "current"), snapshot)
        self.assertEqual(self.tab.position, 0.5)
        self.assertFalse(self.tab.timer.active)
        self.assertFalse(self.tab.playing)
        self.assertFalse(self.tab.paused)
        self.tab.preview_els[0].style.assert_not_called()
        with patch("hot_mess_lights.sequencer_ui.time.monotonic", return_value=20):
            self.tab._tick()
        self.assertEqual(self.lights.fixture_swatch(self.fixture, "current"), snapshot)

    def test_stop_connected_and_paused_does_not_send_blackout(self):
        controller = MagicMock()
        self.lights._dmx = controller
        with patch("hot_mess_lights.sequencer_ui.time.monotonic", return_value=10.5):
            self.tab._tick()
        self.tab.toggle_pause()
        snapshot = self.lights.fixture_swatch(self.fixture, "current")
        controller.reset_mock()
        self.tab.preview_els[0].style.reset_mock()
        self.tab.stop()
        controller.clear_channels.assert_not_called()
        controller.submit.assert_not_called()
        self.tab.preview_els[0].style.assert_not_called()
        self.assertEqual(self.lights.fixture_swatch(self.fixture, "current"), snapshot)
        self.assertFalse(self.tab.timer.active)
        self.assertFalse(self.tab.paused)


if __name__ == "__main__":
    unittest.main()
