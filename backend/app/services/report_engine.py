"""
Report engine: one result shape for every report, rendered as JSON, CSV or a
designed Excel sheet. A report is a function that returns a ReportResult; the
screen and both downloads are produced from that one object, so they can never
disagree with each other.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

TEXT, INT, MONEY, PERCENT, DATE, HOURS = "text", "int", "money", "percent", "date", "hours"
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")

_BRAND = "1F3A5F"
_HEAD_FILL = PatternFill("solid", fgColor=_BRAND)
_BAND_FILL = PatternFill("solid", fgColor="F3F6FA")
_TOTAL_FILL = PatternFill("solid", fgColor="E1E8F2")
_THIN = Side(style="thin", color="D5DCE6")
_NUMBER_FORMAT = {MONEY: "#,##0.00", INT: "#,##0", PERCENT: '0.0"%"', HOURS: "0.0", DATE: "yyyy-mm-dd"}


@dataclass
class Column:
    key: str
    label: str
    type: str = TEXT


@dataclass
class ReportResult:
    key: str
    title: str
    subtitle: str = ""
    columns: list[Column] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    totals: dict | None = None                      # same keys as the columns
    summary: list[dict] = field(default_factory=list)  # [{"label","value","type"}] headline tiles
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "key": self.key, "title": self.title, "subtitle": self.subtitle,
            "columns": [{"key": c.key, "label": c.label, "type": c.type} for c in self.columns],
            "rows": [_jsonable(r) for r in self.rows],
            "totals": _jsonable(self.totals) if self.totals else None,
            "summary": [_jsonable(s) for s in self.summary],
            "notes": self.notes,
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def csv_text(value: Any) -> str:
    """Text a spreadsheet shows as text (a name like '=1+1' must not run)."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def to_csv(report: ReportResult) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c.label for c in report.columns])
    for row in report.rows:
        w.writerow([_csv_cell(row.get(c.key), c) for c in report.columns])
    if report.totals:
        w.writerow([_csv_cell(report.totals.get(c.key), c) for c in report.columns])
    return buf.getvalue()


def _csv_cell(value: Any, col: Column) -> Any:
    if value is None:
        return ""
    if col.type == TEXT:
        return csv_text(value)
    if isinstance(value, Decimal):
        return f"{value:.2f}" if col.type == MONEY else str(value)
    return value


def to_xlsx(report: ReportResult, *, company: str = "", generated_at: datetime | None = None) -> bytes:
    """A readable sheet: title block, coloured header, number formats, banding,
    a totals row, frozen header and a sensible width per column."""
    wb = Workbook()
    ws = wb.active
    ws.title = (report.title[:28] or "Report").replace("/", "-")
    ncols = max(len(report.columns), 1)
    last = get_column_letter(ncols)

    ws["A1"] = company or report.title
    ws["A1"].font = Font(size=16, bold=True, color=_BRAND)
    ws["A2"] = report.title if company else ""
    ws["A2"].font = Font(size=12, bold=True)
    ws["A3"] = report.subtitle
    ws["A3"].font = Font(size=10, color="5B6678")
    stamp = (generated_at or datetime.now()).strftime("%Y-%m-%d %H:%M")
    ws["A4"] = f"Generated {stamp}"
    ws["A4"].font = Font(size=9, italic=True, color="8A94A6")
    for r in range(1, 5):
        ws.merge_cells(f"A{r}:{last}{r}")

    row_no = 6
    if report.summary:
        for i, tile in enumerate(report.summary):
            col = 1 + i * 2
            if col + 1 > ncols + 1:
                break
            lab = ws.cell(row=row_no, column=col, value=tile["label"])
            lab.font = Font(size=9, bold=True, color="5B6678")
            val = ws.cell(row=row_no + 1, column=col, value=_cell_value(tile.get("value"), tile.get("type", TEXT)))
            val.font = Font(size=13, bold=True, color=_BRAND)
            val.number_format = _NUMBER_FORMAT.get(tile.get("type", TEXT), "General")
            val.alignment = Alignment(horizontal="left")
        row_no += 3

    header_row = row_no
    for i, c in enumerate(report.columns, start=1):
        cell = ws.cell(row=header_row, column=i, value=c.label)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = _HEAD_FILL
        cell.alignment = Alignment(horizontal="left" if c.type == TEXT else "right", vertical="center", wrap_text=True)
        cell.border = Border(bottom=_THIN)
    ws.row_dimensions[header_row].height = 28

    widths = [len(c.label) + 2 for c in report.columns]
    for n, row in enumerate(report.rows):
        r = header_row + 1 + n
        for i, c in enumerate(report.columns, start=1):
            value = _cell_value(row.get(c.key), c.type)
            cell = ws.cell(row=r, column=i, value=csv_text(value) if c.type == TEXT and value is not None else value)
            cell.number_format = _NUMBER_FORMAT.get(c.type, "General")
            cell.alignment = Alignment(horizontal="left" if c.type == TEXT else "right")
            cell.border = Border(bottom=_THIN)
            if n % 2:
                cell.fill = _BAND_FILL
            widths[i - 1] = max(widths[i - 1], min(len(str(value if value is not None else "")) + 2, 40))

    end = header_row + len(report.rows)
    if report.totals:
        r = end + 1
        for i, c in enumerate(report.columns, start=1):
            v = report.totals.get(c.key)
            cell = ws.cell(row=r, column=i, value=_cell_value(v, c.type) if c.type != TEXT or v is None else csv_text(v))
            cell.font = Font(bold=True)
            cell.fill = _TOTAL_FILL
            cell.number_format = _NUMBER_FORMAT.get(c.type, "General")
            cell.alignment = Alignment(horizontal="left" if c.type == TEXT else "right")
            cell.border = Border(top=Side(style="medium", color=_BRAND))
        end = r

    for note_no, note in enumerate(report.notes):
        ws.cell(row=end + 2 + note_no, column=1, value=note).font = Font(size=9, italic=True, color="5B6678")

    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(10, min(w, 42))
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _cell_value(value: Any, col_type: str) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if col_type == DATE and isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return value
    return value
