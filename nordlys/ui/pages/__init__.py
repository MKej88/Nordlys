"""Sider for Nordlys-grensesnittet."""

from .comparison_page import ComparisonPage
from .regnskapsanalyse_page import RegnskapsanalysePage
from .sammenstilling_page import SammenstillingsanalysePage
from .summary_page import SummaryPage
from .dashboard_page import DashboardPage
from .dataframe_page import DataFramePage, standard_tb_frame
from .import_page import ImportPage
from .hovedbok_page import HovedbokPage
from .revision_pages import (
    ChecklistPage,
    CostVoucherReviewPage,
    MvaDeviationPage,
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
    "HovedbokPage",
    "ChecklistPage",
    "CostVoucherReviewPage",
    "MvaDeviationPage",
    "PurchasesApPage",
    "SalesArPage",
    "VoucherReviewResult",
]
