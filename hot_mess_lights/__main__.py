import os

from nicegui import ui

from .app import build_ui


def main() -> None:
    build_ui()
    port = os.getenv("HML_PORT")
    ui.run(
        title="Hot Mess Lights",
        host=os.getenv("HML_HOST"),
        port=int(port) if port is not None else None,
        reload=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
