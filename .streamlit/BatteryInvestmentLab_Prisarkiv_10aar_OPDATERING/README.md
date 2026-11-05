# Battery Investment Lab

Et interaktivt Python/Streamlit-porteføljeprojekt om batterilagring, handel på det danske day-ahead-elmarked og investeringsanalyse.

## Funktioner

1. **Oversigt** med indbyggede, færdigberegnede eksempler og faktiske aggregerede historiske spotpriser for DK1 i 2025.
2. **Markedsoptimering** baseret på historiske elpriser, batteriets effekt, kapacitet, virkningsgrad og valgte tarifscenarier.
3. **Handelsstrategier** med fem metoder (historisk profil, gårsdagens priser, kalenderregression, Gradient Boosting og fast nat/aften). Prognoser trænes kun på tidligere data. Backtestene viser også cyklusbegrænsning, risiko og omkostningsfølsomhed.
4. **Investeringsanalyse** med NPV, IRR, tilbagebetaling, følsomhed og mulighed for eget økonomisk scenarie.

## Start lokalt

Anbefalet: Python 3.12.

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Åbn adressen fra terminalen, typisk `http://localhost:8501`. Den første side viser færdigberegnede resultater og kan udforskes uden at hente eller optimere nye data.

### Interaktive analyser

Under **Markedsoptimering** vælger du periode og batteristørrelse og klikker **Start batterioptimering**. Energinets API kan begrænse kald eller være midlertidigt utilgængeligt. Fulde årsberegninger kan tage tid, særligt på delt cloud-hardware. Efter beregning kan historiske data bruges i **Handelsstrategier** og **Investeringsanalyse** i samme session. Navigér via appens indbyggede menupunkter. Skift af browserfane eller ny session kan miste beregningsresultater i Streamlits sessionshukommelse.

**Bemærk:** De statiske demonstrationsresultater åbner direkte på forsiden og i handelsstrategier og investeringsanalysen, uden at et nyt API-kald er nødvendigt. Investeringsanalysens demo har hypotetiske startværdier på 30 mio. kr. for batteriet, 5 mio. kr. til tilslutning, 2 mio. kr. til etablering og 1 mio. kr. i årlige driftsomkostninger. Tallene er alene regneeksempler, ikke pristilbud. De er eksempler fra tidligere gennemførte lokale simuleringer, ikke en prognose.


## Offlineprisarkiv og automatisk opdatering

Det historiske prisarkiv for **DK1 og DK2 fra 2016** opbygges med `scripts/update_price_archive.py`. Start den manuelle **backfill** i GitHub Actions under workflowet **Update historical electricity prices**. Filerne valideres, genbruges og gemmes på GitHub. En automatisk kørsel henter den seneste afsluttede måned den 4. i hver måned. Se [PRISARKIV_GUIDE.md](PRISARKIV_GUIDE.md). Hele arkivet findes først, når backfill har kørt færdig.

## Hosting på Streamlit Community Cloud

1. Opret et offentligt GitHub-repository, eksempelvis `battery-investment-lab`.
2. Upload **filerne inde i denne mappe** til repository-roden, så `app.py`, `requirements.txt`, `overview.py`, `assets/` og `.streamlit/` ligger i roden. Upload ikke en ekstra overordnet mappe.
3. Gå til https://share.streamlit.io, opret en ny app, vælg repository, `main` og **`app.py`** som entrypoint.
4. Vælg Python 3.12 i avancerede indstillinger hvis muligt. Ingen API-nøgle er nødvendig til Energi Data Service.
5. Deploy og test især oversigt, strategiernes demo og investeringens demo uden at køre en tung backtest.

Repoet bør ikke indeholde `data_cache/`, `.env`, `secrets.toml`, personlige CSV'er eller virtuelle miljøer. En `.gitignore` følger med.

## Metode og begrænsninger

Historiske prisdata kommer fra Energinet (Energi Data Service). Inden 1. oktober 2025 er day-ahead-markedets prisprodukter timebaserede. Derefter anvendes kvartersprodukter. Appen tager højde for danske kalenderdage og skiftet mellem sommer- og vintertid.

Den teoretiske handelsoptimering forudsætter perfekt kendskab til priserne i optimeringsperioden og er en **øvre reference**, ikke en realistisk investeringsprognose. De prognosebaserede backtests bruger kun tidligere observerede priser, men antager fuld gennemførelse af planlagte ordrer til clearingprisen. Likviditet, prisafhængige bud, ubalancer og projektspecifikke nettariffer er ikke fuldt modelleret. Batterislitage er en simplificeret variabel omkostning; en fuld cellealdringsmodel er ikke implementeret.

Den viste sammenligning fra oktober–december 2025 har tidligere været brugt til modelvalg, og er derfor **ikke en uberørt valideringsperiode**. Der fremsættes ingen garanti om fremtidig indtjening.

## Kilder og datalicens

**Kilde: Energinet (www.energidataservice.dk), CC BY 4.0.** Den medfølgende `assets/demo_spot_2025_daily.csv` er bearbejdet ved aggregering til daglige gennemsnit for DK1 i 2025. For timeprodukter er døgnmidlet vægtet på de oprindelige timeprodukter, og for kvartersprodukter på 15-minutters observationer. Originale data er ikke medtaget i distributionen. Se https://www.energidataservice.dk/terms-and-conditions.

## Projektstruktur

```text
app.py                    # Fælles navigation, entré
ui.py                     # Visuel designstil
assets/                    # Lille, lokal demo
    demo_metrics.json
    demo_spot_2025_daily.csv
overview.py               # Porteføljeforside
market_optimization.py    # Oprindelig optimering, bevaret
pages/
    1_Investeringsanalyse.py
    2_Realistisk_handelsstrategi.py
battery_optimizer.py      # Optimeringsmotor
ml_price_forecast.py       # ML-prisprognose
price_data.py, tariff_data.py, battery_config.py
requirements.txt
.streamlit/config.toml
```

Dette projekt er en forsknings- og porteføljedemonstration, ikke et system til automatisk handel eller investeringsrådgivning.


## Offline price archive and API limits

This portfolio distribution bundles original historical Energi Data Service CSVs
for DK1 (2024, 2025, and January through October 2026) under
`data_cache/energy_prices_v2/`. The market optimizer reuses these complete
files without a network request. Other areas or newer dates still require
live API access and may be rate-limited (HTTP 429). Prices are never fabricated
or silently replaced with illustrative figures. The overview dashboard uses a
separate, explicitly labeled daily demonstration series.

Source: Energinet / Energi Data Service, CC BY 4.0.
