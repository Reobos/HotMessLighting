import json
import logging
import math
import time

from serial import SerialException

from . import db
from .fixtures import Fixture
from .lights import Lights
from .sequencer import Levels, Swatch, color_at, lerp

TICK_SECONDS = 0.04
PRESET_FADE_SECONDS = 1.0
CHECKPOINT_SECONDS = 1.0
RECONNECT_SECONDS = 5.0
OFF: Levels = (0, 0, 0, 0, 0, 0, 0)
logger = logging.getLogger(__name__)


class PlaybackController:
    """Application-owned playback state and DMX output, independent of browser clients."""

    def __init__(self, lights: Lights) -> None:
        self.lights = lights
        self.steps = int(db.get_setting("steps", 8))
        self.step_seconds = db.get_setting("step_seconds", 1.0)
        self.fixtures: list[Fixture] = []
        self.palette: dict[int, Swatch] = {}
        self.cells: dict[tuple[int, int], int] = {}
        self.row_colors: list[list[Levels]] = []
        self.playing = False
        self.paused = False
        self.position = 0.0
        self._last_tick = 0.0
        self.static_preset_id: int | None = None
        self.static_levels: dict[int, Levels] = {}
        self._fade_start: float | None = None
        self._fade_from: dict[int, Levels] = {}
        self.revision = 0
        self.error: str | None = None
        self.error_revision = 0
        self.recovery_failed = False
        self.port: str | None = None
        self._last_checkpoint = 0.0
        self._next_reconnect = 0.0
        self.reload()

    def checkpoint(self) -> None:
        state = {
            "port": self.port,
            "playing": self.playing,
            "paused": self.paused,
            "position": self.position,
            "static_preset_id": self.static_preset_id,
            "levels": self.lights.snapshot(),
        }
        db.save_runtime_state(json.dumps(state))
        self.recovery_failed = False
        self._last_checkpoint = time.monotonic()

    def restore(self) -> None:
        raw = db.load_runtime_state()
        if raw is None:
            self.lights.initialize_fixtures(self.fixtures)
            return
        try:
            state = json.loads(raw)
            port = state["port"]
            playing, paused = state["playing"], state["paused"]
            position, preset_id, levels = state["position"], state["static_preset_id"], state["levels"]
            if not isinstance(port, (str, type(None))) or (isinstance(port, str) and not port):
                raise ValueError("invalid DMX port")
            if type(playing) is not bool or type(paused) is not bool or (paused and not playing):
                raise ValueError("invalid playback state")
            if isinstance(position, bool) or not isinstance(position, (int, float)) or not math.isfinite(position):
                raise ValueError("invalid playback position")
            if preset_id is not None and (type(preset_id) is not int or preset_id < 1 or playing):
                raise ValueError("invalid static preset")
            if not isinstance(levels, dict):
                raise ValueError("invalid DMX levels")
            restored_levels = {}
            for key, value in levels.items():
                channel = int(key)
                if not 1 <= channel <= 512 or type(value) is not int or not 0 <= value <= 255:
                    raise ValueError("invalid DMX channel or level")
                restored_levels[channel] = value
            presets = {item[0]: item[2] for item in db.load_static_presets()}
            if preset_id is not None and preset_id not in presets:
                raise ValueError("saved static preset no longer exists")
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self.recovery_failed = True
            self._report_error(f"Cannot restore saved playback state: {exc}")
            return
        self.port = port
        self.playing, self.paused = playing, paused
        self.position = position % self.steps
        self.static_preset_id = preset_id
        self.lights.preview_channels(restored_levels)
        if preset_id is not None:
            self.static_levels = self._preset_levels(presets[preset_id])
            self._fade_from = {
                fixture.address: self.lights.fixture_swatch(fixture, fixture.name).levels()
                for fixture in self.fixtures
            }
            self._fade_start = time.monotonic()
        self._last_tick = time.monotonic()
        if self.port:
            self._reconnect()

    def connect(self, port: str) -> None:
        restoring = bool(self.port and not self.lights.connected)
        levels = self.lights.snapshot()
        try:
            self.lights.connect(port)
            if restoring and levels:
                self.lights.set_channels(levels)
            else:
                self.lights.initialize_fixtures(self.fixtures)
        except (OSError, SerialException):
            self.lights.disconnect()
            self.lights.preview_channels(levels)
            raise
        self.port = port
        self.error = None
        self._last_tick = time.monotonic()
        if restoring and self._fade_start is not None:
            self._fade_start = self._last_tick
        self.checkpoint()

    def _report_error(self, message: str) -> None:
        logger.error("%s", message)
        self.error = message
        self.error_revision += 1

    def _reconnect(self) -> None:
        if self.port is None:
            return
        levels = self.lights.snapshot()
        try:
            self.lights.connect(self.port)
            if levels:
                self.lights.set_channels(levels)
            else:
                self.lights.initialize_fixtures(self.fixtures)
        except (OSError, SerialException) as exc:
            self.lights.disconnect()
            self.lights.preview_channels(levels)
            self._next_reconnect = time.monotonic() + RECONNECT_SECONDS
            self._report_error(f"Cannot reconnect to {self.port}; retrying: {exc}")
            return
        self.error = None
        self._last_tick = time.monotonic()
        if self._fade_start is not None:
            self._fade_start = self._last_tick
        logger.info("Restored DMX connection to %s", self.port)

    def reload(self) -> None:
        self.fixtures = db.load_fixtures()
        self.palette = db.load_palette()
        self.cells = db.load_cells()
        self.steps = int(db.get_setting("steps", 8))
        self.step_seconds = db.get_setting("step_seconds", 1.0)
        self.position %= self.steps
        self.row_colors = [
            [self.palette[slot].levels() if (slot := self.cells.get((fixture.address, step))) in self.palette else OFF
             for step in range(self.steps)]
            for fixture in self.fixtures
        ]
        if self.static_preset_id is not None:
            presets = {item[0]: item[2] for item in db.load_static_presets()}
            if self.static_preset_id not in presets:
                self.manual_adjusted()
            else:
                self.static_levels = self._preset_levels(presets[self.static_preset_id])
                if self._fade_start is None:
                    self._output(self.static_levels)
        self.revision += 1

    def _preset_levels(self, colors: dict[int, int | None]) -> dict[int, Levels]:
        result = {}
        for fixture in self.fixtures:
            slot = colors.get(fixture.address)
            result[fixture.address] = self.palette[slot].levels() if slot in self.palette else OFF
        return result

    def start(self) -> None:
        if not self.port or self.lights.connected:
            self.error = None
        self.static_preset_id = None
        self.static_levels = {}
        self._fade_start = None
        self._fade_from = {}
        self.playing = True
        self.paused = False
        self._last_tick = time.monotonic()
        self.checkpoint()

    def stop(self) -> None:
        self.playing = False
        self.paused = False
        self.manual_adjusted()

    def toggle_pause(self) -> None:
        if not self.playing:
            return
        self.paused = not self.paused
        if not self.paused:
            self._last_tick = time.monotonic()
        self.checkpoint()

    def manual_adjusted(self) -> None:
        self.static_preset_id = None
        self.static_levels = {}
        self._fade_start = None
        self._fade_from = {}
        self.checkpoint()

    def apply_static_preset(self, preset_id: int) -> None:
        presets = {item[0]: item[2] for item in db.load_static_presets()}
        if preset_id not in presets:
            raise ValueError("Static preset no longer exists")
        self.stop()
        if not self.port or self.lights.connected:
            self.error = None
        self.static_preset_id = preset_id
        self.static_levels = self._preset_levels(presets[preset_id])
        self._fade_from = {
            fixture.address: self.lights.fixture_swatch(fixture, fixture.name).levels()
            for fixture in self.fixtures
        }
        self._fade_start = time.monotonic()
        self.checkpoint()

    def _output(self, levels: dict[int, Levels]) -> None:
        values: dict[int, int] = {}
        for fixture in self.fixtures:
            values.update(fixture.levels(levels.get(fixture.address, OFF)))
        if self.lights.connected and values:
            self.lights.set_channels(values)
        elif not self.lights.connected:
            self.lights.preview_channels(values)

    def tick(self) -> None:
        try:
            now = time.monotonic()
            if self.port and not self.lights.connected:
                if now >= self._next_reconnect:
                    self._reconnect()
                if not self.lights.connected:
                    return
                now = time.monotonic()
            fading = self._fade_start is not None
            if self._fade_start is not None:
                progress = max(0.0, min(1.0, (now - self._fade_start) / PRESET_FADE_SECONDS))
                levels = {
                    fixture.address: lerp(
                        self._fade_from.get(fixture.address, OFF), self.static_levels.get(fixture.address, OFF), progress
                    )
                    for fixture in self.fixtures
                }
                self._output(levels)
                if progress >= 1:
                    self._fade_start = None
                    self._fade_from = {}
            elif self.playing and not self.paused:
                self.position = (self.position + (now - self._last_tick) / self.step_seconds) % self.steps
                self._last_tick = now
                self._output({
                    fixture.address: color_at(self.row_colors[row], self.position)
                    for row, fixture in enumerate(self.fixtures)
                })
            if (self.playing and not self.paused or fading) and (
                now - self._last_checkpoint >= CHECKPOINT_SECONDS or fading and self._fade_start is None
            ):
                self.checkpoint()
        except Exception as exc:
            logger.exception("Sequencer output failed")
            self.error = str(exc)
            self.error_revision += 1
            self.stop()
