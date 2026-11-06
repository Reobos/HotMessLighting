from collections.abc import Callable

from nicegui import ui

from . import db
from .playback import TICK_SECONDS, PlaybackController
from .sequencer import rgb_to_hex

CELL = 44
LABEL_WIDTH = 140


def _box_style(color: str, outline: bool = False, size: int = CELL) -> str:
    return (
        f"width:{size}px;height:{size}px;flex:none;border-radius:6px;cursor:pointer;background:{color};"
        f"border:1px solid #666;outline:{'3px solid white' if outline else 'none'}"
    )


class SequencerTab:
    """Looping step sequencer: fixtures down the left, steps across, colors crossfade between steps."""

    def __init__(self, controller: PlaybackController, on_palette_changed: Callable[[], None] | None = None) -> None:
        self.controller = controller
        self.lights = controller.lights
        self.on_palette_changed = on_palette_changed
        self.brush: int | None = -1  # palette slot being painted; None paints "off"; -1 = pick first
        self._active_step: int | None = None
        self._revision = controller.revision
        self._error_revision = controller.error_revision
        self.cell_els: dict[tuple[int, int], ui.element] = {}
        self.brush_els: dict[int | None, ui.element] = {}
        self.preview_els: list[ui.element] = []

    def build(self) -> None:
        @ui.refreshable
        def editor() -> None:
            if self.brush is not None and self.brush not in self.palette:
                self.brush = next(iter(self.palette), None)
            self._build_brushes()
            with ui.row().classes("w-full items-start gap-4 flex-wrap"):
                with ui.column().classes("grow min-w-0"):
                    self._build_grid()
                with ui.column().classes("w-80 max-w-full"):
                    self._build_static_presets()

        self._editor_refresh = editor.refresh

        def refresh() -> None:
            self.controller.reload()
            self._revision = self.controller.revision
            self._editor_refresh()

        self.refresh = refresh

        with ui.row().classes("items-center gap-4"):
            self.play_button = ui.button("Play", icon="play_arrow", on_click=self.toggle)
            self.pause_button = ui.button("Pause", icon="pause", on_click=self.toggle_pause)
            self.steps_input = ui.number("Steps", value=self.steps, min=1, max=32, precision=0, on_change=self._set_steps).classes("w-24")
            self.seconds_input = ui.number(
                "Seconds per step", value=self.step_seconds, min=0.1, max=60, step=0.1, on_change=self._set_seconds
            ).classes("w-40")
        self.error_label = ui.label().classes("text-negative")
        editor()
        self._sync_view()
        ui.timer(TICK_SECONDS, self._sync_view)

    @property
    def steps(self):
        return self.controller.steps

    @property
    def step_seconds(self):
        return self.controller.step_seconds

    @property
    def fixtures(self):
        return self.controller.fixtures

    @property
    def palette(self):
        return self.controller.palette

    @property
    def cells(self):
        return self.controller.cells

    @property
    def row_colors(self):
        return self.controller.row_colors

    @property
    def playing(self):
        return self.controller.playing

    @property
    def paused(self):
        return self.controller.paused

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
        self.controller.reload()
        self._revision = self.controller.revision
        self.cell_els[(row, step)].style(replace=self._cell_style(row, step))

    def _set_steps(self, e) -> None:
        if e.value is None:
            return
        steps = max(1, min(32, int(e.value)))
        if steps == self.steps:
            return
        db.set_setting("steps", steps)
        self._active_step = None
        self.refresh()

    def _set_seconds(self, e) -> None:
        if e.value is None:
            return
        seconds = max(0.1, float(e.value))
        if seconds == self.step_seconds:
            return
        db.set_setting("step_seconds", seconds)
        self.controller.reload()

    def toggle(self) -> None:
        self.stop() if self.playing else self.start()

    def start(self) -> None:
        if not self.lights.connected:
            ui.notify(
                "Waiting for the DMX interface to reconnect" if self.controller.port
                else "Not connected to a DMX interface; previewing on screen only",
                type="info",
            )
        self.controller.start()
        self._sync_view()

    def stop(self) -> None:
        self.controller.stop()
        self._sync_view()

    def _capture_ready(self) -> bool:
        if self.playing and not self.paused:
            ui.notify("Pause the sequencer before capturing the current state", type="warning")
            return False
        if not self.fixtures:
            ui.notify("Add fixtures before capturing the current state", type="warning")
            return False
        return True

    def manual_adjusted(self) -> None:
        self.controller.manual_adjusted()

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
        if self.controller.static_preset_id == preset_id:
            self.stop()
        self.refresh()

    def apply_static_preset(self, preset_id: int) -> None:
        try:
            self.controller.apply_static_preset(preset_id)
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            self.refresh()
            return
        self._sync_view()

    def toggle_pause(self) -> None:
        self.controller.toggle_pause()
        self._sync_view()

    def _sync_view(self) -> None:
        if self._revision != self.controller.revision:
            self._revision = self.controller.revision
            self._active_step = None
            self._editor_refresh()
            self.steps_input.set_value(self.steps)
            self.seconds_input.set_value(self.step_seconds)
            return
        self.play_button.set_text("Stop" if self.playing else "Play")
        self.play_button.props("icon=stop" if self.playing else "icon=play_arrow")
        self.pause_button.set_enabled(self.playing)
        self.pause_button.set_text("Resume" if self.paused else "Pause")
        self.pause_button.props("icon=play_arrow" if self.paused else "icon=pause")
        self.error_label.set_text(self.controller.error or "")
        step = int(self.controller.position) if self.playing else None
        if step != self._active_step:
            previous, self._active_step = self._active_step, step
            self._restyle_column(previous)
            self._restyle_column(step)
        for row, fixture in enumerate(self.fixtures):
            self.preview_els[row].style(replace=_box_style(
                self.lights.fixture_swatch(fixture, fixture.name).color, size=CELL // 2
            ))
        if self._error_revision != self.controller.error_revision:
            self._error_revision = self.controller.error_revision
            if self.controller.error:
                ui.notify(self.controller.error, type="negative")
