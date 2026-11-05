
import calendar

import pandas as pd
import streamlit as st


# ============================================================
# SIDEKONFIGURATION
# ============================================================

# Sidekonfiguration håndteres i app.py


# ============================================================
# HJÆLPEFUNKTIONER
# ============================================================

def dkk(value):
    return f"{value:,.0f}".replace(",", ".") + " kr."


def percent(value):
    return f"{value * 100:.1f}".replace(".", ",") + " %"


# ============================================================
# NUTIDSVÆRDI
# ============================================================

def npv(cashflows, discount_rate):
    """
    Beregn nutidsværdien af alle pengestrømme.

    År 0 indeholder den oprindelige investering.
    """

    return sum(
        float(amount) / (1.0 + discount_rate) ** year
        for year, amount in enumerate(cashflows)
    )


# ============================================================
# INTERN RENTE
# ============================================================

def irr(cashflows):
    """
    Beregn intern rente numerisk.

    Returnerer None, hvis der ikke findes
    præcis én identificerbar løsning.
    """

    rates = (
        [-0.99 + n * 0.01 for n in range(100)]
        + [n * 0.01 for n in range(101)]
        + [1.0 + n * 0.1 for n in range(1, 191)]
    )

    rates = sorted(set(rates))

    roots = []

    a = rates[0]
    fa = npv(cashflows, a)

    for b in rates[1:]:

        fb = npv(cashflows, b)

        if abs(fa) < 1e-6:
            roots.append(a)

        elif fa * fb < 0:

            low, high = a, b
            f_low = fa

            for _ in range(65):

                mid = (low + high) / 2
                f_mid = npv(cashflows, mid)

                if f_low * f_mid <= 0:
                    high = mid

                else:
                    low = mid
                    f_low = f_mid

            roots.append((low + high) / 2)

        a, fa = b, fb

    if abs(fa) < 1e-6:
        roots.append(a)

    unique = []

    for value in roots:

        if not any(
            abs(value - x) < 1e-5
            for x in unique
        ):
            unique.append(value)

    if len(unique) == 1:
        return unique[0]

    return None


# ============================================================
# TILBAGEBETALINGSTID
# ============================================================

def payback(cashflows, discount_rate=None):
    """
    Beregn den første tilbagebetalingstid.

    Hvis discount_rate er angivet,
    anvendes diskonterede pengestrømme.
    """

    cumulative = float(cashflows[0])

    for year, raw in enumerate(
        cashflows[1:],
        start=1
    ):

        amount = float(raw)

        if discount_rate is not None:
            amount /= (1.0 + discount_rate) ** year

        previous = cumulative

        cumulative += amount

        if (
            previous < 0 <= cumulative
            and amount > 0
        ):

            return (
                year - 1
                + (-previous / amount)
            )

    return None


# ============================================================
# FREMSKRIV ÅRLIGE PENGESTRØMME
# ============================================================

def create_forecast(
    initial_capex,
    annual_revenue,
    annual_opex,
    life_years,
    discount_rate,
    revenue_growth,
    opex_growth,
    replacement_year,
    replacement_cost,
    end_value,
):
    """
    Opret en investeringsberegning for hele perioden.

    Driftsbidraget er før faste omkostninger,
    men efter de variable handelsomkostninger.

    Batterislitage indgår ikke som en yderligere
    kapitalomkostning i pengestrømmene.
    """

    rows = []

    flows = [-float(initial_capex)]

    # --------------------------------------------------------
    # ÅR 0: OPRINDELIG INVESTERING
    # --------------------------------------------------------

    rows.append({
        "År": 0,
        "Driftsbidrag før faste omkostninger": 0.0,
        "Faste driftsomkostninger": 0.0,
        "Udskiftning": 0.0,
        "Restværdi": 0.0,
        "Pengestrøm": -float(initial_capex),
    })

    # --------------------------------------------------------
    # ÅR 1 TIL ANALYSEHORISONT
    # --------------------------------------------------------

    for year in range(1, life_years + 1):

        revenue = (
            annual_revenue
            * (1 + revenue_growth) ** (year - 1)
        )

        opex = (
            annual_opex
            * (1 + opex_growth) ** (year - 1)
        )

        replacement = (
            replacement_cost
            if year == replacement_year
            else 0.0
        )

        residual = (
            end_value
            if year == life_years
            else 0.0
        )

        cashflow = (
            revenue
            - opex
            - replacement
            + residual
        )

        flows.append(cashflow)

        rows.append({
            "År": year,
            "Driftsbidrag før faste omkostninger": revenue,
            "Faste driftsomkostninger": opex,
            "Udskiftning": replacement,
            "Restværdi": residual,
            "Pengestrøm": cashflow,
        })

    # --------------------------------------------------------
    # RESULTATTABEL
    # --------------------------------------------------------

    frame = pd.DataFrame(rows)

    frame["Akkumuleret pengestrøm"] = (
        frame["Pengestrøm"].cumsum()
    )

    frame["Diskonteret pengestrøm"] = [
        amount / (1 + discount_rate) ** i
        for i, amount in enumerate(flows)
    ]

    frame["Akkumuleret diskonteret"] = (
        frame["Diskonteret pengestrøm"].cumsum()
    )

    return frame, flows


# ============================================================
# HISTORISKE RESULTATER FRA BATTERIOPTIMERINGEN
# ============================================================

def historical_overview(schedule):
    """
    Beregn driftsbidrag for hvert historisk år.

    Den beregnede slitage lægges tilbage,
    fordi batteriets anskaffelse og eventuelle
    udskiftning håndteres som investeringer.
    """

    required = {
        "TimeUTC",
        "NetAfterKnownCostsDKK",
        "DegradationCostDKK",
    }

    missing = required - set(schedule.columns)

    if missing:

        raise ValueError(
            "De gemte resultater mangler: "
            + ", ".join(sorted(missing))
        )

    data = schedule[
        [
            "TimeUTC",
            "NetAfterKnownCostsDKK",
            "DegradationCostDKK",
        ]
    ].copy()

    # --------------------------------------------------------
    # TIDSPUNKTER
    # --------------------------------------------------------

    data["TimeUTC"] = pd.to_datetime(
        data["TimeUTC"],
        utc=True,
        errors="coerce",
    )

    for column in [
        "NetAfterKnownCostsDKK",
        "DegradationCostDKK",
    ]:

        data[column] = pd.to_numeric(
            data[column],
            errors="coerce",
        )

    if (
        data.isna().any().any()
        or data["TimeUTC"].duplicated().any()
    ):

        raise ValueError(
            "Historiske resultater indeholder "
            "manglende værdier eller dubletter."
        )

    local_time = (
        data["TimeUTC"]
        .dt.tz_convert("Europe/Copenhagen")
    )

    data["Dato"] = local_time.dt.date
    data["År"] = local_time.dt.year

    # --------------------------------------------------------
    # TILBAGEFØR BEREGNET SLITAGE
    # --------------------------------------------------------

    data["Driftsbidrag"] = (
        data["NetAfterKnownCostsDKK"]
        + data["DegradationCostDKK"]
    )

    # --------------------------------------------------------
    # ÅRLIG OVERSIGT
    # --------------------------------------------------------

    overview = (
        data.groupby(
            "År",
            as_index=False
        )
        .agg(
            Dage=("Dato", "nunique"),
            Driftsbidrag=("Driftsbidrag", "sum"),
            Slitage_tilbageført=(
                "DegradationCostDKK",
                "sum"
            ),
        )
    )

    overview["Kalenderdage"] = (
        overview["År"].map(
            lambda year: (
                366
                if calendar.isleap(int(year))
                else 365
            )
        )
    )

    overview["Fuldt_år"] = (
        overview["Dage"]
        == overview["Kalenderdage"]
    )

    return overview, data


# ============================================================
# OVERSKRIFT
# ============================================================

st.markdown('<div class="bil-label">03 / INVESTERING</div>',unsafe_allow_html=True)
st.title("💰 Investeringsanalyse")

st.write(
    "Vurdér et batterianlægs økonomi med udgangspunkt "
    "i historiske handelsresultater eller et selvvalgt "
    "indtjeningsscenarie."
)

st.info(
    "Den historiske handelsoptimering forudsætter "
    "perfekt viden om priserne. En investering baseret "
    "på disse resultater er derfor et illustrativt "
    "scenarie, ikke en prognose for faktisk fremtidig "
    "indtjening."
)


# ============================================================
# HENT GEMT BATTERIOPTIMERING
# ============================================================

stored = st.session_state.get(
    "battery_last_result"
)

overview = None

if stored is not None:

    try:

        overview, _ = historical_overview(
            stored["schedule"]
        )

        with st.expander(
            "Se historiske data fra handelsoptimeringen"
        ):

            st.dataframe(
                overview,
                hide_index=True,
                use_container_width=True,
            )

            st.caption(
                "Driftsbidrag er resultatet efter de "
                "tidligere valgte variable omkostninger "
                "og systemabonnementer, men før beregnet "
                "batterislitage og nye faste "
                "driftsomkostninger."
            )

            configuration = stored.get(
                "configuration"
            )

            if (
                isinstance(configuration, tuple)
                and len(configuration) > 13
            ):

                local_mode = str(
                    configuration[7]
                )

                energinet_mode = str(
                    configuration[13]
                )

                if (
                    local_mode.startswith("Ingen")
                    or energinet_mode.startswith("Ingen")
                ):

                    st.warning(
                        "Mindst én tarifkategori var "
                        "fravalgt ved handelsoptimeringen. "
                        "Det historiske driftsbidrag "
                        "omfatter derfor ikke alle tariffer."
                    )

    except (KeyError, TypeError, ValueError) as error:

        st.warning(
            "De gemte handelsresultater "
            f"kunne ikke læses: {error}"
        )

        overview = None


# ============================================================
# 1. FORVENTET ÅRLIGT DRIFTSBIDRAG
# ============================================================

st.header("1. Forventet årligt driftsbidrag")

options = [
    "Demonstration: perfekt handelsfacit 2025",
    "Indtast selv et årligt driftsbidrag",
]

if overview is not None:

    options.insert(
        0,
        "Brug historiske handelsresultater"
    )

revenue_mode = st.radio(
    "Grundlag for indtjening",
    options,
    horizontal=True,
)

base_revenue = 0.0

source_label = "Manuelt scenarie"


# ============================================================
# HISTORISK INDTJENING
# ============================================================

if revenue_mode == "Brug historiske handelsresultater":

    full_years = (
        overview.loc[
            overview["Fuldt_år"],
            "År"
        ]
        .astype(int)
        .tolist()
    )

    methods = [
        "Alle analyserede dage, annualiseret"
    ]

    if full_years:

        methods = [
            "Seneste komplette kalenderår",
            "Gennemsnit af komplette kalenderår",
        ] + methods

    method = st.selectbox(
        "Vælg historisk reference",
        methods,
    )

    # --------------------------------------------------------
    # SENESTE KOMPLETTE ÅR
    # --------------------------------------------------------

    if method == "Seneste komplette kalenderår":

        year = max(full_years)

        base_revenue = float(
            overview.loc[
                overview["År"] == year,
                "Driftsbidrag"
            ].iloc[0]
        )

        source_label = (
            f"Historisk handelsresultat for {year}"
        )

    # --------------------------------------------------------
    # GENNEMSNIT AF KOMPLETTE ÅR
    # --------------------------------------------------------

    elif method == "Gennemsnit af komplette kalenderår":

        base_revenue = float(
            overview.loc[
                overview["År"].isin(full_years),
                "Driftsbidrag"
            ].mean()
        )

        source_label = (
            "Gennemsnit af komplette historiske år"
        )

    # --------------------------------------------------------
    # ANNUALISERING AF EN VALGFRI PERIODE
    # --------------------------------------------------------

    else:

        total_revenue = float(
            overview["Driftsbidrag"].sum()
        )

        total_days = int(
            overview["Dage"].sum()
        )

        base_revenue = (
            total_revenue
            / total_days
            * 365.0
        )

        source_label = (
            f"Annualiseret på baggrund af "
            f"{total_days} analyserede dage"
        )

        st.warning(
            "Annualisering antager, at de analyserede "
            "dage er repræsentative for et helt år. "
            "Det kan være misvisende ved sæsonudsving."
        )

    st.metric(
        "Historisk baseret årligt driftsbidrag "
        "før faste omkostninger",
        dkk(base_revenue),
    )

    st.caption(
        "Den beregnede slitage er lagt tilbage. "
        "Faktiske batteriudskiftninger "
        "modelleres separat."
    )


# ============================================================
# OFFENTLIG DEMONSTRATION
# ============================================================

elif revenue_mode == "Demonstration: perfekt handelsfacit 2025":

    from demo_data import showcase
    demo = showcase()["market_2025"]
    base_revenue = float(demo["gross_dkk"])
    source_label = "Teoretisk demonstrationsscenarie fra DK1, 2025"
    st.metric("Historisk bruttoarbitrage 2025", dkk(base_revenue))
    st.warning(
        "Kun et illustrativt scenarie. Beløbet stammer fra optimering med "
        "perfekt kendskab til markedspriserne og uden tariffer, handelsgebyrer "
        "eller dokumenterede faste omkostninger. Det er ikke en realistisk "
        "indtjeningsprognose. Vælg egne anlægspriser og driftsomkostninger nedenfor."
    )
    st.caption(
        "Startværdierne for investering og faste omkostninger nedenfor er "
        "udelukkende opdigtede regneeksempler og kan ændres. De er ikke "
        "pristilbud eller dokumenterede investeringsomkostninger."
    )

# ============================================================
# MANUELT INDTJENINGSSCENARIE
# ============================================================

else:

    manual_million = st.number_input(
        "Årligt driftsbidrag før faste "
        "omkostninger (mio. kr.)",
        min_value=-1000.0,
        max_value=1000.0,
        value=0.0,
        step=0.5,
        format="%.2f",
        help=(
            "Beløb efter elindkøb, nettariffer "
            "og handelsomkostninger, men før faste "
            "driftsomkostninger og investering."
        ),
    )

    base_revenue = manual_million * 1_000_000


# ============================================================
# 2. ANLÆGSINVESTERING
# ============================================================

st.header("2. Anlægsinvestering og faste omkostninger")

st.caption(
    "Indtast priser fra konkrete tilbud eller et "
    "dokumenteret referencegrundlag. Der indsættes "
    "ikke automatisk usikre standardpriser. "
    "Alle beløb er eksklusive moms."
)

col1, col2, col3 = st.columns(3)

with col1:

    battery_capex = st.number_input(
        "Batterianlæg og installation (mio. kr.)",
        min_value=0.0,
        value=30.0 if revenue_mode == "Demonstration: perfekt handelsfacit 2025" else 0.0,
        step=1.0,
    )

with col2:

    connection_capex = st.number_input(
        "Nettilslutning (mio. kr.)",
        min_value=0.0,
        value=5.0 if revenue_mode == "Demonstration: perfekt handelsfacit 2025" else 0.0,
        step=0.5,
    )

with col3:

    extra_capex = st.number_input(
        "Øvrig etablering (mio. kr.)",
        min_value=0.0,
        value=2.0 if revenue_mode == "Demonstration: perfekt handelsfacit 2025" else 0.0,
        step=0.5,
    )


# ============================================================
# FASTE DRIFTSOMKOSTNINGER
# ============================================================

annual_opex_million = st.number_input(
    "Faste driftsomkostninger i første år "
    "(mio. kr./år)",
    min_value=0.0,
    value=1.0 if revenue_mode == "Demonstration: perfekt handelsfacit 2025" else 0.0,
    step=0.1,
    help=(
        "Eksempelvis service, forsikring, areal, "
        "faste softwareaftaler og administration, "
        "hvis de ikke allerede er medregnet."
    ),
)

initial_capex = (
    battery_capex
    + connection_capex
    + extra_capex
) * 1_000_000

annual_opex = (
    annual_opex_million
    * 1_000_000
)

st.caption(
    "0 kr. i et felt betyder, at udgiften "
    "ikke er oplyst eller ikke medregnes. "
    "Det er ikke dokumentation for, "
    "at den faktiske udgift er nul."
)


# ============================================================
# 3. LEVETID OG ØKONOMISKE FORUDSÆTNINGER
# ============================================================

st.header("3. Levetid og økonomiske forudsætninger")

col4, col5, col6 = st.columns(3)

with col4:

    years = st.number_input(
        "Analysehorisont (år)",
        min_value=1,
        max_value=40,
        value=15,
        step=1,
    )

with col5:

    discount_percent = st.number_input(
        "Diskonteringsrente (% nominelt)",
        min_value=0.0,
        max_value=40.0,
        value=7.0,
        step=0.5,
    )

with col6:

    revenue_growth_percent = st.number_input(
        "Årlig ændring i driftsbidrag (% nominelt)",
        min_value=-30.0,
        max_value=30.0,
        value=0.0,
        step=0.5,
    )


col7, col8 = st.columns(2)

with col7:

    opex_growth_percent = st.number_input(
        "Årlig ændring i faste "
        "driftsudgifter (% nominelt)",
        min_value=-10.0,
        max_value=30.0,
        value=0.0,
        step=0.5,
    )

with col8:

    residual_million = st.number_input(
        "Restværdi ved periodens afslutning "
        "(mio. kr.)",
        min_value=0.0,
        value=0.0,
        step=0.5,
    )


# ============================================================
# BATTERIUDSKIFTNING
# ============================================================

include_replacement = st.checkbox(
    "Medregn en batteriudskiftning undervejs",
    value=False,
)

replacement_year = None
replacement_cost = 0.0

if include_replacement:

    replacement_col1, replacement_col2 = st.columns(2)

    with replacement_col1:

        replacement_year = st.number_input(
            "År for udskiftning",
            min_value=1,
            max_value=int(years),
            value=min(10, int(years)),
            step=1,
        )

    with replacement_col2:

        replacement_million = st.number_input(
            "Udgift til udskiftning (mio. kr.)",
            min_value=0.0,
            value=0.0,
            step=0.5,
        )

        replacement_cost = (
            replacement_million
            * 1_000_000
        )


st.caption(
    "Pengestrømmene beregnes i nominelle kroner. "
    "Det historiske driftsbidrag fastholdes "
    "som udgangspunkt nominelt, medmindre du "
    "ændrer vækstraten. Skat, finansiering "
    "og øvrige ukendte omkostninger "
    "er ikke medregnet."
)


# ============================================================
# KONTROL AF INVESTERING
# ============================================================

if initial_capex <= 0:

    st.warning(
        "Angiv en samlet investering større end "
        "0 kr. for at beregne NPV, IRR og "
        "tilbagebetalingstid."
    )

    st.stop()


# ============================================================
# GENNEMFØR INVESTERINGSBEREGNING
# ============================================================

forecast, cashflows = create_forecast(
    initial_capex=initial_capex,
    annual_revenue=base_revenue,
    annual_opex=annual_opex,
    life_years=int(years),
    discount_rate=discount_percent / 100,
    revenue_growth=revenue_growth_percent / 100,
    opex_growth=opex_growth_percent / 100,
    replacement_year=replacement_year,
    replacement_cost=replacement_cost,
    end_value=residual_million * 1_000_000,
)


# ============================================================
# BEREGN INVESTERINGSNØGLETAL
# ============================================================

calculated_npv = npv(
    cashflows,
    discount_percent / 100
)

calculated_irr = irr(
    cashflows
)

simple_payback = payback(
    cashflows
)

discounted_payback = payback(
    cashflows,
    discount_percent / 100
)


# ============================================================
# 4. INVESTERINGSRESULTAT
# ============================================================

st.header("4. Investeringsresultat")

metric1, metric2, metric3, metric4 = st.columns(4)

with metric1:

    st.metric(
        "Samlet investering",
        dkk(initial_capex),
    )

with metric2:

    st.metric(
        "Nutidsværdi (NPV)",
        dkk(calculated_npv),
    )

with metric3:

    st.metric(
        "Intern rente (IRR)",
        (
            percent(calculated_irr)
            if calculated_irr is not None
            else "Ikke entydig"
        ),
    )

with metric4:

    st.metric(
        "Simpel tilbagebetaling",
        (
            f"{simple_payback:.1f} år"
            if simple_payback is not None
            else "Ikke opnået"
        ),
    )


# ============================================================
# DISKONTERET TILBAGEBETALING
# ============================================================

if discounted_payback is not None:

    st.caption(
        f"Diskonteret tilbagebetalingstid: "
        f"{discounted_payback:.1f} år."
    )

else:

    st.caption(
        "Diskonteret tilbagebetaling opnås ikke "
        "inden for analysehorisonten."
    )


# ============================================================
# ADVARSEL OM MANGLENDE OMKOSTNINGER
# ============================================================

if (
    annual_opex <= 0
    or connection_capex <= 0
):

    st.warning(
        "Mindst én vigtig omkostningspost står "
        "til 0 kr. Resultatet kan derfor "
        "overvurdere investeringens rentabilitet, "
        "hvis der findes udeladte omkostninger."
    )


# ============================================================
# KONTROL AF IRR
# ============================================================

if calculated_irr is None:

    st.caption(
        "IRR kan ikke vises entydigt for de valgte "
        "pengestrømme. Ved flere skift mellem "
        "negative og positive beløb kan der være "
        "flere matematiske løsninger."
    )


# ============================================================
# ÅRLIGE PENGESTRØMME
# ============================================================

st.subheader("Årlige pengestrømme")

chart_data = (
    forecast
    .set_index("År")[
        [
            "Pengestrøm",
            "Akkumuleret pengestrøm",
        ]
    ]
)

st.line_chart(
    chart_data,
    x_label="År",
    y_label="DKK",
)

st.dataframe(
    forecast.round(2),
    hide_index=True,
    use_container_width=True,
)


# ============================================================
# FØLSOMHEDSANALYSE
# ============================================================

st.subheader(
    "Følsomhed over for årligt driftsbidrag"
)

st.caption(
    "Alt andet holdes konstant. Beregningen "
    "kræver ikke en ny batterioptimering."
)

sensitivity = []

for change in (
    -0.30,
    -0.15,
    0.0,
    0.15,
    0.30,
):

    _, altered_cashflows = create_forecast(
        initial_capex=initial_capex,
        annual_revenue=base_revenue * (1 + change),
        annual_opex=annual_opex,
        life_years=int(years),
        discount_rate=discount_percent / 100,
        revenue_growth=revenue_growth_percent / 100,
        opex_growth=opex_growth_percent / 100,
        replacement_year=replacement_year,
        replacement_cost=replacement_cost,
        end_value=residual_million * 1_000_000,
    )

    sensitivity.append({
        "Indtjening": f"{change:+.0%}",
        "NPV (DKK)": npv(
            altered_cashflows,
            discount_percent / 100
        ),
    })

sensitivity_data = pd.DataFrame(
    sensitivity
)

st.bar_chart(
    sensitivity_data,
    x="Indtjening",
    y="NPV (DKK)",
    sort=False,
)


# ============================================================
# DOWNLOAD RESULTATER
# ============================================================

st.download_button(
    "Download investeringsberegning (CSV)",
    data=forecast.to_csv(
        index=False
    ).encode("utf-8-sig"),
    file_name="battery_investment_cashflows.csv",
    mime="text/csv",
    on_click="ignore",
)


# ============================================================
# DOKUMENTATION
# ============================================================

st.caption(
    f"Indtjeningsgrundlag: {source_label}."
)

st.markdown(
    "**Metodekilder:** "
    "[Energistyrelsens rentabilitetsvurderinger]"
    "(https://ens.dk/media/7801/download) "
    "og [teknologikataloger]"
    "(https://ens.dk/technologydata). "
    "Kilderne bruges som metodisk reference. "
    "De konkrete investeringspriser og "
    "driftsomkostninger er de værdier, "
    "du selv har indtastet."
)
