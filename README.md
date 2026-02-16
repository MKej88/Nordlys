# Nordlys

Nordlys er et skrivebordsprogram i Python for gjennomgang av SAF-T-regnskap.
Programmet hjelper deg med import, kontroll og enkel analyse i ett og samme
vindu.

## Hva programmet gjør nå

- Leser én eller flere SAF-T XML-filer.
- Kjører import i bakgrunnen med fremdriftslinje.
- Viser saldobalanse, nøkkeltall og sammenstillinger.
- Bygger kunde-/leverandøranalyser og utvalg av kostnadsbilag.
- Henter Brønnøysund-data og foreslår bransjegruppe når org.nr finnes.
- Eksporterer data til Excel og PDF.
- Støtter sammenligning med forrige år når filer hører til samme selskap.

## Navigasjon i appen

Menyen i venstre side består av:

- **Import**
- **Dashboard**
- **Planlegging**
  - Saldobalanse
  - Kontroll IB
  - Regnskapsanalyse
  - Vesentlighetsvurdering
  - Sammenstillingsanalyse
- **Revisjon**
  - Innkjøp og leverandørgjeld
  - Lønn
  - Kostnad
  - Driftsmidler
  - Finans og likvid
  - Varelager og varekjøp
  - Salg og kundefordringer
  - MVA

## Krav

- Python **3.11**
- Operativsystem med støtte for PySide6
- Internett hvis du vil hente data fra Brønnøysundregistrene

## Installering

1. Opprett virtuelt miljø:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

   På Windows:

   ```bash
   .venv\Scripts\activate
   ```

2. Installer avhengigheter for vanlig bruk (raskest):

   ```bash
   pip install -r requirements.txt
   ```

3. Hvis du også skal kjøre tester/lint lokalt, installer utviklerpakker:

   ```bash
   pip install -r requirements-dev.txt
   ```

## Starte programmet

```bash
python main.py
```

## Valgfrie miljøvariabler

Disse kan settes før oppstart:

- `NORDLYS_SAFT_STREAMING=1`  
  Slår på streaming av hovedbok/prøvebalanse for store filer.
- `NORDLYS_SAFT_STREAMING_VALIDATE=1`  
  Validerer SAF-T under streaming (krever `xmlschema`).
- `NORDLYS_SAFT_HEAVY_PARALLEL=1`  
  Gir mer parallell behandling av tunge filer.
- `NORDLYS_NAV_WIDTH=<tall>`  
  Overstyrer bredden på venstremenyen.

## Kommandolinje for bransjeoppslag

Du kan bruke bransjeklassifisering uten å starte GUI:

```bash
python -m nordlys.industry_groups_cli --orgnr 123456789
```

Du kan også lese direkte fra SAF-T-fil:

```bash
python -m nordlys.industry_groups_cli --saft sti/til/fil.xml
```

Eller overstyre navn i oppslag:

```bash
python -m nordlys.industry_groups_cli --orgnr 123456789 --navn "Eksempel AS"
```

## Eksport

Fra appen kan du eksportere:

- **Excel** med blant annet:
  - Saldobalanse
  - NS4102-sammendrag
  - Salg per kunde
  - Innkjøp per leverandør
  - Brønnøysund-data (rå JSON + mapping)
  - Utvalgte kostnadsbilag
- **PDF** med kort sammendrag:
  - Hovedtall
  - Toppkunder
  - Topp leverandører
  - Utvalgte kostnadsbilag

## Test

Kjør tester med:

```bash
pytest
```

Tips: Bruk `requirements-dev.txt` når du trenger test/lint-verktøy lokalt.

## Struktur (kort)

```text
Nordlys/
├── main.py
├── nordlys/
│   ├── core/          # Bakgrunnsjobber (TaskRunner)
│   ├── integrations/  # Brønnøysund-klient, cache og modeller
│   ├── regnskap/      # Regnskapsanalyse (bl.a. driftsmidler og MVA)
│   ├── saft/          # Parsing, validering og SAF-T-analyse
│   ├── ui/            # PySide6-vinduer, sider og eksport
│   └── settings.py    # Miljøvariabler
└── tests/
```
