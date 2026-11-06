import os
import sqlite3
import tempfile
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
        CREATE TABLE IF NOT EXISTS static_presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS static_preset_colors (
            preset_id INTEGER NOT NULL, address INTEGER NOT NULL, slot INTEGER,
            PRIMARY KEY (preset_id, address));
        CREATE TABLE IF NOT EXISTS runtime_state (
            id INTEGER PRIMARY KEY CHECK (id = 1), state TEXT NOT NULL);
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
        conn.execute("UPDATE static_preset_colors SET slot = NULL WHERE slot = ?", (slot,))


def load_static_presets() -> list[tuple[int, str, dict[int, int | None]]]:
    with closing(_connect()) as conn:
        presets = conn.execute("SELECT id, name FROM static_presets ORDER BY id").fetchall()
        colors = conn.execute("SELECT preset_id, address, slot FROM static_preset_colors").fetchall()
    colors_by_preset: dict[int, dict[int, int | None]] = {}
    for preset_id, address, slot in colors:
        colors_by_preset.setdefault(preset_id, {})[address] = slot
    return [(preset_id, name, colors_by_preset.get(preset_id, {})) for preset_id, name in presets]


def save_static_preset(name: str, colors: dict[int, int | None], preset_id: int | None = None) -> int:
    with closing(_connect()) as conn, conn:
        if preset_id is None:
            cursor = conn.execute("INSERT INTO static_presets (name) VALUES (?)", (name,))
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return an ID for the saved static preset")
            preset_id = cursor.lastrowid
        else:
            cursor = conn.execute("UPDATE static_presets SET name = ? WHERE id = ?", (name, preset_id))
            if cursor.rowcount == 0:
                raise ValueError(f"Static preset {preset_id} does not exist")
            conn.execute("DELETE FROM static_preset_colors WHERE preset_id = ?", (preset_id,))
        conn.executemany(
            "INSERT INTO static_preset_colors (preset_id, address, slot) VALUES (?, ?, ?)",
            [(preset_id, address, slot) for address, slot in colors.items()],
        )
    return preset_id


def capture_static_preset(name: str, swatches: dict[int, Swatch]) -> None:
    """Save a snapshot, reusing equivalent palette colors and creating any missing ones atomically."""
    with closing(_connect()) as conn, conn:
        rows = conn.execute(f"SELECT slot, {_SWATCH_COLUMNS} FROM palette ORDER BY slot").fetchall()
        palette = [(slot, Swatch(*rest)) for slot, *rest in rows]
        cursor = conn.execute("INSERT INTO static_presets (name) VALUES (?)", (name,))
        preset_id = cursor.lastrowid
        if preset_id is None:
            raise RuntimeError("SQLite did not return an ID for the saved static preset")
        for address, swatch in swatches.items():
            if not any(swatch.levels()):
                slot = None
            else:
                slot = next((key for key, existing in palette if existing.levels() == swatch.levels()), None)
                if slot is None:
                    inserted = conn.execute(
                        f"INSERT INTO palette ({_SWATCH_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                        (swatch.name, swatch.color, swatch.white, swatch.amber, swatch.uv, swatch.dimmer),
                    )
                    slot = inserted.lastrowid
                    if slot is None:
                        raise RuntimeError("SQLite did not return an ID for the captured color")
                    palette.append((slot, swatch))
            conn.execute(
                "INSERT INTO static_preset_colors (preset_id, address, slot) VALUES (?, ?, ?)",
                (preset_id, address, slot),
            )


def delete_static_preset(preset_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM static_presets WHERE id = ?", (preset_id,))
        conn.execute("DELETE FROM static_preset_colors WHERE preset_id = ?", (preset_id,))


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


def load_runtime_state() -> str | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT state FROM runtime_state WHERE id = 1").fetchone()
    return row[0] if row else None


def save_runtime_state(state: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO runtime_state (id, state) VALUES (1, ?)", (state,))


def export_database() -> bytes:
    """Return a consistent snapshot of the database file as bytes."""
    with closing(_connect()) as source, tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "export.db")
        with closing(sqlite3.connect(path)) as target:
            source.backup(target)
            with target:
                target.execute("DELETE FROM runtime_state")
        with open(path, "rb") as f:
            return f.read()


def import_database(data: bytes) -> None:
    """Replace the database contents with an uploaded database file. Raises ValueError if it isn't valid."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "import.db")
        with open(path, "wb") as f:
            f.write(data)
        try:
            with closing(sqlite3.connect(path)) as upload:
                tables = {row[0] for row in upload.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                missing = {"fixtures", "palette", "sequence_cells", "settings"} - tables
                if missing:
                    raise ValueError(f"Not a Hot Mess Lights database (missing tables: {', '.join(sorted(missing))})")
                with closing(_connect()) as live:
                    state = live.execute("SELECT state FROM runtime_state WHERE id = 1").fetchone()
                    upload.backup(live)
                    live.execute("CREATE TABLE IF NOT EXISTS runtime_state (id INTEGER PRIMARY KEY CHECK (id = 1), state TEXT NOT NULL)")
                    with live:
                        live.execute("DELETE FROM runtime_state")
                        if state is not None:
                            live.execute("INSERT INTO runtime_state VALUES (1, ?)", state)
        except sqlite3.DatabaseError as e:
            raise ValueError(f"Not a valid SQLite database: {e}") from e
    # Bring older files up to the current schema.
    _connect().close()
