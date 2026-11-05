from dataclasses import dataclass

RGB = tuple[int, int, int]
# Full lighting state in DMX channel-name order: R, G, B, White, Amber, UV, Dimmer.
Levels = tuple[int, ...]
CHANNEL_NAMES = ("Red", "Green", "Blue", "White", "Amber", "UV", "Dimmer")
OPTIONAL_CHANNELS = CHANNEL_NAMES[3:]


@dataclass
class Swatch:
    """A named color: RGB plus optional White/Amber/UV/Dimmer. None means "not set" (off; dimmer full)."""

    name: str
    color: str
    white: int | None = None
    amber: int | None = None
    uv: int | None = None
    dimmer: int | None = None

    @property
    def optional(self) -> dict[str, int | None]:
        return dict(zip(OPTIONAL_CHANNELS, (self.white, self.amber, self.uv, self.dimmer)))

    def levels(self) -> Levels:
        w, a, u, d = self.white, self.amber, self.uv, self.dimmer
        return (*hex_to_rgb(self.color), w or 0, a or 0, u or 0, 255 if d is None else d)


def hex_to_rgb(color: str) -> RGB:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def rgb_to_hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def lerp(a: Levels, b: Levels, t: float) -> Levels:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def color_at(colors: list[Levels], position: float) -> Levels:
    """Color at a fractional step position, crossfading from step i to step i+1 (wrapping to loop)."""
    n = len(colors)
    index = int(position) % n
    return lerp(colors[index], colors[(index + 1) % n], position - int(position))
