from collections.abc import Callable

from nicegui import ui

from .db import delete_color, load_palette, update_color
from .sequencer import OPTIONAL_CHANNELS, Swatch, rgb_to_hex
from .wheel import color_wheel


def _summary(swatch: Swatch) -> str:
    return " ".join(f"{name[0]}{value}" for name, value in swatch.optional.items() if value is not None)


def edit_swatch_dialog(swatch: Swatch, on_save: Callable[[Swatch], None]) -> None:
    """Dialog to edit a swatch's name, RGB color and optional White/Amber/UV/Dimmer values."""
    draft = Swatch(**vars(swatch))
    sliders: dict[str, tuple[ui.checkbox, ui.slider]] = {}

    def set_color(rgb) -> None:
        draft.color = rgb_to_hex(rgb)
        preview.style(replace=_preview_style(draft.color))

    def save() -> None:
        draft.name = name.value.strip()
        if not draft.name:
            ui.notify("Enter a name for the color", type="warning")
            return
        for channel, (enabled, slider) in sliders.items():
            setattr(draft, channel.lower(), int(slider.value) if enabled.value else None)
        dialog.close()
        on_save(draft)

    with ui.dialog() as dialog, ui.card().classes("w-96 items-stretch"):
        name = ui.input("Name", value=swatch.name).props("outlined dense")
        preview = ui.element("div").style(_preview_style(swatch.color))
        color_wheel(set_color, initial=_rgb(swatch.color))
        ui.label("Optional channels (unchecked = not set)").classes("text-sm")
        for channel in OPTIONAL_CHANNELS:
            current = swatch.optional[channel]
            with ui.row().classes("w-full items-center no-wrap"):
                enabled = ui.checkbox(channel, value=current is not None).classes("w-28")
                slider = ui.slider(min=0, max=255, value=current or 0).props("label").classes("grow")
                slider.bind_enabled_from(enabled, "value")
                sliders[channel] = (enabled, slider)
        with ui.row().classes("justify-end w-full"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Save", on_click=save)
    dialog.open()


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _preview_style(color: str) -> str:
    return f"height:32px;border-radius:6px;border:1px solid #666;background:{color}"


def palette_grid(on_changed: Callable[[], None]):
    """Grid of saved swatches with edit and delete buttons. Returns the refreshable grid."""

    def remove(slot: int) -> None:
        delete_color(slot)
        grid.refresh()
        on_changed()

    def edit(slot: int, swatch: Swatch) -> None:
        def save(updated: Swatch) -> None:
            update_color(slot, updated)
            grid.refresh()
            on_changed()
            ui.notify(f"Updated '{updated.name}'", type="positive")

        edit_swatch_dialog(swatch, save)

    @ui.refreshable
    def grid() -> None:
        palette = load_palette()
        if not palette:
            ui.label("No saved colors yet. Set a light's color, name it, and press Save color.")
            return
        with ui.row().classes("gap-3 justify-center"):
            for slot, swatch in palette.items():
                with ui.card().classes("items-center gap-1 p-2 w-32"):
                    ui.element("div").style(
                        f"width:72px;height:48px;border-radius:6px;border:1px solid #666;background:{swatch.color}"
                    )
                    ui.label(swatch.name).classes("text-sm truncate w-full text-center").tooltip(swatch.color)
                    ui.label(_summary(swatch) or "RGB").classes("text-xs opacity-60")
                    with ui.row().classes("gap-0"):
                        ui.button(icon="edit", on_click=lambda s=slot, sw=swatch: edit(s, sw)).props("flat dense size=sm")
                        ui.button(icon="delete", on_click=lambda s=slot: remove(s)).props("flat dense size=sm")

    grid()
    return grid
