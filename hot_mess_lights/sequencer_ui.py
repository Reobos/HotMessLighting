import time
from collections.abc import Callable

from nicegui import ui

from . import db
from .lights import Lights
from .sequencer import Levels, Swatch, color_at, lerp, rgb_to_hex

CELL = 44
LABEL_WIDTH = 140
TICK_SECONDS = 0.04
PRESET_FADE_SECONDS = 1.0
OFF: Levels = (0, 0, 0, 0, 0, 0, 0)


def _box_style(color: str, outline: bool = False, size: int = CELL) -> str:
    return (
        f"width:{size}px;height:{size}px;flex:none;border-radius:6px;cursor:pointer;background:{color};"
        f"border:1px solid #666;outline:{'3px solid white' if outline else 'none'}"
    )


class SequencerTab:
    """Looping step sequencer: fixtures down the left, steps across, colors crossfade between steps."""

    def __init__(self, lights: Lights, on_palette_changed: Callable[[], None] | None = None) -> None:
        self.lights = lights
        self.on_palette_changed = on_palette_changed
        self.steps = int(db.get_setting("steps", 8))
        self.step_seconds = db.get_setting("step_seconds", 1.0)
        self.brush: int | None = -1  # palette slot being painted; None paints "off"; -1 = pick first
        self.playing = False
        self.paused = False
        self.static_preset_id: int | None = None
        self.static_levels: dict[int, Levels] = {}
        self._fade_start: float | None = None
        self._fade_from: dict[int, Levels] = {}
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
            with ui.row().classes("w-full items-start gap-4 flex-wrap"):
                with ui.column().classes("grow min-w-0"):
                    self._build_grid()
                with ui.column().classes("w-80 max-w-full"):
                    self._build_static_presets()

        self.refresh = editor.refresh

        with ui.row().classes("items-center gap-4"):
            self.play_button = ui.button("Play", icon="play_arrow", on_click=self.toggle)
            self.pause_button = ui.button("Pause", icon="pause", on_click=self.toggle_pause).disable()
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
        if self.static_preset_id is not None:
            presets = {item[0]: item for item in db.load_static_presets()}
            if self.static_preset_id in presets:
                colors = presets[self.static_preset_id][2]
                self.static_levels = {
                    fixture.address: self.palette[slot].levels() if slot in self.palette else OFF
                    for fixture in self.fixtures
                    for slot in [colors.get(fixture.address)]
                }
            else:
                self.static_preset_id = None
                self.static_levels = {}
                if self._fade_start is not None:
                    self.timer.active = False
                self._fade_start = None
                self._fade_from = {}
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

    def _build_static_presets(self) -> None:
        with ui.column().classes("w-full items-stretch gap-2"):
            ui.label("Static presets").classes("text-lg font-bold")
            ui.button("New preset", icon="add", on_click=lambda: self.edit_static_preset()).props("dense")
            ui.button("Capture current preset", icon="photo_camera", on_click=self.capture_preset_dialog).props("dense")
            ui.button("Capture current swatch", icon="palette", on_click=self.capture_swatch_dialog).props("dense")
            for preset_id, name, colors in db.load_static_presets():
                with ui.row().classes("w-full items-center gap-1 no-wrap"):
                    ui.button(name, icon="light_mode", on_click=lambda p=preset_id: self.apply_static_preset(p)).classes(
                        "grow min-w-0"
                    )
                    ui.button(icon="edit", on_click=lambda p=(preset_id, name, colors): self.edit_static_preset(*p)).props(
                        "flat dense"
                    ).tooltip("Edit preset")
                    ui.button(icon="delete", on_click=lambda p=preset_id: self.delete_static_preset(p)).props(
                        "flat dense"
                    ).tooltip("Delete preset")

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
                    preview_color = self.lights.fixture_swatch(fixture, fixture.name).color
                    self.preview_els.append(ui.element("div").style(_box_style(preview_color, size=CELL // 2)))
                    for step in range(self.steps):
                        el = ui.element("div").on("click", lambda r=row, s=step: self._paint(r, s))
                        self.cell_els[(row, step)] = el.style(self._cell_style(row, step))
        if self.static_preset_id is not None and self._fade_start is None:
            self._send_static_levels()

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
        self.static_preset_id = None
        self.static_levels = {}
        self._fade_start = None
        self._fade_from = {}
        self.playing = True
        self.paused = False
        self._last_tick = time.monotonic()
        self.timer.active = True
        self.play_button.set_text("Stop")
        self.play_button.props("icon=stop")
        self.pause_button.enable()
        self.pause_button.set_text("Pause")
        self.pause_button.props("icon=pause")

    def stop(self) -> None:
        self._stop_playback()

    def _stop_playback(self) -> None:
        self.timer.active = False
        self.playing = False
        self.paused = False
        self.static_preset_id = None
        self.static_levels = {}
        self._fade_start = None
        self._fade_from = {}
        self.play_button.set_text("Play")
        self.play_button.props("icon=play_arrow")
        self.pause_button.disable()
        self.pause_button.set_text("Pause")
        self.pause_button.props("icon=pause")
        previous, self._active_step = self._active_step, None
        self._restyle_column(previous)

    def _capture_ready(self) -> bool:
        if self.playing and not self.paused:
            ui.notify("Pause the sequencer before capturing the current state", type="warning")
            return False
        if not self.fixtures:
            ui.notify("Add fixtures before capturing the current state", type="warning")
            return False
        return True

    def manual_adjusted(self) -> None:
        if self._fade_start is not None:
            self.timer.active = False
            self._fade_start = None
            self._fade_from = {}
        self.static_preset_id = None
        self.static_levels = {}

    def _palette_changed(self) -> None:
        if self.on_palette_changed is not None:
            self.on_palette_changed()
        self.refresh()

    def capture_preset_dialog(self) -> None:
        if not self._capture_ready():
            return
        captured = {fixture.address: self.lights.fixture_swatch(fixture, fixture.name) for fixture in self.fixtures}
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            name_input = ui.input("Preset name").props("outlined").classes("w-full")
            ui.label("Save the current output for every fixture.").classes("text-sm")

            def save() -> None:
                name = (name_input.value or "").strip()
                if not name:
                    ui.notify("Enter a name for the preset", type="warning")
                    return
                for swatch in captured.values():
                    swatch.name = f"{name} - {swatch.name}"
                db.capture_static_preset(name, captured)
                dialog.close()
                self._palette_changed()
                ui.notify(f"Saved preset '{name}'", type="positive")

            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=dialog.close).props("flat")
                ui.button("Save", on_click=save)
        dialog.open()

    def capture_swatch_dialog(self) -> None:
        if not self._capture_ready():
            return
        captured = {fixture.address: self.lights.fixture_swatch(fixture, fixture.name) for fixture in self.fixtures}
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            fixture_input = ui.select(
                {fixture.address: fixture.name for fixture in self.fixtures},
                value=self.fixtures[0].address,
                label="Fixture",
            ).props("outlined").classes("w-full")
            name_input = ui.input("Color name").props("outlined").classes("w-full")

            def save() -> None:
                name = (name_input.value or "").strip()
                if not name:
                    ui.notify("Enter a name for the color", type="warning")
                    return
                swatch = captured[fixture_input.value]
                swatch.name = name
                db.add_color(swatch)
                dialog.close()
                self._palette_changed()
                ui.notify(f"Saved color '{name}'", type="positive")

            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=dialog.close).props("flat")
                ui.button("Save", on_click=save)
        dialog.open()

    def edit_static_preset(
        self,
        preset_id: int | None = None,
        preset_name: str = "",
        colors: dict[int, int | None] | None = None,
    ) -> None:
        colors = colors or {}
        assignments = {
            fixture.address: colors.get(fixture.address)
            if colors.get(fixture.address) in self.palette
            else None
            for fixture in self.fixtures
        }
        choices: dict[int, dict[int | None, ui.element]] = {}
        with ui.dialog() as dialog, ui.card().classes("w-[48rem] max-w-[90vw]"):
            name_input = ui.input("Preset name", value=preset_name).props("outlined").classes("w-full")
            ui.label("Choose a color for each fixture (hover over a swatch to see its name and color).").classes(
                "font-bold"
            )
            with ui.column().classes("w-full gap-2"):
                for fixture in self.fixtures:
                    with ui.row().classes("w-full items-center gap-3 no-wrap"):
                        ui.label(fixture.name).classes("w-32 shrink-0 truncate").tooltip(fixture.name)
                        with ui.row().classes("items-center gap-2"):
                            choices[fixture.address] = {}
                            for slot, color, label in [
                                (None, "#000000", "Off"),
                                *((key, swatch.color, f"{swatch.name} ({swatch.color})") for key, swatch in self.palette.items()),
                            ]:
                                swatch = ui.element("div").on(
                                    "click", lambda address=fixture.address, selected=slot: select(address, selected)
                                )
                                if slot is None:
                                    with swatch:
                                        ui.icon("block").classes("text-white")
                                swatch.style(_box_style(color, assignments[fixture.address] == slot, 28)).tooltip(label)
                                choices[fixture.address][slot] = swatch

            def select(address: int, slot: int | None) -> None:
                assignments[address] = slot
                for choice, element in choices[address].items():
                    color = self.palette[choice].color if choice is not None else "#000000"
                    element.style(replace=_box_style(color, choice == slot, 28))

            def save() -> None:
                label = (name_input.value or "").strip()
                if not label:
                    ui.notify("Enter a name for the preset", type="warning")
                    return
                db.save_static_preset(label, assignments, preset_id)
                dialog.close()
                self.refresh()
                ui.notify(f"Saved preset '{label}'", type="positive")

            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=dialog.close).props("flat")
                ui.button("Save", on_click=save)
        dialog.open()

    def delete_static_preset(self, preset_id: int) -> None:
        db.delete_static_preset(preset_id)
        if self.static_preset_id == preset_id:
            self.stop()
        self.refresh()

    def apply_static_preset(self, preset_id: int) -> None:
        presets = {item[0]: item for item in db.load_static_presets()}
        if preset_id not in presets:
            ui.notify("Static preset no longer exists", type="negative")
            self.refresh()
            return
        _, _, colors = presets[preset_id]
        self._stop_playback()
        self.static_preset_id = preset_id
        self.static_levels = {}
        self._fade_from = {}
        for fixture in self.fixtures:
            slot = colors.get(fixture.address)
            self.static_levels[fixture.address] = self.palette[slot].levels() if slot in self.palette else OFF
            self._fade_from[fixture.address] = self.lights.fixture_swatch(fixture, fixture.name).levels()
        self._fade_start = time.monotonic()
        self.timer.active = True

    def _send_static_levels(self, levels: dict[int, Levels] | None = None) -> bool:
        values: dict[int, int] = {}
        for fixture in self.fixtures:
            values.update(fixture.levels((self.static_levels if levels is None else levels).get(fixture.address, OFF)))
        if self.lights.connected and values:
            return self._send(self.lights.set_channels, values)
        elif not self.lights.connected:
            self.lights.preview_channels(values)
        return True

    def toggle_pause(self) -> None:
        if not self.playing:
            return
        self.paused = not self.paused
        self.pause_button.set_text("Resume" if self.paused else "Pause")
        self.pause_button.props("icon=play_arrow" if self.paused else "icon=pause")
        if self.paused:
            self.timer.active = False
        else:
            self._last_tick = time.monotonic()
            self.timer.active = True

    def _tick(self) -> None:
        if self._fade_start is not None:
            self._tick_fade()
            return
        if not self.playing or self.paused:
            return
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
        elif not self.lights.connected:
            self.lights.preview_channels(values)

    def _tick_fade(self) -> None:
        if self._fade_start is None:
            return
        progress = max(0.0, min(1.0, (time.monotonic() - self._fade_start) / PRESET_FADE_SECONDS))
        levels = {
            fixture.address: lerp(
                self._fade_from.get(fixture.address, OFF), self.static_levels.get(fixture.address, OFF), progress
            )
            for fixture in self.fixtures
        }
        if not self._send_static_levels(levels):
            self._fade_start = None
            self._fade_from = {}
            self.static_preset_id = None
            self.static_levels = {}
            return
        for row, fixture in enumerate(self.fixtures):
            self.preview_els[row].style(replace=_box_style(rgb_to_hex(levels[fixture.address][:3]), size=CELL // 2))
        if progress >= 1:
            self._fade_start = None
            self._fade_from = {}
            self.timer.active = False

    def _send(self, action, *args) -> bool:
        try:
            action(*args)
        except Exception as e:
            ui.notify(str(e), type="negative")
            self.timer.active = False
            return False
        return True
