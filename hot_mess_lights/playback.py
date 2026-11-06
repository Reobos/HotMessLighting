import logging
import time

from . import db
from .fixtures import Fixture
from .lights import Lights
from .sequencer import Levels, Swatch, color_at, lerp

TICK_SECONDS = 0.04
PRESET_FADE_SECONDS = 1.0
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
        self.reload()

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
        self.error = None
        self.static_preset_id = None
        self.static_levels = {}
        self._fade_start = None
        self._fade_from = {}
        self.playing = True
        self.paused = False
        self._last_tick = time.monotonic()

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

    def manual_adjusted(self) -> None:
        self.static_preset_id = None
        self.static_levels = {}
        self._fade_start = None
        self._fade_from = {}

    def apply_static_preset(self, preset_id: int) -> None:
        presets = {item[0]: item[2] for item in db.load_static_presets()}
        if preset_id not in presets:
            raise ValueError("Static preset no longer exists")
        self.stop()
        self.error = None
        self.static_preset_id = preset_id
        self.static_levels = self._preset_levels(presets[preset_id])
        self._fade_from = {
            fixture.address: self.lights.fixture_swatch(fixture, fixture.name).levels()
            for fixture in self.fixtures
        }
        self._fade_start = time.monotonic()

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
        except Exception as exc:
            logger.exception("Sequencer output failed")
            self.error = str(exc)
            self.error_revision += 1
            self.stop()
