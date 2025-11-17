from __future__ import annotations

import html
import textwrap
from datetime import datetime
from typing import List, Optional, Sequence, Tuple, TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QLabel,
    QFrame,
    QGridLayout,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...industry_groups import IndustryClassification
from ..widgets import CardFrame

if TYPE_CHECKING:  # pragma: no cover
    from ... import saft  # type: ignore

__all__ = ["ImportPage"]


class ImportPage(QWidget):
    """Viser importstatus og bransjeinnsikt."""

    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        layout.addLayout(grid)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        self.status_card = CardFrame(
            "Status", "Hurtigoversikt over siste import og anbefalinger."
        )
        self.status_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.status_label = QLabel("Ingen SAF-T fil er lastet inn ennå.")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.status_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )
        self.status_card.add_widget(self.status_label)

        self.validation_label = QLabel("Ingen XSD-validering er gjennomført.")
        self.validation_label.setObjectName("statusLabel")
        self.validation_label.setWordWrap(True)
        self.validation_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.validation_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )
        self.status_card.add_widget(self.validation_label)

        self.brreg_label = QLabel("Regnskapsregister: ingen data importert ennå.")
        self.brreg_label.setObjectName("statusLabel")
        self.brreg_label.setWordWrap(True)
        self.brreg_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.brreg_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )
        self.status_card.add_widget(self.brreg_label)
        grid.addWidget(self.status_card, 0, 0)

        self.industry_card = CardFrame(
            "Bransjeinnsikt",
            "Vi finner næringskode og bransje automatisk etter import.",
        )
        self.industry_label = QLabel(
            "Importer en SAF-T-fil for å se hvilken bransje kunden havner i."
        )
        self.industry_label.setObjectName("statusLabel")
        self.industry_label.setWordWrap(True)
        self.industry_label.setTextFormat(Qt.RichText)
        self.industry_card.add_widget(self.industry_label)
        grid.addWidget(self.industry_card, 0, 1)

        self.error_card = CardFrame(
            "Feilmeldinger",
            "Viser de siste avvikene fra import, validering og Regnskapsregisteret.",
        )
        self.error_label = QLabel("Ingen feilmeldinger registrert.")
        self.error_label.setObjectName("statusLabel")
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.error_label.setTextFormat(Qt.RichText)
        self.error_card.add_widget(self.error_label)
        grid.addWidget(self.error_card, 0, 2)

        self.log_card = CardFrame(
            "Importlogg",
            "Siste hendelser under import og validering.",
        )
        self.log_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.log_container = QFrame()
        self.log_container.setObjectName("logFieldContainer")
        self.log_container.setFrameShape(QFrame.NoFrame)
        self.log_container.setAttribute(Qt.WA_StyledBackground, True)
        self.log_container.setMinimumHeight(260)
        self.log_container.setMaximumHeight(260)
        self.log_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.log_container.setProperty("focusState", "idle")

        container_layout = QVBoxLayout(self.log_container)
        container_layout.setContentsMargins(12, 12, 12, 12)
        container_layout.setSpacing(0)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setObjectName("logField")
        self.log_output.setFrameShape(QFrame.NoFrame)
        self.log_output.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.log_output.installEventFilter(self)
        container_layout.addWidget(self.log_output)

        self.log_card.add_widget(self.log_container)
        grid.addWidget(self.log_card, 1, 0)
        self._update_log_focus_state(False)

        self.invoice_card = CardFrame(
            "Antall inngående faktura",
            "Tilgjengelige kostnadsbilag klare for stikkprøver.",
        )
        self.invoice_label = QLabel("Ingen SAF-T fil er lastet inn ennå.")
        self.invoice_label.setObjectName("statusLabel")
        self.invoice_label.setWordWrap(True)
        self.invoice_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.invoice_card.add_widget(self.invoice_label)
        grid.addWidget(self.invoice_card, 1, 1)

        self.misc_card = CardFrame(
            "Annet",
            "Tilleggsinformasjon knyttet til valgt datasett.",
        )
        self.misc_label = QLabel("Ingen tilleggsinformasjon tilgjengelig ennå.")
        self.misc_label.setObjectName("statusLabel")
        self.misc_label.setWordWrap(True)
        self.misc_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.misc_label.setTextFormat(Qt.RichText)
        self.misc_card.add_widget(self.misc_label)
        grid.addWidget(self.misc_card, 1, 2)

        self._error_entries: List[str] = []

        layout.addStretch(1)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if obj is self.log_output and event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self._update_log_focus_state(event.type() == QEvent.FocusIn)
        return super().eventFilter(obj, event)

    def _update_log_focus_state(self, focused: bool) -> None:
        state = "focused" if focused else "idle"
        if self.log_container.property("focusState") == state:
            return
        self.log_container.setProperty("focusState", state)
        style = self.log_container.style()
        style.unpolish(self.log_container)
        style.polish(self.log_container)

    def update_status(self, message: str) -> None:
        self.status_label.setText(message)
        self.status_label.updateGeometry()
        self.status_card.updateGeometry()

    def update_validation_status(
        self, result: Optional["saft.SaftValidationResult"]
    ) -> None:
        if result is None:
            self.validation_label.setText("Ingen XSD-validering er gjennomført.")
            self.validation_label.updateGeometry()
            self.status_card.updateGeometry()
            return

        if result.version_family:
            version_txt = result.version_family
            if (
                result.audit_file_version
                and result.audit_file_version != result.version_family
            ):
                version_txt = f"{result.version_family} (AuditFileVersion: {result.audit_file_version})"
        else:
            version_txt = result.audit_file_version or "ukjent"

        status_parts = [f"SAF-T versjon: {version_txt}"]
        if result.is_valid is True:
            status_parts.append("XSD-validering: OK")
        elif result.is_valid is False:
            status_parts.append("XSD-validering: FEILET")
        else:
            status_parts.append("XSD-validering: Ikke tilgjengelig")

        message = " · ".join(status_parts)
        if result.details:
            first_line = result.details.strip().splitlines()[0]
            message = f"{message}\nDetaljer: {first_line}"
        self.validation_label.setText(message)
        self.validation_label.updateGeometry()
        self.status_card.updateGeometry()

    def update_brreg_status(self, message: str) -> None:
        self.brreg_label.setText(message)
        self.brreg_label.updateGeometry()
        self.status_card.updateGeometry()

    def update_industry(
        self,
        classification: Optional[IndustryClassification],
        error: Optional[str] = None,
    ) -> None:
        if error:
            self.industry_label.setText(
                textwrap.dedent(
                    f"""
                    <p><strong>Bransje ikke tilgjengelig:</strong> {error}</p>
                    <p>Prøv igjen når du har nettilgang, eller sjekk at SAF-T-filen inneholder
                    organisasjonsnummer.</p>
                    """
                ).strip()
            )
            return

        if classification is None:
            self.industry_label.setText(
                "Importer en SAF-T-fil for å se hvilken bransje kunden havner i."
            )
            return

        name = classification.name or "Ukjent navn"
        naringskode = classification.naringskode or "–"
        description = classification.description or "Ingen beskrivelse fra Brreg."
        sn2 = classification.sn2 or "–"
        text = textwrap.dedent(
            f"""
            <p><strong>{classification.group}</strong></p>
            <ul>
                <li><strong>Selskap:</strong> {name}</li>
                <li><strong>Org.nr:</strong> {classification.orgnr}</li>
                <li><strong>Næringskode:</strong> {naringskode} ({description})</li>
                <li><strong>SN2:</strong> {sn2}</li>
                <li><strong>Kilde:</strong> {classification.source}</li>
            </ul>
            """
        ).strip()
        self.industry_label.setText(text)

    def update_invoice_count(self, count: Optional[int]) -> None:
        if count is None:
            self.invoice_label.setText("Ingen SAF-T fil er lastet inn ennå.")
            return
        if count == 0:
            self.invoice_label.setText(
                "Ingen inngående fakturaer tilgjengelig i valgt datasett."
            )
            return
        if count == 1:
            message = "1 inngående faktura klar for kontroll."
        else:
            message = f"{count} inngående fakturaer klare for kontroll."
        self.invoice_label.setText(message)

    def reset_errors(self) -> None:
        self._error_entries.clear()
        self.error_label.setText("Ingen feilmeldinger registrert.")

    def record_error(self, message: str) -> None:
        cleaned = (message or "").strip() or "Ukjent feil"
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {cleaned}"
        self._error_entries.append(entry)
        self._error_entries = self._error_entries[-6:]
        bullets = "".join(
            f"<li>{html.escape(item)}</li>" for item in self._error_entries
        )
        self.error_label.setText(f"<ul>{bullets}</ul>")

    def update_misc_info(
        self, entries: Optional[Sequence[Tuple[str, str]]] = None
    ) -> None:
        if not entries:
            self.misc_label.setText("Ingen tilleggsinformasjon tilgjengelig ennå.")
            return
        bullet_items = []
        for title, value in entries:
            if not value:
                continue
            bullet_items.append(
                f"<li><strong>{html.escape(title)}:</strong> {html.escape(value)}</li>"
            )
        if not bullet_items:
            self.misc_label.setText("Ingen tilleggsinformasjon tilgjengelig ennå.")
            return
        self.misc_label.setText(f"<ul>{''.join(bullet_items)}</ul>")

    def reset_log(self) -> None:
        self.log_output.clear()

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.log_output.appendPlainText(entry)
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_output.setTextCursor(cursor)
