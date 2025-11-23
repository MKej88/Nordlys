"""Genererer en enkel PDF-rapport fra SAF-T-dataene."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Iterable, List, Sequence

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

if TYPE_CHECKING:
    from .data_manager import SaftDatasetStore


def export_dataset_to_pdf(dataset_store: "SaftDatasetStore", file_name: str) -> None:
    """Skriv en kortfattet PDF-rapport fra aktive data."""

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    heading_style = styles["Heading2"]

    doc = SimpleDocTemplate(
        file_name,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    story: List[object] = [
        Paragraph("Nordlys – Rapport", title_style),
        Spacer(1, 6 * mm),
    ]

    summary = dataset_store.saft_summary or {}
    if summary:
        story.append(Paragraph("Hovedtall (NS4102)", heading_style))
        story.append(_key_value_table(summary, "Nøkkel", "Beløp"))
        story.append(Spacer(1, 4 * mm))

    customer_sales = dataset_store.customer_sales
    if customer_sales is not None and not customer_sales.empty:
        top_customers = _coerce_numeric(customer_sales, "Omsetning eks mva").nlargest(
            10, "Omsetning eks mva", keep="all"
        )
        story.append(Paragraph("Toppkunder", heading_style))
        story.append(
            _dataframe_table(
                top_customers,
                columns=["Kundenr", "Kundenavn", "Omsetning eks mva"],
            )
        )
        story.append(Spacer(1, 4 * mm))

    supplier_purchases = dataset_store.supplier_purchases
    if supplier_purchases is not None and not supplier_purchases.empty:
        top_suppliers = _coerce_numeric(
            supplier_purchases, "Innkjøp eks mva"
        ).nlargest(10, "Innkjøp eks mva", keep="all")
        story.append(Paragraph("Topp leverandører", heading_style))
        story.append(
            _dataframe_table(
                top_suppliers,
                columns=["Leverandørnr", "Leverandørnavn", "Innkjøp eks mva"],
            )
        )
        story.append(Spacer(1, 4 * mm))

    vouchers = dataset_store.cost_vouchers
    if vouchers:
        story.append(Paragraph("Kostnadsbilag (utvalg)", heading_style))
        story.append(_voucher_table(vouchers[:10]))

    doc.build(story)


def _key_value_table(data: dict[str, float], key_label: str, value_label: str) -> Table:
    rows: List[Sequence[str]] = [(key_label, value_label)]
    for key, value in data.items():
        rows.append((key, _format_number(value)))
    table = Table(rows, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ]
        )
    )
    return table


def _dataframe_table(df, columns: Iterable[str]) -> Table:  # type: ignore[no-untyped-def]
    rows: List[Sequence[str]] = [tuple(columns)]
    for _, row in df[list(columns)].iterrows():
        rows.append(tuple(_format_cell(value) for value in row))
    table = Table(rows, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ]
        )
    )
    return table


def _voucher_table(vouchers) -> Table:  # type: ignore[no-untyped-def]
    rows: List[Sequence[str]] = [
        (
            "Bilag",
            "Dato",
            "Leverandør",
            "Beskrivelse",
            "Beløp",
        )
    ]
    for voucher in vouchers:
        rows.append(
            (
                _format_cell(voucher.document_number or voucher.transaction_id),
                _format_date(voucher.transaction_date),
                _format_cell(voucher.supplier_name or voucher.supplier_id),
                _format_cell(voucher.description),
                _format_number(voucher.amount),
            )
        )
    table = Table(rows, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ]
        )
    )
    return table


def _format_number(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "–"
    return f"{number:,.0f}".replace(",", " ")


def _format_cell(value: object) -> str:
    if value is None:
        return "–"
    text = str(value).strip()
    return text or "–"


def _format_date(value: date | None) -> str:
    if value is None:
        return "–"
    return value.strftime("%d.%m.%Y")


def _coerce_numeric(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Returnerer kopi der kolonnen er numerisk for sortering."""

    work = df.copy()
    work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0.0)
    return work
