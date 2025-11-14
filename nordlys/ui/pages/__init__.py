"""Sider for Nordlys-grensesnittet."""

from .analysis_pages import (
    ComparisonPage,
    RegnskapsanalysePage,
    SammenstillingsanalysePage,
    SummaryPage,
)
from .dashboard_page import DashboardPage
from .dataframe_page import DataFramePage, standard_tb_frame
from .import_page import ImportPage
from .revision_pages import (
    ChecklistPage,
    CostVoucherReviewPage,
    PurchasesApPage,
    SalesArPage,
    VoucherReviewResult,
)

__all__ = [
    "ComparisonPage",
    "RegnskapsanalysePage",
    "SammenstillingsanalysePage",
    "SummaryPage",
    "DashboardPage",
    "DataFramePage",
    "standard_tb_frame",
    "ImportPage",
    "ChecklistPage",
    "CostVoucherReviewPage",
    "PurchasesApPage",
    "SalesArPage",
    "VoucherReviewResult",
]
