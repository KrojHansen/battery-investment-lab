"""Walk-forward gradient boosting model for the Battery Investment Lab.

The target is the next Danish local delivery day's spot-price profile.
Every target's features are calculated using ONLY earlier delivery days.
Each fitted model is frozen for the remainder of its calendar month.
The first fit in an evaluation period uses data strictly before that period.

The model predicts prices, NOT battery charge/discharge decisions. The
existing optimizer subsequently translates forecasts into physical trades.
"""
from __future__ import annotations

from datetime import date
import math
import numpy as np

MODEL_VERSION = "gradient-boosting-2026-11-v1"
MIN_TRAINING_DAYS = 14
MAX_TRAINING_DAYS = 180


def _day_features(days: list[date], values: np.ndarray, index: int) -> np.ndarray:
    """Features for all 96 local quarter-hour positions on day `index`.

    `values[index]` must never be read here. Periodic time labels are known
    in advance, and the price series come from earlier delivery days only.
    """
    if index < 7:
        raise ValueError("Der kræves mindst syv tidligere kalenderdage.")
    d = days[index]
    slots = np.arange(96, dtype=float)
    dow = d.weekday()
    doy = d.timetuple().tm_yday
    yesterday = values[index - 1]
    last_week = values[index - 7]
    last3 = values[index - 3:index]
    last7 = values[index - 7:index]
    n = len(slots)

    # The matrix has one row per local delivery-time slot.
    def constant(x):
        return np.full(n, float(x), dtype=float)

    columns = [
        np.sin(2 * np.pi * slots / 96),
        np.cos(2 * np.pi * slots / 96),
        np.sin(4 * np.pi * slots / 96),
        np.cos(4 * np.pi * slots / 96),
        constant(math.sin(2 * math.pi * dow / 7)),
        constant(math.cos(2 * math.pi * dow / 7)),
        constant(dow >= 5),
        constant(math.sin(2 * math.pi * doy / 365.25)),
        constant(math.cos(2 * math.pi * doy / 365.25)),
        yesterday / 1000,
        last_week / 1000,
        last3.mean(axis=0) / 1000,
        last7.mean(axis=0) / 1000,
        constant(yesterday.mean() / 1000),
        constant(last7.mean() / 1000),
        constant(last7.mean(axis=1).std() / 1000),
        (last3.mean(axis=0) - last7.mean(axis=0)) / 1000,
    ]
    result = np.column_stack(columns)
    if not np.isfinite(result).all():
        raise ValueError("Prognosefeatures indeholder ugyldige værdier.")
    return result


class WalkForwardGradientBoosting:
    """Re-fit at most monthly using strict past-only data and fixed settings."""

    def __init__(self, profiles, first_test_day: date):
        self.dates = list(profiles.index)
        self.day_to_index = {d: i for i, d in enumerate(self.dates)}
        self.values = profiles.to_numpy(dtype=float)
        self.first_test_day = first_test_day
        self.models = {}
        self.training_records = []
        if self.values.ndim != 2 or self.values.shape[1] != 96:
            raise ValueError("Prisprofilerne skal indeholde 96 pladser pr. dag.")
        if not np.isfinite(self.values).all():
            raise ValueError("Historiske prisprofiler indeholder NaN eller infinity.")
        if first_test_day not in self.day_to_index:
            raise ValueError("Første testdag findes ikke i prisdata.")

    def _cutoff(self, day: date):
        # The model is trained at the first evaluated day of its month,
        # or the first calendar day of later months, whichever is later.
        return max(date(day.year, day.month, 1), self.first_test_day)

    def _fit(self, cutoff: date):
        from sklearn.ensemble import HistGradientBoostingRegressor

        cutoff_idx = self.day_to_index[cutoff]
        first = max(7, cutoff_idx - MAX_TRAINING_DAYS)
        train_idx = list(range(first, cutoff_idx))
        if len(train_idx) < MIN_TRAINING_DAYS:
            raise ValueError(
                "Gradient Boosting kræver mindst 14 komplette træningsdage "
                "med 7 dages yderligere historik."
            )
        x = np.concatenate([
            _day_features(self.dates, self.values, i) for i in train_idx
        ])
        y = np.concatenate([self.values[i] for i in train_idx])

        model = HistGradientBoostingRegressor(
            loss="squared_error",
            learning_rate=0.07,
            max_iter=70,
            max_leaf_nodes=13,
            min_samples_leaf=40,
            l2_regularization=10.0,
            early_stopping=False,
            random_state=42,
        )
        model.fit(x, y)
        self.training_records.append({
            "Modeltræning før": cutoff,
            "Træningsdage": len(train_idx),
            "Fra": self.dates[train_idx[0]],
            "Til": self.dates[train_idx[-1]],
        })
        return model

    def predict(self, day: date) -> np.ndarray:
        if day < self.first_test_day:
            raise ValueError("Modellen må ikke forudsige en dag før teststart.")
        index = self.day_to_index.get(day)
        if index is None:
            raise ValueError("Den ønskede leveringsdag findes ikke.")
        cutoff = self._cutoff(day)
        if cutoff not in self.models:
            self.models[cutoff] = self._fit(cutoff)
        forecast = self.models[cutoff].predict(
            _day_features(self.dates, self.values, index)
        )
        if forecast.shape != (96,) or not np.isfinite(forecast).all():
            raise RuntimeError("Maskinlæringsmodellen returnerede ugyldige priser.")
        return forecast
