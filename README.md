# Nordlys

Nordlys er et skrivebordsprogram (Python + PySide6) for revisjonsnær gjennomgang
av SAF-T-regnskap. Målet er å gjøre import, kontroll og analyse enklere, raskere
og mer oversiktlig i ett samlet verktøy.

## Innhold

- [Hvorfor Nordlys](#hvorfor-nordlys)
- [Funksjoner](#funksjoner)
- [Systemkrav](#systemkrav)
- [Installasjon](#installasjon)
- [Kom i gang](#kom-i-gang)
- [Miljøvariabler](#miljøvariabler)
- [Bransjeoppslag i terminal](#bransjeoppslag-i-terminal)
- [Eksport](#eksport)
- [Kvalitetssikring (test og lint)](#kvalitetssikring-test-og-lint)
- [Prosjektstruktur](#prosjektstruktur)

## Hvorfor Nordlys

Nordlys er laget for deg som jobber med revisjon, regnskap eller økonomisk
kontroll, og som vil:

- lese og kontrollere SAF-T-data uten manuell filgraving,
- få rask innsikt i saldobalanse, nøkkeltall og avvik,
- sammenligne perioder/år på en strukturert måte,
- eksportere funn til rapportformat (Excel/PDF).

## Funksjoner

### Kjernefunksjoner

- Import av én eller flere SAF-T XML-filer.
- Bakgrunnsimport med fremdriftslinje.
- Visning av saldobalanse, nøkkeltall og sammenstillinger.
- Sammenligning med forrige år når filer gjelder samme selskap.

### Analyse og databerikelse

- Kunde- og leverandøranalyser.
- Utvalg av kostnadsbilag.
- Oppslag mot Brønnøysundregistrene.
- Forslag til bransjegruppe når organisasjonsnummer finnes.

### Navigasjon i appen

Venstremenyen i appen består av:

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

## Systemkrav

- Python **3.11**
- Operativsystem med støtte for PySide6
- Internett (valgfritt, men nødvendig for Brønnøysund-oppslag)

## Installasjon

1. Opprett virtuelt miljø:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

   På Windows:

   ```bash
   .venv\Scripts\activate
   ```

2. Installer avhengigheter for vanlig bruk:

   ```bash
   pip install -r requirements.txt
   ```

3. Installer utvikleravhengigheter ved behov (test/lint):

   ```bash
   pip install -r requirements-dev.txt
   ```

## Kom i gang

Start programmet:

```bash
python main.py
```

## Miljøvariabler

Du kan styre ytelse og UI-oppsett med følgende variabler:

- `NORDLYS_SAFT_STREAMING=1`  
  Aktiverer streaming av hovedbok/prøvebalanse for store filer.
- `NORDLYS_SAFT_STREAMING_VALIDATE=1`  
  Validerer SAF-T under streaming (krever `xmlschema`).
- `NORDLYS_SAFT_HEAVY_PARALLEL=1`  
  Aktiverer mer parallell behandling av tunge filer.
- `NORDLYS_NAV_WIDTH=<tall>`  
  Overstyrer bredden på venstremenyen.

## Bransjeoppslag i terminal

Du kan bruke bransjeklassifisering uten GUI:

```bash
python -m nordlys.industry_groups_cli --orgnr 123456789
```

Les fra SAF-T-fil:

```bash
python -m nordlys.industry_groups_cli --saft sti/til/fil.xml
```

Overstyr navn i oppslag:

```bash
python -m nordlys.industry_groups_cli --orgnr 123456789 --navn "Eksempel AS"
```

## Eksport

Nordlys støtter eksport til både Excel og PDF.

### Excel

Inkluderer blant annet:

- Saldobalanse
- NS4102-sammendrag
- Salg per kunde
- Innkjøp per leverandør
- Brønnøysund-data (rå JSON + mapping)
- Utvalgte kostnadsbilag

### PDF

Kort sammendrag med:

- Hovedtall
- Toppkunder
- Topp leverandører
- Utvalgte kostnadsbilag

## Kvalitetssikring (test og lint)

Kjør alle tester:

```bash
pytest
```

Kjør lint med Ruff:

```bash
ruff check .
```

Formater kode med Black:

```bash
black .
```

## Prosjektstruktur

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
