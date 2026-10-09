from __future__ import annotations

from fastapi import HTTPException

from backend import database as db


def get_or_404(table: str, row_id: str, label: str) -> dict:
    row = db.fetch_one(f"SELECT * FROM {table} WHERE id=?", (row_id,))
    if not row:
        raise HTTPException(404, f"{label} '{row_id}' not found")
    return row
