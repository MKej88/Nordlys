# Nordlys

Nordlys er et Python-basert analyseverktøy som hjelper revisorer og controllere med å få oversikt over SAF-T-filer. Programmet kombinerer informasjon fra regnskapsregisteret med data som leses fra SAF-T-filer, og presenterer resultatet i et moderne skrivebordsgrensesnitt bygget med PySide6.

## Hovedfunksjoner

- 📂 Import av SAF-T-filer med automatisk uthenting av selskapsinformasjon og regnskapsperiode.
- 📊 Analyse av saldobalanse for å beregne nøkkeltall som driftsinntekter, EBITDA, resultat og balanseavvik.
- 🧾 Kundeanalyse med aggregert omsetning per kunde fra fakturajournalen.
- 🏢 Integrasjon mot Brønnøysundregistrenes regnskapsregister for sammenligning av offentlig rapporterte tall.
- 🗂️ Forhåndsdefinerte revisjonsoppgaver og temakort som gir rask tilgang til relevante kontroller.
- 🧮 Funksjoner for formatering av valuta og differanser som gjør tallene enklere å tolke.

## Forutsetninger

- Python 3.10 eller nyere.
- Operativsystem med støtte for PySide6 (Windows, macOS eller Linux med X11/Wayland).
- Tilgang til internett dersom Brønnøysund-data skal hentes.

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
3. **Start applikasjonen**:
   ```bash
   python main.py
   ```

Når programmet kjøres åpnes et PySide6-basert brukergrensesnitt som lar deg:

- Velge en SAF-T-fil via filvelgeren.
- Se oversiktskort med nøkkeltall og avstemningsforslag.
- Se detaljerte tabeller for saldobalanse og kundespesifikasjoner.
- Oppdatere data fra Brønnøysundregistrene ved å slå opp organisasjonsnummeret i filen.

## Testing

Prosjektet benytter `pytest` til enhetstester. Kjør testene lokalt med:

```bash
pytest
```

Testene bruker eksempeldata som ligger i `tests/`-mappen for å validere parsing av SAF-T-filer og aggregering av regnskapstall.

## Struktur

```
Nordlys/
├── main.py                # Inngangspunkt som starter PySide6-applikasjonen
├── nordlys/
│   ├── saft.py            # Parsing og analyse av SAF-T XML
│   ├── brreg.py           # Integrasjon mot Brønnøysundregistrenes API
│   ├── utils.py           # Hjelpefunksjoner for XML og formatering
│   ├── constants.py       # Konstanter som brukes på tvers av modulene
│   └── ui/
│       └── pyside_app.py  # GUI-komponenter og interaksjon
└── tests/                 # Pytest-tester og eksempeldata
```

## Nyttige tips for videre utvikling

- Behold funksjonelle endringer i egne moduler og legg til nye tester i `tests/` for å dokumentere forventet oppførsel.
- Når nye tredjepartsbibliotek tas i bruk bør `requirements.txt` oppdateres og minimumsversjoner vurderes.
- Brønnøysund-integrasjonen (`nordlys/brreg.py`) har en timeout på 20 sekunder. Håndter eventuelle feil med passende feilmeldinger i UI-et.

## Lisens

Prosjektet distribueres under MIT-lisensen. Se `LICENSE` dersom den er tilgjengelig i prosjektet.
