# Hvor længe har elevatoren været ude af drift?

Uafhængig opsamling af DSB's liste over elevatorer ude af drift
([dsb.dk/trafikinformation/elevatorer](https://www.dsb.dk/trafikinformation/elevatorer/)).
DSB viser kun et øjebliksbillede. Dette projekt gemmer listen hver time og laver
statistik over, hvor længe elevatorerne er i stykker, og om DSB holder den
forventede dato.

- **Kun elevatorer.** Rulletrapper står også på DSB's side, men en defekt rulletrappe kan stadig bruges som trappe.
- **Kun egne data, indsamlet siden 20. oktober 2026.** Hvert tal kan dokumenteres med den rå HTML og et screenshot af DSB's side.

> Projektet er **ikke** tilknyttet DSB.

## Sådan virker det

```
EventBridge (hver time) → scraper-Lambda
   ├─ henter siden → S3 raw/…html.gz          (rå dokumentation)
   ├─ elevator-linjer → hændelser i DynamoDB   (åbn / luk / flet)
   ├─ forudberegner statistik → DynamoDB
   └─ listen ændret, eller >23 t siden? → screenshot-Lambda (Playwright) → S3 screenshots/…png

Browser → CloudFront ─┬─ /*                       → S3 (statisk site)
                      ├─ /api/*                   → Lambda Function URL (FastAPI) → DynamoDB
                      └─ /raw/*, /screenshots/*   → S3 (dokumentation)
```

Alt er serverless og ligger inden for AWS' free tier. Den eneste løbende udgift er ECR-lagring af screenshot-imaget, som koster få kroner om måneden.

### Regler for hændelser
- En hændelse starter, første gang en elevator står på listen.
- Den lukkes, når elevatoren har været væk ved **2 hentninger i træk**. Sluttidspunktet er den første hentning, hvor den manglede.
- Hvis elevatoren kommer tilbage inden for 24 timer, er det samme hændelse.
- Hvis der ikke kan parses nogen elevator-linjer, ændres intet, og der sendes en e-mail-alarm.
- Elevatorer, der allerede var i stykker ved første hentning, vises som "mindst X dage" og indgår ikke i medianen.

## Struktur

```
src/elevator_tracker/   Python-pakken (én zip til begge Lambdas)
  dsb.py                hent + parse DSB's side
  stations.py           fritekst → stabilt elevator-ID (+ manuelle aliaser)
  stations.json         stationer + koordinater (Rejseplanens GTFS)
  incidents.py          åbn / luk / flet hændelser
  stats.py              nøgletal til sitet
  db.py                 DynamoDB-hjælpere og tabelskema
  scraper.py            Lambda: hver time
  api.py                Lambda: FastAPI
screenshot/             container-Lambda: Playwright-screenshot af DSB's side
site/                   statisk HTML/JS/CSS
infra/                  Terraform (pr. feature) + bootstrap/ til state-bucket
tools/                  dev-server, rebuild, build_stations
tests/
```

Nye stavemåder fra DSB rettes i `LABEL_ALIASES` og `STATION_ALIASES` i [src/elevator_tracker/stations.py](src/elevator_tracker/stations.py). Kør derefter `make rebuild`.

## Udvikling

```sh
uv sync
make test
make dev       # http://localhost:8000 med simulerede data, uden AWS og uden Docker
```

## Deploy (AWS via SSO-profilen `Mikkel`)

```sh
aws sso login --profile Mikkel
make plan      # bygger lambda.zip og gemmer planen i infra/tfplan; gennemgå den
make apply     # anvender præcis den plan (bygger og pusher screenshot-imaget med Docker)
make scrape    # hent nu i stedet for at vente på næste hele time
make rebuild   # tøm tabellen og afspil alle egne snapshots fra S3 igen (efter regelændringer)
```

Første gang: opret state-bucketen med `infra/bootstrap/`. Se kommentaren øverst i [main.tf](infra/bootstrap/main.tf).
Kør derefter `cp infra/terraform.tfvars.example infra/terraform.tfvars` (sæt `alert_email`) og `make init`.

## Data

- `GET /api/current`: elevatorer ude af drift nu
- `GET /api/stats`: nøgletal
- `GET /api/stations/{slug}`: historik for én station
- `GET /api/evidence?at=<iso>`: screenshot og rå HTML af DSB's side på et givet tidspunkt
- `GET /api/snapshots?day=YYYY-MM-DD`: alle hentninger én dag
- `GET /api/export.csv`: alle hændelser som CSV

Data stilles til rådighed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Koden er MIT-licenseret.
