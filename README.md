# Nordlys

Nordlys er et skrivebordsprogram i Python som hjelper revisorer og controllere
med å lese, validere og analysere SAF-T-filer. Programmet bruker PySide6 for et
enkelt grensesnitt og kombinerer egen analyse med data fra
Brønnøysundregistrene.

## Hva er nytt nå

- Import av én eller flere SAF-T-filer kjører i bakgrunnen via `TaskRunner`,
  med tydelig fremdrift og statusmeldinger i GUI-et.
- Trådantallet under import begrenses automatisk til to når filene er store,
  slik at minnebruken holder seg moderat.
- Mulighet for strømming av hovedboken med miljøvariabelen
  `NORDLYS_SAFT_STREAMING=1`, slik at prøvebalansen sjekkes før hele filen er
  lest. Sett `NORDLYS_SAFT_STREAMING_VALIDATE=1` hvis du vil validere samtidig
  (krever `xmlschema`).
- Eksport til PDF rett fra toppmenyen, med nøkkeltall, toppkunder/-leverandører
  og et lite utvalg kostnadsbilag.
- Excel-eksporten inkluderer nå også leverandørkjøp og kostnadsbilag i egne ark.
- Brønnøysund-oppslag og bransjeklassifisering skjer parallelt og caches etter
  organisasjonsnummer, slik at samme selskap går raskere å slå opp neste gang.
- Excel-eksport samler saldobalanse, NS4102-sammendrag, kundeomsetning og
  Brønnøysund-data i én fil via `xlsxwriter`.

## Hovedfunksjoner

- 📂 Last inn flere SAF-T-filer i samme operasjon. Datasettene lagres og kan
  byttes mellom via toppfeltet.
- 🔄 Automatisk kobling mot «forrige år» når to SAF-T-filer har samme
  organisasjonsnummer. Kontoer fra tidligere år vises som egne kolonner i
  regnearket i tillegg til en egen «forrige»-kolonne.
- 📊 Dashboard med nøkkeltall (driftsinntekter, EBITDA/EBIT/resultatmargin) og
  NS4102-sammendrag for raskt overblikk.
- 🧾 Kunde- og leverandøranalyse med topplister og transaksjonsantall. Viser
  også et tilfeldig utvalg av kostnadsbilag for manuell kontroll.
- 🧭 Integrasjon mot Brønnøysundregistrene med mapping av nøkkeltall og
  bransjeidentifisering som kan gjenbrukes i appen.
- 💾 Ett-klikks eksport av analyser til Excel, inkludert eventuelle
  Brønnøysund-resultater.

## Forutsetninger

- Python 3.11 anbefales (samme versjon som brukes for linting og formatering).
- Operativsystem med støtte for PySide6 (Windows, macOS eller Linux med X11
  eller Wayland).
- Tilgang til internett dersom Brønnøysund-data skal hentes.
- `xmlschema` er valgfritt og trengs kun hvis du vil XSD-validere SAF-T-filer
  under import eller streaming.

## Avhengigheter og teknologi

Alle avhengigheter ligger i `requirements.txt` og kan installeres med
`pip install -r requirements.txt`.

- `pandas` – behandling av saldobalanse og analyseresultater.
- `PySide6` – driver det grafiske grensesnittet.
- `requests` og `requests-cache` – henter og cacher Brønnøysund-data.
- `xlsxwriter` og `openpyxl` – Excel-eksport.
- `reportlab` – generering av PDF-rapport (ikke aktivert i GUI-et ennå).
- `pytest` – enhetstester som genererer nødvendige SAF-T-data ved kjøring.
- `ruff`, `black` og `mypy` – utviklerverktøy for linting, formatering og
  statisk typekontroll.

## Komme i gang

1. **Opprett og aktiver et virtuelt miljø** (anbefalt):
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```
2. **Installer avhengigheter**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Start Nordlys**:
   ```bash
   python main.py
   ```

## Navigasjon i appen

- **Import**: velg én eller flere SAF-T-filer. Importen kjøres i bakgrunnen og
  fremdrift vises nederst i vinduet.
- **Dashboard**: viser sammendrag av NS4102-nøkkeltall og KPI-er.
- **Planlegging**:
  - *Saldobalanse*: tabellvisning av alle kontoer.
  - *Kontroll IB*: sammenligner mot Brønnøysund-rapporterte tall når de finnes.
  - *Regnskapsanalyse*: viser sentrale nøkkeltall for inneværende år og forrige
    år når tilgjengelig.
  - *Vesentlighetsvurdering*: kort som hjelper med terskelverdier.
  - *Sammenstillingsanalyse*: kontroll av endringer per konto.
- **Revisjon**: sjekklister for hvert revisjonsområde samt egne sider for
  kundefordringer (salg), leverandørgjeld (innkjøp) og bilagsutvalg på
  kostnadskontoer.
- **Eksport**: tilgjengelig fra toppfeltet. Skriver en Excel-rapport med
  saldobalanse, sammendrag, kundeomsetning og Brønnøysund-data.

## Streaming og validering

- Sett `NORDLYS_SAFT_STREAMING=1` hvis du vil at Nordlys skal strømme hovedboken
  og beregne prøvebalanse før hele filen lastes inn.
- Sett også `NORDLYS_SAFT_STREAMING_VALIDATE=1` hvis du har installert
  `xmlschema` og ønsker XSD-validering i samme slengen.
- Eventuelle avvik i prøvebalansen vises som feilmelding etter importen.

## Testing

Kjør testene lokalt med:

```bash
pytest
```

Testene lager alle nødvendige SAF-T-filer og datastrukturer selv, så du trenger
ikke å laste ned eksempler på forhånd.

## Struktur

Kort oversikt over viktige moduler:

```text
Nordlys/
├── main.py                  # Starter PySide6-applikasjonen
├── nordlys/
│   ├── constants.py         # Felles konstanter og URL-mal
│   ├── settings.py          # Miljøvariabler for streaming
│   ├── helpers/             # Formatering, lazy imports, XML-hjelpere
│   ├── saft/                # Parsing, streaming og XSD-validering av SAF-T
│   │   ├── loader.py        # Laster SAF-T-filer i bakgrunnen
│   │   ├── entry_stream.py  # Strømmer hovedboken og beregner prøvebalanse
│   │   ├── trial_balance.py # Pakkefunksjon for streaming og feilrapportering
│   │   └── brreg_enrichment.py # Henter Brønnøysund-data og bransjeinfo
│   ├── saft_customers.py    # Bygger kunde-/leverandørtabeller og bilagsutvalg
│   ├── industry_groups.py   # Bransjeklassifisering og cache
│   ├── integrations/        # HTTP-klient, cache og modeller mot Brønnøysund
│   ├── regnskap/            # Beregning av nøkkeltall for NS4102
│   └── ui/                  # PySide6-grensesnitt, sider og eksport
└── tests/                   # Pytest-suite som dekker parsing og analyser
```
