from DMXEnttecPro import Controller
from serial.tools import list_ports

from .fixtures import Fixture
from .sequencer import CHANNEL_NAMES, Swatch, rgb_to_hex


def discover_ports() -> dict[str, str]:
    """Return {device: label} for attached USB serial devices (Enttec/FTDI first)."""
    usb = [p for p in list_ports.comports() if p.vid is not None]
    usb.sort(key=lambda p: p.vid != 0x0403)
    return {p.device: f"{p.device} - {p.manufacturer or ''} {p.description}".strip() for p in usb}


class Lights:
    """Thin wrapper around the Enttec DMX USB Pro controller."""

    def __init__(self) -> None:
        self._dmx: Controller | None = None
        self._levels: dict[int, int] = {}

    @property
    def connected(self) -> bool:
        return self._dmx is not None

    def connect(self, port: str) -> None:
        self.disconnect()
        self._dmx = Controller(port, auto_submit=True)
        self._levels.clear()

    def disconnect(self) -> None:
        if self._dmx is not None:
            self._dmx.close()
            self._dmx = None

    def set_channel(self, channel: int, value: int) -> None:
        self._require().set_channel(channel, value)
        self._levels[channel] = value

    def set_channels(self, values: dict[int, int]) -> None:
        """Set many channels and send a single DMX frame."""
        dmx = self._require()
        for channel, value in values.items():
            dmx.set_channel(channel, value, submit_after=False)
        dmx.submit()
        self._levels.update(values)

    def initialize_fixtures(self, fixtures: list[Fixture], *, force: bool = False) -> None:
        defaults = {
            fixture.address + fixture.channels.index("Dimmer"): 255
            for fixture in fixtures
            if "Dimmer" in fixture.channels
            and (force or fixture.address + fixture.channels.index("Dimmer") not in self._levels)
        }
        if self.connected and defaults:
            self.set_channels(defaults)
        elif not self.connected:
            self.preview_channels(defaults)

    def preview_channels(self, values: dict[int, int]) -> None:
        """Track the on-screen state when no DMX interface is connected."""
        self._levels.update(values)

    def channel_value(self, channel: int) -> int:
        return self._levels.get(channel, 0)

    def fixture_swatch(self, fixture: Fixture, name: str) -> Swatch:
        values = {channel: self.channel_value(fixture.address + i) for i, channel in enumerate(fixture.channels)}
        rgb = (values["Red"], values["Green"], values["Blue"])
        return Swatch(
            name,
            rgb_to_hex(rgb),
            *(values.get(channel) for channel in CHANNEL_NAMES[3:]),
        )

    def all_on(self) -> None:
        self._require().all_channels_on()
        self._levels = dict.fromkeys(range(1, 513), 255)

    def blackout(self) -> None:
        self._require().clear_channels()
        self.preview_blackout()

    def preview_blackout(self) -> None:
        self._levels = dict.fromkeys(range(1, 513), 0)

    def _require(self) -> Controller:
        if self._dmx is None:
            raise RuntimeError("Not connected to a DMX interface")
        return self._dmx
