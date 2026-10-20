# Hvor længe har elevatoren været ude af drift?

Uafhængig opsamling af DSB's liste over elevatorer og rulletrapper ude af drift
([dsb.dk/trafikinformation/elevatorer](https://www.dsb.dk/trafikinformation/elevatorer/)).
DSB viser kun et øjebliksbillede. Dette projekt gemmer listen hver time og laver
statistik over, hvor længe tingene er i stykker, og om DSB holder den
forventede dato.

> Projektet er **ikke** tilknyttet DSB.

## Sådan virker det

```
EventBridge (hver time) → scraper-Lambda (Python)
   ├─ henter siden → S3 raw/…html.gz          (rå dokumentation)
   ├─ parser → hændelser i DynamoDB            (åbn / luk / flet)
   ├─ forudberegner statistik → DynamoDB
   └─ listen ændret, eller >23 t siden? → screenshot-Lambda (Playwright) → S3 screenshots/…png

Browser → CloudFront ─┬─ /*              → S3 (statisk site)
                      ├─ /api/*          → Lambda Function URL (FastAPI) → DynamoDB
                      └─ /raw/*, /screenshots/* → S3 (dokumentation)
```

Alt er serverless og designet til at ligge inden for AWS' free tier:
- DynamoDB kører med provisioned capacity (5/5 pr. tabel/indeks), fordi det er det, der er always free.
- Vi bruger Lambda Function URL i stedet for API Gateway.
- CloudFront cacher API-svar i 5 minutter.

Den eneste løbende udgift af betydning er ECR-lagring af screenshot-imaget (ca. 1 kr./md.).

### Regler for hændelser
- En hændelse starter, første gang en enhed står på listen.
- Den lukkes, når enheden har været væk ved **2 hentninger i træk**. Sluttidspunktet er den første hentning, hvor den manglede.
- Hvis enheden kommer tilbage inden for 24 timer, er det samme hændelse.
- Mangler en hel sektion, eller giver parsingen 0 linjer, ændres intet, og der sendes en e-mail-alarm.
- Hændelser med ukendt eller upræcis start (ved første hentning eller efter et hul i data) vises som "mindst" og indgår ikke i gennemsnit og median.

DSB's tekster er fritekst. [scraper/normalize.py](scraper/normalize.py) laver dem om til stabile ID'er, og [scraper/aliases.yaml](scraper/aliases.yaml) bruges til manuelle rettelser.

## Udvikling

```sh
uv sync
make test
make dev          # DynamoDB Local + demo-data; følg instruktionerne
```

## Deploy (AWS via SSO)

```sh
aws configure sso --profile Mikkel       # start-URL: https://groenning.awsapps.com/start
aws sso login --profile Mikkel
make bootstrap                            # én gang: state-bucket → infra/backend.hcl
cp infra/terraform.tfvars.example infra/terraform.tfvars   # sæt alert_email
make init
make apply                                # bygger zips + screenshot-image (kræver Docker)
make backfill                             # én gang: historik fra Wayback Machine
make scrape                               # første hentning nu
```

Stationskoordinater: `uv run python -m tools.build_stations` (Rejseplanens GTFS).

## Data

- `GET /api/current`: hvad der er ude af drift nu
- `GET /api/stats`: nøgletal
- `GET /api/stations/{slug}`: historik for én station
- `GET /api/incidents?year=2026&type=elevator`: hændelser for ét år
- `GET /api/evidence?at=<iso>`: screenshot og rå HTML af DSB's side på et givet tidspunkt
- `GET /api/snapshots?day=YYYY-MM-DD`: alle hentninger én dag
- `GET /api/export.csv`: alt som CSV

Data stilles til rådighed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Koden er MIT-licenseret.
