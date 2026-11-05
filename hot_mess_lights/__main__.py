from nicegui import ui

from .app import build_ui


def main() -> None:
    build_ui()
    ui.run(title="Hot Mess Lights", reload=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
