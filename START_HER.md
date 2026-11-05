# Start her: Den nye portfolio-version

Denne mappe er en **selvstændig, opdateret kopi** af Battery Investment Lab. Din oprindelige projektmappe skal ikke overskrives.

## 1. Åbn projektet

1. Pak `BatteryInvestmentLab_Portfolio.zip` ud.
2. Åbn mappen `BatteryInvestmentLab_Portfolio` i Visual Studio Code med **File → Open Folder**.
3. Kontrollér, at du kan se `app.py`, `overview.py`, `requirements.txt`, `market_optimization.py`, `pages/` og `.streamlit/`.

## 2. Start appen

Åbn **Terminal → New Terminal** i VS Code. Indtast:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Appen skal nu åbne på **Oversigt**, hvor du straks kan se historiske eksempelresultater.

## 3. Afprøv alle fire sider

- **Oversigt:** Se den mørke forside, historiske DK1-priser og sammenligning af fem strategier. Der kræves ingen beregning.
- **Handelsstrategier:** Se eksempelresultater fra oktober til december 2025 uden først at køre en analyse.
- **Investeringsanalyse:** Brug demonstrationsscenariet, og justér investeringsbeløb, rente eller analysehorisont. Startværdierne for investering er **opdigtede**, ikke tilbud.
- **Markedsoptimering:** Vælg et kort interval, for eksempel 1. til 7. oktober 2025, med DK1, 10 MW, 20 MWh, 90 % og uden tariffer. Klik **Start batterioptimering**. Prisdata hentes fra Energinets API, og den første hentning kan blive begrænset af API'et.

For en ny **fuld strategi-backtest** kræves mere end 28 sammenhængende dages prisdata fra en tidligere optimering i den samme Streamlit-session.

## 4. Når det virker: GitHub og hjemmeside

1. Opret et **offentligt** repository på https://github.com/new med navnet `battery-investment-lab`.
2. Upload projektfilerne fra **inde i** `BatteryInvestmentLab_Portfolio`. `app.py` skal ligge i **repositoryets rod**, ikke i en ekstra mappe.
3. Sørg især for at få `.streamlit/config.toml`, `assets/`, `pages/`, `requirements.txt` og alle aktive `.py`-filer med. Undlad Python-miljøer, cachefiler og private nøgler.
4. Gå til https://share.streamlit.io og vælg **Create app**.
5. Vælg repository, branch `main` og entrypoint `app.py`. Vælg gerne Python 3.12.
6. Klik **Deploy**. Kontrollér forsiden og demonstrationsvisningerne, inden du deler linket.

## Kendte forbehold

Selve den nye forside, de indbyggede prisdata og de viste historiske resultater er kvalitetstjekket. De oprindelige beregningsscripts er bevaret. I denne udviklingssession kunne den faktiske Streamlit/PuLP-server ikke startes, fordi de to pakker ikke kunne installeres i testmiljøet. Derfor er din lokale test i trin 3 vigtig, før vi kalder siden publiceringsklar.
