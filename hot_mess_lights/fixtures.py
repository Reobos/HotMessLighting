from dataclasses import dataclass

from .sequencer import CHANNEL_NAMES

# Channel layouts per fixture type, in DMX order from the start address.
# Adjust these to match your fixtures' DMX mode.
PROFILES: dict[str, list[str]] = {
    "RGB Wash": ["Red", "Green", "Blue"],
    "RGBWAUS Par": ["Red", "Green", "Blue", "White", "Amber", "UV", "Dimmer"],
}


@dataclass
class Fixture:
    name: str
    type: str
    address: int

    @property
    def channels(self) -> list[str]:
        return PROFILES[self.type]

    @property
    def end(self) -> int:
        return self.address + len(self.channels) - 1

    def levels(self, values: tuple[int, ...]) -> dict[int, int]:
        """DMX {channel: value} for a (R, G, B, White, Amber, UV, Dimmer) state; unused channels are skipped."""
        return {self.address + i: values[CHANNEL_NAMES.index(ch)] for i, ch in enumerate(self.channels)}


def validate(candidate: Fixture, existing: list[Fixture]) -> str | None:
    """Return an error message if the fixture can't be added, else None."""
    if not candidate.name.strip():
        return "Name is required"
    if candidate.address < 1 or candidate.end > 512:
        return f"Address range {candidate.address}-{candidate.end} is outside 1-512"
    for f in existing:
        if candidate.address <= f.end and f.address <= candidate.end:
            return f"Overlaps '{f.name}' ({f.address}-{f.end})"
    return None
