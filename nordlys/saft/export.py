"""Eksport av SAF-T analyser til CSV og XLSX."""

from __future__ import annotations

import numbers
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple
from xml.sax.saxutils import escape

from ..utils import lazy_pandas

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

pd = lazy_pandas()


def _excel_column_letter(index: int) -> str:
    """Konverterer 1-basert kolonneindeks til Excel-kolonnebokstaver."""

    result = ""
    current = index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result or "A"


def _write_basic_xlsx(df: "pd.DataFrame", path: Path) -> None:
    """Skriver en minimalistisk XLSX-fil uten eksterne avhengigheter."""

    path = Path(path)

    def build_cell(row_index: int, col_index: int, value: object) -> Optional[str]:
        if pd.isna(value):
            return None
        cell_ref = f"{_excel_column_letter(col_index)}{row_index}"
        if value is None:
            return None
        if isinstance(value, bool):
            return f'<c r="{cell_ref}" t="b"><v>{int(value)}</v></c>'
        if isinstance(value, Decimal):
            return f'<c r="{cell_ref}"><v>{value}</v></c>'
        if isinstance(value, numbers.Integral):
            return f'<c r="{cell_ref}"><v>{int(value)}</v></c>'
        if isinstance(value, numbers.Real):
            return f'<c r="{cell_ref}"><v>{value}</v></c>'
        text = escape(str(value))
        return f'<c r="{cell_ref}" t="inlineStr"><is><t>{text}</t></is></c>'

    def build_header(row_index: int) -> str:
        cells = [
            f'<c r="{_excel_column_letter(col)}{row_index}" t="inlineStr"><is><t>{escape(str(header))}</t></is></c>'
            for col, header in enumerate(df.columns, start=1)
        ]
        return f'<row r="{row_index}">' + "".join(cells) + "</row>"

    def build_body(start_row: int) -> str:
        rows = []
        row_number = start_row
        for record in df.itertuples(index=False, name=None):
            cells = []
            for col_index, value in enumerate(record, start=1):
                cell = build_cell(row_number, col_index, value)
                if cell:
                    cells.append(cell)
            rows.append(f'<row r="{row_number}">' + "".join(cells) + "</row>")
            row_number += 1
        return "".join(rows)

    header_xml = build_header(1)
    body_xml = build_body(2)

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheetData>"
        f"{header_xml}{body_xml}"
        "</sheetData>"
        "</worksheet>"
    )

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )

    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>"
        '<sheet name="Sheet1" sheetId="1" r:id="rId1"/>'
        "</sheets>"
        "</workbook>"
    )

    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )

    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font/></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="1"><xf xfId="0"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", rels_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/styles.xml", styles_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def save_outputs(
    df: "pd.DataFrame",
    base_path: str | Path,
    year: int | str,
    tag: str = "alle_3xxx",
) -> Tuple[Path, Path]:
    """Lagrer DataFrame til CSV (UTF-8-BOM) og XLSX."""

    output_dir = Path(base_path)
    if output_dir.is_file():
        output_dir = output_dir.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    year_text = str(year)
    csv_path = output_dir / f"salg_per_kunde_eks_mva_{year_text}_{tag}.csv"
    xlsx_path = output_dir / f"salg_per_kunde_eks_mva_{year_text}_{tag}.xlsx"

    export_df = df.copy()
    export_df["Omsetning eks mva"] = (
        export_df["Omsetning eks mva"].astype(float).round(2)
    )
    export_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    try:
        export_df.to_excel(xlsx_path, index=False)
    except ModuleNotFoundError:
        try:
            import xlsxwriter  # type: ignore  # noqa: F401
        except ModuleNotFoundError:
            _write_basic_xlsx(export_df, xlsx_path)
            return csv_path, xlsx_path
        with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as writer:
            export_df.to_excel(writer, index=False)
    except ValueError:
        _write_basic_xlsx(export_df, xlsx_path)

    return csv_path, xlsx_path


__all__ = ["save_outputs"]
