from DMXEnttecPro import Controller
from serial.tools import list_ports


def discover_ports() -> dict[str, str]:
    """Return {device: label} for attached USB serial devices (Enttec/FTDI first)."""
    usb = [p for p in list_ports.comports() if p.vid is not None]
    usb.sort(key=lambda p: p.vid != 0x0403)
    return {p.device: f"{p.device} - {p.manufacturer or ''} {p.description}".strip() for p in usb}


class Lights:
    """Thin wrapper around the Enttec DMX USB Pro controller."""

    def __init__(self) -> None:
        self._dmx: Controller | None = None

    @property
    def connected(self) -> bool:
        return self._dmx is not None

    def connect(self, port: str) -> None:
        self.disconnect()
        self._dmx = Controller(port, auto_submit=True)

    def disconnect(self) -> None:
        if self._dmx is not None:
            self._dmx.close()
            self._dmx = None

    def set_channel(self, channel: int, value: int) -> None:
        self._require().set_channel(channel, value)

    def set_channels(self, values: dict[int, int]) -> None:
        """Set many channels and send a single DMX frame."""
        dmx = self._require()
        for channel, value in values.items():
            dmx.set_channel(channel, value, submit_after=False)
        dmx.submit()

    def all_on(self) -> None:
        self._require().all_channels_on()

    def blackout(self) -> None:
        self._require().clear_channels()

    def _require(self) -> Controller:
        if self._dmx is None:
            raise RuntimeError("Not connected to a DMX interface")
        return self._dmx
