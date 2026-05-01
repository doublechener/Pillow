# 库存数据持久化:SQLite (inventory.db) + JSON 备份 (inventory.json)
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Optional

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "inventory.db"
JSON_PATH = BASE_DIR / "inventory.json"


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _create_schema(con):
    con.execute(
        "CREATE TABLE IF NOT EXISTS inventory ("
        "  code TEXT PRIMARY KEY,"
        "  quantity INTEGER NOT NULL DEFAULT 0,"
        "  updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))"
        ")"
    )


def init_db(default_inventory: Optional[Dict[str, int]] = None) -> None:
    # 表不存在则建,空表则从 JSON 或默认值水合
    with _conn() as con:
        _create_schema(con)
        empty = con.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0
    if empty:
        if JSON_PATH.exists():
            data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        elif default_inventory:
            data = dict(default_inventory)
        else:
            data = {}
        if data:
            with _conn() as con:
                con.executemany(
                    "INSERT INTO inventory (code, quantity) VALUES (?, ?) "
                    "ON CONFLICT(code) DO NOTHING",
                    [(c, int(q)) for c, q in data.items()],
                )
            export_json()


def load_inventory() -> Dict[str, int]:
    init_db()
    with _conn() as con:
        rows = con.execute("SELECT code, quantity FROM inventory").fetchall()
    return {c: int(q) for c, q in rows}


def save_inventory(updates: Dict[str, int], sync_json: bool = True) -> None:
    if not updates:
        return
    with _conn() as con:
        con.executemany(
            "INSERT INTO inventory (code, quantity, updated_at) "
            "VALUES (?, ?, datetime('now', 'localtime')) "
            "ON CONFLICT(code) DO UPDATE SET "
            "  quantity = excluded.quantity, "
            "  updated_at = excluded.updated_at",
            [(c, int(q)) for c, q in updates.items()],
        )
    if sync_json:
        export_json()


def replace_all(inventory: Dict[str, int]) -> None:
    with _conn() as con:
        con.execute("DELETE FROM inventory")
    save_inventory(inventory)


def export_json() -> Path:
    with _conn() as con:
        rows = con.execute(
            "SELECT code, quantity FROM inventory ORDER BY code"
        ).fetchall()
    inv = {c: int(q) for c, q in rows}
    JSON_PATH.write_text(
        json.dumps(inv, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return JSON_PATH


def last_updated() -> Optional[str]:
    with _conn() as con:
        row = con.execute("SELECT MAX(updated_at) FROM inventory").fetchone()
    return row[0] if row and row[0] else None