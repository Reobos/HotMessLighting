import unittest
from unittest.mock import MagicMock

from hot_mess_lights.fixtures import Fixture
from hot_mess_lights.lights import Lights


class DimmerDefaultTests(unittest.TestCase):
    def setUp(self):
        self.lights = Lights()
        self.par = Fixture("Par", "RGBWAUS Par", 4)
        self.wash = Fixture("Wash", "RGB Wash", 1)

    def test_offline_initialization_and_explicit_zero(self):
        self.lights.initialize_fixtures([self.wash, self.par])
        self.assertEqual(self.lights.channel_value(10), 255)
        self.assertEqual(self.lights.channel_value(1), 0)
        self.lights.preview_channels({10: 0})
        self.lights.initialize_fixtures([self.par])
        self.assertEqual(self.lights.channel_value(10), 0)
        self.assertEqual(self.lights.fixture_swatch(self.par, "test").dimmer, 0)

    def test_blackout_stays_off_after_refresh(self):
        self.lights.initialize_fixtures([self.par])
        self.lights.preview_blackout()
        self.lights.initialize_fixtures([self.par])
        self.assertEqual(self.lights.channel_value(10), 0)
        self.lights.initialize_fixtures([self.par], force=True)
        self.assertEqual(self.lights.channel_value(10), 255)

    def test_connected_defaults_are_sent_and_recorded(self):
        controller = MagicMock()
        self.lights._dmx = controller
        self.lights.initialize_fixtures([self.wash, self.par])
        controller.set_channel.assert_called_once_with(10, 255, submit_after=False)
        controller.submit.assert_called_once_with()
        self.assertEqual(self.lights.channel_value(10), 255)

    def test_failed_output_does_not_record_default(self):
        controller = MagicMock()
        controller.submit.side_effect = OSError("port failed")
        self.lights._dmx = controller
        with self.assertRaises(OSError):
            self.lights.initialize_fixtures([self.par])
        self.assertEqual(self.lights.channel_value(10), 0)


if __name__ == "__main__":
    unittest.main()
