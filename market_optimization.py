import calendar
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from price_data import fetch_prices
from battery_optimizer import optimize_battery

from tariff_data import (
    get_active_tariffs,
    add_tariffs_to_prices,
)


# ============================================================
# SIDEKONFIGURATION
# ============================================================

# Sidekonfiguration håndteres i app.py


# ============================================================
# KONSTANTER
# ============================================================

TIMEZONE = "Europe/Copenhagen"

INTERVAL_HOURS = 0.25

MAX_ANALYSIS_MONTHS = 72


GRID_COMPANIES = {
    "Vores Elnet A/S": "5790000610976",
    "TREFOR El-net Øst A/S": "5790000706686",
    "NOE Net A/S": "5790000395620",
    "Andet netselskab": None,
}


# Officielle referenceværdier for Energinets almindelige
# tariffer ved tilslutning gennem distributionsnettet.
#
# Alle energitariffer er angivet i DKK/MWh.
#
# 2025:
# https://energinet.dk/media/alpn1j0h/
# fremskrivning-af-energinets-eltariffer-2025-2027-1.pdf
#
# 2026:
# https://energinet.dk/media/5v3pikp3/
# energinets_tarifkatalog_2026.pdf
#
# Producentbalancetarif 2026:
# https://energinet.dk/media/1tgh2lvv/
# faktaark-producentbetaling-for-
# distributionstilsluttede-produktionsanlaeg-2026.pdf
#
# Bemærk, at 2026-faktaarket og tarifkataloget angiver
# forskellige værdier for producentbalancetariffen.
# Derfor kan 2026-satsen ændres i brugergrænsefladen.

ENERGINET_TARIFFS = {
    2025: {
        "system": 74.0,
        "network": 61.0,
        "injection": 5.0,
        "producer_balance": 6.5,
        "subscription": 182.0,
    },
    2026: {
        "system": 72.0,
        "network": 43.0,
        "injection": 5.0,
        "producer_balance": 6.5,
        "subscription": 187.0,
    },
}


# ============================================================
# FORMATERING
# ============================================================

def format_dkk(value):
    return f"{value:,.0f}".replace(",", ".") + " kr."


def format_mwh(value):
    return f"{value:,.2f}".replace(",", ".") + " MWh"


def format_number(value, decimals=2):
    return (
        f"{value:,.{decimals}f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


# ============================================================
# DATOHJÆLPERE
# ============================================================

def first_day_of_next_month(day):
    if day.month == 12:
        return date(day.year + 1, 1, 1)

    return date(day.year, day.month + 1, 1)


def get_month_windows(start_date, end_date):
    """
    Opdel en analyseperiode i kalendermåneder.

    Første og sidste måned afgrænses til de datoer,
    som brugeren har valgt.
    """

    windows = []

    current_month = date(
        start_date.year,
        start_date.month,
        1,
    )

    while current_month <= end_date:
        next_month = first_day_of_next_month(
            current_month
        )

        window_start = max(
            start_date,
            current_month,
        )

        window_end = min(
            end_date,
            next_month - timedelta(days=1),
        )

        windows.append(
            {
                "start": window_start,
                "end": window_end,
                "month_start": current_month,
                "next_month": next_month,
            }
        )

        current_month = next_month

    return windows


def number_of_calendar_days(year):
    return 366 if calendar.isleap(year) else 365


# ============================================================
# CACHE
# ============================================================

@st.cache_data(
    ttl=86400,
    max_entries=100,
    show_spinner=False,
)
def load_prices_cached(
    start_iso,
    end_iso,
    price_area,
):
    return fetch_prices(
        start_date=start_iso,
        end_date=end_iso,
        price_area=price_area,
    )


@st.cache_data(
    ttl=86400,
    max_entries=100,
    show_spinner=False,
)
def load_active_tariffs_cached(
    gln_number,
    analysis_date,
):
    return get_active_tariffs(
        gln_number=gln_number,
        analysis_date=analysis_date,
    )


@st.cache_data(
    ttl=86400,
    max_entries=100,
    show_spinner=False,
)
def load_prices_with_tariffs_cached(
    prices,
    gln_number,
    import_tariff_code,
    export_tariff_code,
):
    return add_tariffs_to_prices(
        prices=prices,
        gln_number=gln_number,
        import_tariff_code=import_tariff_code,
        export_tariff_code=export_tariff_code,
    )


@st.cache_data(
    max_entries=100,
    show_spinner=False,
)
def optimize_cached(
    prices,
    battery_power,
    battery_capacity,
    roundtrip_efficiency,
    degradation_cost,
    import_cost,
    export_cost,
    trading_cost,
):
    """
    Genbrug en måneds optimeringsresultat,
    hvis data og alle relevante parametre er uændrede.
    """

    return optimize_battery(
        prices=prices,
        battery_power=battery_power,
        battery_capacity=battery_capacity,
        roundtrip_efficiency=roundtrip_efficiency,
        interval_hours=INTERVAL_HOURS,
        start_soc=0,
        end_soc=0,
        degradation_cost_per_mwh=degradation_cost,
        grid_import_tariff_dkk_per_mwh=import_cost,
        grid_export_tariff_dkk_per_mwh=export_cost,
        trading_cost_dkk_per_mwh=trading_cost,
    )


# ============================================================
# VALIDERING OG TIDSOPLØSNING
# ============================================================

def prepare_month_prices(
    raw_prices,
    start_date,
    end_date,
):
    """
    Klargør historiske elpriser til optimering.

    Ældre timepriser udvides til fire kvartersintervaller
    med samme observerede timepris.

    Det skaber ikke nye prisobservationer eller viden.
    Det gør blot tidsopløsningen kompatibel med modellen.

    Funktionen kontrollerer efterfølgende, at samtlige
    forventede kvartersintervaller findes præcis én gang.
    """

    required = [
        "TimeUTC",
        "DayAheadPriceDKK",
    ]

    missing = [
        col
        for col in required
        if col not in raw_prices.columns
    ]

    if missing:
        raise ValueError(
            "Prisdata mangler kolonnerne: "
            + ", ".join(missing)
        )

    prices = raw_prices.copy()

    prices["TimeUTC"] = pd.to_datetime(
        prices["TimeUTC"],
        utc=True,
        errors="coerce",
    )

    prices["DayAheadPriceDKK"] = pd.to_numeric(
        prices["DayAheadPriceDKK"],
        errors="coerce",
    )

    if prices["TimeUTC"].isna().any():
        raise ValueError(
            "Prisdata indeholder ugyldige tidspunkter."
        )

    if prices["DayAheadPriceDKK"].isna().any():
        raise ValueError(
            "Prisdata indeholder manglende eller "
            "ugyldige elpriser."
        )

    if prices["TimeUTC"].duplicated().any():
        raise ValueError(
            "Prisdata indeholder dublerede tidspunkter."
        )

    prices = prices.sort_values(
        "TimeUTC"
    ).reset_index(drop=True)

    prices["TimeDK"] = (
        prices["TimeUTC"]
        .dt.tz_convert(TIMEZONE)
    )

    local_dates = prices["TimeDK"].dt.date

    prices = prices.loc[
        (local_dates >= start_date)
        & (local_dates <= end_date)
    ].copy()

    if prices.empty:
        raise ValueError(
            "Der blev ikke fundet elpriser "
            "for den valgte periode."
        )

    prices = prices.sort_values(
        "TimeUTC"
    ).reset_index(drop=True)

    differences = (
        prices["TimeUTC"]
        .diff()
        .dropna()
        .dt.total_seconds()
    )

    # Historiske priser kan være timebaserede.
    # En time opdeles derfor i fire kvarterer.

    if len(differences) > 0 and (
        differences == 3600
    ).all():

        expanded_parts = []

        for quarter in range(4):

            part = prices.copy()

            part["TimeUTC"] = (
                part["TimeUTC"]
                + pd.Timedelta(
                    minutes=15 * quarter
                )
            )

            expanded_parts.append(part)

        prices = pd.concat(
            expanded_parts,
            ignore_index=True,
        )

        prices = prices.sort_values(
            "TimeUTC"
        ).reset_index(drop=True)

    elif len(differences) > 0 and not (
        differences == 900
    ).all():

        raise ValueError(
            "Prisdata indeholder uregelmæssige "
            "tidsintervaller. Analysen afbrydes "
            "for at undgå et misvisende resultat."
        )

    prices["TimeDK"] = (
        prices["TimeUTC"]
        .dt.tz_convert(TIMEZONE)
    )

    # Forventet tidsakse baseret på danske kalenderdage.
    # UTC-konvertering håndterer sommer- og vintertid.

    expected_start = pd.Timestamp(
        start_date.isoformat(),
        tz=TIMEZONE,
    ).tz_convert("UTC")

    expected_end = pd.Timestamp(
        (
            end_date + timedelta(days=1)
        ).isoformat(),
        tz=TIMEZONE,
    ).tz_convert("UTC")

    expected_times = pd.date_range(
        start=expected_start,
        end=expected_end,
        freq="15min",
        inclusive="left",
    )

    actual_times = pd.DatetimeIndex(
        prices["TimeUTC"]
    )

    if not actual_times.equals(expected_times):

        missing_times = expected_times.difference(
            actual_times
        )

        extra_times = actual_times.difference(
            expected_times
        )

        raise ValueError(
            "Elpriserne dækker ikke hele den valgte "
            "periode korrekt. "
            f"Manglende intervaller: {len(missing_times)}. "
            f"Ekstra intervaller: {len(extra_times)}."
        )

    return prices


def fetch_month_prices(
    window,
    price_area,
):
    """
    Hent en hel kalendermåned med lidt ekstra data
    omkring månedsskiftet.

    Det sikrer korrekt afgrænsning til danske
    kalenderdage, også når UTC og dansk tid afviger.
    """

    fetch_start = (
        window["month_start"]
        - timedelta(days=1)
    )

    fetch_end = (
        window["next_month"]
        + timedelta(days=1)
    )

    raw_prices = load_prices_cached(
        fetch_start.isoformat(),
        fetch_end.isoformat(),
        price_area,
    )

    return prepare_month_prices(
        raw_prices,
        window["start"],
        window["end"],
    )


# ============================================================
# DATAHUB TARIFKATALOG
# ============================================================

def prepare_tariff_catalog(
    tariffs,
    is_export,
):
    catalog = tariffs.copy()

    for column in (
        "Note",
        "Description",
        "ChargeTypeCode",
    ):

        if column not in catalog.columns:
            raise ValueError(
                f"Tarifkataloget mangler {column}."
            )

        catalog[column] = (
            catalog[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    export_mask = (
        catalog["Note"].str.contains(
            "indfødning",
            case=False,
            regex=False,
        )
        | catalog["Description"].str.contains(
            "indfødning",
            case=False,
            regex=False,
        )
    )

    catalog = catalog.loc[
        export_mask if is_export else ~export_mask
    ]

    catalog = catalog.loc[
        catalog["ChargeTypeCode"].ne("")
    ]

    catalog = (
        catalog
        .sort_values(
            "ValidFrom",
            ascending=False,
        )
        .drop_duplicates(
            subset="ChargeTypeCode"
        )
        .reset_index(drop=True)
    )

    return catalog


def short_tariff_label(tariff):

    code = str(
        tariff["ChargeTypeCode"]
    )

    note = str(
        tariff["Note"]
    )

    description = str(
        tariff["Description"]
    )

    if description.casefold().startswith(
        note.casefold()
    ):
        description = description[
            len(note):
        ].strip(" :,-")

    if not description:
        description = "Standardtarif"

    if len(description) > 38:
        description = (
            description[:35].rstrip()
            + "..."
        )

    return f"{code} | {description}"


def render_tariff_picker(
    catalog,
    heading,
    prefix,
):
    """
    Vælgeren vises i det aktuelle Streamlit-område.
    Funktionen kaldes fra sidebaren.

    Alle widgetnøgler er entydige.
    """

    st.markdown(f"#### {heading}")

    if catalog.empty:
        st.warning(
            "Ingen tariffer i denne kategori."
        )
        return None

    groups = sorted(
        catalog["Note"].unique().tolist(),
        key=str.casefold,
    )

    selected_group = st.selectbox(
        "1. Vælg tarifgruppe",
        options=groups,
        index=None,
        placeholder="Vælg tarifgruppe",
        key=f"{prefix}_group",
    )

    if selected_group is None:
        return None

    group_tariffs = catalog.loc[
        catalog["Note"] == selected_group
    ].copy()

    group_tariffs = group_tariffs.sort_values(
        ["Description", "ChargeTypeCode"],
        key=lambda x: x.str.casefold(),
    )

    tariffs_by_code = {
        str(row["ChargeTypeCode"]): row
        for _, row in group_tariffs.iterrows()
    }

    selected_code = st.selectbox(
        "2. Vælg konkret tarif",
        options=list(tariffs_by_code.keys()),
        index=None,
        placeholder="Vælg tarifkode",
        format_func=lambda code: short_tariff_label(
            tariffs_by_code[code]
        ),
        key=(
            f"{prefix}_code_"
            f"{selected_group}"
        ),
    )

    if selected_code is not None:

        tariff = tariffs_by_code[
            selected_code
        ]

        st.success(
            f"Valgt: {selected_group} "
            f"({selected_code})"
        )

        st.caption(
            str(tariff["Description"])
        )

        valid_from = str(
            tariff.get("ValidFrom", "")
        )[:10]

        valid_to = str(
            tariff.get("ValidTo", "")
        )[:10]

        st.caption(
            f"Gyldighed: {valid_from} til "
            f"{valid_to}. Historiske satser "
            "anvendes ved beregningen."
        )

    with st.expander(
        "Se alle tarifkoder i gruppen"
    ):

        st.dataframe(
            group_tariffs[
                [
                    "ChargeTypeCode",
                    "Description",
                    "ValidFrom",
                    "ValidTo",
                ]
            ],
            hide_index=True,
            use_container_width=True,
        )

    return selected_code


# ============================================================
# ENERGINETS TARIFFER
# ============================================================

def get_energinet_costs(
    year,
    mode,
    manual_import,
    manual_export,
    manual_subscription,
    include_balance_tariff,
    balance_tariff_2026,
):
    """
    Returnerer Energinets omkostninger for ét år.

    Lokal DataHub-tarif er ikke inkluderet her.
    Dermed holdes de to typer tariffer adskilt.
    """

    if mode == "Ingen Energinet-tariffer":

        return {
            "import": 0.0,
            "export": 0.0,
            "subscription": 0.0,
        }

    if mode == "Manuelle Energinet-tariffer":

        return {
            "import": manual_import,
            "export": manual_export,
            "subscription": manual_subscription,
        }

    if year not in ENERGINET_TARIFFS:

        raise ValueError(
            "Automatiske Energinet-tariffer "
            f"er endnu ikke dokumenteret for {year}. "
            "Vælg manuelle Energinet-tariffer "
            "eller udelad dem for denne analyse."
        )

    tariff = ENERGINET_TARIFFS[
        year
    ].copy()

    import_cost = (
        tariff["system"]
        + tariff["network"]
    )

    balance_cost = 0.0

    if include_balance_tariff:

        if year == 2026:
            balance_cost = (
                balance_tariff_2026
            )
        else:
            balance_cost = (
                tariff["producer_balance"]
            )

    export_cost = (
        tariff["injection"]
        + balance_cost
    )

    return {
        "import": import_cost,
        "export": export_cost,
        "subscription": tariff["subscription"],
    }


# ============================================================
# RESULTATKONTROL
# ============================================================

def validate_optimization_result(
    schedule,
    optimized_profit,
):
    required = [
        "TimeUTC",
        "PriceDKK",
        "CashflowDKK",
        "DegradationCostDKK",
        "GridImportCostDKK",
        "GridExportCostDKK",
        "GridCostDKK",
        "TradingCostDKK",
        "NetCashflowDKK",
        "ChargeMWh",
        "DischargeMWh",
        "SoCMWh",
    ]

    missing = [
        col
        for col in required
        if col not in schedule.columns
    ]

    if missing:
        raise ValueError(
            "Optimeringsresultatet mangler: "
            + ", ".join(missing)
        )

    if schedule.empty:
        raise ValueError(
            "Optimeringen returnerede "
            "ingen handelsstrategi."
        )

    calculated_profit = (
        schedule["CashflowDKK"].sum()
        - schedule["DegradationCostDKK"].sum()
        - schedule["GridCostDKK"].sum()
        - schedule["TradingCostDKK"].sum()
    )

    schedule_profit = (
        schedule["NetCashflowDKK"].sum()
    )

    if abs(
        calculated_profit - schedule_profit
    ) > 0.05:

        raise ValueError(
            "Omkostningerne stemmer ikke "
            "med nettoresultatet."
        )

    if abs(
        schedule_profit - optimized_profit
    ) > 0.05:

        raise ValueError(
            "Optimeringsresultatet stemmer "
            "ikke med handelsstrategien."
        )


# ============================================================
# RESULTATTABELLER
# ============================================================

AGGREGATION = {
    "CashflowDKK": "sum",
    "DegradationCostDKK": "sum",
    "LocalGridCostDKK": "sum",
    "EnerginetCostDKK": "sum",
    "GridCostDKK": "sum",
    "TradingCostDKK": "sum",
    "SystemSubscriptionDKK": "sum",
    "NetCashflowDKK": "sum",
    "NetAfterKnownCostsDKK": "sum",
    "ChargeMWh": "sum",
    "DischargeMWh": "sum",
}


def create_summary(
    schedule,
    group_column,
):
    summary = (
        schedule
        .groupby(
            group_column,
            as_index=False,
        )
        .agg(AGGREGATION)
    )

    return summary


def calculate_totals(schedule):

    columns = list(
        AGGREGATION.keys()
    )

    return {
        col: float(
            schedule[col].sum()
        )
        for col in columns
    }


# ============================================================
# SIDENS OVERSKRIFT
# ============================================================

st.markdown('<div class="bil-label">01 / MARKEDSMODEL</div>',unsafe_allow_html=True)
st.title("🔋 Markedsoptimering")

st.write(
    "Udforsk historisk batteriarbitrage på DK1 og DK2. "
    "Beregn den teoretisk optimale drift under valgte tariffer og batteribegrænsninger."
)

st.info(
    "Den nuværende handelsmodel beregner den "
    "teoretisk optimale batteridrift ud fra "
    "historiske elpriser. Modellen forudsætter "
    "perfekt kendskab til priserne i hver "
    "optimeringsperiode."
)


# ============================================================
# SIDEBAR
# ============================================================

# Genbrug sidst beregnede indstillinger på tværs af navigation.
_saved_result = st.session_state.get("battery_last_result")
_saved_config = _saved_result.get("configuration") if isinstance(_saved_result, dict) else None
if not isinstance(_saved_config, (list, tuple)) or len(_saved_config) < 20:
    _saved_config = None

with st.sidebar:

    st.header("Analyseindstillinger")

    st.subheader("Elmarked")

    price_area = st.selectbox(
        "Vælg prisområde",
        ["DK1", "DK2"],
        index=["DK1", "DK2"].index(_saved_config[0]) if _saved_config and _saved_config[0] in ("DK1","DK2") else 0,
    )

    st.subheader("Analyseperiode")

    start_date = st.date_input(
        "Startdato",
        value=_saved_config[1] if _saved_config else date(2025, 10, 1),
    )

    end_date = st.date_input(
        "Slutdato",
        value=_saved_config[2] if _saved_config else date(2025, 10, 31),
    )

    if start_date <= end_date:

        selected_windows = get_month_windows(
            start_date,
            end_date,
        )

        st.caption(
            f"Valgt periode: "
            f"{len(selected_windows)} månedlige "
            "beregningsvinduer."
        )

    st.subheader("Batterispecifikationer")

    battery_power = st.number_input(
        "Batterieffekt (MW)",
        min_value=0.1,
        value=float(_saved_config[3]) if _saved_config else 10.0,
        step=1.0,
    )

    battery_capacity = st.number_input(
        "Batterikapacitet (MWh)",
        min_value=0.1,
        value=float(_saved_config[4]) if _saved_config else 20.0,
        step=1.0,
    )

    efficiency_percent = st.number_input(
        "Virkningsgrad (%)",
        min_value=1.0,
        max_value=100.0,
        value=float(_saved_config[5]) if _saved_config else 90.0,
        step=1.0,
    )

    degradation_cost = st.number_input(
        "Batterislitage (kr./MWh afladet)",
        min_value=0.0,
        value=float(_saved_config[6]) if _saved_config else 277.90,
        step=10.0,
    )

    roundtrip_efficiency = (
        efficiency_percent / 100
    )

    st.divider()

    # ========================================================
    # LOKALE NETTARIFFER
    # ========================================================

    st.subheader("Lokale nettariffer")

    tariff_mode = st.radio(
        "Hvordan beregnes lokale nettariffer?",
        [
            "Ingen lokale nettariffer",
            "Automatiske tariffer fra DataHub",
            "Manuelle lokale nettariffer",
        ],
        index=["Ingen lokale nettariffer", "Automatiske tariffer fra DataHub", "Manuelle lokale nettariffer"].index(_saved_config[7]) if _saved_config and _saved_config[7] in ("Ingen lokale nettariffer", "Automatiske tariffer fra DataHub", "Manuelle lokale nettariffer") else 0,
    )

    gln_number = None

    import_tariff_code = None
    export_tariff_code = None

    manual_local_import = 0.0
    manual_local_export = 0.0

    if tariff_mode == (
        "Automatiske tariffer fra DataHub"
    ):

        selected_company = st.selectbox(
            "Vælg netselskab",
            list(GRID_COMPANIES.keys()),
        )

        gln_number = GRID_COMPANIES[
            selected_company
        ]

        if selected_company == (
            "Andet netselskab"
        ):

            gln_number = st.text_input(
                "GLN-nummer",
                value=str(_saved_config[8] or "") if _saved_config else "",
            ).strip()

        if gln_number:

            try:

                with st.spinner(
                    "Henter tarifkatalog..."
                ):

                    active_tariffs = (
                        load_active_tariffs_cached(
                            gln_number,
                            end_date.isoformat(),
                        )
                    )

                import_catalog = (
                    prepare_tariff_catalog(
                        active_tariffs,
                        is_export=False,
                    )
                )

                export_catalog = (
                    prepare_tariff_catalog(
                        active_tariffs,
                        is_export=True,
                    )
                )

                st.markdown(
                    "#### Køb af elektricitet"
                )

                import_tariff_code = (
                    render_tariff_picker(
                        import_catalog,
                        "Importtarif",
                        "import_tariff",
                    )
                )

                st.markdown(
                    "#### Salg af elektricitet"
                )

                export_tariff_code = (
                    render_tariff_picker(
                        export_catalog,
                        "Eksporttarif",
                        "export_tariff",
                    )
                )

                st.caption(
                    "Vælg tarifkoder efter anlæggets "
                    "faktiske nettilslutning. "
                    "Kontrollér især, at koderne "
                    "også er relevante for ældre "
                    "dele af en flerårig periode."
                )

            except Exception as error:

                st.error(
                    "Kunne ikke hente "
                    "tarifmuligheder."
                )

                st.caption(
                    str(error)
                )

    elif tariff_mode == (
        "Manuelle lokale nettariffer"
    ):

        manual_local_import = (
            st.number_input(
                "Lokal importtarif (kr./MWh)",
                min_value=0.0,
                value=float(_saved_config[11]) if _saved_config else 0.0,
                step=10.0,
            )
        )

        manual_local_export = (
            st.number_input(
                "Lokal eksporttarif (kr./MWh)",
                min_value=0.0,
                value=float(_saved_config[12]) if _saved_config else 0.0,
                step=10.0,
            )
        )

    # ========================================================
    # ENERGINETS TARIFFER
    # ========================================================

    st.divider()

    st.subheader("Energinets tariffer")

    energinet_mode = st.radio(
        "Hvordan beregnes Energinets tariffer?",
        [
            "Ingen Energinet-tariffer",
            "Automatiske standardtariffer",
            "Manuelle Energinet-tariffer",
        ],
        index=["Ingen Energinet-tariffer", "Automatiske standardtariffer", "Manuelle Energinet-tariffer"].index(_saved_config[13]) if _saved_config and _saved_config[13] in ("Ingen Energinet-tariffer", "Automatiske standardtariffer", "Manuelle Energinet-tariffer") else 0,
    )

    manual_energinet_import = 0.0
    manual_energinet_export = 0.0
    manual_subscription = 0.0

    include_balance_tariff = True

    balance_tariff_2026 = 6.5

    if energinet_mode == (
        "Automatiske standardtariffer"
    ):

        st.caption(
            "Anvender almindelige Energinet-"
            "tariffer for anlæg tilsluttet "
            "distributionsnettet. "
            "Understøttede år: 2025 og 2026."
        )

        include_balance_tariff = st.checkbox(
            "Medregn producentens balancetarif",
            value=bool(_saved_config[17]) if _saved_config else True,
        )

        if (
            start_date.year <= 2026
            and end_date.year >= 2026
            and include_balance_tariff
        ):

            balance_tariff_2026 = (
                st.number_input(
                    "Producentbalancetarif 2026 "
                    "(kr./MWh)",
                    min_value=0.0,
                    value=float(_saved_config[18]) if _saved_config else 6.5,
                    step=0.1,
                )
            )

            st.caption(
                "Januar-faktaarket angiver "
                "6,50 kr./MWh. Energinets "
                "tidligere tarifkatalog angiver "
                "5,30 kr./MWh. Kontrollér den "
                "gældende sats for det konkrete "
                "anlæg."
            )

        with st.expander(
            "Se de automatiske satser"
        ):

            tariff_table = pd.DataFrame(
                [
                    {
                        "År": year,
                        "Systemtarif": values["system"],
                        "Nettarif": values["network"],
                        "Indfødning": values["injection"],
                        "Producentbalance": (
                            values["producer_balance"]
                        ),
                        "Årligt abonnement": (
                            values["subscription"]
                        ),
                    }
                    for year, values
                    in ENERGINET_TARIFFS.items()
                ]
            )

            st.dataframe(
                tariff_table,
                hide_index=True,
                use_container_width=True,
            )

    elif energinet_mode == (
        "Manuelle Energinet-tariffer"
    ):

        manual_energinet_import = (
            st.number_input(
                "Energinet import (kr./MWh)",
                min_value=0.0,
                value=float(_saved_config[14]) if _saved_config else 0.0,
                step=10.0,
            )
        )

        manual_energinet_export = (
            st.number_input(
                "Energinet eksport (kr./MWh)",
                min_value=0.0,
                value=float(_saved_config[15]) if _saved_config else 0.0,
                step=10.0,
            )
        )

        manual_subscription = (
            st.number_input(
                "Energinet abonnement (kr./år)",
                min_value=0.0,
                value=float(_saved_config[16]) if _saved_config else 0.0,
                step=10.0,
            )
        )

        st.caption(
            "De manuelle satser anvendes "
            "på alle år i analyseperioden."
        )

    # ========================================================
    # HANDELSOMKOSTNINGER
    # ========================================================

    st.divider()

    st.subheader("Handelsomkostninger")

    trading_cost = st.number_input(
        "Handelsomkostning (kr./MWh handlet)",
        min_value=0.0,
        value=float(_saved_config[19]) if _saved_config else 0.0,
        step=1.0,
    )

    st.caption(
        "Opkræves på både købt og solgt "
        "energi. Sæt til 0, hvis den "
        "ikke skal medregnes."
    )

    # ========================================================
    # START
    # ========================================================

    st.divider()

    run_optimization = st.button(
        "Start batterioptimering",
        type="primary",
        use_container_width=True,
    )


# ============================================================
# PARAMETERIDENTIFIKATION
# ============================================================

# Bruges til at sikre, at gemte resultater kun vises
# for netop de indstillinger, som de er beregnet med.

current_configuration = (
    price_area,
    start_date,
    end_date,
    battery_power,
    battery_capacity,
    efficiency_percent,
    degradation_cost,
    tariff_mode,
    gln_number,
    import_tariff_code,
    export_tariff_code,
    manual_local_import,
    manual_local_export,
    energinet_mode,
    manual_energinet_import,
    manual_energinet_export,
    manual_subscription,
    include_balance_tariff,
    balance_tariff_2026,
    trading_cost,
)


# ============================================================
# GENNEMFØR OPTIMERING
# ============================================================

if run_optimization:

    if start_date > end_date:
        st.error(
            "Startdato skal ligge før "
            "eller på slutdato."
        )
        st.stop()

    windows = get_month_windows(
        start_date,
        end_date,
    )

    if len(windows) > MAX_ANALYSIS_MONTHS:

        st.error(
            "Vælg højst 72 måneder "
            "pr. optimering."
        )

        st.stop()

    if tariff_mode == (
        "Automatiske tariffer fra DataHub"
    ):

        if not gln_number:
            st.error(
                "Vælg et netselskab."
            )
            st.stop()

        if not import_tariff_code:
            st.error(
                "Vælg en importtarif."
            )
            st.stop()

        if not export_tariff_code:
            st.error(
                "Vælg en eksporttarif."
            )
            st.stop()

    if energinet_mode == (
        "Automatiske standardtariffer"
    ):

        unsupported_years = sorted(
            {
                window["start"].year
                for window in windows
                if window["start"].year
                not in ENERGINET_TARIFFS
            }
        )

        if unsupported_years:

            st.error(
                "Automatiske Energinet-tariffer "
                "mangler for følgende år: "
                + ", ".join(
                    str(year)
                    for year in unsupported_years
                )
                + ". Vælg manuelle tariffer "
                "eller udelad Energinets tariffer."
            )

            st.stop()

    if len(windows) > 12:

        st.info(
            "Du har valgt en flerårig analyse. "
            "Optimeringen gennemføres måned "
            "for måned, og første gennemløb "
            "kan tage noget tid."
        )

    progress_bar = st.progress(0)

    progress_text = st.empty()

    all_schedules = []

    try:

        for index, window in enumerate(
            windows,
            start=1,
        ):

            window_start = window["start"]
            window_end = window["end"]

            progress_text.info(
                "Behandler "
                f"{window_start:%m/%Y} "
                f"({index} af {len(windows)})..."
            )

            # ========================================
            # HENT OG KONTROLLÉR PRISER
            # ========================================

            prices = fetch_month_prices(
                window,
                price_area,
            )

            # ========================================
            # LOKALE NETTARIFFER
            # ========================================

            local_import_scalar = 0.0
            local_export_scalar = 0.0

            if tariff_mode == (
                "Automatiske tariffer fra DataHub"
            ):

                prices = (
                    load_prices_with_tariffs_cached(
                        prices,
                        gln_number,
                        import_tariff_code,
                        export_tariff_code,
                    )
                )

                for col in (
                    "ImportTariffDKKPerMWh",
                    "ExportTariffDKKPerMWh",
                ):

                    if col not in prices.columns:

                        raise ValueError(
                            "DataHub-data mangler "
                            f"kolonnen {col}."
                        )

                    values = pd.to_numeric(
                        prices[col],
                        errors="coerce",
                    )

                    if values.isna().any():

                        raise ValueError(
                            "Der mangler historiske "
                            "DataHub-tariffer i "
                            f"{window_start:%m/%Y}. "
                            "Kontrollér tarifkoder "
                            "og gyldighed."
                        )

            elif tariff_mode == (
                "Manuelle lokale nettariffer"
            ):

                local_import_scalar = (
                    manual_local_import
                )

                local_export_scalar = (
                    manual_local_export
                )

            # ========================================
            # ENERGINET
            # ========================================

            energinet = get_energinet_costs(
                year=window_start.year,
                mode=energinet_mode,
                manual_import=manual_energinet_import,
                manual_export=manual_energinet_export,
                manual_subscription=manual_subscription,
                include_balance_tariff=(
                    include_balance_tariff
                ),
                balance_tariff_2026=(
                    balance_tariff_2026
                ),
            )

            total_import_scalar = (
                local_import_scalar
                + energinet["import"]
            )

            total_export_scalar = (
                local_export_scalar
                + energinet["export"]
            )

            # ========================================
            # OPTIMER BATTERIET
            # ========================================

            schedule, optimized_profit = (
                optimize_cached(
                    prices=prices,
                    battery_power=battery_power,
                    battery_capacity=battery_capacity,
                    roundtrip_efficiency=(
                        roundtrip_efficiency
                    ),
                    degradation_cost=(
                        degradation_cost
                    ),
                    import_cost=(
                        total_import_scalar
                    ),
                    export_cost=(
                        total_export_scalar
                    ),
                    trading_cost=trading_cost,
                )
            )

            schedule = schedule.copy()

            validate_optimization_result(
                schedule,
                optimized_profit,
            )

            # ========================================
            # TID OG PERIODE
            # ========================================

            schedule["TimeUTC"] = (
                pd.to_datetime(
                    schedule["TimeUTC"],
                    utc=True,
                )
            )

            schedule["TimeDK"] = (
                schedule["TimeUTC"]
                .dt.tz_convert(TIMEZONE)
            )

            schedule["Date"] = (
                schedule["TimeDK"]
                .dt.date
            )

            schedule["Year"] = (
                schedule["TimeDK"]
                .dt.year
            )

            schedule["Month"] = (
                schedule["TimeDK"]
                .dt.strftime("%Y-%m")
            )

            # ========================================
            # FORDEL OMKOSTNINGER
            # ========================================

            schedule["EnerginetImportCostDKK"] = (
                schedule["ChargeMWh"]
                * energinet["import"]
            )

            schedule["EnerginetExportCostDKK"] = (
                schedule["DischargeMWh"]
                * energinet["export"]
            )

            schedule["EnerginetCostDKK"] = (
                schedule["EnerginetImportCostDKK"]
                + schedule["EnerginetExportCostDKK"]
            )

            schedule["LocalGridCostDKK"] = (
                schedule["GridCostDKK"]
                - schedule["EnerginetCostDKK"]
            )

            # Systemabonnement er en fast omkostning.
            # Derfor påvirker det ikke handelsstrategien.
            #
            # Beløbet fordeles efter de lokale kalenderdage
            # og derefter på dagens faktiske intervaller.

            annual_subscription = (
                energinet["subscription"]
            )

            intervals_per_day = (
                schedule
                .groupby("Date")["TimeUTC"]
                .transform("size")
            )

            schedule["SystemSubscriptionDKK"] = (
                annual_subscription
                / number_of_calendar_days(
                    window_start.year
                )
                / intervals_per_day
            )

            schedule["NetAfterKnownCostsDKK"] = (
                schedule["NetCashflowDKK"]
                - schedule["SystemSubscriptionDKK"]
            )

            # ========================================
            # GEM MÅNED
            # ========================================

            all_schedules.append(
                schedule
            )

            progress_bar.progress(
                index / len(windows)
            )

        # ============================================
        # SAMLET RESULTAT
        # ============================================

        complete_schedule = pd.concat(
            all_schedules,
            ignore_index=True,
        )

        complete_schedule = (
            complete_schedule
            .sort_values("TimeUTC")
            .reset_index(drop=True)
        )

        if complete_schedule[
            "TimeUTC"
        ].duplicated().any():

            raise ValueError(
                "Den samlede handelsstrategi "
                "indeholder dublerede tidspunkter."
            )

        daily = create_summary(
            complete_schedule,
            "Date",
        )

        monthly = create_summary(
            complete_schedule,
            "Month",
        )

        yearly = create_summary(
            complete_schedule,
            "Year",
        )

        totals = calculate_totals(
            complete_schedule
        )

        # Streamlit genkører scriptet ved ændringer.
        # Vi gemmer derfor resultaterne i sessionen.

        st.session_state[
            "battery_last_result"
        ] = {
            "configuration": current_configuration,
            "schedule": complete_schedule,
            "daily": daily,
            "monthly": monthly,
            "yearly": yearly,
            "totals": totals,
            "months": len(windows),
        }

        progress_text.empty()
        progress_bar.empty()

        st.success(
            "Batterioptimeringen er gennemført!"
        )

    except Exception as error:

        progress_text.empty()
        progress_bar.empty()

        st.error(
            f"Der opstod en fejl: {error}"
        )

        st.exception(error)

        st.stop()


# ============================================================
# VIS RESULTATER
# ============================================================

result = st.session_state.get(
    "battery_last_result"
)

if result is None:

    st.subheader("Prøv en interaktiv analyse")
    st.caption("Vælg en kort historisk periode og klik på 'Start batterioptimering' i sidepanelet. Store analyser tager længere tid og afhænger af Energinets API.")

    st.subheader("Allerede beregnet eksempel")
    st.caption("DK1, hele 2025, 10 MW / 20 MWh, 90 % virkningsgrad, uden tariffer og handelsgebyrer. Historisk model med perfekt prisviden.")
    _ex1, _ex2, _ex3 = st.columns(3)
    _ex1.metric("Bruttofortjeneste", "5.683.268 kr.")
    _ex2.metric("Batterislitage", "1.907.515 kr.")
    _ex3.metric("Efter variable omkostninger", "3.775.753 kr.")
    st.info("Eksemplet er en tidligere beregnet teoretisk reference, ikke en forventet fremtidig handelsindtjening.")
    st.page_link("overview.py",label="Tilbage til oversigten",icon="🏠")
    st.stop()


if result["configuration"] != current_configuration:

    st.warning(
        "Du har ændret analyseindstillingerne. "
        "Klik på 'Start batterioptimering' "
        "for at beregne et nyt resultat."
    )

    st.stop()


schedule = result["schedule"]

daily = result["daily"]

monthly = result["monthly"]

yearly = result["yearly"]

totals = result["totals"]


# ============================================================
# ØKONOMISK RESULTAT
# ============================================================

st.header("Økonomisk resultat")

col1, col2, col3 = st.columns(3)

with col1:

    st.metric(
        "Bruttofortjeneste",
        format_dkk(
            totals["CashflowDKK"]
        ),
    )

with col2:

    st.metric(
        "Batterislitage",
        format_dkk(
            totals["DegradationCostDKK"]
        ),
    )

with col3:

    st.metric(
        "Samlede energitariffer",
        format_dkk(
            totals["GridCostDKK"]
        ),
    )


col4, col5, col6 = st.columns(3)

with col4:

    st.metric(
        "Handelsomkostninger",
        format_dkk(
            totals["TradingCostDKK"]
        ),
    )

with col5:

    st.metric(
        "Resultat efter variable omkostninger",
        format_dkk(
            totals["NetCashflowDKK"]
        ),
    )

with col6:

    st.metric(
        "Resultat efter kendte abonnementer",
        format_dkk(
            totals["NetAfterKnownCostsDKK"]
        ),
    )


with st.expander(
    "Se detaljeret omkostningsfordeling"
):

    cost_overview = pd.DataFrame(
        {
            "Omkostningspost": [
                "Bruttofortjeneste",
                "Batterislitage",
                "Lokale nettariffer",
                "Energinets energitariffer",
                "Handelsomkostninger",
                "Energinets systemabonnement",
                "Resultat efter variable omkostninger",
                "Resultat efter kendte abonnementer",
            ],
            "Beløb (DKK)": [
                totals["CashflowDKK"],
                totals["DegradationCostDKK"],
                totals["LocalGridCostDKK"],
                totals["EnerginetCostDKK"],
                totals["TradingCostDKK"],
                totals["SystemSubscriptionDKK"],
                totals["NetCashflowDKK"],
                totals["NetAfterKnownCostsDKK"],
            ],
        }
    )

    st.dataframe(
        cost_overview.round(2),
        hide_index=True,
        use_container_width=True,
    )


st.info(
    "Resultaterne omfatter de valgte "
    "handelsomkostninger og energitariffer. "
    "Eventuelle investeringsomkostninger, "
    "forsikring, øvrige faste driftsomkostninger "
    "og projektspecifikke udgifter er endnu "
    "ikke medregnet. Resultaterne er derfor "
    "ikke et samlet investeringsafkast."
)


# ============================================================
# OPLYSNING OM MÅNEDSVIS OPTIMERING
# ============================================================

if result["months"] > 1:

    st.caption(
        "Lange analyseperioder er optimeret "
        "måned for måned. Batteriet starter "
        "og slutter hver måned med 0 MWh. "
        "Resultatet er derfor summen af de "
        "teoretisk optimale månedsstrategier "
        "under disse betingelser."
    )


# ============================================================
# BATTERIDRIFT
# ============================================================

st.header("Batteridrift")

bought_energy = (
    schedule["ChargeMWh"].sum()
)

sold_energy = (
    schedule["DischargeMWh"].sum()
)

max_soc = (
    schedule["SoCMWh"].max()
)

end_soc = (
    schedule["SoCMWh"].iloc[-1]
)

col7, col8, col9, col10 = st.columns(4)

with col7:

    st.metric(
        "Samlet købt energi",
        format_mwh(bought_energy),
    )

with col8:

    st.metric(
        "Samlet solgt energi",
        format_mwh(sold_energy),
    )

with col9:

    st.metric(
        "Højeste energiniveau",
        format_mwh(max_soc),
    )

with col10:

    st.metric(
        "Energi ved periodens afslutning",
        format_mwh(end_soc),
    )


# ============================================================
# ÅRLIGE RESULTATER
# ============================================================

if len(yearly) > 1:

    st.header("Årlig indtjening")

    st.write(
        "Sammenligning af de beregnede "
        "resultater mellem kalenderår."
    )

    yearly_chart = yearly[
        [
            "Year",
            "NetAfterKnownCostsDKK",
        ]
    ].copy()

    yearly_chart["Year"] = (
        yearly_chart["Year"].astype(str)
    )

    st.bar_chart(
        yearly_chart,
        x="Year",
        y="NetAfterKnownCostsDKK",
        x_label="År",
        y_label="Resultat (DKK)",
        sort=False,
    )

    st.dataframe(
        yearly.round(2),
        hide_index=True,
        use_container_width=True,
    )


# ============================================================
# MÅNEDLIGE RESULTATER
# ============================================================

st.header("Månedlig indtjening")

st.write(
    "Resultat efter de medregnede variable "
    "omkostninger og kendte systemabonnementer."
)

monthly_chart = monthly[
    [
        "Month",
        "NetAfterKnownCostsDKK",
    ]
].copy()

st.bar_chart(
    monthly_chart,
    x="Month",
    y="NetAfterKnownCostsDKK",
    x_label="Måned",
    y_label="Resultat (DKK)",
    sort=False,
)


# ============================================================
# DAGLIG INDTJENING
# ============================================================

if len(daily) <= 100:

    st.header("Daglig indtjening")

    daily_chart = daily[
        [
            "Date",
            "NetAfterKnownCostsDKK",
        ]
    ].copy()

    daily_chart["Date"] = (
        pd.to_datetime(
            daily_chart["Date"]
        ).dt.strftime("%d.%m.%Y")
    )

    st.bar_chart(
        daily_chart,
        x="Date",
        y="NetAfterKnownCostsDKK",
        x_label="Dato",
        y_label="Resultat (DKK)",
        sort=False,
    )


# ============================================================
# ELPRISER OG ENERGINIVEAU
# ============================================================

st.header("Elpriser")

st.write(
    "Historiske elpriser for den "
    "valgte analyseperiode."
)

price_chart = (
    schedule
    .set_index("TimeUTC")[
        ["PriceDKK"]
    ]
)

st.line_chart(
    price_chart,
    x_label="Tidspunkt (UTC)",
    y_label="Elpris (DKK/MWh)",
)


st.header("Batteriets energiniveau")

soc_chart = (
    schedule
    .set_index("TimeUTC")[
        ["SoCMWh"]
    ]
)

st.line_chart(
    soc_chart,
    x_label="Tidspunkt (UTC)",
    y_label="Energiniveau (MWh)",
)


# ============================================================
# DETALJEREDE RESULTATER
# ============================================================

st.header("Detaljerede resultater")

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "Årlige resultater",
        "Månedlige resultater",
        "Daglige resultater",
        "Handelsstrategi",
    ]
)

with tab1:

    st.subheader(
        "Årlig oversigt"
    )

    st.dataframe(
        yearly.round(2),
        hide_index=True,
        use_container_width=True,
    )

with tab2:

    st.subheader(
        "Månedlig oversigt"
    )

    st.dataframe(
        monthly.round(2),
        hide_index=True,
        use_container_width=True,
    )

with tab3:

    st.subheader(
        "Daglig oversigt"
    )

    st.dataframe(
        daily.round(2),
        hide_index=True,
        use_container_width=True,
    )

with tab4:

    st.subheader(
        "Optimal handelsstrategi"
    )

    st.dataframe(
        schedule.round(2),
        hide_index=True,
        use_container_width=True,
    )


# ============================================================
# DOWNLOAD
# ============================================================

st.header("Download resultater")

download_col1, download_col2 = st.columns(2)

with download_col1:

    st.download_button(
        label="Download handelsstrategi",
        data=schedule.to_csv(
            index=False
        ).encode("utf-8-sig"),
        file_name="battery_schedule.csv",
        mime="text/csv",
        on_click="ignore",
        use_container_width=True,
    )

with download_col2:

    st.download_button(
        label="Download daglige resultater",
        data=daily.to_csv(
            index=False
        ).encode("utf-8-sig"),
        file_name="battery_daily_results.csv",
        mime="text/csv",
        on_click="ignore",
        use_container_width=True,
    )


download_col3, download_col4 = st.columns(2)

with download_col3:

    st.download_button(
        label="Download månedlige resultater",
        data=monthly.to_csv(
            index=False
        ).encode("utf-8-sig"),
        file_name="battery_monthly_results.csv",
        mime="text/csv",
        on_click="ignore",
        use_container_width=True,
    )

with download_col4:

    st.download_button(
        label="Download årlige resultater",
        data=yearly.to_csv(
            index=False
        ).encode("utf-8-sig"),
        file_name="battery_yearly_results.csv",
        mime="text/csv",
        on_click="ignore",
        use_container_width=True,
    )