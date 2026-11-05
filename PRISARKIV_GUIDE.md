# Historisk elprisarkiv: DK1 og DK2 fra 2016

## Hvad er klar?

Appen læser allerede CSV-filer fra `data_cache/energy_prices_v2/` inden den forsøger Energinets API. Scriptet `scripts/update_price_archive.py` udfylder manglende arkivfiler og kontrollerer antallet af perioder, tidsstempler, prisområde og priser. Gemte, gyldige CSV-filer genbruges. Scriptet kan genstartes uden at begynde forfra.

Der er to rå datasæt: `Elspotprices` (én time pr. pris indtil 30. september 2025), og `DayAheadPrices` (15 minutter fra 1. oktober 2025). Gamle timepriser omregnes til kvartersintervaller **i appen** uden at de bliver til faktiske kvarterspriser. Data gemmes derfor i original tidsopløsning.

Arkivet indeholder kun **afsluttede måneder**. Ved opdatering 5. november 2026 er den seneste komplette måned oktober 2026. Datasættet indeholder kun spotpriser, ikke historiske kundetariffer eller faktiske handelsomkostninger.

## Sådan henter du alle historiske data direkte på GitHub

1. Åbn repoets fane **Actions** på GitHub.
2. Vælg workflowet **Update historical electricity prices**.
3. Klik **Run workflow**, vælg **backfill**, og start det én gang.
4. Følg loggen. Hvert validt filarkiv gemmes ved afslutning i repositoryet. Hvis API'et afviser en forespørgsel med HTTP 429 eller arbejdet afbrydes, kan du blot køre **backfill** igen. Allerede hentede, komplette data springes over.
5. Kontrollér efterfølgende `data_cache/energy_prices_v2/`. Der skal være både DK1 og DK2 og ingen manglende år eller afsluttede måneder.

`workflow_dispatch` kan kræve, at du aktiverer GitHub Actions for repoet og tillader skriveadgang til `GITHUB_TOKEN` under **Settings > Actions > General > Workflow permissions**. GitHub kan også blokere automatiske pushes ved beskyttede branches.

Når den første hentning lykkes, opdateres den seneste afsluttede måned automatisk den 4. hver måned via GitHub Actions. En månedlig opdatering giver kun to nye arkivfiler, én for DK1 og én for DK2. Besøgende på Streamlit henter dermed ikke fortiden igen fra API'et.

## Lokal kommando (alternativ til GitHub Actions)

Brug Python 3.12 eller 3.13 og det eksisterende projektmiljø:

```powershell
.\.venv\Scripts\python.exe scripts\update_price_archive.py --mode backfill --start-year 2016
```

Eller med almindelig Python, hvis afhængighederne er installeret:

```powershell
python scripts/update_price_archive.py --mode backfill --start-year 2016
python scripts/update_price_archive.py --mode check --start-year 2016
python scripts/update_price_archive.py --mode monthly
```

`--dry-run` viser manglende filer uden API-kald. `--area DK1` downloader kun Vestdanmark, og `--area DK2` kun Østdanmark. Med `--max-new-files 5` kan du begrænse antallet af nye downloads per kørsel.

## Vigtigt for offentliggørelse

`data_cache/` skal **ikke** stå som ignoreret i `.gitignore`. GitHub Action committer kun valide datafiler. Streaming af 10 års optimeringer på én gang kan blive tungt, så appens eksisterende 72-måneders begrænsning pr. optimering bevares.

**Status:** Denne opdatering tilføjer automatisering og validering. Den garanterer ikke, at hele tiårsarkivet allerede er hentet. Det sker først, når backfill-kørslen er gennemført, og filerne kan ses på GitHub.

Datakilde: https://www.energidataservice.dk/guides/api-guides
