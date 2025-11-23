from __future__ import annotations

import html
import textwrap
from datetime import datetime
from typing import List, Optional, Sequence, Tuple, TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextOption
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
        self._apply_status_state(self.status_label, "pending")

        self.trial_balance_label = QLabel("Prøvebalanse er ikke beregnet ennå.")
        self.trial_balance_label.setObjectName("statusLabel")
        self.trial_balance_label.setWordWrap(True)
        self.trial_balance_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.trial_balance_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )
        self.status_card.add_widget(self.trial_balance_label)
        self._apply_status_state(self.trial_balance_label, "pending")

        self.validation_label = QLabel("Ingen XSD-validering er gjennomført.")
        self.validation_label.setObjectName("statusLabel")
        self.validation_label.setWordWrap(True)
        self.validation_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.validation_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )
        self.status_card.add_widget(self.validation_label)
        self._apply_status_state(self.validation_label, "pending")

        self.brreg_label = QLabel("Regnskapsregister: ingen data importert ennå.")
        self.brreg_label.setObjectName("statusLabel")
        self.brreg_label.setWordWrap(True)
        self.brreg_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.brreg_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )
        self.status_card.add_widget(self.brreg_label)
        self._apply_status_state(self.brreg_label, "pending")
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
        log_height = 230
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logText")
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.log_view.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.log_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.log_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.log_view.setFrameShape(QFrame.NoFrame)
        self.log_view.setMinimumHeight(log_height)
        self.log_view.setMaximumHeight(log_height)
        self.log_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.log_view.document().setDocumentMargin(10)

        self.log_card.add_widget(self.log_view)
        self.log_card.body_layout.setStretchFactor(self.log_view, 1)
        grid.addWidget(self.log_card, 1, 0)

        self.invoice_card = CardFrame(
            "Antall inngående faktura",
            "Tilgjengelige kostnadsbilag klare for stikkprøver.",
        )
        self.invoice_label = QLabel("Ingen SAF-T fil er lastet inn ennå.")
        self.invoice_label.setObjectName("statusLabel")
        self.invoice_label.setWordWrap(True)
        self.invoice_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.invoice_card.add_widget(self.invoice_label)
        self._apply_status_state(self.invoice_label, "pending")
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

        self._log_entries: List[str] = []
        self._error_entries: List[str] = []

        layout.addStretch(1)

    def update_status(self, message: str, *, state: str = "approved") -> None:
        self.status_label.setText(message)
        self.status_label.updateGeometry()
        self.status_card.updateGeometry()
        self._apply_status_state(self.status_label, state)

    def update_validation_status(
        self, result: Optional["saft.SaftValidationResult"]
    ) -> None:
        if result is None:
            self.validation_label.setText("Ingen XSD-validering er gjennomført.")
            self.validation_label.updateGeometry()
            self.status_card.updateGeometry()
            self._apply_status_state(self.validation_label, "pending")
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
        if result.is_valid is True:
            state = "approved"
        elif result.is_valid is False:
            state = "rejected"
        else:
            state = "pending"
        self._apply_status_state(self.validation_label, state)

    def update_trial_balance_status(
        self, message: str, *, state: str = "pending"
    ) -> None:
        self.trial_balance_label.setText(message)
        self.trial_balance_label.updateGeometry()
        self.status_card.updateGeometry()
        self._apply_status_state(self.trial_balance_label, state)

    def update_brreg_status(self, message: str, *, state: str = "pending") -> None:
        self.brreg_label.setText(message)
        self.brreg_label.updateGeometry()
        self.status_card.updateGeometry()
        self._apply_status_state(self.brreg_label, state)

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
            self._apply_status_state(self.invoice_label, "pending")
            return
        if count == 0:
            self.invoice_label.setText(
                "Ingen inngående fakturaer tilgjengelig i valgt datasett."
            )
            self._apply_status_state(self.invoice_label, "pending")
            return
        if count == 1:
            message = "1 inngående faktura klar for kontroll."
        else:
            message = f"{count} inngående fakturaer klare for kontroll."
        self.invoice_label.setText(message)
        self._apply_status_state(self.invoice_label, "approved")

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
        self._log_entries.clear()
        self.log_view.clear()

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self._log_entries.append(entry)
        self._trim_and_update_log()

    def _trim_and_update_log(self) -> None:
        max_entries = 200
        if len(self._log_entries) > max_entries:
            self._log_entries = self._log_entries[-max_entries:]
        self.log_view.setPlainText("\n".join(self._log_entries))
        scrollbar = self.log_view.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())

    def _apply_status_state(self, label: QLabel, state: str) -> None:
        label.setProperty("statusState", state)
        label.style().unpolish(label)
        label.style().polish(label)
