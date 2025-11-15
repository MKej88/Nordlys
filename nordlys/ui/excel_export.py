"""Funksjoner for å skrive SAF-T-data til Excel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..helpers.lazy_imports import lazy_pandas

if TYPE_CHECKING:
    from .data_manager import SaftDatasetStore

pd = lazy_pandas()


def export_dataset_to_excel(dataset_store: "SaftDatasetStore", file_name: str) -> None:
    """Skriv gjeldende datasett til en Excel-fil."""

    with pd.ExcelWriter(file_name, engine="xlsxwriter") as writer:
        saft_df = dataset_store.saft_df
        if saft_df is not None:
            saft_df.to_excel(writer, sheet_name="Saldobalanse", index=False)
        summary = dataset_store.saft_summary
        if summary:
            summary_df = pd.DataFrame([summary]).T.reset_index()
            summary_df.columns = ["Nøkkel", "Beløp"]
            summary_df.to_excel(
                writer,
                sheet_name="NS4102_Sammendrag",
                index=False,
            )
        customer_sales = dataset_store.customer_sales
        if customer_sales is not None:
            customer_sales.to_excel(writer, sheet_name="Sales_by_customer", index=False)
        brreg_json = dataset_store.brreg_json
        if brreg_json:
            pd.json_normalize(brreg_json).to_excel(
                writer, sheet_name="Brreg_JSON", index=False
            )
        brreg_map = dataset_store.brreg_map
        if brreg_map:
            map_df = pd.DataFrame(list(brreg_map.items()), columns=["Felt", "Verdi"])
            map_df.to_excel(writer, sheet_name="Brreg_Mapping", index=False)
