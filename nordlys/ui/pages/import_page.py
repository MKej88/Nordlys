from __future__ import annotations

import html
import textwrap
from datetime import datetime
from typing import List, Optional, Sequence, Tuple, TYPE_CHECKING, Literal

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

StatusState = Literal["approved", "pending", "rejected"]

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
        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.status_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )
        self.status_card.add_widget(self.status_label)

        self.trial_balance_label = QLabel()
        self.trial_balance_label.setObjectName("statusLabel")
        self.trial_balance_label.setWordWrap(True)
        self.trial_balance_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.trial_balance_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )
        self.status_card.add_widget(self.trial_balance_label)

        self.validation_label = QLabel()
        self.validation_label.setObjectName("statusLabel")
        self.validation_label.setWordWrap(True)
        self.validation_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.validation_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.MinimumExpanding
        )
        self.status_card.add_widget(self.validation_label)

        self.brreg_label = QLabel()
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
        self.invoice_label = QLabel()
        self.invoice_label.setObjectName("statusLabel")
        self.invoice_label.setWordWrap(True)
        self.invoice_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.invoice_card.add_widget(self.invoice_label)
        grid.addWidget(self.invoice_card, 1, 1)

        self.misc_card = CardFrame(
            "Annet",
            "Tilleggsinformasjon knyttet til valgt datasett.",
        )
        self.misc_label = QLabel()
        self.misc_label.setObjectName("statusLabel")
        self.misc_label.setWordWrap(True)
        self.misc_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.misc_label.setTextFormat(Qt.RichText)
        self.misc_card.add_widget(self.misc_label)
        grid.addWidget(self.misc_card, 1, 2)

        self._log_entries: List[str] = []
        self._error_entries: List[str] = []

        self.update_status("Ingen SAF-T fil er lastet inn ennå.")
        self.update_trial_balance_status("Prøvebalanse er ikke beregnet ennå.")
        self.update_validation_status(None)
        self.update_brreg_status("Regnskapsregister: ingen data importert ennå.")
        self.update_invoice_count(None)
        self.update_misc_info(None)

        layout.addStretch(1)

    def update_status(self, message: str, state: StatusState = "pending") -> None:
        self._set_status_label(self.status_label, message, state=state)
        self.status_card.updateGeometry()

    def update_validation_status(
        self, result: Optional["saft.SaftValidationResult"]
    ) -> None:
        if result is None:
            self._set_status_label(
                self.validation_label,
                "Ingen XSD-validering er gjennomført.",
                state="pending",
            )
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
            state: StatusState = "approved"
        elif result.is_valid is False:
            status_parts.append("XSD-validering: FEILET")
            state = "rejected"
        else:
            status_parts.append("XSD-validering: Ikke tilgjengelig")
            state = "pending"

        message = " · ".join(status_parts)
        if result.details:
            first_line = result.details.strip().splitlines()[0]
            message = f"{message}\nDetaljer: {first_line}"
        self._set_status_label(self.validation_label, message, state=state)
        self.status_card.updateGeometry()

    def update_trial_balance_status(
        self, message: str, *, state: StatusState = "pending"
    ) -> None:
        self._set_status_label(self.trial_balance_label, message, state=state)
        self.status_card.updateGeometry()

    def update_brreg_status(
        self, message: str, *, state: StatusState = "pending"
    ) -> None:
        self._set_status_label(self.brreg_label, message, state=state)
        self.status_card.updateGeometry()

    def update_industry(
        self,
        classification: Optional[IndustryClassification],
        error: Optional[str] = None,
    ) -> None:
        if error:
            self._set_status_label(
                self.industry_label,
                textwrap.dedent(
                    f"""
                    <p><strong>Bransje ikke tilgjengelig:</strong> {error}</p>
                    <p>Prøv igjen når du har nettilgang, eller sjekk at SAF-T-filen inneholder
                    organisasjonsnummer.</p>
                    """
                ).strip(),
                state="rejected",
            )
            return

        if classification is None:
            self._set_status_label(
                self.industry_label,
                "Importer en SAF-T-fil for å se hvilken bransje kunden havner i.",
                state="pending",
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
        self._set_status_label(self.industry_label, text, state="approved")

    def update_invoice_count(self, count: Optional[int]) -> None:
        if count is None:
            self._set_status_label(
                self.invoice_label,
                "Ingen SAF-T fil er lastet inn ennå.",
                state="pending",
            )
            return
        if count == 0:
            self._set_status_label(
                self.invoice_label,
                "Ingen inngående fakturaer tilgjengelig i valgt datasett.",
                state="pending",
            )
            return
        if count == 1:
            message = "1 inngående faktura klar for kontroll."
        else:
            message = f"{count} inngående fakturaer klare for kontroll."
        self._set_status_label(self.invoice_label, message, state="approved")

    def reset_errors(self) -> None:
        self._error_entries.clear()
        self._set_status_label(
            self.error_label, "Ingen feilmeldinger registrert.", state="pending"
        )

    def record_error(self, message: str) -> None:
        cleaned = (message or "").strip() or "Ukjent feil"
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {cleaned}"
        self._error_entries.append(entry)
        self._error_entries = self._error_entries[-6:]
        bullets = "".join(
            f"<li>{html.escape(item)}</li>" for item in self._error_entries
        )
        self._set_status_label(
            self.error_label, f"<ul>{bullets}</ul>", state="rejected"
        )

    def update_misc_info(
        self, entries: Optional[Sequence[Tuple[str, str]]] = None
    ) -> None:
        if not entries:
            self._set_status_label(
                self.misc_label,
                "Ingen tilleggsinformasjon tilgjengelig ennå.",
                state="pending",
            )
            return
        bullet_items = []
        for title, value in entries:
            if not value:
                continue
            bullet_items.append(
                f"<li><strong>{html.escape(title)}:</strong> {html.escape(value)}</li>"
            )
        if not bullet_items:
            self._set_status_label(
                self.misc_label,
                "Ingen tilleggsinformasjon tilgjengelig ennå.",
                state="pending",
            )
            return
        self._set_status_label(
            self.misc_label, f"<ul>{''.join(bullet_items)}</ul>", state="approved"
        )

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

    def _set_status_label(
        self, label: QLabel, message: str, *, state: StatusState = "pending"
    ) -> None:
        label.setText(message)
        label.setProperty("statusState", state)
        label.style().unpolish(label)
        label.style().polish(label)
        label.updateGeometry()
