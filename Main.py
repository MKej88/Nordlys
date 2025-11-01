#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SAF-T Analysator GUI v3.5
Nyheter:
- "Topp kunder" henter nå primært omsetning eks. mva direkte fra SalesInvoices:
  * CustomerID fra Invoice/CustomerID eller Invoice/Customer/CustomerID
  * Beløp = DocumentTotals/NetTotal (hvis finnes), ellers SUM(alle TaxBase under Invoice)
- Kundenavn hentes fra MasterFiles/Customer (CustomerID -> Name). 
- Fallback: Hvis SalesInvoices mangler, brukes reskontro (1500–1599) som i tidligere versjoner.
"""
import json
import sys
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import xml.etree.ElementTree as ET
import requests
import pandas as pd
from typing import Dict, Any, List, Tuple, Optional

APP_TITLE = "SAF-T Analysator v3.5 + Regnskapsregister (åpen del)"
BRREG_URL_TMPL = "https://data.brreg.no/regnskapsregisteret/regnskap/{orgnr}"
NS = {'n1': 'urn:StandardAuditFile-Taxation-Financial:NO'}

def _to_float(x: Optional[str]) -> float:
    if x in (None, ''):
        return 0.0
    try:
        return float(str(x).replace(' ', '').replace('\\xa0','').replace(',',''))
    except:
        try:
            return float(x)
        except:
            return 0.0

def _text(el: Optional[ET.Element]) -> Optional[str]:
    return (el.text or '').strip() if el is not None and el.text else None

def _findall_any_ns(inv: ET.Element, localname: str):
    res = []
    for e in inv.iter():
        if e.tag.split('}')[-1].lower() == localname.lower():
            res.append(e)
    return res

def parse_saft_header(root: ET.Element) -> Dict[str, Optional[str]]:
    header = root.find('n1:Header', NS)
    comp = header.find('n1:Company', NS) if header is not None else None
    sel = header.find('n1:SelectionCriteria', NS) if header is not None else None
    def txt(elem, tag):
        c = elem.find(f"n1:{tag}", NS) if elem is not None else None
        return (c.text or '').strip() if c is not None and c.text is not None else None
    return {
        'company_name': txt(comp, 'Name'),
        'orgnr': txt(comp, 'RegistrationNumber'),
        'fiscal_year': txt(sel, 'PeriodEndYear'),
        'period_start': txt(sel, 'PeriodStart'),
        'period_end': txt(sel, 'PeriodEnd'),
        'file_version': (header.find('n1:AuditFileVersion', NS).text if header is not None and header.find('n1:AuditFileVersion', NS) is not None else None)
    }

def parse_saldobalanse(root: ET.Element) -> pd.DataFrame:
    gl = root.find('n1:MasterFiles/n1:GeneralLedgerAccounts', NS)
    rows = []
    if gl is None:
        return pd.DataFrame(columns=['Konto','Kontonavn','IB Debet','IB Kredit','Endring Debet','Endring Kredit','UB Debet','UB Kredit'])
    def get(acct, tag):
        e = acct.find(f"n1:{tag}", NS)
        return (e.text or '').strip() if e is not None and e.text is not None else None
    for acct in gl.findall('n1:Account', NS):
        konto = get(acct, 'AccountID')
        navn = get(acct, 'AccountDescription') or ''
        od = _to_float(get(acct, 'OpeningDebitBalance'))
        oc = _to_float(get(acct, 'OpeningCreditBalance'))
        cd = _to_float(get(acct, 'ClosingDebitBalance'))
        cc = _to_float(get(acct, 'ClosingCreditBalance'))
        rows.append({
            'Konto': konto, 'Kontonavn': navn,
            'IB Debet': od, 'IB Kredit': oc,
            'Endring Debet': 0.0, 'Endring Kredit': 0.0,
            'UB Debet': cd, 'UB Kredit': cc
        })
    df = pd.DataFrame(rows)
    df['IB_netto'] = df['IB Debet'].fillna(0) - df['IB Kredit'].fillna(0)
    df['UB_netto'] = df['UB Debet'].fillna(0) - df['UB Kredit'].fillna(0)
    end = df['UB_netto'] - df['IB_netto']
    df['Endring Debet'] = end.where(end>0, 0.0)
    df['Endring Kredit'] = (-end).where(end<0, 0.0)
    def konto_to_int(x):
        try:
            return int(float(str(x).strip()))
        except:
            if x is None:
                return None
            s = ''.join(ch for ch in str(x) if ch.isdigit())
            return int(s) if s else None
    df['Konto_int'] = df['Konto'].apply(konto_to_int)
    return df

def ns4102_summary_from_tb(df: pd.DataFrame) -> Dict[str, float]:
    work = df.copy()
    work = work[~work['Konto_int'].isna()].copy()
    work['Konto_int'] = work['Konto_int'].astype(int)
    work['IB_netto'] = work['IB Debet'].fillna(0) - work['IB Kredit'].fillna(0)
    work['UB_netto'] = work['UB Debet'].fillna(0) - work['UB Kredit'].fillna(0)
    work['END_netto'] = work['Endring Debet'].fillna(0) - work['Endring Kredit'].fillna(0)
    def s(col, a, b):
        m = (work['Konto_int']>=a) & (work['Konto_int']<=b)
        return work.loc[m, col].sum()
    driftsinntekter = -s('END_netto', 3000, 3999)
    varekostnad = s('END_netto', 4000, 4999)
    lonn = s('END_netto', 5000, 5999)
    avskr = s('END_netto', 6000, 6099) + s('END_netto', 7800, 7899)
    andre_drift = s('END_netto', 6100, 7999) - s('END_netto', 7800, 7899)
    ebitda = driftsinntekter - (varekostnad + lonn + andre_drift)
    ebit = ebitda - avskr
    finans = -(s('END_netto', 8000, 8299) + s('END_netto', 8400, 8899))
    skatt = s('END_netto', 8300, 8399)
    ebt = ebit + finans
    arsresultat = ebt - skatt
    anlegg_UB = s('UB_netto', 1000, 1399)
    omlop_UB = s('UB_netto', 1400, 1999)
    eiendeler_netto = anlegg_UB + omlop_UB
    egenkap_UB = -s('UB_netto', 2000, 2099)
    liab = work[(work['Konto_int']>=2100)&(work['Konto_int']<=2999)]
    liab_kreditt = -liab.loc[liab['UB_netto']<0, 'UB_netto'].sum()
    liab_debet = liab.loc[liab['UB_netto']>0, 'UB_netto'].sum()
    gjeld_netto = liab_kreditt - liab_debet
    balanse_diff_netto = eiendeler_netto - (egenkap_UB + gjeld_netto)
    eiendeler_brreg = eiendeler_netto + liab_debet
    gjeld_brreg = liab_kreditt
    balanse_diff_brreg = eiendeler_brreg - (egenkap_UB + gjeld_brreg)
    return {
        'driftsinntekter': driftsinntekter,
        'varekostnad': varekostnad,
        'lonn': lonn,
        'avskrivninger': avskr,
        'andre_drift': andre_drift,
        'ebitda': ebitda,
        'ebit': ebit,
        'finans_netto': finans,
        'skattekostnad': skatt,
        'ebt': ebt,
        'arsresultat': arsresultat,
        'eiendeler_UB': eiendeler_netto,
        'egenkapital_UB': egenkap_UB,
        'gjeld_UB': gjeld_netto,
        'balanse_diff': balanse_diff_netto,
        'eiendeler_UB_brreg': eiendeler_brreg,
        'gjeld_UB_brreg': gjeld_brreg,
        'balanse_diff_brreg': balanse_diff_brreg,
        'liab_debet_21xx_29xx': liab_debet
    }

def parse_customers(root: ET.Element) -> Dict[str, str]:
    custs = {}
    for c in root.findall('.//n1:MasterFiles/n1:Customer', NS):
        cid = (c.find('n1:CustomerID', NS).text or '').strip() if c.find('n1:CustomerID', NS) is not None and c.find('n1:CustomerID', NS).text else None
        nm = (c.find('n1:Name', NS).text or '').strip() if c.find('n1:Name', NS) is not None and c.find('n1:Name', NS).text else ''
        if cid:
            custs[cid] = nm
    return custs

def _findall_any_ns(inv: ET.Element, localname: str):
    res = []
    for e in inv.iter():
        if e.tag.split('}')[-1].lower() == localname.lower():
            res.append(e)
    return res

def extract_sales_taxbase_by_customer(root: ET.Element) -> pd.DataFrame:
    rows = []
    for inv in root.findall('.//n1:SourceDocuments/n1:SalesInvoices/n1:Invoice', NS):
        custid = None
        for path in ['n1:CustomerID', 'n1:Customer/n1:CustomerID']:
            el = inv.find(path, NS)
            if el is not None and el.text and el.text.strip():
                custid = el.text.strip()
                break
        if not custid:
            continue
        net_el = inv.find('n1:DocumentTotals/n1:NetTotal', NS)
        amount = _to_float((net_el.text or '').strip() if net_el is not None and net_el.text else None)
        if amount == 0.0:
            net2 = inv.find('n1:DocumentTotals/n1:InvoiceNetTotal', NS)
            amount = _to_float((net2.text or '').strip() if net2 is not None and net2.text else None)
        if amount == 0.0:
            bases = _findall_any_ns(inv, 'TaxBase')
            s = 0.0
            for b in bases:
                s += _to_float((b.text or '').strip() if b is not None and b.text else None)
            amount = s
        rows.append({'CustomerID': custid, 'NetExVAT': float(amount if amount is not None else 0.0)})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    grp = df.groupby('CustomerID')['NetExVAT'].agg(['sum','count']).reset_index()
    grp.rename(columns={'sum':'OmsetningEksMva','count':'Fakturaer'}, inplace=True)
    return grp

def extract_ar_from_gl(root: ET.Element) -> pd.DataFrame:
    def _get_amount(line: ET.Element, tag: str) -> float:
        el = line.find(f'n1:{tag}', NS)
        if el is not None and el.text and el.text.strip():
            return _to_float(el.text)
        a = line.find(f'n1:{tag}/n1:Amount', NS)
        if a is not None and a.text and a.text.strip():
            return _to_float(a.text)
        return 0.0
    rows = []
    for line in root.findall('.//n1:GeneralLedgerEntries/n1:Journal/n1:Transaction/n1:Line', NS):
        cid = None
        for el in line.iter():
            tag = el.tag.split('}')[-1].lower()
            if 'customer' in tag and 'id' in tag and el.text and el.text.strip():
                cid = el.text.strip()
                break
        if not cid:
            continue
        acct_el = line.find('n1:AccountID', NS)
        acct = (acct_el.text or '').strip() if acct_el is not None and acct_el.text else ''
        acct_digits = ''.join(ch for ch in acct if ch.isdigit())
        acct_i = int(acct_digits) if acct_digits else 0
        if 1500 <= acct_i <= 1599:
            debit = _get_amount(line, 'DebitAmount')
            credit = _get_amount(line, 'CreditAmount')
            rows.append({'CustomerID': cid, 'AR_Debit': debit, 'AR_Credit': credit})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    grp = df.groupby('CustomerID').agg({'AR_Debit':'sum','AR_Credit':'sum'}).reset_index()
    grp['AR_Netto'] = grp['AR_Debit'] - grp['AR_Credit']
    return grp

def fetch_brreg(orgnr: str) -> dict:
    url = BRREG_URL_TMPL.format(orgnr=orgnr)
    r = requests.get(url, headers={'Accept': 'application/json'}, timeout=20)
    r.raise_for_status()
    return r.json()

def find_numbers(d, path=''):
    found = []
    if isinstance(d, dict):
        for k, v in d.items():
            newp = f"{path}.{k}" if path else k
            found.extend(find_numbers(v, newp))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            newp = f"{path}[{i}]"
            found.extend(find_numbers(v, newp))
    else:
        try:
            if isinstance(d, (int, float)) and not isinstance(d, bool):
                found.append((path, float(d)))
        except:
            pass
    return found

def _last_key(seg_path: str) -> str:
    p = seg_path.split('.')
    while p:
        last = p[-1]
        if '[' in last:
            last = last.split(']')[-1]
        if last and not last.endswith(']'):
            return last
        p = p[:-1]
    return ''

def find_first_by_exact_endkey(d, prefer_keys, disallow_contains=None):
    disallow_contains = disallow_contains or []
    nums = find_numbers(d)
    for k in prefer_keys:
        for path, val in nums:
            lk = _last_key(path).lower()
            if lk == k.lower() and not any(bad.lower() in path.lower() for bad in disallow_contains):
                return (path, val)
    for k in prefer_keys:
        for path, val in nums:
            if k.lower() in path.lower() and not any(bad.lower() in path.lower() for bad in disallow_contains):
                return (path, val)
    return None

def map_brreg_metrics(json_obj):
    mapped = {}
    hit_eiendeler = find_first_by_exact_endkey(json_obj, ['sumEiendeler'])
    if not hit_eiendeler:
        hit_eiendeler = find_first_by_exact_endkey(json_obj, ['sumEgenkapitalOgGjeld'])
    mapped['eiendeler_UB'] = hit_eiendeler[1] if hit_eiendeler else None
    hit_ek = find_first_by_exact_endkey(json_obj, ['sumEgenkapital'], disallow_contains=['EgenkapitalOgGjeld','egenkapitalOgGjeld'])
    mapped['egenkapital_UB'] = hit_ek[1] if hit_ek else None
    hit_gjeld = find_first_by_exact_endkey(json_obj, ['sumGjeld'])
    mapped['gjeld_UB'] = hit_gjeld[1] if hit_gjeld else None
    for key, hints in [('driftsinntekter', ['driftsinntekter','sumDriftsinntekter','salgsinntekter']),
                       ('ebit', ['driftsresultat','ebit','driftsresultatFoerFinans']),
                       ('arsresultat', ['arsresultat','resultat','resultatEtterSkatt'])]:
        hit = find_first_by_exact_endkey(json_obj, hints)
        mapped[key] = hit[1] if hit else None
    return mapped

def _fmt_kroner(x):
    try:
        return f"{round(float(x)):,.0f}"
    except:
        return "—"

def _fmt_diff(a, b):
    try:
        return f"{round(float(a) - float(b)):,.0f}"
    except:
        return "—"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1280x860")
        self.minsize(1060, 760)
        self._saft_df = None
        self._saft_summary = None
        self._header = None
        self._brreg_json = None
        self._brreg_map = None
        self._cust_map = {}
        self._sales_agg = None
        self._ar_agg = None
        self.create_widgets()

    def create_widgets(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill='x')
        self.btn_open = ttk.Button(top, text="Åpne SAF-T XML …", command=self.on_open)
        self.btn_open.pack(side='left')
        self.btn_brreg = ttk.Button(top, text="Hent fra Regnskapsregisteret", command=self.on_brreg, state='disabled')
        self.btn_brreg.pack(side='left', padx=(10,0))
        self.btn_export = ttk.Button(top, text="Eksporter rapport (Excel)", command=self.on_export, state='disabled')
        self.btn_export.pack(side='left', padx=(10,0))

        info = ttk.LabelFrame(self, text="Fil- og selskapsinformasjon", padding=10)
        info.pack(fill='x', padx=10, pady=(0,10))
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
        self.tree_tb = self._make_tree(self.tab_tb, ["Konto","Kontonavn","IB Debet","IB Kredit","Endring Debet","Endring Kredit","UB Debet","UB Kredit"])

        self.tab_ns = ttk.Frame(nb)
        nb.add(self.tab_ns, text="NS 4102 (Oppsummering)")
        self.tree_ns = self._make_tree(self.tab_ns, ["Linje","Beløp"])

        self.tab_rr = ttk.Frame(nb)
        nb.add(self.tab_rr, text="Regnskapsregisteret")
        self.text_json = tk.Text(self.tab_rr, height=20, wrap='none')
        self.text_json.pack(fill='both', expand=True, padx=5, pady=5)
        self.tree_map = self._make_tree(self.tab_rr, ["Felt","Sti = Verdi"])

        self.tab_cmp = ttk.Frame(nb)
        nb.add(self.tab_cmp, text="Sammenligning (SAF-T vs. Brreg)")
        self.tree_cmp = self._make_tree(self.tab_cmp, ["Nøkkel","SAF-T (Brreg-tilpasset)","Brreg (siste år)","Avvik"])

        # Topp kunder
        self.tab_top = ttk.Frame(nb)
        nb.add(self.tab_top, text="Topp kunder")
        topbar = ttk.Frame(self.tab_top)
        topbar.pack(fill='x', padx=5, pady=5)
        ttk.Label(topbar, text="Antall:").pack(side='left')
        self.var_topn = tk.IntVar(value=10)
        self.spn_topn = ttk.Spinbox(topbar, from_=5, to=100, textvariable=self.var_topn, width=6)
        self.spn_topn.pack(side='left', padx=(4,10))
        ttk.Label(topbar, text="Kilde:").pack(side='left')
        self.var_source = tk.StringVar(value='faktura')
        self.cmb_source = ttk.Combobox(topbar, state='readonly', textvariable=self.var_source, width=14, values=['faktura','reskontro'])
        self.cmb_source.pack(side='left', padx=(4,10))
        self.btn_calc_top = ttk.Button(topbar, text="Beregn topp kunder", command=self.on_calc_top_customers)
        self.btn_calc_top.pack(side='left')
        self.tree_top = self._make_tree(self.tab_top, ["KundeID","Kundenavn","Fakturaer","Omsetning (eks. mva)"])

        self.var_status = tk.StringVar(value="Klar.")
        status = ttk.Label(self, textvariable=self.var_status, anchor='w')
        status.pack(fill='x', padx=10, pady=(0,8))

    def _make_tree(self, parent, cols):
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True, padx=5, pady=5)
        tree = ttk.Treeview(frame, columns=cols, show='headings', height=10)
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=220 if c in ('Kundenavn','Linje') else 170, anchor='w')
        vsb = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    def on_open(self):
        path = filedialog.askopenfilename(filetypes=[("SAF-T XML","*.xml"),("All files","*.*")])
        if not path:
            return
        try:
            root = ET.parse(path).getroot()
            self._header = parse_saft_header(root)
            df = parse_saldobalanse(root)
            self._cust_map = parse_customers(root)
            self._sales_agg = extract_sales_taxbase_by_customer(root)  # ny primærkilde
            self._ar_agg = extract_ar_from_gl(root)  # fallback
            self._saft_df = df
            self._saft_summary = ns4102_summary_from_tb(df)
            self.var_company.set(f"Selskap: {self._header.get('company_name') or '–'}")
            self.var_orgnr.set(f"Org.nr: {self._header.get('orgnr') or '–'}")
            per = f"{self._header.get('fiscal_year') or '–'} P{self._header.get('period_start') or '?'}–P{self._header.get('period_end') or '?'}"
            self.var_period.set(f"Periode: {per}")
            self._fill_tree_df(self.tree_tb, df)
            ns_rows = [
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
            self._fill_tree_rows(self.tree_ns, ["Linje","Beløp"], ns_rows, money_cols=[1])
            self.var_status.set("SAF-T lest. Topp kunder kan nå beregnes fra fakturaer (TaxBase/NetTotal).")
            self.btn_brreg.config(state='normal')
            self.btn_export.config(state='normal')
        except Exception as e:
            messagebox.showerror("Feil ved lesing av SAF-T", str(e))
            self.var_status.set("Feil ved lesing.")

    def _fill_tree_df(self, tree, df):
        tree.delete(*tree.get_children())
        cols = list(df.columns)
        tree["columns"] = cols
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=140, anchor='e' if c not in ('Konto','Kontonavn') else 'w')
        for _, row in df.iterrows():
            vals = [row[c] for c in cols]
            tree.insert('', 'end', values=vals)

    def _fill_tree_rows(self, tree, cols, rows, money_cols=[]):
        tree.delete(*tree.get_children())
        tree["columns"] = cols
        for i, c in enumerate(cols):
            tree.heading(c, text=c)
            tree.column(c, width=220 if i==0 else 180, anchor='e' if i in money_cols else 'w')
        for r in rows:
            vals = list(r)
            for i in money_cols:
                try:
                    if vals[i] is None:
                        continue
                    vals[i] = f"{float(vals[i]):,.2f}"
                except:
                    pass
            tree.insert('', 'end', values=vals)

    def on_calc_top_customers(self):
        src = self.var_source.get()
        topn = max(1, min(int(self.var_topn.get() or 10), 100))
        if src == 'faktura':
            if self._sales_agg is None or self._sales_agg.empty:
                messagebox.showinfo("Ingen fakturaer", "Fant ingen SalesInvoices med CustomerID/TaxBase/NetTotal i SAF‑T. Prøv 'reskontro'.")
                return
            g = self._sales_agg.copy()
            g['Kundenavn'] = g['CustomerID'].map(self._cust_map).fillna('')
            g = g.sort_values('OmsetningEksMva', ascending=False).head(topn)
            rows = [(r['CustomerID'], r['Kundenavn'], int(r['Fakturaer']), float(r['OmsetningEksMva'])) for _, r in g.iterrows()]
            self._fill_tree_rows(self.tree_top, ["KundeID","Kundenavn","Fakturaer","Omsetning (eks. mva)"], rows, money_cols=[3])
            self.var_status.set(f"Topp kunder (fakturaer) beregnet (N={topn}).")
            return
        else:
            if self._ar_agg is None or self._ar_agg.empty:
                messagebox.showinfo("Ingen reskontro", "Fant ikke kunde-ID på reskontro (1500–1599) i SAF‑T.")
                return
            g = self._ar_agg.copy()
            g['Kundenavn'] = g['CustomerID'].map(self._cust_map).fillna('')
            g['OmsetningEksMva'] = g['AR_Debit']
            g['Fakturaer'] = None
            g = g.sort_values('AR_Debit', ascending=False).head(topn)
            rows = [(r['CustomerID'], r['Kundenavn'], r['Fakturaer'] if r['Fakturaer'] is not None else 0, float(r['OmsetningEksMva'])) for _, r in g.iterrows()]
            self._fill_tree_rows(self.tree_top, ["KundeID","Kundenavn","Fakturaer","Omsetning (eks. mva)"], rows, money_cols=[3])
            self.var_status.set(f"Topp kunder (reskontro) beregnet (N={topn}).")

    def on_brreg(self):
        if not self._header or not self._header.get('orgnr'):
            messagebox.showwarning("Mangler org.nr", "Fant ikke org.nr i SAF-T-headeren.")
            return
        orgnr = self._header['orgnr']
        try:
            js = fetch_brreg(orgnr)
        except Exception as e:
            messagebox.showerror("Feil ved henting fra Regnskapsregisteret", str(e))
            return
        self._brreg_json = js
        self.text_json.delete('1.0', 'end')
        self.text_json.insert('1.0', json.dumps(js, indent=2, ensure_ascii=False))
        self._brreg_map = map_brreg_metrics(js)
        rows = []
        def add_row(label, prefer_keys):
            hit = find_first_by_exact_endkey(js, prefer_keys, disallow_contains=['egenkapitalOgGjeld'] if 'sumEgenkapital' in prefer_keys else None)
            if not hit and 'sumEiendeler' in prefer_keys:
                hit = find_first_by_exact_endkey(js, ['sumEgenkapitalOgGjeld'])
            rows.append((label, f"{hit[0]} = {hit[1]}" if hit else "—"))
        add_row('Eiendeler (UB)', ['sumEiendeler'])
        add_row('Egenkapital (UB)', ['sumEgenkapital'])
        add_row('Gjeld (UB)', ['sumGjeld'])
        add_row('Driftsinntekter', ['driftsinntekter','sumDriftsinntekter','salgsinntekter'])
        add_row('EBIT', ['driftsresultat','ebit','driftsresultatFoerFinans'])
        add_row('Årsresultat', ['arsresultat','resultat','resultatEtterSkatt'])
        self._fill_tree_rows(self.tree_map, ["Felt","Sti = Verdi"], rows, money_cols=[])

        cmp_rows = []
        def add_cmp(label, saf_v, br_v):
            cmp_rows.append((label,
                             _fmt_kroner(saf_v),
                             _fmt_kroner(br_v),
                             _fmt_diff(saf_v, br_v)))
        add_cmp("Driftsinntekter", self._saft_summary['driftsinntekter'], self._brreg_map.get('driftsinntekter'))
        add_cmp("EBIT", self._saft_summary['ebit'], self._brreg_map.get('ebit'))
        add_cmp("Årsresultat", self._saft_summary['arsresultat'], self._brreg_map.get('arsresultat'))
        add_cmp("Eiendeler (UB)", self._saft_summary['eiendeler_UB_brreg'], self._brreg_map.get('eiendeler_UB'))
        add_cmp("Egenkapital (UB)", self._saft_summary['egenkapital_UB'], self._brreg_map.get('egenkapital_UB'))
        add_cmp("Gjeld (UB)", self._saft_summary['gjeld_UB_brreg'], self._brreg_map.get('gjeld_UB'))
        self._fill_tree_rows(self.tree_cmp, ["Nøkkel","SAF-T (Brreg-tilpasset)","Brreg (siste år)","Avvik"], cmp_rows, money_cols=[1,2,3])
        self.var_status.set("Data hentet.")

    def on_export(self):
        if self._saft_df is None:
            messagebox.showwarning("Ingenting å eksportere", "Last inn SAF-T først.")
            return
        out = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel","*.xlsx")], initialfile="SAFT_rapport.xlsx")
        if not out:
            return
        try:
            with pd.ExcelWriter(out, engine='xlsxwriter') as w:
                self._saft_df.to_excel(w, sheet_name='Saldobalanse', index=False)
                if self._saft_summary:
                    summ_df = pd.DataFrame([self._saft_summary]).T.reset_index()
                    summ_df.columns = ['Nøkkel','Beløp']
                    summ_df.to_excel(w, sheet_name='NS4102_Sammendrag', index=False)
                if self._sales_agg is not None:
                    self._sales_agg.to_excel(w, sheet_name='Sales_by_customer', index=False)
                if self._ar_agg is not None:
                    self._ar_agg.to_excel(w, sheet_name='AR_agg', index=False)
                if self._brreg_json:
                    pd.json_normalize(self._brreg_json).to_excel(w, sheet_name='Brreg_JSON', index=False)
                if self._brreg_map:
                    map_df = pd.DataFrame(list(self._brreg_map.items()), columns=['Felt','Verdi'])
                    map_df.to_excel(w, sheet_name='Brreg_Mapping', index=False)
            self.var_status.set(f"Eksportert: {out}")
        except Exception as e:
            messagebox.showerror("Feil ved eksport", str(e))

if __name__ == '__main__':
    try:
        app = App()
        app.mainloop()
    except Exception as ex:
        print("Kritisk feil:", ex, file=sys.stderr)
        sys.exit(1)
