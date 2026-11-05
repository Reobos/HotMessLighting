import os
import sqlite3
from contextlib import closing

from .fixtures import Fixture
from .sequencer import Swatch

DB_PATH = os.getenv("HML_DB", "hot_mess_lights.db")

DEFAULT_PALETTE = [
    ("Red", "#ff0000"), ("Orange", "#ff7f00"), ("Yellow", "#ffff00"), ("Green", "#00ff00"),
    ("Cyan", "#00ffff"), ("Blue", "#0000ff"), ("Purple", "#8000ff"), ("Magenta", "#ff00ff"),
    ("White", "#ffffff"),
]  # fmt: skip


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS fixtures (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, address INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS palette (
            slot INTEGER PRIMARY KEY, color TEXT NOT NULL, name TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS sequence_cells (
            address INTEGER NOT NULL, step INTEGER NOT NULL, slot INTEGER NOT NULL, PRIMARY KEY (address, step));
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    if "name" not in {row[1] for row in conn.execute("PRAGMA table_info(palette)")}:
        conn.execute("ALTER TABLE palette ADD COLUMN name TEXT NOT NULL DEFAULT ''")
    for column in ("white", "amber", "uv", "dimmer"):
        if column not in {row[1] for row in conn.execute("PRAGMA table_info(palette)")}:
            conn.execute(f"ALTER TABLE palette ADD COLUMN {column} INTEGER")
    conn.execute("UPDATE palette SET name = 'Color ' || (slot + 1) WHERE name = ''")
    # Seed starter colors once, so deleting them later sticks.
    if not conn.execute("SELECT 1 FROM settings WHERE key = 'palette_seeded'").fetchone():
        if not conn.execute("SELECT 1 FROM palette").fetchone():
            conn.executemany("INSERT INTO palette (name, color) VALUES (?, ?)", DEFAULT_PALETTE)
        conn.execute("INSERT INTO settings VALUES ('palette_seeded', '1')")
    conn.commit()
    return conn


def load_fixtures() -> list[Fixture]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT name, type, address FROM fixtures ORDER BY id").fetchall()
    return [Fixture(*row) for row in rows]


def save_fixtures(fixtures: list[Fixture]) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM fixtures")
        conn.executemany(
            "INSERT INTO fixtures (name, type, address) VALUES (?, ?, ?)",
            [(f.name, f.type, f.address) for f in fixtures],
        )


_SWATCH_COLUMNS = "name, color, white, amber, uv, dimmer"


def load_palette() -> dict[int, Swatch]:
    with closing(_connect()) as conn:
        rows = conn.execute(f"SELECT slot, {_SWATCH_COLUMNS} FROM palette ORDER BY slot").fetchall()
    return {slot: Swatch(*rest) for slot, *rest in rows}


def add_color(swatch: Swatch) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            f"INSERT INTO palette ({_SWATCH_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
            (swatch.name, swatch.color, swatch.white, swatch.amber, swatch.uv, swatch.dimmer),
        )


def update_color(slot: int, swatch: Swatch) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE palette SET name = ?, color = ?, white = ?, amber = ?, uv = ?, dimmer = ? WHERE slot = ?",
            (swatch.name, swatch.color, swatch.white, swatch.amber, swatch.uv, swatch.dimmer, slot),
        )


def delete_color(slot: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM palette WHERE slot = ?", (slot,))
        conn.execute("DELETE FROM sequence_cells WHERE slot = ?", (slot,))


def load_cells() -> dict[tuple[int, int], int]:
    """Sequencer cells as {(fixture address, step): palette slot}."""
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT address, step, slot FROM sequence_cells").fetchall()
    return {(address, step): slot for address, step, slot in rows}


def set_cell(address: int, step: int, slot: int | None) -> None:
    with closing(_connect()) as conn, conn:
        if slot is None:
            conn.execute("DELETE FROM sequence_cells WHERE address = ? AND step = ?", (address, step))
        else:
            conn.execute("INSERT OR REPLACE INTO sequence_cells VALUES (?, ?, ?)", (address, step, slot))


def delete_cells(address: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM sequence_cells WHERE address = ?", (address,))


def get_setting(key: str, default: float) -> float:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return float(row[0]) if row else default


def set_setting(key: str, value: float) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))
