import json

import pandas as pd
import requests


# ==========================================
# BATTERY INVESTMENT LAB
# NETTARIFFER FRA ENERGINET
# ==========================================

DATAHUB_API_URL = (
    "https://api.energidataservice.dk/"
    "dataset/DatahubPricelist"
)


# ==========================================
# HENT NETTARIFFER FRA DATAHUB
# ==========================================

def fetch_datahub_tariffs(
    gln_number=None,
    charge_type_code=None,
    end_date=None,
    limit=100
):
    """
    Henter tarifdata fra Energinets DataHub.

    Parametre:
        gln_number:
            Netselskabets GLN-nummer.

        charge_type_code:
            Valgfri specifik tarifkode.

        end_date:
            Hent tariffer med ValidFrom før denne dato.

        limit:
            Maksimalt antal observationer.
            0 betyder alle observationer.
    """

    params = {
        "limit": limit,
        "sort": "ValidFrom desc"
    }

    if end_date is not None:
        params["end"] = str(end_date)

    filters = {}

    if gln_number is not None:

        filters["GLN_Number"] = [
            str(gln_number)
        ]

    if charge_type_code is not None:

        filters["ChargeTypeCode"] = [
            str(charge_type_code)
        ]

    if filters:

        params["filter"] = json.dumps(filters)

    print(
        "\nForbinder til Energinets tarifdatabase...",
        flush=True
    )

    try:

        response = requests.get(
            DATAHUB_API_URL,
            params=params,
            timeout=60
        )

        response.raise_for_status()

        data = response.json()

    except requests.RequestException as error:

        raise RuntimeError(
            f"Kunne ikke hente tarifdata: {error}"
        ) from error

    records = data.get("records", [])

    if not records:

        raise ValueError(
            "Ingen tarifdata fundet for de valgte kriterier."
        )

    tariffs = pd.DataFrame(records)

    return tariffs


# ==========================================
# KLARGØR TARIFDATA
# ==========================================

def prepare_tariff_data(tariffs):
    """
    Klargør datoer og udvælger nettariffer.

    D03 er tariftypen i DataHub.
    """

    result = tariffs.copy()

    required_columns = [
        "ChargeType",
        "ChargeTypeCode",
        "ValidFrom",
        "ValidTo",
        "ResolutionDuration"
    ]

    for column in required_columns:

        if column not in result.columns:

            raise ValueError(
                f"Tarifdata mangler kolonnen: {column}"
            )

    result["ValidFrom"] = pd.to_datetime(
        result["ValidFrom"],
        errors="coerce"
    )

    result["ValidTo"] = pd.to_datetime(
        result["ValidTo"],
        errors="coerce"
    )

    result = result[
        result["ChargeType"] == "D03"
    ].copy()

    result = result.dropna(
        subset=["ValidFrom"]
    )

    return result


# ==========================================
# FIND GÆLDENDE NETTARIFFER
# ==========================================

def get_active_tariffs(
    gln_number,
    analysis_date
):
    """
    Finder de nettariffer, der var gældende
    på den valgte analysedato.
    """

    analysis_date = pd.Timestamp(
        analysis_date
    )

    api_end_date = (
        analysis_date + pd.Timedelta(days=1)
    ).strftime("%Y-%m-%d")

    tariffs = fetch_datahub_tariffs(
        gln_number=gln_number,
        end_date=api_end_date,
        limit=0
    )

    tariffs = prepare_tariff_data(tariffs)

    active = tariffs[
        (tariffs["ValidFrom"] <= analysis_date)
        &
        (
            tariffs["ValidTo"].isna()
            |
            (tariffs["ValidTo"] > analysis_date)
        )
    ].copy()

    if active.empty:

        raise ValueError(
            "Ingen gældende nettariffer fundet "
            "for den valgte dato."
        )

    active = active[
        active["Note"]
        .fillna("")
        .str.contains(
            "nettarif",
            case=False,
            regex=False
        )
    ].copy()

    if active.empty:

        raise ValueError(
            "Ingen nettariffer fundet "
            "blandt de gældende tariffer."
        )

    active = active.sort_values(
        ["Note", "ValidFrom"],
        ascending=[True, False]
    )

    return active


# ==========================================
# KONVERTÉR TIDSPUNKT TIL DANSK TID
# ==========================================

def to_danish_local_time(value):
    """
    Konverterer et tidspunkt til dansk lokaltid.

    Hvis tidspunktet allerede er uden tidszone,
    antages det at være angivet i dansk lokaltid.
    """

    timestamp = pd.Timestamp(value)

    if pd.isna(timestamp):

        raise ValueError(
            "Elprisdata indeholder et ugyldigt tidspunkt."
        )

    if timestamp.tzinfo is not None:

        timestamp = (
            timestamp
            .tz_convert("Europe/Copenhagen")
            .tz_localize(None)
        )

    return timestamp


# ==========================================
# FIND TARIFPRIS PÅ ET BESTEMT TIDSPUNKT
# ==========================================

def get_tariff_price(
    tariffs,
    tariff_code,
    timestamp
):
    """
    Finder tarifprisen på et bestemt tidspunkt.

    Understøttede opløsninger:
        PT1H: Timepris.
        P1D: Døgnpris.

    Returnerer prisen i kr./MWh.
    """

    selected = tariffs[
        tariffs["ChargeTypeCode"].astype(str)
        == str(tariff_code)
    ].copy()

    if selected.empty:

        raise ValueError(
            f"Tarifkode {tariff_code} blev ikke fundet."
        )

    # Find de tarifversioner, der gælder
    # på det aktuelle tidspunkt.

    active = selected[
        (selected["ValidFrom"] <= timestamp)
        &
        (
            selected["ValidTo"].isna()
            |
            (selected["ValidTo"] > timestamp)
        )
    ].copy()

    if active.empty:

        raise ValueError(
            f"Ingen gældende tarif for "
            f"{tariff_code} den {timestamp}."
        )

    # Hvis flere versioner overlapper,
    # anvendes den med seneste startdato.

    active = active.sort_values(
        "ValidFrom",
        ascending=False
    )

    tariff = active.iloc[0]

    resolution = tariff["ResolutionDuration"]

    # ==========================================
    # VÆLG KORREKT PRISKOLONNE
    # ==========================================

    if resolution == "PT1H":

        # Price1 svarer til kl. 00-01.
        # Price2 svarer til kl. 01-02 osv.

        price_column = (
            f"Price{timestamp.hour + 1}"
        )

    elif resolution == "P1D":

        # Døgnsats gælder alle døgnets timer.

        price_column = "Price1"

    else:

        raise ValueError(
            f"Ukendt tarifopløsning "
            f"for {tariff_code}: {resolution}"
        )

    # ==========================================
    # HENT PRIS
    # ==========================================

    price_kwh = pd.to_numeric(
        tariff[price_column],
        errors="coerce"
    )

    if pd.isna(price_kwh):

        raise ValueError(
            f"Manglende tarifpris for "
            f"{tariff_code} den {timestamp}."
        )

    # ==========================================
    # OMREGN TIL KR./MWH
    # ==========================================

    price_mwh = float(price_kwh) * 1000

    return price_mwh


# ==========================================
# TILFØJ NETTARIFFER TIL ELPRISDATA
# ==========================================

def add_tariffs_to_prices(
    prices,
    gln_number,
    import_tariff_code,
    export_tariff_code
):
    """
    Tilføjer import- og eksporttariffer
    til hvert interval i elprisdataene.

    Funktionens resultat indeholder:

        ImportTariffDKKPerMWh
        ExportTariffDKKPerMWh

    Tarifferne vælges automatisk efter
    tidspunkt og gyldighedsperiode.
    """

    # ==========================================
    # KONTROL AF INPUT
    # ==========================================

    if prices.empty:

        raise ValueError(
            "Elprisdata må ikke være tomme."
        )

    if "TimeDK" not in prices.columns:

        raise ValueError(
            "Elprisdata mangler kolonnen TimeDK."
        )

    if not str(gln_number).strip():

        raise ValueError(
            "Netselskabets GLN-nummer mangler."
        )

    if not str(import_tariff_code).strip():

        raise ValueError(
            "Importtarifkoden mangler."
        )

    if not str(export_tariff_code).strip():

        raise ValueError(
            "Eksporttarifkoden mangler."
        )

    result = prices.copy().reset_index(drop=True)

    # ==========================================
    # KLARGØR TIDSPUNKTER
    # ==========================================

    local_times = result["TimeDK"].map(
        to_danish_local_time
    )

    # ==========================================
    # FIND SENESTE ANALYSEDATO
    # ==========================================

    last_date = local_times.max().normalize()

    api_end_date = (
        last_date + pd.Timedelta(days=1)
    ).strftime("%Y-%m-%d")

    # ==========================================
    # HENT NETTARIFFER
    # ==========================================

    print(
        "\nHenter nettariffer til analyseperioden...",
        flush=True
    )

    tariffs = fetch_datahub_tariffs(
        gln_number=gln_number,
        end_date=api_end_date,
        limit=0
    )

    tariffs = prepare_tariff_data(tariffs)

    # ==========================================
    # BEREGN IMPORTTARIFFER
    # ==========================================

    print(
        "\nBeregner importtariffer...",
        flush=True
    )

    import_tariffs = []

    for timestamp in local_times:

        tariff_price = get_tariff_price(
            tariffs=tariffs,
            tariff_code=import_tariff_code,
            timestamp=timestamp
        )

        import_tariffs.append(tariff_price)

    # ==========================================
    # BEREGN EKSPORTTARIFFER
    # ==========================================

    print(
        "\nBeregner eksporttariffer...",
        flush=True
    )

    export_tariffs = []

    for timestamp in local_times:

        tariff_price = get_tariff_price(
            tariffs=tariffs,
            tariff_code=export_tariff_code,
            timestamp=timestamp
        )

        export_tariffs.append(tariff_price)

    # ==========================================
    # TILFØJ KOLONNER
    # ==========================================

    result["ImportTariffDKKPerMWh"] = (
        import_tariffs
    )

    result["ExportTariffDKKPerMWh"] = (
        export_tariffs
    )

    # ==========================================
    # KONTROLLÉR RESULTAT
    # ==========================================

    if result[
        [
            "ImportTariffDKKPerMWh",
            "ExportTariffDKKPerMWh"
        ]
    ].isna().any().any():

        raise RuntimeError(
            "Nogle prisintervaller mangler nettariffer."
        )

    print(
        "\nNettariffer tilføjet til alle "
        f"{len(result)} prisintervaller!"
    )

    return result


# ==========================================
# TEST AF TARIFSYSTEMET
# ==========================================

if __name__ == "__main__":

    from price_data import fetch_prices

    print("\nBATTERY INVESTMENT LAB")
    print("KONTROL AF NETTARIFFER")

    # ==========================================
    # TESTINDSTILLINGER
    # ==========================================

    TEST_GLN = "5790000610976"

    TEST_DATE = "2026-09-01"

    TEST_IMPORT_CODE = "TNT1018"

    TEST_EXPORT_CODE = "NTINDF11"

    # ==========================================
    # TEST 1: FIND GÆLDENDE TARIFKODER
    # ==========================================

    print("\nTEST 1: GÆLDENDE NETTARIFFER")

    print("Analysedato:", TEST_DATE)

    print("Netområde:", TEST_GLN)

    active_tariffs = get_active_tariffs(
        gln_number=TEST_GLN,
        analysis_date=TEST_DATE
    )

    columns = [
        "ChargeOwner",
        "ChargeTypeCode",
        "Note",
        "ResolutionDuration",
        "ValidFrom",
        "ValidTo",
        "Price1"
    ]

    print("\nGÆLDENDE NETTARIFFER")

    print(
        active_tariffs[columns].to_string(
            index=False
        )
    )

    print(
        "\nAntal gældende nettariffer:",
        len(active_tariffs)
    )

    # ==========================================
    # TEST 2: HENT ELPRISER
    # ==========================================

    print("\nTEST 2: HENT ELPRISER")

    test_prices = fetch_prices(
        start_date="2026-09-01",
        end_date="2026-09-02",
        price_area="DK1"
    )

    print(
        "\nAntal elprisobservationer:",
        len(test_prices)
    )

    # ==========================================
    # TEST 3: TILFØJ NETTARIFFER
    # ==========================================

    print("\nTEST 3: TILFØJ NETTARIFFER")

    combined_prices = add_tariffs_to_prices(
        prices=test_prices,
        gln_number=TEST_GLN,
        import_tariff_code=TEST_IMPORT_CODE,
        export_tariff_code=TEST_EXPORT_CODE
    )

    # ==========================================
    # VIS RESULTATER
    # ==========================================

    result_columns = [
        "TimeDK",
        "DayAheadPriceDKK",
        "ImportTariffDKKPerMWh",
        "ExportTariffDKKPerMWh"
    ]

    print("\nELPRISER MED NETTARIFFER")

    print(
        combined_prices[result_columns]
        .head(32)
        .to_string(index=False)
    )

    # ==========================================
    # KONTROLLÉR OVERGANGEN KL. 06
    # ==========================================

    print("\nKONTROL AF TARIFSKIFT")

    positions = [0, 23, 24, 27, 95]

    positions = [
        i for i in positions
        if i < len(combined_prices)
    ]

    print(
        combined_prices[result_columns]
        .iloc[positions]
        .to_string(index=False)
    )

    # ==========================================
    # SAMLET KONTROL
    # ==========================================

    print("\nSAMLET DATAKONTROL")

    print(
        "Antal prisintervaller:",
        len(combined_prices)
    )

    print(
        "Laveste importtarif:",
        round(
            combined_prices[
                "ImportTariffDKKPerMWh"
            ].min(),
            2
        ),
        "kr./MWh"
    )

    print(
        "Højeste importtarif:",
        round(
            combined_prices[
                "ImportTariffDKKPerMWh"
            ].max(),
            2
        ),
        "kr./MWh"
    )

    print(
        "Laveste eksporttarif:",
        round(
            combined_prices[
                "ExportTariffDKKPerMWh"
            ].min(),
            2
        ),
        "kr./MWh"
    )

    print(
        "Højeste eksporttarif:",
        round(
            combined_prices[
                "ExportTariffDKKPerMWh"
            ].max(),
            2
        ),
        "kr./MWh"
    )

    print("\nAlle tests er gennemført!")