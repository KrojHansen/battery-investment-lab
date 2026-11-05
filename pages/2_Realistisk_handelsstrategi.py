"""
Battery Investment Lab | Sammenligning af handelsstrategier, version 4.
Placering: BatteryInvestmentLab/pages/2_Realistisk_handelsstrategi.py

Fem strategier: historisk prisprofil, gårsdagens priser,
kalenderregression, gradient boosting og fast nat/aften.

Funktioner i version 4:
    * Trænet Gradient Boosting-model, opdateret månedligt uden fremtidsviden.
    * Valgfrit, FÆLLES dagligt loft for ækvivalente fulde cyklusser.
    * Omkostningsfølsomhed med UÆNDREDE historiske handler.
    * Prognosekvalitet: MAE, rangkorrelation og top/bund-træfsikkerhed.
    * Risiko, handelsvolumen, cyklusser og indtjening pr. cyklus.
    * Valgfrie testperioder og daglige/månedlige sammenligninger.

De prognosebaserede strategier bruger kun spotpriser fra D-1 eller
ældre, når planen for leveringsdag D besluttes. Bud antages gennemført
til day-ahead-prisen. Ingen simulering af balanceansvar eller likviditet.
Før 1. oktober 2025 handles timeprodukter, derefter kvartersprodukter.
Batteriet starter og slutter hver leveringsdag med 0 MWh.

Når et fælles cyklusloft anvendes, optimeres prognosestrategier og
teoretisk maksimum under samme begrænsning. Den faste benchmark
nedskaleres ved behov. Loftet sikrer IKKE samme faktiske cyklustal.
"""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import math
import time

import numpy as np
import pandas as pd
import streamlit as st

from battery_optimizer import optimize_battery
from ml_price_forecast import WalkForwardGradientBoosting, MODEL_VERSION

TZ = "Europe/Copenhagen"
QUARTER_CHANGE = date(2025, 10, 1)
WARMUP_DAYS = 28
VERSION = "v4-ml-cycle-cost-rank-2026-11-05-" + MODEL_VERSION

MODEL_NAMES = (
    "Historisk prisprofil",
    "Gårsdagens priser",
    "Kalenderregression",
    "Gradient Boosting (ML)",
    "Fast nat/aften",
)


def kroner(value):
    return f"{value:,.0f}".replace(",", ".") + " kr."


def percent(value):
    return "Ikke beregnet" if not np.isfinite(value) else f"{100 * value:.1f}".replace(".", ",") + " %"


# ============================================================
# HENT PRISER OG BATTERI FRA HOVEDAPPEN
# ============================================================

def load_source(stored):
    if not isinstance(stored, dict):
        raise ValueError("Kør først en historisk optimering i hovedappen.")

    config = stored.get("configuration")
    schedule = stored.get("schedule")

    if not isinstance(config, (tuple, list)) or len(config) < 20:
        raise ValueError("De gemte batterispecifikationer er ufuldstændige.")
    if not isinstance(schedule, pd.DataFrame) or schedule.empty:
        raise ValueError("Der mangler gemte historiske prisdata.")
    if not {"TimeUTC", "PriceDKK"}.issubset(schedule.columns):
        raise ValueError("Der mangler TimeUTC eller PriceDKK i prisdata.")

    frame = schedule[["TimeUTC", "PriceDKK"]].copy()
    frame["TimeUTC"] = pd.to_datetime(frame["TimeUTC"], utc=True, errors="coerce")
    frame["PriceDKK"] = pd.to_numeric(frame["PriceDKK"], errors="coerce")

    if frame.isna().any().any():
        raise ValueError("Prisdata indeholder ugyldige tidspunkter eller priser.")

    frame = frame.sort_values("TimeUTC").reset_index(drop=True)
    if frame["TimeUTC"].duplicated().any():
        raise ValueError("Priserne indeholder dublerede UTC-tidspunkter.")

    frame["TimeDK"] = frame["TimeUTC"].dt.tz_convert(TZ)
    frame["Dato"] = frame["TimeDK"].dt.date
    frame["Slot"] = frame["TimeDK"].dt.hour * 4 + frame["TimeDK"].dt.minute // 15

    days = sorted(frame["Dato"].unique())
    expected_days = [
        days[0] + timedelta(days=i)
        for i in range((days[-1] - days[0]).days + 1)
    ]
    if days != expected_days:
        raise ValueError("Der mangler én eller flere kalenderdage i prishistorikken.")

    for day, group in frame.groupby("Dato", sort=True):
        begin = pd.Timestamp(day.isoformat(), tz=TZ).tz_convert("UTC")
        end = pd.Timestamp((day + timedelta(days=1)).isoformat(), tz=TZ).tz_convert("UTC")
        expected = pd.date_range(begin, end, freq="15min", inclusive="left")
        if not pd.DatetimeIndex(group["TimeUTC"]).equals(expected):
            raise ValueError(f"Ufuldstændige eller uregelmæssige priser: {day}.")

    battery = {
        "power": float(config[3]),
        "capacity": float(config[4]),
        "eta": float(config[5]) / 100.0,
        "wear": float(config[6]),
    }
    if (battery["power"] <= 0 or battery["capacity"] <= 0
            or not 0 < battery["eta"] <= 1 or battery["wear"] < 0):
        raise ValueError("Batterispecifikationerne er ugyldige.")

    return frame, battery


# ============================================================
# PROGNOSEMODELLER, KUN PRISER FØR LEVERINGSDAGEN
# ============================================================

def make_profiles(frame):
    profiles = (
        frame.groupby(["Dato", "Slot"])["PriceDKK"]
        .mean().unstack("Slot").reindex(columns=range(96))
    )
    # Tidsomstillingsdage kan mangle lokale slots. De udfyldes
    # kun til brug for prognosemodellen, ikke for faktiske handler.
    return profiles.ffill(axis=1).bfill(axis=1)


def historical_profile(profiles, day):
    past = profiles.loc[profiles.index < day]
    recent = past.loc[past.index >= day - timedelta(days=14)]
    weekday = past.loc[
        (past.index >= day - timedelta(days=56))
        & np.array([d.weekday() == day.weekday() for d in past.index])
    ]
    fallback = past.iloc[-28:].median(axis=0)
    recent_profile = recent.median(axis=0).fillna(fallback)
    weekday_profile = weekday.median(axis=0).fillna(recent_profile)
    w = 0.30 if len(weekday) >= 4 else 0.0
    return ((1 - w) * recent_profile + w * weekday_profile).to_numpy(dtype=float)


def calendar_features(days, prices, index):
    day = days[index]
    previous = prices[index - 1]
    previous_week = prices[index - 7]
    last_seven = prices[index - 7:index]
    weekday = day.weekday()
    day_of_year = day.timetuple().tm_yday
    return np.array([
        1.0,
        math.sin(2 * math.pi * weekday / 7),
        math.cos(2 * math.pi * weekday / 7),
        float(weekday >= 5),
        math.sin(2 * math.pi * day_of_year / 365.25),
        math.cos(2 * math.pi * day_of_year / 365.25),
        previous.mean() / 1000,
        previous_week.mean() / 1000,
        last_seven.mean() / 1000,
        last_seven.mean(axis=1).std() / 1000,
    ], dtype=float)


def ridge_forecast(profiles, day):
    days = list(profiles.index)
    idx = days.index(day)
    matrix = profiles.to_numpy(dtype=float)
    train_indices = range(max(7, idx - 120), idx)
    if len(train_indices) < 14:
        return historical_profile(profiles, day)

    X = np.vstack([calendar_features(days, matrix, i) for i in train_indices])
    Y = matrix[list(train_indices)]
    x_test = calendar_features(days, matrix, idx)
    ridge = np.eye(X.shape[1]) * 3.0
    ridge[0, 0] = 0.0
    betas = np.linalg.solve(X.T @ X + ridge, X.T @ Y)
    return 0.70 * (x_test @ betas) + 0.30 * historical_profile(profiles, day)


def predict(profiles, day, model, ml_forecaster=None):
    if model == "Historisk prisprofil":
        return historical_profile(profiles, day)
    if model == "Gårsdagens priser":
        return profiles.loc[day - timedelta(days=1)].to_numpy(dtype=float)
    if model == "Kalenderregression":
        return ridge_forecast(profiles, day)
    if model == "Gradient Boosting (ML)":
        if ml_forecaster is None:
            raise ValueError("Maskinlæringsmodellen er ikke initialiseret.")
        return ml_forecaster.predict(day)
    raise ValueError(f"Ukendt prognosemodel: {model}")


# ============================================================
# HISTORISKE BØRSPRODUKTER
# ============================================================

def market_inputs(day_data, forecast):
    forecast = np.asarray(forecast, dtype=float)
    if len(forecast) != len(day_data) or not np.isfinite(forecast).all():
        raise ValueError("Prognosen har ugyldig længde eller ugyldige værdier.")

    day = day_data["Dato"].iloc[0]
    if day >= QUARTER_CHANGE:
        return pd.DataFrame({
            "TimeUTC": day_data["TimeUTC"].reset_index(drop=True),
            "DayAheadPriceDKK": forecast,
        }), 0.25, None

    work = day_data[["TimeUTC", "PriceDKK"]].copy()
    work["Prediction"] = forecast
    work["UTC_hour"] = work["TimeUTC"].dt.floor("h")
    grouped = work.groupby("UTC_hour", sort=True)
    if not grouped.size().eq(4).all():
        raise ValueError("Et historisk timeprodukt mangler kvartersobservationer.")
    if grouped["PriceDKK"].agg(lambda x: x.max() - x.min()).gt(1e-6).any():
        raise ValueError("Historiske timepriser er ikke identiske i samme time.")

    hourly_prediction = grouped["Prediction"].mean()
    prices = pd.DataFrame({
        "TimeUTC": hourly_prediction.index,
        "DayAheadPriceDKK": hourly_prediction.to_numpy(dtype=float),
    })
    return prices, 1.0, work["UTC_hour"].reset_index(drop=True)


def actual_market_prices(day_data):
    actual = day_data["PriceDKK"].to_numpy(dtype=float)
    return market_inputs(day_data, actual)[0]["DayAheadPriceDKK"].to_numpy(dtype=float)


# ============================================================
# BATTERIOPTIMERING MED VALGFRIT CYKLUSLOFT
# ============================================================

def capped_optimizer(inputs, dt, battery, costs, max_cycles):
    """Eksakt daglig LP/MILP med begrænsning på intern afladet energi.

    FEC = solgte MWh / sqrt(eta) / batterikapacitet.
    Binære variable tilføjes kun, hvor negative priser ellers kan
    skabe en økonomisk fordel ved samtidig opladning/afladning.
    """
    import pulp

    prices = inputs["DayAheadPriceDKK"].to_numpy(dtype=float)
    n = len(prices)
    sqrt_eta = math.sqrt(battery["eta"])
    max_interval = battery["power"] * dt
    buy_price = prices + costs["import"] + costs["trading"]
    sell_price = prices - costs["export"] - costs["trading"] - battery["wear"]

    model = pulp.LpProblem("DailyBatteryWithCycleLimit", pulp.LpMaximize)
    charge = [pulp.LpVariable(f"charge_{i}", lowBound=0, upBound=max_interval)
              for i in range(n)]
    discharge = [pulp.LpVariable(f"discharge_{i}", lowBound=0, upBound=max_interval)
                 for i in range(n)]
    soc = [pulp.LpVariable(f"soc_{i}", lowBound=0, upBound=battery["capacity"])
           for i in range(n + 1)]

    model += soc[0] == 0
    model += soc[n] == 0
    model += pulp.lpSum(discharge) <= max_cycles * battery["capacity"] * sqrt_eta

    for i in range(n):
        model += soc[i + 1] == soc[i] + sqrt_eta * charge[i] - discharge[i] / sqrt_eta
        model += charge[i] + discharge[i] <= max_interval
        if buy_price[i] < battery["eta"] * sell_price[i] - 1e-9:
            mode = pulp.LpVariable(f"mode_{i}", cat="Binary")
            model += charge[i] <= max_interval * mode
            model += discharge[i] <= max_interval * (1 - mode)

    model += pulp.lpSum(
        float(sell_price[i]) * discharge[i] - float(buy_price[i]) * charge[i]
        for i in range(n)
    )

    solver = pulp.PULP_CBC_CMD(msg=False, threads=1, timeLimit=90)
    model.solve(solver)
    if pulp.LpStatus[model.status] != "Optimal":
        raise RuntimeError(
            "Optimeringen under cyklusloftet kunne ikke løses optimalt: "
            + pulp.LpStatus[model.status]
        )

    buy = np.array([pulp.value(x) for x in charge], dtype=float)
    sell = np.array([pulp.value(x) for x in discharge], dtype=float)
    buy = np.maximum(buy, 0)
    sell = np.maximum(sell, 0)

    # Neutral samtidig handel kan forekomme ved identisk marginalpris.
    # Den kan fjernes uden at ændre batteriets SoC.
    neutral = np.minimum(buy, sell / battery["eta"])
    buy = buy - neutral
    sell = sell - battery["eta"] * neutral

    profit = float(np.sum(
        sell * sell_price - buy * buy_price
    ))
    return buy, sell, profit


def optimize_plan(day_data, forecast, battery, costs, max_cycles):
    inputs, dt, hour_keys = market_inputs(day_data, forecast)

    if max_cycles is None:
        schedule, expected_net = optimize_battery(
            prices=inputs,
            battery_power=battery["power"],
            battery_capacity=battery["capacity"],
            roundtrip_efficiency=battery["eta"],
            interval_hours=dt,
            start_soc=0,
            end_soc=0,
            degradation_cost_per_mwh=battery["wear"],
            grid_import_tariff_dkk_per_mwh=costs["import"],
            grid_export_tariff_dkk_per_mwh=costs["export"],
            trading_cost_dkk_per_mwh=costs["trading"],
        )
        buy = schedule["ChargeMWh"].to_numpy(dtype=float)
        sell = schedule["DischargeMWh"].to_numpy(dtype=float)
    else:
        buy, sell, expected_net = capped_optimizer(
            inputs, dt, battery, costs, float(max_cycles)
        )

    if dt == 1.0:
        hourly = pd.DataFrame({
            "Buy": buy,
            "Sell": sell,
        }, index=pd.DatetimeIndex(inputs["TimeUTC"]))
        expanded = hourly.reindex(pd.DatetimeIndex(hour_keys))
        if expanded.isna().any().any():
            raise RuntimeError("Timeplanen kunne ikke udfoldes til kvartersdata.")
        buy = expanded["Buy"].to_numpy(dtype=float) / 4.0
        sell = expanded["Sell"].to_numpy(dtype=float) / 4.0

    return buy, sell, float(expected_net)


def fixed_plan(day_data, battery, max_cycles):
    """Fast benchmark med samme effekt-, kapacitets- og cyklusloft."""
    slot = day_data["Slot"].to_numpy(dtype=int)
    buy = np.where((slot >= 0) & (slot < 8), battery["power"] * 0.25, 0.0)
    sell = np.where((slot >= 72) & (slot < 80),
                    battery["power"] * battery["eta"] * 0.25, 0.0)

    root_eta = math.sqrt(battery["eta"])
    constraints = [1.0]
    if buy.sum() > 0:
        constraints.append(battery["capacity"] / (buy.sum() * root_eta))
    if max_cycles is not None and sell.sum() > 0:
        constraints.append(max_cycles * battery["capacity"] * root_eta / sell.sum())
    factor = max(0.0, min(constraints))
    return buy * factor, sell * factor


def settle(day_data, buy, sell, battery, costs, max_cycles):
    actual = day_data["PriceDKK"].to_numpy(dtype=float)
    buy = np.asarray(buy, dtype=float)
    sell = np.asarray(sell, dtype=float)
    tol = 0.003

    if (len(buy) != len(day_data) or len(sell) != len(day_data)
            or not np.isfinite(buy).all() or not np.isfinite(sell).all()):
        raise ValueError("Handelsplanen indeholder ugyldig energi.")
    if (buy.min() < -1e-6 or sell.min() < -1e-6
            or (buy + sell).max() > battery["power"] * 0.25 + tol
            or np.any((buy > 1e-5) & (sell > 1e-5))):
        raise ValueError("Handelsplanen overskrider effekt eller samtidighedsbegrænsning.")

    root_eta = math.sqrt(battery["eta"])
    soc = np.cumsum(buy * root_eta - sell / root_eta)
    if (soc.min() < -tol or soc.max() > battery["capacity"] + tol
            or abs(soc[-1]) > tol):
        raise ValueError("Batteriets energiniveau er ugyldigt.")

    cycles = float(sell.sum() / root_eta / battery["capacity"])
    if max_cycles is not None and cycles > max_cycles + 0.001:
        raise ValueError("Handelsplanen overstiger det daglige cyklusloft.")

    revenue = (sell - buy) * actual
    import_cost = buy * (costs["import"] + costs["trading"])
    export_cost = sell * (costs["export"] + costs["trading"] + battery["wear"])
    cashflows = revenue - import_cost - export_cost
    return cashflows, soc, cycles


# ============================================================
# PRÆCISION: DE HØJESTE OG LAVESTE MARKEDSPRISER
# ============================================================

def forecast_quality(day_data, prediction):
    """MAE, rangkorrelation og overlap for 2 dyreste/billigste timer.

    Tidligere timeprodukter tæller som én observation pr. time.
    Ved 15-minutters handel vælges 8 prisintervaller på hver side.
    Top/bund-overlap er ikke en handelsstrategi i sig selv.
    """
    predicted = market_inputs(day_data, prediction)[0]["DayAheadPriceDKK"].to_numpy(dtype=float)
    actual = actual_market_prices(day_data)
    mae = float(np.abs(predicted - actual).mean())
    correlation = float(pd.Series(predicted).rank().corr(pd.Series(actual).rank()))
    k = 2 if day_data["Dato"].iloc[0] < QUARTER_CHANGE else 8
    k = min(k, len(actual) // 2)

    forecast_order = np.argsort(predicted, kind="stable")
    actual_order = np.argsort(actual, kind="stable")
    bottom_hits = len(set(forecast_order[:k]) & set(actual_order[:k])) / k
    top_hits = len(set(forecast_order[-k:]) & set(actual_order[-k:])) / k
    return mae, correlation, bottom_hits, top_hits


# ============================================================
# BACKTEST PÅ DE VALGTE DAGE
# ============================================================

def backtest(frame, battery, first_day, last_day, costs,
             min_profit, compute_oracle, max_cycles, progress=None):
    profiles = make_profiles(frame)
    days = list(profiles.index)
    if len(days) <= WARMUP_DAYS:
        raise ValueError("Der mangler indledende historik.")
    if first_day < days[WARMUP_DAYS] or last_day > days[-1] or first_day > last_day:
        raise ValueError("Testdatoerne ligger uden for den tilgængelige periode.")
    selected = [d for d in days if first_day <= d <= last_day]
    grouped = {d: group.reset_index(drop=True) for d, group in frame.groupby("Dato")}
    ml_forecaster = WalkForwardGradientBoosting(profiles, first_day)
    daily_rows, trade_rows = [], []

    for number, day in enumerate(selected, 1):
        part = grouped[day]
        actual = part["PriceDKK"].to_numpy(dtype=float)
        slots = part["Slot"].to_numpy(dtype=int)

        oracle = np.nan
        if compute_oracle:
            buy_o, sell_o, _ = optimize_plan(part, actual, battery, costs, max_cycles)
            oracle = float(settle(part, buy_o, sell_o, battery, costs, max_cycles)[0].sum())

        for name in MODEL_NAMES:
            prediction = np.full(len(part), np.nan)
            estimated_profit = np.nan
            mae, rank_corr, bottom_hits, top_hits = [np.nan] * 4

            if name == "Fast nat/aften":
                buy, sell = fixed_plan(part, battery, max_cycles)
            else:
                profile_prediction = predict(profiles, day, name, ml_forecaster)
                prediction = profile_prediction[slots]
                mae, rank_corr, bottom_hits, top_hits = forecast_quality(part, prediction)
                buy, sell, estimated_profit = optimize_plan(
                    part, prediction, battery, costs, max_cycles
                )
                if estimated_profit < min_profit:
                    buy = np.zeros_like(buy)
                    sell = np.zeros_like(sell)

            cashflows, soc, cycles = settle(part, buy, sell, battery, costs, max_cycles)
            pnl = float(cashflows.sum())
            daily_rows.append({
                "Dato": day,
                "Strategi": name,
                "ResultatDKK": pnl,
                "PerfektDKK": oracle,
                "KøbtMWh": float(buy.sum()),
                "SolgtMWh": float(sell.sum()),
                "Fuldcyklusser": cycles,
                "MAE": mae,
                "Rangkorrelation": rank_corr,
                "BundHitrate": bottom_hits,
                "TopHitrate": top_hits,
                "ForventetDKK": estimated_profit,
                "Produkter": 24 if day < QUARTER_CHANGE else len(part),
            })
            trade_rows.append(pd.DataFrame({
                "Dato": day,
                "Strategi": name,
                "TimeUTC": part["TimeUTC"],
                "TimeDK": part["TimeDK"],
                "FaktiskPris": actual,
                "Prognose": prediction,
                "KøbtMWh": buy,
                "SolgtMWh": sell,
                "SoCMWh": soc,
                "ResultatDKK": cashflows,
            }))

        if progress is not None:
            progress(number, len(selected), day)

    daily = pd.DataFrame(daily_rows)
    trades = pd.concat(trade_rows, ignore_index=True)
    if compute_oracle and (daily["ResultatDKK"] - daily["PerfektDKK"]).max() > 5.0:
        raise RuntimeError("En strategi overstiger det teoretiske dagsmaksimum.")
    return daily, trades


# ============================================================
# NØGLETAL OG OMKOSTNINGSSTRESSTEST
# ============================================================

def summarize(daily):
    rows = []
    for name in MODEL_NAMES:
        part = daily.loc[daily["Strategi"] == name].sort_values("Dato")
        pnl = part["ResultatDKK"].to_numpy(dtype=float)
        cum = np.r_[0.0, np.cumsum(pnl)]
        dd = np.maximum.accumulate(cum) - cum
        total = float(pnl.sum())
        oracle = float(part["PerfektDKK"].sum()) if part["PerfektDKK"].notna().all() else np.nan
        cycles = float(part["Fuldcyklusser"].sum())
        bought = float(part["KøbtMWh"].sum())
        sold = float(part["SolgtMWh"].sum())
        rows.append({
            "Strategi": name,
            "Resultat (kr.)": total,
            "Andel af dagsoptimum": total / oracle if oracle > 0 else np.nan,
            "Tabsgivende dage": int((pnl < -0.01).sum()),
            "Største drawdown (kr.)": float(dd.max()),
            "Købt (MWh)": bought,
            "Solgt (MWh)": sold,
            "Ækvivalente fulde cyklusser": cycles,
            "Kr. pr. cyklus": total / cycles if cycles > 1e-12 else np.nan,
            "MAE (kr./MWh)": float(part["MAE"].mean()) if part["MAE"].notna().any() else np.nan,
            "Rangkorrelation": float(part["Rangkorrelation"].mean()) if part["Rangkorrelation"].notna().any() else np.nan,
            "Billige timer hitrate": float(part["BundHitrate"].mean()) if part["BundHitrate"].notna().any() else np.nan,
            "Dyre timer hitrate": float(part["TopHitrate"].mean()) if part["TopHitrate"].notna().any() else np.nan,
        })
    return pd.DataFrame(rows)


def cost_sensitivity(daily, extra_import, extra_export, extra_trading):
    """Afregner IDENTISKE handelsplaner ved ekstra omkostninger.

    Dette er IKKE en ny optimal plan ved ændrede omkostninger.
    """
    rows = []
    for name in MODEL_NAMES:
        x = daily.loc[daily["Strategi"] == name]
        base = float(x["ResultatDKK"].sum())
        bought = float(x["KøbtMWh"].sum())
        sold = float(x["SolgtMWh"].sum())
        scenario = base - extra_import * bought - extra_export * sold \
                   - extra_trading * (bought + sold)
        break_even = base / (bought + sold) if bought + sold > 0 else np.nan
        rows.append({
            "Strategi": name,
            "Grundscenarie (kr.)": base,
            "Stresset resultat (kr.)": scenario,
            "Forskel (kr.)": scenario - base,
            "Nulpunkt for ekstra handelsgebyr (kr./MWh)": break_even,
        })
    return pd.DataFrame(rows)


def signature_for(frame, battery, costs, first, last, min_profit, oracle, max_cycles):
    digest = hashlib.sha256(pd.util.hash_pandas_object(
        frame[["TimeUTC", "PriceDKK"]], index=False
    ).values.tobytes()).hexdigest()
    return (VERSION, digest, tuple(sorted(battery.items())),
            tuple(sorted(costs.items())), str(first), str(last),
            float(min_profit), bool(oracle), max_cycles)


# ============================================================
# STREAMLIT: SIDEN VISER ALTID INDHOLD
# ============================================================

def main():
    # Sidekonfiguration håndteres i app.py
    st.markdown('<div class="bil-label">02 / STRATEGIER OG MASKINLÆRING</div>',unsafe_allow_html=True)
    st.title("📈 Sammenligning af handelsstrategier")
    st.write(
        "Fem strategier på identiske testdage, inklusive en trænet ML-model. Sammenlign indtjening, "
        "fælles cyklusbegrænsning, omkostningsfølsomhed og prognosernes "
        "evne til at identificere billige og dyre handelstidspunkter."
    )
    st.info(
        "Historisk day-ahead-backtest med fuld gennemførelse til clearingprisen. "
        "Modellen medtager ikke balanceansvar, likviditet, prisafhængige bud "
        "eller dokumenterede projektspecifikke nettariffer."
    )

    stored = st.session_state.get("battery_last_result")
    if stored is None:
        from demo_data import showcase, strategies
        st.info("Du kan undersøge et historisk demoscenarie med det samme. For en ny interaktiv backtest skal du først køre markedsoptimeringen.")
        demo = showcase()["strategy_2025_q4"]
        st.subheader("Historisk demonstration: fem handelsstrategier")
        st.caption(f"DK1 · {demo['start']} til {demo['end']} · {demo['days']} dage · maksimalt én cyklus pr. dag. Resultaterne er fra tidligere lokale beregninger, ikke genereret på denne side.")
        demo_rows = strategies()
        dm1, dm2, dm3 = st.columns(3)
        dm1.metric("Bedste model", "Kalenderregression")
        dm2.metric("Nettoresultat", "217.967 kr.")
        dm3.metric("Andel af perfekt dagsoptimum", "45,2 %")
        st.bar_chart(demo_rows.set_index('strategy')[['profit_dkk']], horizontal=True, color="#39D9C1", height=310)
        show = demo_rows.rename(columns={"strategy":"Strategi", "profit_dkk":"Nettoresultat (kr.)", "cycles":"Ækvivalente cyklusser", "loss_days":"Tabsgivende dage", "mae":"MAE (kr./MWh)", "drawdown_dkk":"Maks. drawdown (kr.)"})
        st.dataframe(show[["Strategi", "Nettoresultat (kr.)", "Ækvivalente cyklusser", "Tabsgivende dage", "MAE (kr./MWh)", "Maks. drawdown (kr.)"]],hide_index=True,use_container_width=True)
        st.caption("Efter beregnet batterislitage. Uden nettariffer og handelsgebyrer. Ordreudførelse antages. Testperioden er ikke uberørt efter tidligere modelvalg.")
        st.page_link("market_optimization.py",label="Beregn en ny historisk analyse",icon="🔋")
        st.stop()

    try:
        frame, battery = load_source(stored)
    except (ValueError, TypeError, KeyError) as error:
        st.error(str(error))
        st.stop()

    days = sorted(frame["Dato"].unique())
    if len(days) <= WARMUP_DAYS:
        st.warning(f"Du skal have mere end {WARMUP_DAYS} sammenhængende dages prisdata.")
        st.stop()

    a, b, c = st.columns(3)
    a.metric("Historiske dage", len(days))
    b.metric("Tidligste testdag", str(days[WARMUP_DAYS]))
    c.metric("Batteri", f"{battery['power']:g} MW / {battery['capacity']:g} MWh")

    st.subheader("1. Vælg testperiode")
    scope = st.radio(
        "Omfang",
        ["Første 30 dage", "Seneste 90 dage", "Hele perioden", "Vælg selv"],
        horizontal=True,
    )
    possible = days[WARMUP_DAYS:]
    if scope == "Første 30 dage":
        first, last = possible[0], possible[min(29, len(possible)-1)]
    elif scope == "Seneste 90 dage":
        first, last = possible[max(0, len(possible)-90)], possible[-1]
    elif scope == "Hele perioden":
        first, last = possible[0], possible[-1]
    else:
        chosen = st.date_input(
            "Vælg fra og til", value=(possible[0], possible[-1]),
            min_value=possible[0], max_value=possible[-1]
        )
        if not isinstance(chosen, (list, tuple)) or len(chosen) != 2:
            st.info("Vælg begge datoer.")
            st.stop()
        first, last = chosen
        if first > last:
            st.error("Slutdatoen skal ligge efter startdatoen.")
            st.stop()

    st.caption(
        f"Valgt testperiode: {first} til {last}. "
        f"De første {WARMUP_DAYS} dage er indledende historik. "
        "Prognoser bruger alene historisk kendte priser. "
        "Gradient Boosting genoptrænes ved starten af hver testmåned "
        "med data fra før træningstidspunktet. "
        "Modeller og parametre er ikke tunet automatisk efter resultatet."
    )

    st.subheader("2. Fælles begrænsning af battericyklusser")
    use_limit = st.checkbox(
        "Brug samme maksimale antal cyklusser pr. dag for alle strategier",
        value=True,
    )
    max_cycles = None
    if use_limit:
        max_cycles = float(st.number_input(
            "Maksimalt antal ækvivalente fulde cyklusser pr. dag",
            min_value=0.1, max_value=10.0, value=1.0,
            step=0.25, format="%.2f",
        ))
    st.caption(
        "Et fælles cyklusloft gør sammenligningen mere ensartet. "
        "Det betyder ikke, at strategierne udfører præcis samme antal cyklusser. "
        "Loftet gælder også perfekt dagsoptimum og den faste benchmark."
    )

    st.subheader("3. Omkostninger i grundscenariet")
    x, y, z = st.columns(3)
    costs = {
        "import": float(x.number_input("Importtarif (kr./MWh købt)", min_value=0.0, value=0.0, step=10.0)),
        "export": float(y.number_input("Eksporttarif (kr./MWh solgt)", min_value=0.0, value=0.0, step=10.0)),
        "trading": float(z.number_input("Handelsgebyr (kr./MWh købt og solgt)", min_value=0.0, value=0.0, step=5.0)),
    }
    st.caption(
        "Alle satser gælder ens for strategierne. Disse er brugerens egne "
        "scenariesatser og skal ikke automatisk lægges oven i andre opgørelser."
    )

    st.subheader("4. Backtest")
    st.caption(
        "ML-modellen bruger Gradient Boosting med faste hyperparametre, "
        "op til 180 forudgående træningsdage og ny træning ved månedsskiftet. "
        "Funktioner bruger kendte kalenderforhold og tidligere spotpriser. "
        "Det er stadig en prisprognose, som derefter optimeres til handler."
    )
    l, r = st.columns(2)
    min_profit = float(l.number_input(
        "Minimum forventet dagsfortjeneste (kr.)",
        min_value=0.0, value=0.0, step=250.0,
    ))
    oracle = r.checkbox("Beregn perfekt dagsoptimum", value=True)
    st.caption(
        "Fortjenestekravet gælder prognosestrategierne. "
        "Den faste benchmark handler kl. 00 til 02 og 18 til 20 "
        "og følger batteriets fysiske begrænsninger."
    )

    signature = signature_for(
        frame, battery, costs, first, last, min_profit, oracle, max_cycles
    )
    if st.button("Start sammenlignende backtest", type="primary", use_container_width=True):
        bar = st.progress(0)
        status = st.empty()
        start_time = time.perf_counter()

        def update(done, total, day):
            bar.progress(done / total)
            status.caption(f"Beregner {day}: {done} af {total} dage")

        try:
            daily, trades = backtest(
                frame, battery, first, last, costs, min_profit,
                oracle, max_cycles, progress=update,
            )
            st.session_state["battery_strategy_v3"] = {
                "signature": signature,
                "daily": daily,
                "trades": trades,
                "seconds": time.perf_counter() - start_time,
            }
            bar.empty()
            status.empty()
        except Exception as error:
            bar.empty()
            status.empty()
            st.error("Backtesten kunne ikke gennemføres.")
            st.exception(error)
            st.stop()

    result = st.session_state.get("battery_strategy_v3")
    if not isinstance(result, dict) or result.get("signature") != signature:
        st.caption("Start backtesten for at se sammenligningen.")
        st.stop()

    daily = result["daily"]
    trades = result["trades"]
    summary = summarize(daily)
    st.success(
        f"Backtest gennemført for {daily['Dato'].nunique()} handelsdage "
        f"på {result['seconds']:.1f} sekunder."
    )

    st.header("Resultater")
    if oracle:
        perfect = daily.loc[daily["Strategi"] == MODEL_NAMES[0], "PerfektDKK"].sum()
        st.metric("Perfekt dagsoptimum med samme cyklusloft", kroner(perfect))
    else:
        st.caption("Det teoretiske dagsoptimum blev ikke beregnet.")

    st.dataframe(
        summary.style.format({
            "Resultat (kr.)": "{:,.0f}",
            "Andel af dagsoptimum": "{:.1%}",
            "Største drawdown (kr.)": "{:,.0f}",
            "Købt (MWh)": "{:,.1f}",
            "Solgt (MWh)": "{:,.1f}",
            "Ækvivalente fulde cyklusser": "{:,.1f}",
            "Kr. pr. cyklus": "{:,.0f}",
            "MAE (kr./MWh)": "{:,.0f}",
            "Rangkorrelation": "{:.2f}",
            "Billige timer hitrate": "{:.1%}",
            "Dyre timer hitrate": "{:.1%}",
        }, na_rep="Ikke målt"),
        hide_index=True, use_container_width=True,
    )
    st.caption(
        "Hitraterne måler overlap mellem de forudsagte og faktiske 2 billigste "
        "henholdsvis 2 dyreste handelstimer. Efter 1. oktober svarer det "
        "til 8 kvartersintervaller. Rangkorrelation måler rækkefølgen af priserne. "
        "Indtjening pr. cyklus er netto efter beregnet batterislitage."
    )

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Daglige resultater", "Måneder", "Risiko og cyklusser",
        "Omkostningsfølsomhed", "Handelsplaner og prognoser",
    ])

    with tab1:
        pivot = daily.pivot(index="Dato", columns="Strategi", values="ResultatDKK")
        if oracle:
            pivot["Perfekt dagsoptimum"] = daily.loc[
                daily["Strategi"] == MODEL_NAMES[0], "PerfektDKK"
            ].to_numpy(dtype=float)
        st.line_chart(pivot, x_label="Leveringsdag", y_label="Nettoresultat (kr.)")
        st.dataframe(daily.round(3), hide_index=True, use_container_width=True)

    with tab2:
        monthly = daily.copy()
        monthly["Måned"] = pd.to_datetime(monthly["Dato"]).dt.strftime("%Y-%m")
        month_table = monthly.pivot_table(
            index="Måned", columns="Strategi", values="ResultatDKK", aggfunc="sum"
        )
        st.bar_chart(month_table, x_label="Måned", y_label="Nettoresultat (kr.)")
        st.dataframe(month_table.round(0), use_container_width=True)

    with tab3:
        selected_model = st.selectbox("Strategi", MODEL_NAMES, key="v3_risk_model")
        chosen = daily.loc[daily["Strategi"] == selected_model].sort_values("Dato").copy()
        chosen["AkkumuleretDKK"] = chosen["ResultatDKK"].cumsum()
        st.line_chart(
            chosen.set_index("Dato")[["AkkumuleretDKK"]],
            x_label="Leveringsdag", y_label="Akkumuleret resultat (kr.)"
        )
        a1, a2, a3 = st.columns(3)
        a1.metric("Tabsgivende dage", int((chosen["ResultatDKK"] < -0.01).sum()))
        a2.metric("Samlede cyklusser", f"{chosen['Fuldcyklusser'].sum():.1f}")
        a3.metric("Dårligste dag", kroner(chosen["ResultatDKK"].min()))
        st.dataframe(
            chosen.nsmallest(min(5, len(chosen)), "ResultatDKK")[
                ["Dato", "ResultatDKK", "Fuldcyklusser", "KøbtMWh", "SolgtMWh"]
            ].round(2), hide_index=True, use_container_width=True
        )

    with tab4:
        st.write(
            "Beregn effekten af højere variable omkostninger på PRÆCIS de handler, "
            "der allerede er gennemført i backtesten. Det kræver ikke en ny "
            "optimering. Hvis aktøren kendte de højere omkostninger før auktionen, "
            "kunne den have valgt andre handler. Tabellen er derfor en stresstest, "
            "ikke en ny optimal strategi."
        )
        cx, cy, cz = st.columns(3)
        extra_import = float(cx.number_input(
            "Ekstra importomkostning (kr./MWh)",
            min_value=0.0, value=50.0, step=25.0, key="v3_extra_import",
        ))
        extra_export = float(cy.number_input(
            "Ekstra eksportomkostning (kr./MWh)",
            min_value=0.0, value=25.0, step=25.0, key="v3_extra_export",
        ))
        extra_fee = float(cz.number_input(
            "Ekstra handelsgebyr på begge sider (kr./MWh)",
            min_value=0.0, value=25.0, step=25.0, key="v3_extra_fee",
        ))
        stress = cost_sensitivity(daily, extra_import, extra_export, extra_fee)
        st.dataframe(stress.style.format({
            "Grundscenarie (kr.)": "{:,.0f}",
            "Stresset resultat (kr.)": "{:,.0f}",
            "Forskel (kr.)": "{:,.0f}",
            "Nulpunkt for ekstra handelsgebyr (kr./MWh)": "{:,.1f}",
        }, na_rep="Ikke målt"), hide_index=True, use_container_width=True)
        st.caption(
            "Nulpunktet er det ekstra handelsgebyr på både købt og solgt energi, "
            "som alene ville bringe resultatet ned på 0 kr. med uændrede handler "
            "og øvrige omkostninger holdt fast."
        )
        st.bar_chart(
            stress.set_index("Strategi")[["Grundscenarie (kr.)", "Stresset resultat (kr.)"]],
            x_label="Strategi", y_label="Resultat (kr.)",
        )

    with tab5:
        model_name = st.selectbox("Handelsstrategi", MODEL_NAMES, key="v3_detail_model")
        day = st.selectbox(
            "Leveringsdag", sorted(daily["Dato"].unique()), key="v3_detail_day"
        )
        detail = trades.loc[
            (trades["Strategi"] == model_name) & (trades["Dato"] == day)
        ].copy()
        detail["NettohandelMWh"] = detail["SolgtMWh"] - detail["KøbtMWh"]
        st.line_chart(
            detail.set_index("TimeDK")[["FaktiskPris", "Prognose"]],
            x_label="Dansk tid", y_label="kr./MWh",
        )
        st.bar_chart(
            detail.set_index("TimeDK")[["NettohandelMWh"]],
            x_label="Dansk tid", y_label="MWh",
        )
        st.dataframe(detail.round(3), hide_index=True, use_container_width=True)

    st.subheader("Download")
    dl1, dl2, dl3 = st.columns(3)
    dl1.download_button(
        "Daglige resultater (CSV)",
        daily.to_csv(index=False).encode("utf-8-sig"),
        file_name="battery_strategy_v3_daily.csv", mime="text/csv", on_click="ignore",
    )
    dl2.download_button(
        "Alle handler (CSV)",
        trades.to_csv(index=False).encode("utf-8-sig"),
        file_name="battery_strategy_v3_trades.csv", mime="text/csv", on_click="ignore",
    )
    dl3.download_button(
        "Sammenligning (CSV)",
        summary.to_csv(index=False).encode("utf-8-sig"),
        file_name="battery_strategy_v3_summary.csv", mime="text/csv", on_click="ignore",
    )

    st.warning(
        "Dette er en forenklet historisk spotmarkedsmodel, ikke en dokumenteret "
        "indtjeningsprognose. En fast daglig cyklusgrænse er ikke det samme som "
        "en fuld modellering af batteriets aldring. Samme tidligere testperiode "
        "må ikke betragtes som uberørt, hvis vi bruger dens resultater til at vælge "
        "eller justere modeller. Brug efterfølgende data til selvstændig validering."
    )


# Streamlit-undersider skal kalde hovedfunktionen direkte.
main()
