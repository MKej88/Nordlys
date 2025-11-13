# Nordlys

Nordlys er et Python-basert analyseverktøy som hjelper revisorer og controllere med å få oversikt over SAF-T-filer. Målet er å gi klar sikt i komplekse regnskapsdata gjennom et moderne skrivebordsgrensesnitt bygget med PySide6. Løsningen kombinerer informasjon fra regnskapsregisteret med data som leses fra SAF-T-filer og presenterer resultatet i et visuelt og interaktivt grensesnitt.

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
- `openpyxl>=3.1` – standardmotor når analyser eksporteres til Excel (XLSX).
- `xlsxwriter>=3.0` – trer inn automatisk hvis `openpyxl` mangler, slik at
  eksporten alltid fungerer.
- `reportlab>=3.6` – lager PDF-rapporter med samme utseende som i
  skrivebordsappen.
- `pytest>=7.4` – sikrer at parsing, beregninger og eksport holder seg stabile
  gjennom automatiserte tester.
- `xmlschema>=2.2` – valgfri validering av SAF-T-filer mot XSD-skjema for mer
  presise feilmeldinger.

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

```
Nordlys/
├── main.py                # Inngangspunkt som starter PySide6-applikasjonen
├── nordlys/
│   ├── brreg.py           # Integrasjon mot Brønnøysundregistrenes API
│   ├── constants.py       # Konstanter som brukes på tvers av modulene
│   ├── industry_groups.py # Bransjeklassifisering og caching
│   ├── regnskap.py        # Beregninger for resultat- og balanseanalyse
│   ├── saft.py            # Parsing og analyse av SAF-T XML
│   ├── saft_customers.py  # Kunde- og leverandøranalyse + eksport
│   ├── ui/
│   │   └── pyside_app.py  # GUI-komponenter, datasettvelger og interaksjon
│   └── resources/         # Ikoner og cachefiler brukt i grensesnittet
└── tests/                 # Pytest-tester som genererer data programmatisk
```

## Nyttige tips for videre utvikling

- Behold funksjonelle endringer i egne moduler og legg til nye tester i `tests/` for å dokumentere forventet oppførsel.
- Når nye tredjepartsbibliotek tas i bruk bør `requirements.txt` oppdateres og minimumsversjoner vurderes for å beholde Nordlys-navnet tydelig i alle miljø.
- Brønnøysund-integrasjonen (`nordlys/brreg.py`) har en timeout på 20 sekunder. Håndter eventuelle feil med passende feilmeldinger i UI-et.

## Lisens

Prosjektet distribueres under MIT-lisensen. Se `LICENSE` dersom den er tilgjengelig i prosjektet.
