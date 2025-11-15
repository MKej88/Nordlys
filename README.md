# Nordlys

Nordlys er et Python-basert analyseverktøy som hjelper revisorer og controllere med å få oversikt over SAF-T-filer. Målet er å gi klar sikt i komplekse regnskapsdata gjennom et moderne skrivebordsgrensesnitt bygget med PySide6. Løsningen kombinerer informasjon fra regnskapsregisteret med data som leses fra SAF-T-filer og presenterer resultatet i et visuelt og interaktivt grensesnitt.

De siste versjonene har fått raskere import ved hjelp av strømming av hovedboken, smartere bakgrunnsjobber og mer robust innhenting av informasjon fra Brønnøysundregistrene. Dette gir et smidigere brukergrensesnitt og færre feilmeldinger når nettet er ustabilt.

## Hovedfunksjoner

- 📂 Importer én eller flere SAF-T-filer i samme operasjon. Alle datasettene legges i en årvelger slik at du enkelt kan hoppe mellom selskap og år.
- 🔄 Automatisk matching av «forrige år»-data mot samme organisasjonsnummer slik at sammenligningen alltid skjer mot riktig selskap.
- 📊 Analyse av saldobalanse for å beregne nøkkeltall som driftsinntekter, EBITDA, resultat og balanseavvik – nå med forbedret avrunding av både positive og negative tall.
- 🧾 Kunde- og leverandøranalyse med aggregert omsetning per motpart fra fakturajournalen, inkludert eksport til CSV og XLSX.
- 🧭 Bransjeklassifisering basert på data fra Brønnøysundregistrene, med caching som gjør gjentatte oppslag raskere.
- 📈 Topplister for omsetning per kunde med filtrering på regnskapsår eller valgte datoer.
- 🏢 Integrasjon mot Brønnøysundregistrenes regnskapsregister for sammenligning av offentlig rapporterte tall.
- 🗂️ Forhåndsdefinerte revisjonsoppgaver og temakort som gir rask tilgang til relevante kontroller.
- 🧮 Funksjoner for formatering av valuta og differanser som gjør tallene enklere å tolke.
- 💾 Ett-klikks eksport av analyser til CSV- og XLSX-filer, inkludert innebygd fallback når `openpyxl` ikke er tilgjengelig.
- 🚀 Strømming av hovedboken for store SAF-T-filer (aktiveres med `NORDLYS_SAFT_STREAMING=1`) slik at prøvebalansen kontrolleres før hele filen lastes inn.
- 🧠 Bakgrunnskø for tyngre analyser med tydelig fremdrift, slik at grensesnittet holder seg responsivt mens data leses og prosesseres.
- 🛡️ Forbedret Brønnøysund-integrasjon med HTTP-cache, feiltoleranse og mulighet til å angi egen cache-katalog via `NORDLYS_CACHE_DIR`.
- 📂 Uttrekk av bilag med kostnadskontroller og leverandørdata for målrettet revisjon av inngående fakturaer.

## Forutsetninger

- Python 3.10 eller nyere.
- Operativsystem med støtte for PySide6 (Windows, macOS eller Linux med X11/Wayland).
- Tilgang til internett dersom Brønnøysund-data skal hentes.
- Tilgang til `xmlschema` dersom Nordlys skal utføre utvidet XSD-validering (se under).

## Avhengigheter og teknologi

Nordlys bruker et utvalg veletablerte Python-bibliotek. Alle er listet i
`requirements.txt`, slik at du kan installere dem med én kommando:

- `pandas>=1.5` – behandler saldobalanse, fakturajournal og sammenstilling av
  flere SAF-T-filer.
- `PySide6>=6.5` – driver skrivebordsgrensesnittet med datasettvelger, kort og
  tabeller.
- `requests>=2.31` – henter bransjeinformasjon og regnskapstall fra
  Brønnøysundregistrene.
- `requests-cache>=1.1` – gir automatisk HTTP-cache slik at flere oppslag
  mot samme organisasjonsnummer går raskt.
- `openpyxl>=3.1` – standardmotor når analyser eksporteres til Excel (XLSX).
- `xlsxwriter>=3.0` – trer inn automatisk hvis `openpyxl` mangler, slik at
  eksporten alltid fungerer.
- `reportlab>=3.6` – lager PDF-rapporter med samme utseende som i
  skrivebordsappen.
- `pytest>=7.4` – sikrer at parsing, beregninger og eksport holder seg stabile
  gjennom automatiserte tester.
- `xmlschema>=2.2` – valgfri validering av SAF-T-filer mot XSD-skjema for mer
  presise feilmeldinger.
- `ruff>=0.4`, `black>=24.0` og `mypy>=1.8` – utviklerverktøy for linting,
  formatering og statisk typekontroll.

## Komme i gang

1. **Opprett og aktiver et virtuelt miljø** (anbefalt):
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```
2. **Installer prosjektavhengigheter**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Start Nordlys**:
   ```bash
   python main.py
   ```

Når Nordlys kjøres åpnes et PySide6-basert brukergrensesnitt som lar deg:

- Velge en eller flere SAF-T-filer via filvelgeren.
- Bytte mellom datasettene via årvelgeren i toppmenyen. Nordlys foreslår alltid siste år som standard.
- Se oversiktskort med nøkkeltall, forslag til revisjonsoppgaver og avstemningspunkter.
- Se detaljerte tabeller for saldobalanse, kundespesifikasjoner og leverandørspesifikasjoner.
- Oppdatere data fra Brønnøysundregistrene ved å slå opp organisasjonsnummeret i filen og få bransjegruppering.
- Aktivere prøvebalanse-sjekk i forkant ved å sette miljøvariabelen `NORDLYS_SAFT_STREAMING=1` (valgfritt). Dette er nyttig for store filer fordi differanser fanges opp tidlig.

## Arbeidsflyt for flere SAF-T-filer

1. Trykk på **Importer SAF-T** og marker alle filene du vil lese inn.
2. Nordlys laster filene i bakgrunnen og sorterer dem etter år og selskap.
3. Bruk rullegardinlisten «Datasett» for å hoppe mellom filene. Teksten viser selskap, regnskapsår og om filen stammer fra samme kunde.
4. Når du åpner regnskapsanalysen bruker Nordlys automatisk datasettene fra samme organisasjonsnummer for å fylle inn kolonnen «Forrige år».

## Testing

Prosjektet benytter `pytest` til enhetstester. Kjør testene lokalt med:

```bash
pytest
```

Testene genererer alle nødvendige SAF-T- og regnskapsdata programmatisk ved kjøring. Det finnes derfor ingen egne eksempeldatafiler lagret i `tests/`, og du trenger ikke å laste ned eller opprette tilleggsfiler for å få testene til å passere.

## Struktur

Tabellen under viser hvordan prosjektet nå er delt inn. Målet er å gjøre det
enkelt å finne riktig sted når du skal feilsøke, legge til analyser eller
justere brukergrensesnittet.

```
Nordlys/
├── main.py                     # Starter hele PySide6-applikasjonen
├── nordlys/
│   ├── core/
│   │   └── task_runner.py      # Oppgavekø som holder tunge jobber unna UI-tråden
│   ├── helpers/
│   │   ├── formatting.py       # Felles regler for tall- og tekstformatering
│   │   ├── lazy_imports.py     # Hjelper med å laste tunge biblioteker ved behov
│   │   ├── number_parsing.py   # Tolkning av tall fra SAF-T og CSV
│   │   └── xml_helpers.py      # Små verktøy for trygg XML-lesing
│   ├── integrations/
│   │   └── brreg_service.py    # HTTP-klient med cache mot Brønnøysundregistrene
│   ├── regnskap/
│   │   ├── analysis.py         # Beregner nøkkeltall og revisjonskort
│   │   └── prep.py             # Gjør saldobalansen klar for analyse
│   ├── saft/
│   │   ├── loader.py           # Leser SAF-T-filer og bygger datastrukturen
│   │   ├── parsing.py          # Strømmer XML og validerer innhold
│   │   ├── analytics.py        # Temaanalyser av hovedbok og bilag
│   │   └── export.py           # Utskrift til CSV og Excel
│   ├── saft_customers.py       # Samler kunde- og leverandørinformasjon
│   ├── industry_groups.py      # Bransjekoder og grupperinger med cache
│   ├── industry_groups_cli.py  # Lite CLI for å teste bransjeklassifisering
│   ├── brreg.py                # Høyere nivå-funksjoner for oppslag i Brønnøysund
│   ├── constants.py            # Samlede konstanter og typer brukt i hele appen
│   ├── settings.py             # Leser miljøvariabler og andre innstillinger
│   ├── utils.py                # Mindre hjelpefunksjoner som gjenbrukes flere steder
│   └── ui/
│       ├── config.py           # Konfigurasjon for tema, skrifttyper og farger
│       ├── data_controller/    # Laster datasett og holder styr på statusmeldinger
│       ├── data_manager/       # Deling av datasett mellom ulike sider i UI-et
│       ├── models/             # Qt-modeller for tabeller, lister og analyser
│       ├── navigation.py       # Felles navigasjonslogikk for sider og kort
│       ├── navigation_builder.py # Definerer hvilke sider og kort som vises
│       ├── pages/              # Selve sidene (import, dashboard, analyser m.m.)
│       ├── pyside_app.py       # Starter Qt-applikasjonen og hovedvinduet
│       ├── widgets.py          # Egendefinerte Qt-widgets for tabeller og kort
│       └── styles.py           # Samler QSS-stiler for et enhetlig uttrykk
├── tests/
│   ├── conftest.py             # Testdata og felles fiksturer
│   └── test_*.py               # Dekker SAF-T-parsing, analyser og integrasjoner
└── requirements.txt, pyproject.toml osv.
```

### Samspillet mellom modulene

- **SAF-T-flyten** starter i `nordlys/saft/loader.py`. Filene leses inn,
  valideres og sendes videre til `regnskap/` for tallknusing.
- **Analyse og revisjonskort** bygges i `nordlys/regnskap/analysis.py`, som
  bruker helper-modulene for avrunding, gruppering og visning.
- **Brønnøysund-oppdateringer** går gjennom `nordlys/brreg.py`, som igjen
  bruker `integrations/brreg_service.py` for selve HTTP-kallene og caching.
- **Brukergrensesnittet** styres fra `nordlys/ui/pyside_app.py`. Her kobles
  `data_controller/` og `page_manager.py` sammen slik at hver side får riktig
  datasett og status. Sidene i `ui/pages/` leser data fra modeller i
  `ui/models/` og viser dem i komponenter fra `ui/widgets.py`.
- **Bakgrunnsjobber** håndteres av `core/task_runner.py`, slik at store filer
  ikke fryser brukeropplevelsen.

### Ressurser og testdata

- Ikoner og XSD-filer ligger i `nordlys/resources/`. Disse pakkes inn med
  applikasjonen slik at alt fungerer også uten nett.
- Testpakken i `tests/` bygger nødvendige SAF-T-eksempler automatisk. Du kan
  derfor kjøre `pytest` uten å finne egne datafiler.

## Nyttige tips for videre utvikling

- Bruk `TaskRunner` til tunge operasjoner hvis du lager nye funksjoner som arbeider med mange transaksjoner, slik at UI-et forblir responsivt.
- Behold funksjonelle endringer i egne moduler og legg til nye tester i `tests/` for å dokumentere forventet oppførsel.
- Når nye tredjepartsbibliotek tas i bruk bør `requirements.txt` oppdateres og minimumsversjoner vurderes for å beholde Nordlys-navnet tydelig i alle miljø.
- Brønnøysund-integrasjonen (`nordlys/brreg.py`) har en timeout på 20 sekunder. Håndter eventuelle feil med passende feilmeldinger i UI-et.
- Sett `NORDLYS_CACHE_DIR` dersom du ønsker å kontrollere hvor HTTP-cachen lagres, for eksempel på en delt nettverksdisk. Nordlys faller automatisk tilbake til minne-cache hvis katalogen ikke kan brukes.

## Lisens

Prosjektet distribueres under MIT-lisensen. Se `LICENSE` dersom den er tilgjengelig i prosjektet.
