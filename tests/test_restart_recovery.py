import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from hot_mess_lights import db
from hot_mess_lights.fixtures import Fixture
from hot_mess_lights.lights import Lights
from hot_mess_lights.playback import PlaybackController


class RestartRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp_dir = temp.name
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
        self.interface = MagicMock()
        patcher = patch("hot_mess_lights.lights.Controller", return_value=self.interface)
        self.device = patcher.start()
        self.addCleanup(patcher.stop)

    def recover(self):
        lights = Lights()
        controller = PlaybackController(lights)
        controller.restore()
        return lights, controller

    def test_running_sequence_restores_connection_output_and_position(self):
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10):
            self.controller.connect("/dev/serial/by-id/test")
            self.controller.start()
        with patch("hot_mess_lights.playback.time.monotonic", return_value=11):
            self.controller.tick()
        self.lights.disconnect()
        with patch("hot_mess_lights.playback.time.monotonic", return_value=100):
            lights, controller = self.recover()
        self.assertTrue(lights.connected)
        self.assertTrue(controller.playing)
        self.assertEqual(controller.position, 1)
        self.assertEqual(lights.channel_value(3), 255)
        self.device.assert_called_with("/dev/serial/by-id/test", auto_submit=True)
        self.interface.set_channel.assert_any_call(3, 255, submit_after=False)
        with patch("hot_mess_lights.playback.time.monotonic", return_value=100.5):
            controller.tick()
        self.assertEqual(controller.position, 1.5)

    def test_paused_and_stopped_state_preserve_zero_output(self):
        self.controller.connect("/dev/test")
        self.controller.start()
        self.lights.set_channels({1: 0, 2: 12, 3: 0})
        self.controller.toggle_pause()
        lights, controller = self.recover()
        self.assertTrue(controller.playing)
        self.assertTrue(controller.paused)
        self.assertEqual(lights.snapshot(), {1: 0, 2: 12, 3: 0})
        controller.tick()
        self.assertEqual(lights.channel_value(2), 12)
        controller.stop()
        lights, controller = self.recover()
        self.assertFalse(controller.playing)
        self.assertFalse(controller.paused)
        self.assertEqual(lights.channel_value(2), 12)

    def test_blackout_and_manual_preview_are_saved(self):
        self.lights.preview_channels({1: 5, 2: 50})
        self.controller.manual_adjusted()
        lights, controller = self.recover()
        self.assertEqual(lights.channel_value(2), 50)
        lights.preview_blackout()
        controller.manual_adjusted()
        lights, controller = self.recover()
        self.assertFalse(controller.playing)
        self.assertEqual(lights.channel_value(1), 0)
        self.assertEqual(len(lights.snapshot()), 512)

    def test_missing_device_holds_position_and_retries(self):
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10):
            self.controller.connect("/dev/test")
            self.controller.start()
        with patch("hot_mess_lights.playback.time.monotonic", return_value=11):
            self.controller.tick()
        self.device.side_effect = [OSError("missing"), self.interface]
        with patch("hot_mess_lights.playback.time.monotonic", return_value=100):
            lights, controller = self.recover()
        self.assertFalse(lights.connected)
        self.assertIn("missing", controller.error)
        self.assertEqual(controller.position, 1)
        with patch("hot_mess_lights.playback.time.monotonic", return_value=104):
            controller.tick()
        self.assertFalse(lights.connected)
        self.assertEqual(controller.position, 1)
        with patch("hot_mess_lights.playback.time.monotonic", return_value=105):
            controller.tick()
        self.assertTrue(lights.connected)
        self.assertIsNone(controller.error)
        self.assertEqual(controller.position, 1)
        with patch("hot_mess_lights.playback.time.monotonic", return_value=105.5):
            controller.tick()
        self.assertEqual(controller.position, 1.5)

    def test_selecting_replacement_device_preserves_pending_output(self):
        self.controller.connect("/dev/old")
        self.lights.set_channels({1: 34, 2: 12, 3: 0})
        self.controller.checkpoint()
        self.device.side_effect = OSError("missing")
        lights, controller = self.recover()
        self.device.side_effect = None
        controller.connect("/dev/new")
        self.assertEqual(lights.snapshot(), {1: 34, 2: 12, 3: 0})
        self.assertEqual(controller.port, "/dev/new")
        self.assertIsNone(controller.error)

    def test_failed_initial_frame_is_retried_with_saved_levels(self):
        self.controller.connect("/dev/test")
        self.lights.set_channels({1: 34, 2: 12, 3: 0})
        self.controller.checkpoint()
        failed = MagicMock()
        failed.submit.side_effect = OSError("write failed")
        self.device.side_effect = [failed, self.interface]
        with patch("hot_mess_lights.playback.time.monotonic", return_value=100):
            lights, controller = self.recover()
        self.assertFalse(lights.connected)
        self.assertEqual(lights.channel_value(1), 34)
        with patch("hot_mess_lights.playback.time.monotonic", return_value=105):
            controller.tick()
        self.assertTrue(lights.connected)
        self.assertEqual(lights.channel_value(1), 34)

    def test_static_preset_fade_recovers(self):
        preset = db.save_static_preset("Red", {1: self.red})
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10):
            self.controller.apply_static_preset(preset)
        with patch("hot_mess_lights.playback.time.monotonic", return_value=10.5):
            self.controller.tick()
            self.controller.checkpoint()
        with patch("hot_mess_lights.playback.time.monotonic", return_value=20):
            lights, controller = self.recover()
        self.assertEqual(lights.channel_value(1), 128)
        with patch("hot_mess_lights.playback.time.monotonic", return_value=21):
            controller.tick()
        self.assertEqual(lights.channel_value(1), 255)
        self.assertEqual(controller.static_preset_id, preset)
        lights, controller = self.recover()
        self.assertEqual(lights.channel_value(1), 255)

    def test_backup_does_not_transfer_runtime_state(self):
        self.controller.connect("/dev/test")
        self.controller.start()
        data = db.export_database()
        self.controller.stop()
        current = db.load_runtime_state()
        db.import_database(data)
        self.assertEqual(db.load_runtime_state(), current)
        self.assertFalse(json.loads(db.load_runtime_state())["playing"])

    def test_invalid_saved_state_is_reported_without_connecting(self):
        db.save_runtime_state('{"port": "/dev/test"}')
        lights, controller = self.recover()
        self.assertFalse(lights.connected)
        self.assertIn("Cannot restore", controller.error)
        self.assertTrue(controller.recovery_failed)
        self.device.assert_not_called()

    def test_server_startup_recovers_and_ticks_without_a_browser(self):
        self.controller.connect("/dev/test")
        self.controller.start()
        marker = os.path.join(self.temp_dir, "submitted")
        script = """
import os
from nicegui import ui
import hot_mess_lights.lights as lights
from hot_mess_lights.app import build_ui

class Device:
    def __init__(self, port, auto_submit):
        assert port == '/dev/test'
    def set_channel(self, channel, value, submit_after=False):
        pass
    def submit(self):
        with open(os.environ['MARKER'], 'w') as f:
            f.write('submitted')
    def close(self):
        with open(os.environ['MARKER'] + '.closed', 'w') as f:
            f.write('closed')

lights.Controller = Device
build_ui()
ui.run(host='127.0.0.1', port=int(os.environ['HML_PORT']), show=False, reload=False)
"""
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, HML_DB=db.DB_PATH, HML_PORT=str(port), MARKER=marker)
        process = subprocess.Popen(
            [sys.executable, "-c", script], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and process.poll() is None:
                state = json.loads(db.load_runtime_state())
                if os.path.exists(marker) and state["position"] > 0:
                    break
                time.sleep(0.1)
            else:
                self.fail("Server failed to restore and checkpoint playback without a browser")
        finally:
            if process.poll() is None:
                process.terminate()
            output, _ = process.communicate(timeout=10)
        self.assertTrue(os.path.exists(marker + ".closed"), output)
        self.assertTrue(json.loads(db.load_runtime_state())["playing"])


if __name__ == "__main__":
    unittest.main()
