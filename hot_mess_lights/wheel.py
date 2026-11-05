import colorsys
import math
from collections.abc import Callable

from nicegui import ui

RGB = tuple[int, int, int]


def color_wheel(on_change: Callable[[RGB], None], size: int = 160, initial: RGB = (255, 255, 255)) -> None:
    """Hue/saturation wheel plus a brightness slider; calls on_change(rgb) as the user picks."""
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in initial))
    state = {"h": h, "s": s}
    radius = size / 2

    def marker_pos(hue: float, sat: float) -> str:
        angle = 2 * math.pi * hue
        x = radius + sat * radius * math.cos(angle) - 6
        y = radius - sat * radius * math.sin(angle) - 6
        return f"left:{x}px;top:{y}px"

    def emit() -> None:
        r, g, b = colorsys.hsv_to_rgb(state["h"], state["s"], brightness.value / 255)
        on_change((round(r * 255), round(g * 255), round(b * 255)))

    def pick(e) -> None:
        if e.args.get("buttons") == 0 and e.args["type"] == "mousemove":
            return
        dx, dy = e.args["offsetX"] - radius, e.args["offsetY"] - radius
        # Matches the conic-gradient: red at 3 o'clock, hue increasing counter-clockwise.
        state["h"] = (math.atan2(-dy, dx) / (2 * math.pi)) % 1
        state["s"] = min(math.hypot(dx, dy), radius) / radius
        marker.style(marker_pos(state["h"], state["s"]))
        emit()

    wheel = (
        ui.element("div")
        .style(
            f"position:relative;width:{size}px;height:{size}px;border-radius:50%;cursor:crosshair;"
            "background:radial-gradient(circle,white,transparent 70%),"
            "conic-gradient(from 90deg,red,magenta,blue,cyan,lime,yellow,red);"
        )
        .classes("self-center")
    )
    with wheel:
        marker = ui.element("div").style(
            "position:absolute;width:12px;height:12px;border-radius:50%;pointer-events:none;"
            "border:2px solid black;box-shadow:0 0 0 1px white;" + marker_pos(h, s)
        )
    for event in ("mousedown", "mousemove"):
        wheel.on(event, pick, args=["type", "buttons", "offsetX", "offsetY"], throttle=0.05)
    with ui.row().classes("w-full items-center no-wrap"):
        ui.label("Bright").classes("w-14")
        brightness = ui.slider(min=0, max=255, value=round(v * 255)).props("label").classes("grow")
        brightness.on_value_change(emit)
