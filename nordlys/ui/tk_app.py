"""Tkinter-basert GUI for Nordlys SAF-T analysator."""
from __future__ import annotations

import json
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, Iterable, List, Optional, Sequence
import xml.etree.ElementTree as ET

import pandas as pd

from ..brreg import fetch_brreg, find_first_by_exact_endkey, map_brreg_metrics
from ..constants import APP_TITLE
from ..saft import (
    SaftHeader,
    extract_ar_from_gl,
    extract_sales_taxbase_by_customer,
    ns4102_summary_from_tb,
    parse_customers,
    parse_saldobalanse,
    parse_saft_header,
)
from ..utils import format_currency, format_difference


class TkApp(tk.Tk):
    """Hovedapplikasjonen basert på Tkinter."""

    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1280x860")
        self.minsize(1060, 760)

        self._saft_df: Optional[pd.DataFrame] = None
        self._saft_summary: Optional[Dict[str, float]] = None
        self._header: Optional[SaftHeader] = None
        self._brreg_json: Optional[Dict[str, object]] = None
        self._brreg_map: Optional[Dict[str, Optional[float]]] = None
        self._cust_map: Dict[str, str] = {}
        self._sales_agg: Optional[pd.DataFrame] = None
        self._ar_agg: Optional[pd.DataFrame] = None

        self.create_widgets()

    # region UI-oppbygning
    def create_widgets(self) -> None:
        top = ttk.Frame(self, padding=10)
        top.pack(fill='x')
        self.btn_open = ttk.Button(top, text="Åpne SAF-T XML …", command=self.on_open)
        self.btn_open.pack(side='left')
        self.btn_brreg = ttk.Button(top, text="Hent fra Regnskapsregisteret", command=self.on_brreg, state='disabled')
        self.btn_brreg.pack(side='left', padx=(10, 0))
        self.btn_export = ttk.Button(top, text="Eksporter rapport (Excel)", command=self.on_export, state='disabled')
        self.btn_export.pack(side='left', padx=(10, 0))

        info = ttk.LabelFrame(self, text="Fil- og selskapsinformasjon", padding=10)
        info.pack(fill='x', padx=10, pady=(0, 10))
        self.var_company = tk.StringVar(value="Selskap: –")
        self.var_orgnr = tk.StringVar(value="Org.nr: –")
        self.var_period = tk.StringVar(value="Periode: –")
        ttk.Label(info, textvariable=self.var_company).grid(row=0, column=0, sticky='w', padx=5, pady=2)
        ttk.Label(info, textvariable=self.var_orgnr).grid(row=0, column=1, sticky='w', padx=5, pady=2)
        ttk.Label(info, textvariable=self.var_period).grid(row=0, column=2, sticky='w', padx=5, pady=2)

        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True, padx=10, pady=10)

        self.tab_tb = ttk.Frame(nb)
        nb.add(self.tab_tb, text="Saldobalanse")
        self.tree_tb = self._make_tree(self.tab_tb, ["Konto", "Kontonavn", "IB Debet", "IB Kredit", "Endring Debet", "Endring Kredit", "UB Debet", "UB Kredit"])

        self.tab_ns = ttk.Frame(nb)
        nb.add(self.tab_ns, text="NS 4102 (Oppsummering)")
        self.tree_ns = self._make_tree(self.tab_ns, ["Linje", "Beløp"])

        self.tab_rr = ttk.Frame(nb)
        nb.add(self.tab_rr, text="Regnskapsregisteret")
        self.text_json = tk.Text(self.tab_rr, height=20, wrap='none')
        self.text_json.pack(fill='both', expand=True, padx=5, pady=5)
        self.tree_map = self._make_tree(self.tab_rr, ["Felt", "Sti = Verdi"])

        self.tab_cmp = ttk.Frame(nb)
        nb.add(self.tab_cmp, text="Sammenligning (SAF-T vs. Brreg)")
        self.tree_cmp = self._make_tree(self.tab_cmp, ["Nøkkel", "SAF-T (Brreg-tilpasset)", "Brreg (siste år)", "Avvik"])

        self.tab_top = ttk.Frame(nb)
        nb.add(self.tab_top, text="Topp kunder")
        topbar = ttk.Frame(self.tab_top)
        topbar.pack(fill='x', padx=5, pady=5)
        ttk.Label(topbar, text="Antall:").pack(side='left')
        self.var_topn = tk.IntVar(value=10)
        self.spn_topn = ttk.Spinbox(topbar, from_=5, to=100, textvariable=self.var_topn, width=6)
        self.spn_topn.pack(side='left', padx=(4, 10))
        ttk.Label(topbar, text="Kilde:").pack(side='left')
        self.var_source = tk.StringVar(value='faktura')
        self.cmb_source = ttk.Combobox(topbar, state='readonly', textvariable=self.var_source, width=14, values=['faktura', 'reskontro'])
        self.cmb_source.pack(side='left', padx=(4, 10))
        self.btn_calc_top = ttk.Button(topbar, text="Beregn topp kunder", command=self.on_calc_top_customers)
        self.btn_calc_top.pack(side='left')
        self.tree_top = self._make_tree(self.tab_top, ["KundeID", "Kundenavn", "Fakturaer", "Omsetning (eks. mva)"])

        self.var_status = tk.StringVar(value="Klar.")
        status = ttk.Label(self, textvariable=self.var_status, anchor='w')
        status.pack(fill='x', padx=10, pady=(0, 8))

    def _make_tree(self, parent: tk.Widget, columns: Sequence[str]) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True, padx=5, pady=5)
        tree = ttk.Treeview(frame, columns=columns, show='headings', height=10)
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=220 if column in ('Kundenavn', 'Linje') else 170, anchor='w')
        vsb = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    # endregion

    # region Handlinger
    def on_open(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("SAF-T XML", "*.xml"), ("All files", "*.*")])
        if not path:
            return
        try:
            root = ET.parse(path).getroot()
            self._header = parse_saft_header(root)
            df = parse_saldobalanse(root)
            self._cust_map = parse_customers(root)
            self._sales_agg = extract_sales_taxbase_by_customer(root)
            self._ar_agg = extract_ar_from_gl(root)
            self._saft_df = df
            self._saft_summary = ns4102_summary_from_tb(df)
            self._update_header_fields()
            self._fill_tree_df(self.tree_tb, df)
            self._populate_summary()
            self.var_status.set("SAF-T lest. Topp kunder kan nå beregnes fra fakturaer (TaxBase/NetTotal).")
            self.btn_brreg.config(state='normal')
            self.btn_export.config(state='normal')
        except Exception as exc:  # pragma: no cover - vises i GUI
            messagebox.showerror("Feil ved lesing av SAF-T", str(exc))
            self.var_status.set("Feil ved lesing.")

    def on_calc_top_customers(self) -> None:
        source = self.var_source.get()
        topn = max(1, min(int(self.var_topn.get() or 10), 100))
        if source == 'faktura':
            if self._sales_agg is None or self._sales_agg.empty:
                messagebox.showinfo("Ingen fakturaer", "Fant ingen SalesInvoices med CustomerID/TaxBase/NetTotal i SAF‑T. Prøv 'reskontro'.")
                return
            data = self._sales_agg.copy()
            data['Kundenavn'] = data['CustomerID'].map(self._cust_map).fillna('')
            data = data.sort_values('OmsetningEksMva', ascending=False).head(topn)
            rows = [
                (row['CustomerID'], row['Kundenavn'], int(row['Fakturaer']), float(row['OmsetningEksMva']))
                for _, row in data.iterrows()
            ]
            self._fill_tree_rows(self.tree_top, ["KundeID", "Kundenavn", "Fakturaer", "Omsetning (eks. mva)"], rows, money_cols=[3])
            self.var_status.set(f"Topp kunder (fakturaer) beregnet (N={topn}).")
            return
        if self._ar_agg is None or self._ar_agg.empty:
            messagebox.showinfo("Ingen reskontro", "Fant ikke kunde-ID på reskontro (1500–1599) i SAF‑T.")
            return
        data = self._ar_agg.copy()
        data['Kundenavn'] = data['CustomerID'].map(self._cust_map).fillna('')
        data['OmsetningEksMva'] = data['AR_Debit']
        data['Fakturaer'] = None
        data = data.sort_values('AR_Debit', ascending=False).head(topn)
        rows = [
            (
                row['CustomerID'],
                row['Kundenavn'],
                int(row['Fakturaer']) if row['Fakturaer'] is not None else 0,
                float(row['OmsetningEksMva']),
            )
            for _, row in data.iterrows()
        ]
        self._fill_tree_rows(self.tree_top, ["KundeID", "Kundenavn", "Fakturaer", "Omsetning (eks. mva)"], rows, money_cols=[3])
        self.var_status.set(f"Topp kunder (reskontro) beregnet (N={topn}).")

    def on_brreg(self) -> None:
        if not self._header or not self._header.orgnr:
            messagebox.showwarning("Mangler org.nr", "Fant ikke org.nr i SAF-T-headeren.")
            return
        orgnr = self._header.orgnr
        try:
            js = fetch_brreg(orgnr)
        except Exception as exc:  # pragma: no cover - vises i GUI
            messagebox.showerror("Feil ved henting fra Regnskapsregisteret", str(exc))
            return
        self._brreg_json = js
        self.text_json.delete('1.0', 'end')
        self.text_json.insert('1.0', json.dumps(js, indent=2, ensure_ascii=False))
        self._brreg_map = map_brreg_metrics(js)
        rows: List[tuple[str, str]] = []

        def add_row(label: str, prefer_keys: Iterable[str]) -> None:
            hit = find_first_by_exact_endkey(js, prefer_keys, disallow_contains=['egenkapitalOgGjeld'] if 'sumEgenkapital' in prefer_keys else None)
            if not hit and 'sumEiendeler' in prefer_keys:
                hit = find_first_by_exact_endkey(js, ['sumEgenkapitalOgGjeld'])
            rows.append((label, f"{hit[0]} = {hit[1]}" if hit else "—"))

        add_row('Eiendeler (UB)', ['sumEiendeler'])
        add_row('Egenkapital (UB)', ['sumEgenkapital'])
        add_row('Gjeld (UB)', ['sumGjeld'])
        add_row('Driftsinntekter', ['driftsinntekter', 'sumDriftsinntekter', 'salgsinntekter'])
        add_row('EBIT', ['driftsresultat', 'ebit', 'driftsresultatFoerFinans'])
        add_row('Årsresultat', ['arsresultat', 'resultat', 'resultatEtterSkatt'])
        self._fill_tree_rows(self.tree_map, ["Felt", "Sti = Verdi"], rows)

        if not self._saft_summary:
            return
        cmp_rows: List[tuple[str, str, str, str]] = []

        def add_cmp(label: str, saf_v: Optional[float], br_v: Optional[float]) -> None:
            cmp_rows.append((label, format_currency(saf_v), format_currency(br_v), format_difference(saf_v, br_v)))

        add_cmp("Driftsinntekter", self._saft_summary['driftsinntekter'], self._brreg_map.get('driftsinntekter') if self._brreg_map else None)
        add_cmp("EBIT", self._saft_summary['ebit'], self._brreg_map.get('ebit') if self._brreg_map else None)
        add_cmp("Årsresultat", self._saft_summary['arsresultat'], self._brreg_map.get('arsresultat') if self._brreg_map else None)
        add_cmp("Eiendeler (UB)", self._saft_summary['eiendeler_UB_brreg'], self._brreg_map.get('eiendeler_UB') if self._brreg_map else None)
        add_cmp("Egenkapital (UB)", self._saft_summary['egenkapital_UB'], self._brreg_map.get('egenkapital_UB') if self._brreg_map else None)
        add_cmp("Gjeld (UB)", self._saft_summary['gjeld_UB_brreg'], self._brreg_map.get('gjeld_UB') if self._brreg_map else None)
        self._fill_tree_rows(
            self.tree_cmp,
            ["Nøkkel", "SAF-T (Brreg-tilpasset)", "Brreg (siste år)", "Avvik"],
            cmp_rows,
            money_cols=[1, 2, 3],
        )
        self.var_status.set("Data hentet.")

    def on_export(self) -> None:
        if self._saft_df is None:
            messagebox.showwarning("Ingenting å eksportere", "Last inn SAF-T først.")
            return
        out = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")], initialfile="SAFT_rapport.xlsx")
        if not out:
            return
        try:
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                self._saft_df.to_excel(writer, sheet_name='Saldobalanse', index=False)
                if self._saft_summary:
                    summary_df = pd.DataFrame([self._saft_summary]).T.reset_index()
                    summary_df.columns = ['Nøkkel', 'Beløp']
                    summary_df.to_excel(writer, sheet_name='NS4102_Sammendrag', index=False)
                if self._sales_agg is not None:
                    self._sales_agg.to_excel(writer, sheet_name='Sales_by_customer', index=False)
                if self._ar_agg is not None:
                    self._ar_agg.to_excel(writer, sheet_name='AR_agg', index=False)
                if self._brreg_json:
                    pd.json_normalize(self._brreg_json).to_excel(writer, sheet_name='Brreg_JSON', index=False)
                if self._brreg_map:
                    map_df = pd.DataFrame(list(self._brreg_map.items()), columns=['Felt', 'Verdi'])
                    map_df.to_excel(writer, sheet_name='Brreg_Mapping', index=False)
            self.var_status.set(f"Eksportert: {out}")
        except Exception as exc:  # pragma: no cover - vises i GUI
            messagebox.showerror("Feil ved eksport", str(exc))

    # endregion

    # region Hjelpere
    def _update_header_fields(self) -> None:
        if not self._header:
            return
        self.var_company.set(f"Selskap: {self._header.company_name or '–'}")
        self.var_orgnr.set(f"Org.nr: {self._header.orgnr or '–'}")
        per = f"{self._header.fiscal_year or '–'} P{self._header.period_start or '?'}–P{self._header.period_end or '?'}"
        self.var_period.set(f"Periode: {per}")

    def _populate_summary(self) -> None:
        if not self._saft_summary:
            return
        rows = [
            ("Driftsinntekter (3xxx)", self._saft_summary['driftsinntekter']),
            ("Varekostnad (4xxx)", self._saft_summary['varekostnad']),
            ("Lønn (5xxx)", self._saft_summary['lonn']),
            ("Andre driftskostn. (61xx–79xx, ekskl. 78xx)", self._saft_summary['andre_drift']),
            ("EBITDA", self._saft_summary['ebitda']),
            ("Avskrivninger (6000–6099 + 78xx)", self._saft_summary['avskrivninger']),
            ("EBIT", self._saft_summary['ebit']),
            ("Netto finans (8xxx, ekskl. 83xx/896x)", self._saft_summary['finans_netto']),
            ("Skatt (83xx)", self._saft_summary['skattekostnad']),
            ("Årsresultat", self._saft_summary['arsresultat']),
            ("Eiendeler (UB) – netto", self._saft_summary['eiendeler_UB']),
            ("Gjeld (UB) – netto", self._saft_summary['gjeld_UB']),
            ("Balanseavvik (netto)", self._saft_summary['balanse_diff']),
            ("Eiendeler (UB) – Brreg-tilpasset", self._saft_summary['eiendeler_UB_brreg']),
            ("Gjeld (UB) – Brreg-tilpasset", self._saft_summary['gjeld_UB_brreg']),
            ("Balanseavvik (Brreg-tilpasset)", self._saft_summary['balanse_diff_brreg']),
            ("Reklassifisert fra gjeld til eiendeler (21xx–29xx debet)", self._saft_summary['liab_debet_21xx_29xx']),
        ]
        self._fill_tree_rows(self.tree_ns, ["Linje", "Beløp"], rows, money_cols=[1])

    def _fill_tree_df(self, tree: ttk.Treeview, df: pd.DataFrame) -> None:
        tree.delete(*tree.get_children())
        columns = list(df.columns)
        tree['columns'] = columns
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=140, anchor='e' if column not in ('Konto', 'Kontonavn') else 'w')
        for _, row in df.iterrows():
            values = [row[column] for column in columns]
            tree.insert('', 'end', values=values)

    def _fill_tree_rows(
        self,
        tree: ttk.Treeview,
        columns: Sequence[str],
        rows: Iterable[Sequence[object]],
        money_cols: Optional[Sequence[int]] = None,
    ) -> None:
        tree.delete(*tree.get_children())
        tree['columns'] = columns
        money_cols = money_cols or []
        for index, column in enumerate(columns):
            tree.heading(column, text=column)
            tree.column(column, width=220 if index == 0 else 180, anchor='e' if index in money_cols else 'w')
        for row in rows:
            values = list(row)
            for index in money_cols:
                try:
                    if values[index] is None:
                        continue
                    values[index] = f"{float(values[index]):,.2f}"
                except Exception:
                    pass
            tree.insert('', 'end', values=values)

    # endregion


def create_app() -> TkApp:
    """Fabrikkfunksjon slik at alternative GUI-er kan gjenbruke logikken."""
    return TkApp()


def run() -> None:
    """Starter Tk-applikasjonen på en trygg måte."""
    try:
        app = create_app()
        app.mainloop()
    except Exception as exc:  # pragma: no cover - fallback dersom Tk ikke starter
        print("Kritisk feil:", exc, file=sys.stderr)
        sys.exit(1)


__all__ = ['TkApp', 'create_app', 'run']
