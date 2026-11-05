
"""
Battery Investment Lab: hurtigere batterioptimering.

LP anvendes, hvor samtidig opladning og afladning
ikke kan forbedre løsningen.

Binære variabler anvendes kun i prisintervaller,
hvor denne garanti ikke holder.

Output er kompatibelt med den eksisterende app.py.
"""

import math
import time

import numpy as np
import pandas as pd
import pulp


# ============================================================
# INDSTILLINGER
# ============================================================

TIMEZONE = "Europe/Copenhagen"

SOLVER_TIME_LIMIT_SECONDS = 120


# ============================================================
# HJÆLPEFUNKTIONER
# ============================================================

def _numeric_column(frame, name, default=0.0):

    if name not in frame.columns:

        return np.full(
            len(frame),
            float(default),
            dtype=float
        )

    values = pd.to_numeric(
        frame[name],
        errors="coerce"
    )

    array = values.to_numpy(dtype=float)

    if not np.isfinite(array).all():

        raise ValueError(
            f"Prisdata indeholder ugyldige eller "
            f"manglende værdier i {name}."
        )

    return array


def _finite_number(
    value,
    name,
    minimum=None,
    maximum=None
):

    try:

        number = float(value)

    except (TypeError, ValueError) as error:

        raise ValueError(
            f"{name} skal være et tal."
        ) from error

    if not math.isfinite(number):

        raise ValueError(
            f"{name} skal være et endeligt tal."
        )

    if minimum is not None and number < minimum:

        raise ValueError(
            f"{name} skal være mindst {minimum}."
        )

    if maximum is not None and number > maximum:

        raise ValueError(
            f"{name} må højst være {maximum}."
        )

    return number


# ============================================================
# HOVEDFUNKTION
# ============================================================

def optimize_battery(
    prices,
    battery_power,
    battery_capacity,
    roundtrip_efficiency,
    interval_hours=0.25,
    start_soc=0,
    end_soc=0,
    degradation_cost_per_mwh=0,
    grid_import_tariff_dkk_per_mwh=0,
    grid_export_tariff_dkk_per_mwh=0,
    trading_cost_dkk_per_mwh=0,
):
    """
    Maksimerer batteriets historiske nettoresultat.

    Batterifysik:

    soc[t+1] = soc[t]
               + charge_mwh * sqrt(eta)
               - discharge_mwh / sqrt(eta)

    Lokale DataHub-tariffer hentes fra priserne.

    Skalarbaserede import- og eksporttariffer
    lægges oveni, eksempelvis Energinets tariffer.

    Kun intervaller, hvor samtidig opladning og
    afladning kan forbedre den lineære løsning,
    får binære beslutningsvariabler.
    """

    # ========================================================
    # 1. KONTROLLÉR INPUT
    # ========================================================

    if (
        not isinstance(prices, pd.DataFrame)
        or prices.empty
    ):

        raise ValueError(
            "Der er ingen elpriser at optimere."
        )

    battery_power = _finite_number(
        battery_power,
        "Batterieffekt",
        minimum=0.0000001
    )

    battery_capacity = _finite_number(
        battery_capacity,
        "Batterikapacitet",
        minimum=0.0000001
    )

    eta = _finite_number(
        roundtrip_efficiency,
        "Virkningsgrad",
        minimum=0.0000001,
        maximum=1
    )

    dt = _finite_number(
        interval_hours,
        "Intervallængde",
        minimum=0.0000001
    )

    start_soc = _finite_number(
        start_soc,
        "Startenergi",
        minimum=0,
        maximum=battery_capacity
    )

    end_soc = _finite_number(
        end_soc,
        "Slutenergi",
        minimum=0,
        maximum=battery_capacity
    )

    wear = _finite_number(
        degradation_cost_per_mwh,
        "Batterislitage",
        minimum=0
    )

    scalar_import = _finite_number(
        grid_import_tariff_dkk_per_mwh,
        "Importtarif"
    )

    scalar_export = _finite_number(
        grid_export_tariff_dkk_per_mwh,
        "Eksporttarif"
    )

    trading_fee = _finite_number(
        trading_cost_dkk_per_mwh,
        "Handelsomkostning",
        minimum=0
    )

    # ========================================================
    # 2. KLARGØR PRISDATA
    # ========================================================

    required = {
        "TimeUTC",
        "DayAheadPriceDKK"
    }

    missing = required - set(prices.columns)

    if missing:

        raise ValueError(
            "Prisdata mangler kolonnerne: "
            + ", ".join(sorted(missing))
        )

    frame = prices.copy()

    frame["TimeUTC"] = pd.to_datetime(
        frame["TimeUTC"],
        utc=True,
        errors="coerce"
    )

    if frame["TimeUTC"].isna().any():

        raise ValueError(
            "Der er ugyldige UTC-tidspunkter "
            "i prisdata."
        )

    frame = (
        frame
        .sort_values("TimeUTC")
        .reset_index(drop=True)
    )

    if frame["TimeUTC"].duplicated().any():

        raise ValueError(
            "Prisdata indeholder dublerede "
            "UTC-tidspunkter."
        )

    price = _numeric_column(
        frame,
        "DayAheadPriceDKK"
    )

    # ========================================================
    # 3. TARIFFER OG OMKOSTNINGER
    # ========================================================

    local_import = _numeric_column(
        frame,
        "ImportTariffDKKPerMWh"
    )

    local_export = _numeric_column(
        frame,
        "ExportTariffDKKPerMWh"
    )

    import_tariff = (
        local_import + scalar_import
    )

    export_tariff = (
        local_export + scalar_export
    )

    # Pris pr. købt MWh, inklusive omkostninger.

    buy_price = (
        price
        + import_tariff
        + trading_fee
    )

    # Nettoindtægt pr. solgt MWh,
    # inklusive batterislitage.

    sell_price = (
        price
        - export_tariff
        - trading_fee
        - wear
    )

    if not (
        np.isfinite(buy_price).all()
        and np.isfinite(sell_price).all()
    ):

        raise ValueError(
            "Priser og tariffer giver ugyldige "
            "handelspriser."
        )

    # ========================================================
    # 4. VÆLG OPTIMERINGSMETODE
    # ========================================================

    n = len(frame)

    sqrt_eta = math.sqrt(eta)

    # Når:
    #
    # buy_price >= eta * sell_price
    #
    # kan samtidig opladning og afladning ikke
    # øge fortjenesten.
    #
    # Her behøves ingen binær variabel.
    #
    # Ved ekstremt negative priser kan
    # betingelsen være brudt. I de intervaller
    # bevarer vi den præcise binære model.

    risky = np.flatnonzero(
        buy_price < eta * sell_price - 1e-9
    )

    risky_set = set(risky.tolist())

    print(
        f"Starter batterioptimering: {n} intervaller, "
        f"{len(risky_set)} binære variabler.",
        flush=True
    )

    started = time.perf_counter()

    # ========================================================
    # 5. OPRET OPTIMERINGSMODEL
    # ========================================================

    model = pulp.LpProblem(
        "Battery_Investment_Lab",
        pulp.LpMaximize
    )

    # Opladningseffekt i MW.

    charge = [
        pulp.LpVariable(
            f"ChargePower_{t}",
            lowBound=0,
            upBound=battery_power
        )
        for t in range(n)
    ]

    # Afladningseffekt i MW.

    discharge = [
        pulp.LpVariable(
            f"DischargePower_{t}",
            lowBound=0,
            upBound=battery_power
        )
        for t in range(n)
    ]

    # Energiniveau i MWh.
    # Der er ét ekstra tidspunkt, så vi
    # kan kontrollere slutniveauet.

    soc = [
        pulp.LpVariable(
            f"SoC_{t}",
            lowBound=0,
            upBound=battery_capacity
        )
        for t in range(n + 1)
    ]

    # ========================================================
    # 6. START- OG SLUTENERGI
    # ========================================================

    model += soc[0] == start_soc

    model += soc[n] == end_soc

    # ========================================================
    # 7. BATTERIETS FYSISKE BEGRÆNSNINGER
    # ========================================================

    for t in range(n):

        # Energibalance.

        model += (
            soc[t + 1]
            == soc[t]
            + charge[t] * dt * sqrt_eta
            - discharge[t] * dt / sqrt_eta
        )

        # Samlet effektbegrænsning.

        model += (
            charge[t] + discharge[t]
            <= battery_power
        )

        # Binære variabler bruges kun
        # ved de kritiske prisintervaller.

        if t in risky_set:

            mode = pulp.LpVariable(
                f"Mode_{t}",
                cat="Binary"
            )

            model += (
                charge[t]
                <= battery_power * mode
            )

            model += (
                discharge[t]
                <= battery_power * (1 - mode)
            )

    # ========================================================
    # 8. MAKSIMER NETTOFORTJENESTE
    # ========================================================

    model += pulp.lpSum(
        dt * (
            discharge[t] * float(sell_price[t])
            - charge[t] * float(buy_price[t])
        )
        for t in range(n)
    )

    # ========================================================
    # 9. LØS OPTIMERINGEN
    # ========================================================

    solver = pulp.PULP_CBC_CMD(
        msg=False,
        threads=1,
        timeLimit=SOLVER_TIME_LIMIT_SECONDS
    )

    model.solve(solver)

    elapsed = (
        time.perf_counter() - started
    )

    status = pulp.LpStatus[
        model.status
    ]

    print(
        f"Optimering afsluttet efter "
        f"{elapsed:.1f} sekunder. "
        f"Løserstatus: {status}.",
        flush=True
    )

    if status != "Optimal":

        raise RuntimeError(
            "Batterimodellen blev ikke løst "
            "optimalt. "
            f"Løserstatus: {status}. "
            "Se terminalen for oplysninger "
            "om måneden."
        )

    # Hvis en optimering med binære variabler
    # rammer tidsgrænsen, accepterer vi ikke
    # stiltiende en løsning, hvis optimalitet
    # ikke kan garanteres.

    if (
        risky_set
        and elapsed >= SOLVER_TIME_LIMIT_SECONDS - 1
    ):

        raise RuntimeError(
            "Optimeringen ramte tidsgrænsen på "
            f"{SOLVER_TIME_LIMIT_SECONDS} sekunder. "
            "Optimalitet kan ikke garanteres."
        )

    # ========================================================
    # 10. HENT OPTIMALE BESLUTNINGER
    # ========================================================

    charge_mw = np.array([
        float(pulp.value(variable))
        for variable in charge
    ])

    discharge_mw = np.array([
        float(pulp.value(variable))
        for variable in discharge
    ])

    soc_values = np.array([
        float(pulp.value(variable))
        for variable in soc
    ])

    if not (
        np.isfinite(charge_mw).all()
        and np.isfinite(discharge_mw).all()
        and np.isfinite(soc_values).all()
    ):

        raise RuntimeError(
            "Optimeringen gav ugyldige "
            "beslutningsvariabler."
        )

    # ========================================================
    # 11. FJERN EVENTUELLE NEUTRALE CYKLER
    # ========================================================

    # Ved præcis ens økonomisk værdi kan
    # en lineær løser i særlige tilfælde
    # vælge både opladning og afladning.
    #
    # Sådanne cykler fjernes uden at ændre
    # batteriets energibalance.

    for t in range(n):

        if (
            charge_mw[t] > 1e-6
            and discharge_mw[t] > 1e-6
        ):

            if t in risky_set:

                raise RuntimeError(
                    "Ulovlig samtidig opladning "
                    "og afladning ved "
                    f"interval {t}."
                )

            reduction_charge = min(
                charge_mw[t],
                discharge_mw[t] / eta
            )

            charge_mw[t] -= reduction_charge

            discharge_mw[t] -= (
                eta * reduction_charge
            )

    charge_mw = np.maximum(
        0.0,
        charge_mw
    )

    discharge_mw = np.maximum(
        0.0,
        discharge_mw
    )

    charge_mwh = charge_mw * dt

    discharge_mwh = discharge_mw * dt

    # ========================================================
    # 12. VALIDÉR BATTERIETS ENERGIBALANCE
    # ========================================================

    reconstructed_soc = np.concatenate([
        [start_soc],
        start_soc + np.cumsum(
            charge_mwh * sqrt_eta
            - discharge_mwh / sqrt_eta
        )
    ])

    if np.max(
        np.abs(
            reconstructed_soc - soc_values
        )
    ) > 0.002:

        raise RuntimeError(
            "Energibalancen stemmer ikke "
            "med den fundne strategi."
        )

    if (
        reconstructed_soc.min() < -0.002
        or reconstructed_soc.max()
        > battery_capacity + 0.002
        or abs(
            reconstructed_soc[-1] - end_soc
        ) > 0.002
    ):

        raise RuntimeError(
            "Batteriets energigrænser "
            "er ikke overholdt."
        )

    # ========================================================
    # 13. OPRET RESULTATTABEL
    # ========================================================

    result = pd.DataFrame({
        "TimeUTC": frame["TimeUTC"],
        "TimeDK": (
            frame["TimeUTC"]
            .dt.tz_convert(TIMEZONE)
        ),
        "PriceDKK": price,
        "ChargeMWh": charge_mwh,
        "DischargeMWh": discharge_mwh,
        "SoCMWh": reconstructed_soc[1:]
    })

    # ========================================================
    # 14. BEREGN ØKONOMISKE RESULTATER
    # ========================================================

    # Bruttofortjeneste på spotmarkedet.

    result["CashflowDKK"] = (
        result["DischargeMWh"]
        - result["ChargeMWh"]
    ) * result["PriceDKK"]

    # Batterislitage.

    result["DegradationCostDKK"] = (
        result["DischargeMWh"] * wear
    )

    # Importtariffer.

    result["GridImportCostDKK"] = (
        result["ChargeMWh"]
        * import_tariff
    )

    # Eksporttariffer.

    result["GridExportCostDKK"] = (
        result["DischargeMWh"]
        * export_tariff
    )

    # Samlede energitariffer.

    result["GridCostDKK"] = (
        result["GridImportCostDKK"]
        + result["GridExportCostDKK"]
    )

    # Handelsomkostninger ved køb og salg.

    result["TradingCostDKK"] = (
        result["ChargeMWh"]
        + result["DischargeMWh"]
    ) * trading_fee

    # Nettoresultat efter variable omkostninger.

    result["NetCashflowDKK"] = (
        result["CashflowDKK"]
        - result["DegradationCostDKK"]
        - result["GridCostDKK"]
        - result["TradingCostDKK"]
    )

    # ========================================================
    # 15. KONTROLLÉR REGNSKABET
    # ========================================================

    optimized_profit = float(
        result["NetCashflowDKK"].sum()
    )

    solver_profit = float(
        pulp.value(model.objective)
    )

    allowed_difference = max(
        2.0,
        abs(solver_profit) * 1e-5
    )

    if abs(
        solver_profit - optimized_profit
    ) > allowed_difference:

        raise RuntimeError(
            "Regnskabet stemmer ikke med "
            "optimeringsmodellens målfunktion."
        )

    print(
        f"Månedsresultat: "
        f"{optimized_profit:,.2f} DKK.",
        flush=True
    )

    # ========================================================
    # 16. RETURNÉR RESULTATER
    # ========================================================

    return result, optimized_profit
