"""FastAPI application: measurement unit checker.

Endpoints
----------
GET  /                     single-page UI (static/index.html)
GET  /api/units            known units & prefixes (for help text)
POST /api/calculate        parse + evaluate an expression
GET  /api/entries          list saved calculation entries
POST /api/entries          save a calculation entry
DELETE /api/entries/{id}   delete one entry
GET  /api/export.json      export all entries as JSON
GET  /api/export.csv       export all entries as CSV
"""
from __future__ import annotations

import csv
import io
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import CalcError, Measurement, evaluate
from .units import DIM_NAMES, SI_PREFIXES, UNITS, format_dimension

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "entries.db"

app = FastAPI(title="实验测量单位校验", version="1.0.0")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            expression  TEXT NOT NULL,
            value       REAL NOT NULL,
            uncertainty REAL NOT NULL,
            dimension   TEXT NOT NULL,
            unit_label  TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
        """
    )
    return conn


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CalculateIn(BaseModel):
    expression: str = Field(..., min_length=1)


class EntryIn(BaseModel):
    expression: str = Field(..., min_length=1)
    label: Optional[str] = None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def round_to_uncertainty(value: float, unc: float) -> str:
    """Render value(unc) with significant-figure uncertainty (1-2 sig digits)."""
    if not math.isfinite(value):
        return str(value)
    if unc <= 0 or not math.isfinite(unc):
        return f"{value:.6g}"
    # uncertainty: two significant digits if first digit is 1 or 2, else one
    order = math.floor(math.log10(unc))
    first_digits = unc / 10 ** order
    ndigits_unc = 2 if first_digits < 3 else 1
    decimals = max(0, -order + ndigits_unc - 1)
    v_rounded = round(value, decimals)
    u_rounded = round(unc, decimals)
    if decimals == 0:
        v_txt = f"{v_rounded:.0f}"
        u_txt = f"{u_rounded:.0f}"
    else:
        v_txt = f"{v_rounded:.{decimals}f}"
        u_txt = f"{u_rounded:.{decimals}f}"
    return f"{v_txt} ± {u_txt}"


def relative_uncertainty(m: Measurement) -> Optional[float]:
    if m.value == 0:
        return None
    return m.uncertainty / abs(m.value)


def serialize_measurement(m: Measurement, expression: str) -> Dict[str, Any]:
    return {
        "expression": expression,
        "value": m.value,
        "uncertainty": m.uncertainty,
        "relative_uncertainty": relative_uncertainty(m),
        "dimension": list(m.dim),
        "dimension_label": format_dimension(m.dim),
        "si_unit_label": format_dimension(m.dim).replace("·", " "),
        "display": round_to_uncertainty(m.value, m.uncertainty),
    }


def calc_error_response(err: CalcError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {
                    "field": "expression",
                    "type": err.kind,
                    "msg": err.message,
                    "pos": err.position,
                }
            ]
        },
    )


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@app.get("/api/units")
def list_units() -> Dict[str, Any]:
    return {
        "base_dimensions": list(DIM_NAMES),
        "units": sorted(UNITS.keys()),
        "si_prefixes": SI_PREFIXES,
    }


@app.post("/api/calculate")
def calculate(payload: CalculateIn) -> Dict[str, Any]:
    try:
        m = evaluate(payload.expression)
    except CalcError as err:
        return calc_error_response(err)  # type: ignore[return-value]
    return serialize_measurement(m, payload.expression)


@app.get("/api/entries")
def list_entries() -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM entries ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/entries", status_code=201)
def create_entry(payload: EntryIn) -> Dict[str, Any]:
    try:
        m = evaluate(payload.expression)
    except CalcError as err:
        return calc_error_response(err)  # type: ignore[return-value]
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO entries
                (expression, value, uncertainty, dimension, unit_label, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.expression,
                m.value,
                m.uncertainty,
                json.dumps(list(m.dim)),
                format_dimension(m.dim),
                created,
            ),
        )
        entry_id = cur.lastrowid
        row = conn.execute(
            "SELECT * FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
    return dict(row)


@app.delete("/api/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int) -> Response:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="条目不存在")
    return Response(status_code=204)


def _all_entries() -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM entries ORDER BY id ASC"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/export.json")
def export_json() -> Response:
    data = json.dumps(_all_entries(), ensure_ascii=False, indent=2)
    return Response(
        content=data,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="measurements.json"'},
    )


@app.get("/api/export.csv")
def export_csv() -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["id", "expression", "value", "uncertainty", "dimension", "created_at"]
    )
    for r in _all_entries():
        writer.writerow(
            [
                r["id"],
                r["expression"],
                r["value"],
                r["uncertainty"],
                r["unit_label"],
                r["created_at"],
            ]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="measurements.csv"'},
    )


# ---------------------------------------------------------------------------
# Static UI
# ---------------------------------------------------------------------------

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((BASE_DIR / "static" / "index.html").read_text("utf-8"))
