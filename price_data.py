
import json
import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd
import requests


# ============================================================
# INDSTILLINGER
# ============================================================

API_URL = "https://api.energidataservice.dk/dataset"
TIMEZONE = "Europe/Copenhagen"
CHANGE_DATE = date(2025, 10, 1)

CACHE_DIR = (
    Path(__file__).resolve().parent
    / "data_cache"
    / "energy_prices_v2"
)


# ============================================================
# DATOHJÆLPERE
# ============================================================

def _date(value):
    return pd.Timestamp(value).date()


def _next_month(day):
    if day.month == 12:
        return date(day.year + 1, 1, 1)

    return date(day.year, day.month + 1, 1)


def _chunk_period(dataset, year, month):

    if dataset == "Elspotprices":
        return (
            date(year, 1, 1),
            min(date(year + 1, 1, 1), CHANGE_DATE)
        )

    start = date(year, month, 1)
    return start, _next_month(start)


# ============================================================
# LOKALT PRISARKIV
# ============================================================

def _cache_file(dataset, area, year, month):

    if dataset == "Elspotprices":
        return (
            CACHE_DIR
            / f"Elspotprices_{area}_{year}.csv"
        )

    return (
        CACHE_DIR
        / f"DayAheadPrices_{area}_{year}_{month:02d}.csv"
    )


def _save_csv(data, path):

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temporary = None

    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".tmp",
            dir=path.parent,
            delete=False
        ) as file:

            temporary = Path(file.name)
            data.to_csv(file, index=False)

        temporary.replace(path)

    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


# ============================================================
# HÅNDTERING AF API-BEGRÆNSNINGER
# ============================================================

def _retry_delay(response):

    header = response.headers.get(
        "Retry-After", ""
    ).strip()

    if header:
        try:
            return max(1, int(float(header)))

        except ValueError:
            try:
                retry_at = parsedate_to_datetime(
                    header
                )

                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(
                        tzinfo=timezone.utc
                    )

                seconds = (
                    retry_at
                    - datetime.now(timezone.utc)
                ).total_seconds()

                return max(1, int(seconds) + 1)

            except (
                ValueError,
                TypeError,
                OverflowError
            ):
                pass

    match = re.search(
        r"try again in\s+(\d+)\s+seconds?",
        response.text,
        flags=re.I
    )

    if match:
        return max(1, int(match.group(1)))

    return 120


# ============================================================
# HENT PRISER FRA ENERGINET
# ============================================================

def _fetch_remote(dataset, area, start, end):

    cooldown = (
        CACHE_DIR / f"cooldown_{dataset}.json"
    )

    if cooldown.exists():

        try:
            saved = json.loads(
                cooldown.read_text(
                    encoding="utf-8"
                )
            )

            until = datetime.fromisoformat(
                saved["until"]
            )

            remaining = (
                until - datetime.now(timezone.utc)
            ).total_seconds()

            if remaining > 0:
                raise RuntimeError(
                    f"Energinet begrænser kald "
                    f"til {dataset}. Vent "
                    f"{int(remaining) + 1} "
                    "sekunder før næste forsøg."
                )

            cooldown.unlink(missing_ok=True)

        except (KeyError, TypeError, ValueError):
            cooldown.unlink(missing_ok=True)

    print(
        f"Henter {dataset}, {area}: "
        f"{start} til {end}",
        flush=True
    )

    params = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "filter": json.dumps({
            "PriceArea": [area]
        }),
        "limit": 0
    }

    try:
        response = requests.get(
            f"{API_URL}/{dataset}",
            params=params,
            timeout=90
        )

    except requests.RequestException as error:
        raise RuntimeError(
            f"Netværksfejl ved hentning "
            f"af {dataset}: {error}"
        ) from error

    if response.status_code == 429:

        seconds = _retry_delay(response)

        CACHE_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

        until = (
            datetime.now(timezone.utc)
            + timedelta(seconds=seconds)
        )

        cooldown.write_text(
            json.dumps({
                "until": until.isoformat()
            }),
            encoding="utf-8"
        )

        raise RuntimeError(
            f"Energinet har afvist "
            f"forespørgslen (HTTP 429). "
            f"Vent {seconds} sekunder. "
            "Allerede gemte data bevares."
        )

    try:
        response.raise_for_status()

        records = response.json().get(
            "records", []
        )

    except (requests.HTTPError, ValueError) as error:
        raise RuntimeError(
            f"Kunne ikke hente {dataset}: {error}"
        ) from error

    if not records:
        raise ValueError(
            f"Ingen elpriser i {dataset} "
            f"for {area}, {start} til {end}."
        )

    return pd.DataFrame(records)


# ============================================================
# KONTROLLÉR DATA
# ============================================================

def _validate_chunk(
    data,
    dataset,
    area,
    start,
    end
):

    if dataset == "Elspotprices":
        time_col = "HourUTC"
        price_col = "SpotPriceDKK"

    else:
        time_col = "TimeUTC"
        price_col = "DayAheadPriceDKK"

    required = {
        time_col,
        price_col,
        "PriceArea"
    }

    missing = required - set(data.columns)

    if missing:
        raise ValueError(
            f"{dataset} mangler kolonner: {missing}"
        )

    if not data["PriceArea"].astype(str).eq(area).all():
        raise ValueError(
            f"{dataset} indeholder forkert prisområde."
        )

    times = pd.to_datetime(
        data[time_col],
        utc=True,
        errors="coerce"
    )

    prices = pd.to_numeric(
        data[price_col],
        errors="coerce"
    )

    if (
        times.isna().any()
        or prices.isna().any()
        or times.duplicated().any()
    ):
        raise ValueError(
            f"{dataset} indeholder ugyldige "
            "priser, tidspunkter eller dubletter."
        )

    # Kontrollér, at afsluttede perioder
    # indeholder samtlige forventede tidspunkter.

    if end <= date.today():

        expected = pd.date_range(
            start=pd.Timestamp(
                start.isoformat(),
                tz=TIMEZONE
            ).tz_convert("UTC"),

            end=pd.Timestamp(
                end.isoformat(),
                tz=TIMEZONE
            ).tz_convert("UTC"),

            freq=(
                "h"
                if dataset == "Elspotprices"
                else "15min"
            ),

            inclusive="left"
        )

        actual = pd.DatetimeIndex(
            times
        ).sort_values()

        if not actual.equals(expected):
            raise ValueError(
                f"{dataset} for {area} "
                f"({start} til {end}) "
                "er ufuldstændigt. "
                f"Modtog {len(actual)} observationer, "
                f"forventede {len(expected)}."
            )


# ============================================================
# HENT FRA CACHE ELLER API
# ============================================================

def _load_chunk(dataset, area, year, month):

    start, end = _chunk_period(
        dataset,
        year,
        month
    )

    path = _cache_file(
        dataset,
        area,
        year,
        month
    )

    # Genbrug allerede hentede priser.

    if path.exists():

        data = pd.read_csv(
            path,
            dtype={"PriceArea": "string"}
        )

        _validate_chunk(
            data,
            dataset,
            area,
            start,
            end
        )

        print(
            f"Bruger gemte priser: {path.name}",
            flush=True
        )

        return data

    # Hent kun fra API, når filen mangler.

    data = _fetch_remote(
        dataset,
        area,
        start,
        end
    )

    _validate_chunk(
        data,
        dataset,
        area,
        start,
        end
    )

    if end <= date.today():

        _save_csv(data, path)

        print(
            f"Gemt prisarkiv: {path.name}",
            flush=True
        )

    return data


# ============================================================
# STANDARDISÉR PRISDATA
# ============================================================

def _normalize(data, dataset, area):

    prices = data.copy()

    if dataset == "Elspotprices":

        prices = prices.rename(
            columns={
                "HourUTC": "TimeUTC",
                "SpotPriceDKK": "DayAheadPriceDKK",
                "SpotPriceEUR": "DayAheadPriceEUR"
            }
        )

    prices["TimeUTC"] = pd.to_datetime(
        prices["TimeUTC"],
        utc=True
    )

    prices["DayAheadPriceDKK"] = pd.to_numeric(
        prices["DayAheadPriceDKK"],
        errors="raise"
    )

    if "DayAheadPriceEUR" not in prices.columns:
        prices["DayAheadPriceEUR"] = float("nan")

    prices["PriceArea"] = area

    # Historiske timepriser kopieres til
    # fire kvartersintervaller med samme pris.

    if dataset == "Elspotprices":

        pieces = []

        for quarter in range(4):

            part = prices.copy()

            part["TimeUTC"] = (
                part["TimeUTC"]
                + pd.Timedelta(
                    minutes=15 * quarter
                )
            )

            pieces.append(part)

        prices = pd.concat(
            pieces,
            ignore_index=True
        )

    prices["TimeDK"] = (
        prices["TimeUTC"]
        .dt.tz_convert(TIMEZONE)
    )

    return prices[
        [
            "TimeUTC",
            "TimeDK",
            "PriceArea",
            "DayAheadPriceEUR",
            "DayAheadPriceDKK"
        ]
    ]


# ============================================================
# HOVEDFUNKTION
# ============================================================

def fetch_prices(
    start_date,
    end_date,
    price_area
):
    """
    Henter historiske priser for DK1 eller DK2.

    Startdato er inkluderet.
    Slutdato er ekskluderet.

    Historiske timepriser omdannes til kvarterer.

    Hver årsfil eller månedsfil indlæses kun
    én gang pr. kald til denne funktion.
    """

    start = _date(start_date)
    end = _date(end_date)

    area = str(price_area).upper().strip()

    if area not in ("DK1", "DK2"):
        raise ValueError(
            "Prisområdet skal være DK1 eller DK2."
        )

    if start >= end:
        raise ValueError(
            "Slutdatoen skal ligge efter startdatoen."
        )

    parts = []

    # Nøgler til datablokke, der allerede
    # er blevet indlæst under dette kald.

    loaded_keys = set()

    cursor = date(
        start.year,
        start.month,
        1
    )

    while cursor < end:

        if cursor < CHANGE_DATE:
            dataset = "Elspotprices"

        else:
            dataset = "DayAheadPrices"

        # ----------------------------------------------------
        # VIGTIG RETTELSE
        # ----------------------------------------------------
        #
        # Elspotprices ligger som hele årsarkiver.
        # Derfor skal hver årsfil kun indlæses én gang.
        #
        # DayAheadPrices ligger i månedsfiler.
        # Derfor bruges både år og måned som nøgle.

        if dataset == "Elspotprices":

            key = (
                dataset,
                area,
                cursor.year
            )

        else:

            key = (
                dataset,
                area,
                cursor.year,
                cursor.month
            )

        if key not in loaded_keys:

            chunk = _load_chunk(
                dataset,
                area,
                cursor.year,
                cursor.month
            )

            normalized = _normalize(
                chunk,
                dataset,
                area
            )

            parts.append(normalized)

            loaded_keys.add(key)

        cursor = _next_month(cursor)

    if not parts:
        raise ValueError(
            "Ingen elpriser fundet."
        )

    # --------------------------------------------------------
    # SAMMENLÆG PRISER
    # --------------------------------------------------------

    prices = pd.concat(
        parts,
        ignore_index=True
    )

    local_start = pd.Timestamp(
        start.isoformat(),
        tz=TIMEZONE
    )

    local_end = pd.Timestamp(
        end.isoformat(),
        tz=TIMEZONE
    )

    # Afgræns efter dansk tid.

    prices = prices.loc[
        (prices["TimeDK"] >= local_start)
        &
        (prices["TimeDK"] < local_end)
    ]

    prices = (
        prices
        .sort_values("TimeUTC")
        .reset_index(drop=True)
    )

    # --------------------------------------------------------
    # KONTROLLÉR ÆGTE DUBLETTER
    # --------------------------------------------------------

    duplicates = (
        prices["TimeUTC"]
        .duplicated()
        .sum()
    )

    if duplicates > 0:
        raise ValueError(
            f"Prisdata indeholder {duplicates} "
            "dublerede tidspunkter fra "
            "forskellige datablokke."
        )

    # --------------------------------------------------------
    # KONTROLLÉR HELE PERIODEN
    # --------------------------------------------------------

    expected = pd.date_range(
        start=local_start.tz_convert("UTC"),
        end=local_end.tz_convert("UTC"),
        freq="15min",
        inclusive="left"
    )

    actual = pd.DatetimeIndex(
        prices["TimeUTC"]
    )

    if not actual.equals(expected):

        missing = expected.difference(actual)
        extra = actual.difference(expected)

        raise ValueError(
            f"Prisdata dækker ikke hele perioden "
            f"{start} til {end}. "
            f"Manglende intervaller: {len(missing)}. "
            f"Ekstra intervaller: {len(extra)}."
        )

    return prices


# ============================================================
# SELVSTÆNDIG TEST
# ============================================================

if __name__ == "__main__":

    prices = fetch_prices(
        start_date="2024-09-01",
        end_date="2024-10-01",
        price_area="DK1"
    )

    print("\nDATAKONTROL")

    print(
        "Antal kvartersintervaller:",
        len(prices)
    )

    print(
        "Dublerede tidspunkter:",
        prices["TimeUTC"].duplicated().sum()
    )

    print(
        "Første tidspunkt:",
        prices["TimeDK"].iloc[0]
    )

    print(
        "Sidste tidspunkt:",
        prices["TimeDK"].iloc[-1]
    )

    print("\nDatakontrollen er bestået!")
