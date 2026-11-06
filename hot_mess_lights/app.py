import os
from datetime import datetime

from nicegui import app, ui

from .db import add_color, delete_cells, export_database, import_database, load_fixtures, save_fixtures
from .fixtures import PROFILES, Fixture, validate
from .lights import Lights, discover_ports
from .palette_ui import palette_grid
from .playback import TICK_SECONDS, PlaybackController
from .sequencer_ui import SequencerTab
from .wheel import color_wheel

lights = Lights()


def _safe(action, *args) -> bool:
    try:
        action(*args)
    except Exception as e:
        ui.notify(str(e), type="negative")
        return False
    return True


def build_ui() -> None:
    controller = PlaybackController(lights)

    def startup() -> None:
        controller.restore()
        app.timer(TICK_SECONDS, controller.tick)

    def shutdown() -> None:
        try:
            if not controller.recovery_failed:
                controller.checkpoint()
        finally:
            lights.disconnect()

    app.on_startup(startup)
    app.on_shutdown(shutdown)

    @ui.page("/")
    def index() -> None:
        ui.dark_mode().enable()
        sequencer = SequencerTab(controller, on_palette_changed=lambda: palette.refresh())
        _safe(lights.initialize_fixtures, load_fixtures())
        fixture_controls = {}
        syncing = False

        def scan() -> None:
            ports = discover_ports()
            port.set_options(ports)
            if port.value not in ports:
                port.set_value(controller.port or next(iter(ports), os.getenv("HML_DMX_PORT")))
            if not ports:
                ui.notify("No USB serial devices found", type="warning")

        def connect() -> None:
            if not port.value:
                ui.notify("Select a USB device first", type="warning")
                return
            if _safe(controller.connect, port.value):
                fixture_list.refresh()
                sequencer.refresh()
            status.set_text("Connected" if lights.connected else "Disconnected")

        def add_fixture() -> None:
            fixtures = load_fixtures()
            fixture = Fixture(name.value or "", fixture_type.value, int(address.value or 0))
            error = validate(fixture, fixtures)
            if error:
                ui.notify(error, type="negative")
                return
            fixtures.append(fixture)
            save_fixtures(fixtures)
            _safe(lambda: lights.initialize_fixtures([fixture], force=True))
            controller.checkpoint()
            name.set_value("")
            address.set_value(fixture.end + 1)
            fixture_list.refresh()
            sequencer.refresh()

        def remove_fixture(index: int) -> None:
            fixtures = load_fixtures()
            delete_cells(fixtures.pop(index).address)
            save_fixtures(fixtures)
            fixture_list.refresh()
            sequencer.refresh()

        def save_color(color_name, fixture) -> None:
            if sequencer.playing and not sequencer.paused:
                ui.notify("Pause the sequencer before capturing the current state", type="warning")
                return
            label = (color_name.value or "").strip()
            if not label:
                ui.notify("Enter a name for the color", type="warning")
                return
            add_color(lights.fixture_swatch(fixture, label))
            color_name.set_value("")
            palette.refresh()
            sequencer.refresh()
            ui.notify(f"Saved color '{label}'", type="positive")

        def set_channel(channel: int, value: int) -> None:
            if syncing:
                return
            if lights.connected:
                if not _safe(lights.set_channel, channel, value):
                    return
            else:
                lights.preview_channels({channel: value})
                ui.notify("Not connected to a DMX interface; previewing on screen only", type="info")
            sequencer.manual_adjusted()

        def set_all(action) -> None:
            if _safe(action):
                sequencer.manual_adjusted()

        def download_database() -> None:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            ui.download.content(export_database(), f"hot_mess_lights-{stamp}.db", "application/vnd.sqlite3")

        async def upload_database(e) -> None:
            uploader.reset()  # frees the single file slot so a failed upload can be retried
            try:
                import_database(await e.file.read())
            except ValueError as err:
                ui.notify(str(err), type="negative")
                return
            controller.stop()
            controller.reload()
            ui.notify("Database loaded", type="positive")
            ui.navigate.reload()

        def make_wheel(sliders, initial):
            @ui.refreshable
            def wheel(rgb) -> None:
                def drive_rgb(values) -> None:
                    for slider, value in zip(sliders[:3], values):
                        slider.set_value(value)

                color_wheel(drive_rgb, initial=rgb)

            wheel(initial)
            return wheel

        def sync_setup() -> None:
            nonlocal syncing
            syncing = True
            try:
                for address, (sliders, wheel) in fixture_controls.items():
                    values = [lights.channel_value(address + offset) for offset in range(len(sliders))]
                    for slider, value in zip(sliders, values):
                        slider.set_value(value)
                    wheel.refresh(tuple(values[:3]))
            finally:
                syncing = False
            ui.notify("Setup controls synced to current light output", type="positive")

        @ui.refreshable
        def fixture_list() -> None:
            fixture_controls.clear()
            with ui.row().classes("gap-4 justify-center"):
                for i, f in enumerate(load_fixtures()):
                    with ui.card().classes("w-96"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label(f"{f.name} ({f.type}, {f.address}-{f.end})").classes("font-bold")
                            ui.button(icon="delete", on_click=lambda i=i: remove_fixture(i)).props("flat dense")
                        sliders = []
                        for offset, channel in enumerate(f.channels):
                            with ui.row().classes("w-full items-center no-wrap"):
                                ui.label(channel).classes("w-14")
                                sliders.append(
                                    ui.slider(min=0, max=255, value=lights.channel_value(f.address + offset))
                                    .props("label")
                                    .classes("grow")
                                    .on_value_change(
                                        lambda e, ch=f.address + offset: set_channel(ch, int(e.value))
                                    )
                                )

                        rgb = tuple(lights.channel_value(f.address + offset) for offset in range(3))
                        wheel = make_wheel(sliders, rgb)
                        fixture_controls[f.address] = (sliders, wheel)
                        with ui.row().classes("w-full items-end no-wrap"):
                            color_name = ui.input("Color name").props("dense outlined").classes("grow")
                            ui.button(
                                "Save color", on_click=lambda n=color_name, fx=f: save_color(n, fx)
                            ).props("dense")

        with ui.column().classes("items-center gap-2 w-full px-4"):
            ui.label("Hot Mess Lights").classes("text-4xl font-bold")
        with ui.tabs().classes("w-full") as tabs:
            setup_tab = ui.tab("Setup")
            sequencer_tab = ui.tab("Sequencer")
        tabs.on_value_change(lambda e: fixture_list.refresh() if e.value in (setup_tab, "Setup") else None)
        with ui.tab_panels(tabs, value=setup_tab).classes("w-full"):
            with ui.tab_panel(setup_tab), ui.column().classes("items-center gap-4 w-full"):
                with ui.row().classes("items-center"):
                    port = ui.select({}, label="USB device", with_input=True, new_value_mode="add-unique").classes(
                        "w-96"
                    )
                    ui.button(icon="refresh", on_click=scan).props("flat").tooltip("Rescan USB devices")
                    ui.button("Connect", on_click=connect)
                    status = ui.label("Connected" if lights.connected else controller.error or "Disconnected")
                    ui.timer(0.5, lambda: status.set_text(
                        "Connected" if lights.connected else controller.error or "Disconnected"
                    ))
                with ui.row():
                    ui.button("All on", on_click=lambda: set_all(lights.all_on))
                    ui.button("Blackout", on_click=lambda: set_all(lights.blackout))
                    ui.button("Sync from sequencer", icon="sync", on_click=sync_setup)
                    ui.button("Capture current preset", icon="photo_camera", on_click=sequencer.capture_preset_dialog)

                ui.separator()
                ui.label("Add fixture").classes("text-xl")
                with ui.row().classes("items-end"):
                    name = ui.input("Name").props("outlined")
                    fixture_type = ui.select(list(PROFILES), value=next(iter(PROFILES)), label="Type")
                    address = ui.number("Start address", value=1, min=1, max=512, precision=0)
                    ui.button("Add", on_click=add_fixture)
                fixture_list()

                ui.separator()
                ui.label("Color palette").classes("text-xl")
                palette = palette_grid(on_changed=lambda: sequencer.refresh())
                scan()

                ui.separator()
                ui.label("Save / load database").classes("text-xl")
                ui.label("Download fixtures, colors and the sequence, or replace them by uploading a saved file.").classes(
                    "text-sm opacity-70"
                )
                with ui.row().classes("items-center gap-4"):
                    ui.button("Download database", icon="download", on_click=download_database)
                    uploader = ui.upload(
                        label="Upload database (replaces current)", auto_upload=True, max_files=1, on_upload=upload_database
                    ).props("accept=.db,.sqlite,.sqlite3")
            with ui.tab_panel(sequencer_tab):
                sequencer.build()
