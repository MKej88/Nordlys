"""Cache og hjelpefunksjoner for SAF-T datasett."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from ...industry_groups import IndustryClassification
from ...saft.loader import SaftLoadResult
from ...helpers.lazy_imports import lazy_import, lazy_pandas

pd = lazy_pandas()
saft = lazy_import("nordlys.saft")
saft_customers = lazy_import("nordlys.saft_customers")

__all__ = ["DatasetMetadata", "SaftDatasetStore"]


@dataclass(frozen=True)
class DatasetMetadata:
    """Metainformasjon for et tilgjengelig datasett."""

    key: str
    result: SaftLoadResult


class SaftDatasetStore:
    """Holder oversikt over innleste SAF-T-data og hjelpe-tabeller."""

    def __init__(self) -> None:
        self._results: Dict[str, SaftLoadResult] = {}
        self._positions: Dict[str, int] = {}
        self._years: Dict[str, Optional[int]] = {}
        self._orgnrs: Dict[str, Optional[str]] = {}
        self._order: List[str] = []
        self._current_key: Optional[str] = None
        self._current_result: Optional[SaftLoadResult] = None

        self._saft_df: Optional[pd.DataFrame] = None
        self._saft_summary: Optional[Dict[str, float]] = None
        self._header: Optional["saft.SaftHeader"] = None
        self._validation_result: Optional["saft.SaftValidationResult"] = None
        self._current_file: Optional[str] = None

        self._customers: Dict[str, "saft.CustomerInfo"] = {}
        self._cust_name_by_nr: Dict[str, str] = {}
        self._cust_id_to_nr: Dict[str, str] = {}
        self._suppliers: Dict[str, "saft.SupplierInfo"] = {}
        self._sup_name_by_nr: Dict[str, str] = {}
        self._sup_id_to_nr: Dict[str, str] = {}
        self._customer_sales: Optional[pd.DataFrame] = None
        self._supplier_purchases: Optional[pd.DataFrame] = None
        self._cost_vouchers: List["saft_customers.CostVoucher"] = []

        self._industry: Optional[IndustryClassification] = None
        self._industry_error: Optional[str] = None
        self._brreg_json: Optional[Dict[str, object]] = None
        self._brreg_map: Optional[Dict[str, Optional[float]]] = None

    # region Offentlige API-er
    def apply_batch(self, results: Sequence[SaftLoadResult]) -> None:
        """Lagrer resultatene fra SAF-T-importen i intern struktur."""

        self._results = {res.file_path: res for res in results}
        self._positions = {res.file_path: idx for idx, res in enumerate(results)}
        self._years = {
            res.file_path: self._resolve_dataset_year(res) for res in results
        }
        self._orgnrs = {
            res.file_path: self._resolve_dataset_orgnr(res) for res in results
        }
        self._order = self._sorted_dataset_keys()
        self._current_key = None
        self._current_result = None
        self._clear_active_dataset()

    def reset(self) -> None:
        """Nullstiller all data."""

        self._results = {}
        self._positions = {}
        self._years = {}
        self._orgnrs = {}
        self._order = []
        self._current_key = None
        self._current_result = None
        self._clear_active_dataset()

    def activate(self, key: str) -> bool:
        """Aktiverer et datasett og forbereder hjelpe-tabeller."""

        result = self._results.get(key)
        if result is None:
            return False

        previous_key = self._find_previous_dataset_key(key)
        previous_result = self._results.get(previous_key) if previous_key else None

        self._current_key = key
        self._current_result = result
        self._header = result.header
        self._saft_summary = result.summary
        self._validation_result = result.validation
        self._current_file = result.file_path
        self._industry = result.industry
        self._industry_error = result.industry_error
        self._brreg_json = result.brreg_json
        self._brreg_map = result.brreg_map

        previous_df = previous_result.dataframe if previous_result is not None else None
        self._saft_df = self._prepare_dataframe_with_previous(
            result.dataframe, previous_df
        )

        self._ingest_customers(result.customers)
        self._ingest_suppliers(result.suppliers)
        self._customer_sales = self._prepare_customer_sales(result.customer_sales)
        self._supplier_purchases = self._prepare_supplier_purchases(
            result.supplier_purchases
        )
        self._cost_vouchers = list(result.cost_vouchers)
        return True

    def dataset_items(self) -> List[DatasetMetadata]:
        """Returnerer alle tilgjengelige datasett i sortert rekkefølge."""

        return [
            DatasetMetadata(key=key, result=self._results[key])
            for key in self._order
            if key in self._results
        ]

    def dataset_label(self, result: SaftLoadResult) -> str:
        year = self._years.get(result.file_path)
        if year is None and result.analysis_year is not None:
            year = result.analysis_year
        if year is not None:
            return str(year)
        header = result.header
        if header and header.fiscal_year and str(header.fiscal_year).strip():
            return str(header.fiscal_year).strip()
        position = self._positions.get(result.file_path)
        if position is not None:
            return str(position + 1)
        return "1"

    def select_default_key(self) -> Optional[str]:
        if not self._order:
            return None
        for key in reversed(self._order):
            year = self._years.get(key)
            if year is not None:
                return key
        return self._order[-1]

    # endregion

    # region Egenskaper
    @property
    def has_customer_data(self) -> bool:
        return self._customer_sales is not None and not self._customer_sales.empty

    @property
    def has_supplier_data(self) -> bool:
        return (
            self._supplier_purchases is not None and not self._supplier_purchases.empty
        )

    @property
    def saft_df(self) -> Optional[pd.DataFrame]:
        return self._saft_df

    @property
    def saft_summary(self) -> Optional[Dict[str, float]]:
        return self._saft_summary

    @property
    def header(self) -> Optional["saft.SaftHeader"]:
        return self._header

    @property
    def validation_result(self) -> Optional["saft.SaftValidationResult"]:
        return self._validation_result

    @property
    def customer_sales(self) -> Optional[pd.DataFrame]:
        return self._customer_sales

    @property
    def supplier_purchases(self) -> Optional[pd.DataFrame]:
        return self._supplier_purchases

    @property
    def cost_vouchers(self) -> List["saft_customers.CostVoucher"]:
        return self._cost_vouchers

    @property
    def current_file(self) -> Optional[str]:
        return self._current_file

    @property
    def customer_sales_total(self) -> Optional[float]:
        """Summerer kundesalgene dersom data er tilgjengelig."""

        if self._customer_sales is None or self._customer_sales.empty:
            return None
        column = "Omsetning eks mva"
        if column not in self._customer_sales.columns:
            return None
        try:
            series = pd.to_numeric(
                self._customer_sales[column], errors="coerce"
            ).fillna(0.0)
        except Exception:
            return None
        total = float(series.sum())
        return total

    @property
    def sales_account_total(self) -> Optional[float]:
        """Henter driftsinntektene fra saldobalansens sammendrag."""

        if not self._saft_summary:
            return None
        value = self._saft_summary.get("driftsinntekter")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @property
    def customer_sales_balance_diff(self) -> Optional[float]:
        """Returnerer avviket mellom kundesalg og salgskonti."""

        sales_total = self.customer_sales_total
        revenue_total = self.sales_account_total
        if sales_total is None or revenue_total is None:
            return None
        return sales_total - revenue_total

    @property
    def industry(self) -> Optional[IndustryClassification]:
        return self._industry

    @property
    def industry_error(self) -> Optional[str]:
        return self._industry_error

    @property
    def brreg_json(self) -> Optional[Dict[str, object]]:
        return self._brreg_json

    @property
    def brreg_map(self) -> Optional[Dict[str, Optional[float]]]:
        return self._brreg_map

    @property
    def current_key(self) -> Optional[str]:
        return self._current_key

    @property
    def current_result(self) -> Optional[SaftLoadResult]:
        return self._current_result

    @property
    def current_year(self) -> Optional[int]:
        if self._current_key is None:
            return None
        return self._years.get(self._current_key)

    @property
    def current_year_text(self) -> Optional[str]:
        year = self.current_year
        if year is not None:
            return str(year)
        header = self._header
        if header and header.fiscal_year:
            text = str(header.fiscal_year).strip()
            return text or None
        return None

    @property
    def dataset_order(self) -> List[str]:
        return list(self._order)

    # endregion

    # region Delte hjelpefunksjoner
    def normalize_customer_key(self, value: object) -> Optional[str]:
        return self._normalize_identifier(value)

    def normalize_supplier_key(self, value: object) -> Optional[str]:
        return self._normalize_identifier(value)

    def lookup_customer_name(
        self, number: object, customer_id: object
    ) -> Optional[str]:
        number_key = self.normalize_customer_key(number)
        if number_key:
            name = self._cust_name_by_nr.get(number_key)
            if name:
                return name
        cid_key = self.normalize_customer_key(customer_id)
        if cid_key:
            info = self._customers.get(cid_key)
            if info and info.name:
                return info.name
            name = self._cust_name_by_nr.get(cid_key)
            if name:
                return name
        return None

    def lookup_supplier_name(
        self, number: object, supplier_id: object
    ) -> Optional[str]:
        number_key = self.normalize_supplier_key(number)
        if number_key:
            name = self._sup_name_by_nr.get(number_key)
            if name:
                return name
        sid_key = self.normalize_supplier_key(supplier_id)
        if sid_key:
            info = self._suppliers.get(sid_key)
            if info and info.name:
                return info.name
            name = self._sup_name_by_nr.get(sid_key)
            if name:
                return name
        return None

    def safe_float(self, value: object) -> float:
        try:
            if pd.isna(value):  # type: ignore[arg-type]
                return 0.0
        except Exception:
            pass
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    # endregion

    # region Interne hjelpere
    def _clear_active_dataset(self) -> None:
        self._saft_df = None
        self._saft_summary = None
        self._header = None
        self._validation_result = None
        self._current_file = None
        self._customers = {}
        self._cust_name_by_nr = {}
        self._cust_id_to_nr = {}
        self._suppliers = {}
        self._sup_name_by_nr = {}
        self._sup_id_to_nr = {}
        self._customer_sales = None
        self._supplier_purchases = None
        self._cost_vouchers = []
        self._industry = None
        self._industry_error = None
        self._brreg_json = None
        self._brreg_map = None

    def _resolve_dataset_year(self, result: SaftLoadResult) -> Optional[int]:
        if result.analysis_year is not None:
            return result.analysis_year
        header = result.header
        if header and header.fiscal_year:
            try:
                return int(str(header.fiscal_year).strip())
            except (TypeError, ValueError):
                return None
        return None

    def _resolve_dataset_orgnr(self, result: SaftLoadResult) -> Optional[str]:
        header = result.header
        if not header or not header.orgnr:
            return None
        raw_orgnr = str(header.orgnr).strip()
        if not raw_orgnr:
            return None
        normalized = "".join(ch for ch in raw_orgnr if ch.isdigit())
        if normalized:
            return normalized
        return raw_orgnr

    def _sorted_dataset_keys(self) -> List[str]:
        def sort_key(key: str) -> Tuple[int, int]:
            year = self._years.get(key)
            year_value = year if year is not None else 9999
            position = self._positions.get(key, 0)
            return (year_value, position)

        return sorted(self._results.keys(), key=sort_key)

    def _find_previous_dataset_key(self, current_key: str) -> Optional[str]:
        current_year = self._years.get(current_key)
        current_org = self._orgnrs.get(current_key)
        if current_year is None or not current_org:
            return None
        exact_year = current_year - 1
        for key, year in self._years.items():
            if key == current_key or year is None:
                continue
            if year == exact_year and self._orgnrs.get(key) == current_org:
                return key
        closest_key: Optional[str] = None
        closest_year: Optional[int] = None
        for key, year in self._years.items():
            if key == current_key or year is None:
                continue
            if self._orgnrs.get(key) != current_org:
                continue
            if year < current_year and (closest_year is None or year > closest_year):
                closest_key = key
                closest_year = year
        return closest_key

    def _prepare_dataframe_with_previous(
        self, dataframe: pd.DataFrame, previous: Optional[pd.DataFrame]
    ) -> pd.DataFrame:
        if previous is None or previous.empty:
            return dataframe

        df = dataframe.copy()
        prev = previous.copy()

        def _konto_series(frame: pd.DataFrame) -> Optional[pd.Series]:
            for column in ("Konto", "Kontonr", "Kontonummer", "AccountID", "Konto_int"):
                if column in frame.columns:
                    series = frame[column]
                    if column == "Konto_int":
                        # Konto_int er numerisk, men vi ønsker strengrepresentasjon for mappingen.
                        return series.apply(self._normalize_identifier)
                    return series.apply(self._normalize_identifier)
            return None

        current_keys = _konto_series(df)
        previous_keys = _konto_series(prev)

        previous_map: Optional[pd.Series] = None
        if previous_keys is not None:
            previous_ub = prev.get("UB_netto")
            if previous_ub is not None:
                previous_ub = pd.to_numeric(previous_ub, errors="coerce")
            else:
                debit = (
                    pd.to_numeric(prev["UB Debet"], errors="coerce").fillna(0.0)
                    if "UB Debet" in prev.columns
                    else pd.Series(0.0, index=prev.index, dtype=float)
                )
                credit = (
                    pd.to_numeric(prev["UB Kredit"], errors="coerce").fillna(0.0)
                    if "UB Kredit" in prev.columns
                    else pd.Series(0.0, index=prev.index, dtype=float)
                )
                previous_ub = debit - credit

            mapping_frame = pd.DataFrame(
                {
                    "_key": previous_keys,
                    "_value": previous_ub,
                }
            )
            mapping_frame = mapping_frame.dropna(subset=["_key"])
            if not mapping_frame.empty:
                previous_map = mapping_frame.groupby("_key")["_value"].sum()

        if current_keys is not None and previous_map is not None:
            df["forrige"] = current_keys.map(previous_map)

        prev = prev.add_prefix("Forrige ")
        df = pd.concat([df, prev], axis=1)
        return df

    def _prepare_customer_sales(
        self, dataframe: Optional[pd.DataFrame]
    ) -> Optional[pd.DataFrame]:
        if dataframe is None or dataframe.empty:
            return dataframe
        work = dataframe.copy()
        if "Kundenavn" in work.columns:
            mask = work["Kundenavn"].astype(str).str.strip() == ""
            if mask.any():
                work.loc[mask, "Kundenavn"] = work.loc[mask, "Kundenr"].apply(
                    lambda value: self.lookup_customer_name(value, value) or value
                )
        else:
            work["Kundenavn"] = work["Kundenr"].apply(
                lambda value: self.lookup_customer_name(value, value) or value
            )
        ordered_cols = ["Kundenr", "Kundenavn", "Omsetning eks mva"]
        ordered_cols += [col for col in ["Transaksjoner"] if col in work.columns]
        remaining = [col for col in work.columns if col not in ordered_cols]
        return work.loc[:, ordered_cols + remaining]

    def _prepare_supplier_purchases(
        self, dataframe: Optional[pd.DataFrame]
    ) -> Optional[pd.DataFrame]:
        if dataframe is None or dataframe.empty:
            return dataframe
        work = dataframe.copy()
        if "Leverandørnavn" in work.columns:
            mask = work["Leverandørnavn"].astype(str).str.strip() == ""
            if mask.any():
                work.loc[mask, "Leverandørnavn"] = work.loc[mask, "Leverandørnr"].apply(
                    lambda value: self.lookup_supplier_name(value, value) or value
                )
        else:
            work["Leverandørnavn"] = work["Leverandørnr"].apply(
                lambda value: self.lookup_supplier_name(value, value) or value
            )
        ordered_cols = ["Leverandørnr", "Leverandørnavn", "Innkjøp eks mva"]
        ordered_cols += [col for col in ["Transaksjoner"] if col in work.columns]
        remaining = [col for col in work.columns if col not in ordered_cols]
        return work.loc[:, ordered_cols + remaining]

    def _normalize_identifier(self, value: object) -> Optional[str]:
        if value is None:
            return None
        try:
            if pd.isna(value):  # type: ignore[arg-type]
                return None
        except Exception:
            pass
        text = str(value).strip()
        return text or None

    def _ingest_customers(self, customers: Dict[str, "saft.CustomerInfo"]) -> None:
        self._customers = {}
        self._cust_name_by_nr = {}
        self._cust_id_to_nr = {}
        for info in customers.values():
            name = (info.name or "").strip()
            raw_id = info.customer_id
            raw_number = info.customer_number or info.customer_id
            norm_id = self.normalize_customer_key(raw_id)
            norm_number = self.normalize_customer_key(raw_number)
            resolved_number = (
                norm_number or norm_id or self.normalize_customer_key(raw_id)
            )
            if (
                not resolved_number
                and isinstance(raw_number, str)
                and raw_number.strip()
            ):
                resolved_number = raw_number.strip()
            if not resolved_number and isinstance(raw_id, str) and raw_id.strip():
                resolved_number = raw_id.strip()

            customer_key = norm_id or (
                raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else None
            )
            if customer_key:
                self._customers[customer_key] = saft.CustomerInfo(
                    customer_id=customer_key,
                    customer_number=resolved_number or customer_key,
                    name=name,
                )

            keys = {raw_id, norm_id, raw_number, norm_number, resolved_number}
            keys = {key for key in keys if isinstance(key, str) and key}

            if resolved_number:
                norm_resolved = self.normalize_customer_key(resolved_number)
                all_number_keys = set(keys)
                if norm_resolved:
                    all_number_keys.add(norm_resolved)
                all_number_keys.add(resolved_number)
                for key in all_number_keys:
                    norm_key = self.normalize_customer_key(key)
                    if norm_key:
                        self._cust_id_to_nr[norm_key] = resolved_number
                    self._cust_id_to_nr[key] = resolved_number

            if name:
                for key in keys:
                    norm_key = self.normalize_customer_key(key)
                    if norm_key:
                        self._cust_name_by_nr[norm_key] = name
                    self._cust_name_by_nr[key] = name

    def _ingest_suppliers(self, suppliers: Dict[str, "saft.SupplierInfo"]) -> None:
        self._suppliers = {}
        self._sup_name_by_nr = {}
        self._sup_id_to_nr = {}
        for info in suppliers.values():
            name = (info.name or "").strip()
            raw_id = info.supplier_id
            raw_number = info.supplier_number or info.supplier_id
            norm_id = self.normalize_supplier_key(raw_id)
            norm_number = self.normalize_supplier_key(raw_number)
            resolved_number = (
                norm_number or norm_id or self.normalize_supplier_key(raw_id)
            )
            if (
                not resolved_number
                and isinstance(raw_number, str)
                and raw_number.strip()
            ):
                resolved_number = raw_number.strip()
            if not resolved_number and isinstance(raw_id, str) and raw_id.strip():
                resolved_number = raw_id.strip()

            supplier_key = norm_id or (
                raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else None
            )
            if supplier_key:
                self._suppliers[supplier_key] = saft.SupplierInfo(
                    supplier_id=supplier_key,
                    supplier_number=resolved_number or supplier_key,
                    name=name,
                )

            keys = {raw_id, norm_id, raw_number, norm_number, resolved_number}
            keys = {key for key in keys if isinstance(key, str) and key}

            if resolved_number:
                norm_resolved = self.normalize_supplier_key(resolved_number)
                all_number_keys = set(keys)
                if norm_resolved:
                    all_number_keys.add(norm_resolved)
                all_number_keys.add(resolved_number)
                for key in all_number_keys:
                    norm_key = self.normalize_supplier_key(key)
                    if norm_key:
                        self._sup_id_to_nr[norm_key] = resolved_number
                    self._sup_id_to_nr[key] = resolved_number

            if name:
                for key in keys:
                    norm_key = self.normalize_supplier_key(key)
                    if norm_key:
                        self._sup_name_by_nr[norm_key] = name
                    self._sup_name_by_nr[key] = name

    # endregion
