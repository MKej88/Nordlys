"""Setter opp venstremenyen i Nordlys."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtWidgets import QTreeWidgetItem

from .navigation import NavigationPanel
from .page_registry import REVISION_DEFINITIONS


class NavigationBuilder:
    """Legger inn alle menyvalg og kobler signalet for valg."""

    def __init__(self, panel: NavigationPanel) -> None:
        self._panel = panel

    def populate(
        self,
        on_selection_changed: Callable[
            [Optional[QTreeWidgetItem], Optional[QTreeWidgetItem]], None
        ],
    ) -> None:
        nav = self._panel
        import_item = nav.add_root("Import", "import")
        nav.add_root("Dashboard", "dashboard")

        planning_root = nav.add_root("Planlegging")
        nav.add_child(planning_root, "Saldobalanse", "plan.saldobalanse")
        nav.add_child(planning_root, "Hovedbok", "plan.hovedbok")
        nav.add_child(planning_root, "Kontroll IB", "plan.kontroll")
        nav.add_child(planning_root, "Regnskapsanalyse", "plan.regnskapsanalyse")
        nav.add_child(planning_root, "Vesentlighetsvurdering", "plan.vesentlighet")
        nav.add_child(planning_root, "Sammenstillingsanalyse", "plan.sammenstilling")

        revision_root = nav.add_root("Revisjon")
        for key, (title, _) in REVISION_DEFINITIONS.items():
            nav.add_child(revision_root, title, key)

        nav.tree.currentItemChanged.connect(on_selection_changed)
        nav.tree.setCurrentItem(import_item.item)
