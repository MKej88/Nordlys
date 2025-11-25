"""Samler all registrering av sider i `PageManager`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Tuple

from PySide6.QtWidgets import QHeaderView

from .data_controller import SaftDataController
from .page_manager import PageManager

if TYPE_CHECKING:  # pragma: no cover - kun for typekontroll
    from .pages import (
        ComparisonPage,
        RegnskapsanalysePage,
        SammenstillingsanalysePage,
        SummaryPage,
    )
    from .pages.dashboard_page import DashboardPage
    from .pages.dataframe_page import DataFramePage
    from .pages.revision_pages import (
        ChecklistPage,
        CostVoucherReviewPage,
        FixedAssetsPage,
        PurchasesApPage,
        SalesArPage,
    )

REVISION_DEFINITIONS: Dict[str, Tuple[str, str]] = {
    "rev.innkjop": (
        "Innkjøp og leverandørgjeld",
        "Fokuser på varekjøp, kredittider og periodisering.",
    ),
    "rev.lonn": (
        "Lønn",
        "Kontroll av lønnskjøringer, skatt og arbeidsgiveravgift.",
    ),
    "rev.kostnad": (
        "Kostnad",
        "Analyse av driftskostnader og periodisering.",
    ),
    "rev.driftsmidler": (
        "Driftsmidler",
        "Verifikasjon av investeringer og avskrivninger.",
    ),
    "rev.finans": (
        "Finans og likvid",
        "Bank, finansielle instrumenter og kontantstrøm.",
    ),
    "rev.varelager": (
        "Varelager og varekjøp",
        "Telling, nedskrivninger og bruttomargin.",
    ),
    "rev.salg": (
        "Salg og kundefordringer",
        "Omsetning, cut-off og reskontro.",
    ),
    "rev.mva": (
        "MVA",
        "Kontroll av avgiftsbehandling og rapportering.",
    ),
}


class PageRegistry:
    """Oppretter og registrerer alle sider i `PageManager`."""

    def __init__(
        self, manager: PageManager, data_controller: SaftDataController
    ) -> None:
        self._manager = manager
        self._data_controller = data_controller

    def register_all(self) -> None:
        from .pages.import_page import ImportPage

        self._manager.register_page("import", ImportPage(), attr="import_page")

        self._manager.register_lazy_page(
            "dashboard", self._build_dashboard_page, attr="dashboard_page"
        )
        self._manager.register_lazy_page(
            "plan.saldobalanse",
            self._build_saldobalanse_page,
            attr="saldobalanse_page",
        )
        self._manager.register_lazy_page(
            "plan.kontroll",
            self._build_kontroll_page,
            attr="kontroll_page",
        )
        self._manager.register_lazy_page(
            "plan.regnskapsanalyse",
            self._build_regnskap_page,
            attr="regnskap_page",
        )
        self._manager.register_lazy_page(
            "plan.vesentlighet",
            self._build_vesentlig_page,
            attr="vesentlig_page",
        )
        self._manager.register_lazy_page(
            "plan.sammenstilling",
            self._build_sammenstilling_page,
            attr="sammenstilling_page",
        )

        for key, (title, subtitle) in REVISION_DEFINITIONS.items():
            if key == "rev.salg":
                self._manager.register_lazy_page(
                    key,
                    lambda title=title, subtitle=subtitle: self._build_sales_page(
                        title, subtitle
                    ),
                    attr="sales_ar_page",
                )
            elif key == "rev.innkjop":
                self._manager.register_lazy_page(
                    key,
                    lambda title=title, subtitle=subtitle: self._build_purchases_page(
                        title, subtitle
                    ),
                    attr="purchases_ap_page",
                )
            elif key == "rev.kostnad":
                self._manager.register_lazy_page(
                    key,
                    lambda title=title, subtitle=subtitle: self._build_cost_page(
                        title, subtitle
                    ),
                    attr="cost_review_page",
                )
            elif key == "rev.driftsmidler":
                self._manager.register_lazy_page(
                    key,
                    lambda title=title, subtitle=subtitle: self._build_fixed_assets_page(
                        title, subtitle
                    ),
                    attr="fixed_assets_page",
                )
            else:
                self._manager.register_lazy_page(
                    key,
                    lambda key=key, title=title, subtitle=subtitle: self._build_checklist_page(
                        key, title, subtitle
                    ),
                )

    def _build_dashboard_page(self) -> DashboardPage:
        from .pages.dashboard_page import DashboardPage

        return DashboardPage()

    def _build_saldobalanse_page(self) -> DataFramePage:
        from .pages.dataframe_page import DataFramePage, standard_tb_frame

        return DataFramePage(
            "Saldobalanse",
            "Viser saldobalansen slik den er rapportert i SAF-T.",
            frame_builder=standard_tb_frame,
            money_columns=("IB", "Endringer", "UB"),
            header_mode=QHeaderView.ResizeToContents,
            full_window=True,
        )

    def _build_kontroll_page(self) -> ComparisonPage:
        from .pages import ComparisonPage

        return ComparisonPage(
            "Kontroll av inngående balanse",
            "Sammenligner SAF-T mot Regnskapsregisteret for å avdekke avvik i inngående balanse.",
        )

    def _build_regnskap_page(self) -> RegnskapsanalysePage:
        from .pages import RegnskapsanalysePage

        return RegnskapsanalysePage()

    def _build_vesentlig_page(self) -> SummaryPage:
        from .pages import SummaryPage

        return SummaryPage(
            "Vesentlighetsvurdering",
            "Nøkkeltall som understøtter fastsettelse av vesentlighetsgrenser.",
        )

    def _build_sammenstilling_page(self) -> SammenstillingsanalysePage:
        from .pages import SammenstillingsanalysePage

        return SammenstillingsanalysePage()

    def _build_sales_page(self, title: str, subtitle: str) -> SalesArPage:
        from .pages.revision_pages import SalesArPage

        return SalesArPage(title, subtitle, self._data_controller.on_calc_top_customers)

    def _build_purchases_page(self, title: str, subtitle: str) -> PurchasesApPage:
        from .pages.revision_pages import PurchasesApPage

        return PurchasesApPage(
            title, subtitle, self._data_controller.on_calc_top_suppliers
        )

    def _build_cost_page(self, title: str, subtitle: str) -> CostVoucherReviewPage:
        from .pages.revision_pages import CostVoucherReviewPage

        return CostVoucherReviewPage(title, subtitle)

    def _build_fixed_assets_page(
        self, title: str, subtitle: str
    ) -> "FixedAssetsPage":
        from .pages.revision_pages import FixedAssetsPage

        return FixedAssetsPage(title, subtitle)

    def _build_checklist_page(
        self, _key: str, title: str, subtitle: str
    ) -> ChecklistPage:
        from .pages.revision_pages import ChecklistPage

        return ChecklistPage(title, subtitle)
