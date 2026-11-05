import time

from nicegui import ui

from . import db
from .lights import Lights
from .sequencer import Levels, Swatch, color_at, rgb_to_hex

CELL = 44
LABEL_WIDTH = 140
TICK_SECONDS = 0.04
OFF: Levels = (0, 0, 0, 0, 0, 0, 0)


def _box_style(color: str, outline: bool = False, size: int = CELL) -> str:
    return (
        f"width:{size}px;height:{size}px;flex:none;border-radius:6px;cursor:pointer;background:{color};"
        f"border:1px solid #666;outline:{'3px solid white' if outline else 'none'}"
    )


class SequencerTab:
    """Looping step sequencer: fixtures down the left, steps across, colors crossfade between steps."""

    def __init__(self, lights: Lights) -> None:
        self.lights = lights
        self.steps = int(db.get_setting("steps", 8))
        self.step_seconds = db.get_setting("step_seconds", 1.0)
        self.brush: int | None = -1  # palette slot being painted; None paints "off"; -1 = pick first
        self.playing = False
        self.position = 0.0
        self._last_tick = 0.0
        self._active_step: int | None = None
        self.fixtures = []
        self.palette: dict[int, Swatch] = {}
        self.cells: dict[tuple[int, int], int] = {}
        self.row_colors: list[list[Levels]] = []
        self.cell_els: dict[tuple[int, int], ui.element] = {}
        self.brush_els: dict[int | None, ui.element] = {}
        self.preview_els: list[ui.element] = []

    def build(self) -> None:
        @ui.refreshable
        def editor() -> None:
            self._load()
            self._build_brushes()
            self._build_grid()

        self.refresh = editor.refresh

        with ui.row().classes("items-center gap-4"):
            self.play_button = ui.button("Play", icon="play_arrow", on_click=self.toggle)
            ui.number("Steps", value=self.steps, min=1, max=32, precision=0, on_change=self._set_steps).classes("w-24")
            ui.number(
                "Seconds per step", value=self.step_seconds, min=0.1, max=60, step=0.1, on_change=self._set_seconds
            ).classes("w-40")
        editor()
        self.timer = ui.timer(TICK_SECONDS, self._tick, active=False)

    def _load(self) -> None:
        self.fixtures = db.load_fixtures()
        self.palette = db.load_palette()
        self.cells = db.load_cells()
        if self.brush is not None and self.brush not in self.palette:
            self.brush = next(iter(self.palette), None)
        self._compute_colors()

    def _compute_colors(self) -> None:
        self.row_colors = [[self._cell_color(f.address, s) for s in range(self.steps)] for f in self.fixtures]

    def _cell_color(self, address: int, step: int) -> Levels:
        slot = self.cells.get((address, step))
        return self.palette[slot].levels() if slot is not None else OFF

    def _build_brushes(self) -> None:
        self.brush_els = {}
        with ui.row().classes("items-center gap-1 no-wrap"):
            ui.label("Brush").classes("mr-2")
            for slot, swatch in self.palette.items():
                self.brush_els[slot] = ui.element("div").on("click", lambda s=slot: self._select_brush(s))
                self.brush_els[slot].style(_box_style(swatch.color, slot == self.brush, 28)).tooltip(swatch.name)
            off = ui.element("div").on("click", lambda: self._select_brush(None)).tooltip("Off")
            off.style(_box_style("#000000", self.brush is None, 28))
            self.brush_els[None] = off

    def _select_brush(self, slot: int | None) -> None:
        self.brush = slot
        for key, el in self.brush_els.items():
            color = self.palette[key].color if key is not None else "#000000"
            el.style(replace=_box_style(color, key == slot, 28))

    def _build_grid(self) -> None:
        self.cell_els = {}
        self.preview_els = []
        if not self.fixtures:
            ui.label("Add fixtures on the Setup tab to sequence them.")
            return
        with ui.element("div").classes("overflow-x-auto w-full"), ui.column().classes("gap-1 py-2"):
            with ui.row().classes("no-wrap gap-1 items-center"):
                ui.element("div").style(f"width:{LABEL_WIDTH + CELL // 2 + 8}px;flex:none")
                for step in range(self.steps):
                    ui.label(str(step + 1)).classes("text-center text-xs").style(f"width:{CELL}px;flex:none")
            for row, fixture in enumerate(self.fixtures):
                with ui.row().classes("no-wrap gap-1 items-center"):
                    ui.label(fixture.name).classes("truncate").style(f"width:{LABEL_WIDTH}px;flex:none")
                    self.preview_els.append(ui.element("div").style(_box_style("#000000", size=CELL // 2)))
                    for step in range(self.steps):
                        el = ui.element("div").on("click", lambda r=row, s=step: self._paint(r, s))
                        self.cell_els[(row, step)] = el.style(self._cell_style(row, step))

    def _cell_style(self, row: int, step: int) -> str:
        active = self.playing and step == self._active_step
        return _box_style(rgb_to_hex(self.row_colors[row][step][:3]), active)

    def _restyle_column(self, step: int | None) -> None:
        if step is None:
            return
        for row in range(len(self.fixtures)):
            self.cell_els[(row, step)].style(replace=self._cell_style(row, step))

    def _paint(self, row: int, step: int) -> None:
        address = self.fixtures[row].address
        db.set_cell(address, step, self.brush)
        if self.brush is None:
            self.cells.pop((address, step), None)
        else:
            self.cells[(address, step)] = self.brush
        self.row_colors[row][step] = self._cell_color(address, step)
        self.cell_els[(row, step)].style(replace=self._cell_style(row, step))

    def _set_steps(self, e) -> None:
        if e.value is None:
            return
        self.steps = max(1, min(32, int(e.value)))
        db.set_setting("steps", self.steps)
        self.position %= self.steps
        self._active_step = None
        self.refresh()

    def _set_seconds(self, e) -> None:
        if e.value is None:
            return
        self.step_seconds = max(0.1, float(e.value))
        db.set_setting("step_seconds", self.step_seconds)

    def toggle(self) -> None:
        self.stop() if self.playing else self.start()

    def start(self) -> None:
        if not self.lights.connected:
            ui.notify("Not connected to a DMX interface; previewing on screen only", type="info")
        self.playing = True
        self._last_tick = time.monotonic()
        self.timer.active = True
        self.play_button.set_text("Stop")
        self.play_button.props("icon=stop")

    def stop(self) -> None:
        self.timer.active = False
        self.playing = False
        self.play_button.set_text("Play")
        self.play_button.props("icon=play_arrow")
        previous, self._active_step = self._active_step, None
        self._restyle_column(previous)
        for el in self.preview_els:
            el.style(replace=_box_style("#000000", size=CELL // 2))
        if self.lights.connected:
            self._send(self.lights.blackout)

    def _tick(self) -> None:
        now = time.monotonic()
        self.position = (self.position + (now - self._last_tick) / self.step_seconds) % self.steps
        self._last_tick = now
        step = int(self.position)
        if step != self._active_step:
            previous, self._active_step = self._active_step, step
            self._restyle_column(previous)
            self._restyle_column(step)

        values: dict[int, int] = {}
        for row, fixture in enumerate(self.fixtures):
            levels = color_at(self.row_colors[row], self.position)
            self.preview_els[row].style(replace=_box_style(rgb_to_hex(levels[:3]), size=CELL // 2))
            values.update(fixture.levels(levels))
        if self.lights.connected and values:
            self._send(self.lights.set_channels, values)

    def _send(self, action, *args) -> None:
        try:
            action(*args)
        except Exception as e:
            ui.notify(str(e), type="negative")
            self.timer.active = False
