"""
forecast_engine.py — paragliding forecast scoring (pure functions, no I/O).

Wind directions use standard 16-point English compass labels: N, NNE, NE, ENE,
E, ESE, SE, SSE, S, SSW, SW, WSW, W, WNW, NW, NNW.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

# ── Wind direction helpers ───────────────────────────────────────────────────

_SECTORS: list[tuple[str, float]] = [
    ("N",   0.0),  ("NNE", 22.5),  ("NE",  45.0),  ("ENE",  67.5),
    ("E",  90.0),  ("ESE",112.5),  ("SE", 135.0),  ("SSE", 157.5),
    ("S", 180.0),  ("SSW",202.5),  ("SW", 225.0),  ("WSW", 247.5),
    ("W", 270.0),  ("WNW",292.5),  ("NW", 315.0),  ("NNW", 337.5),
]
_SECTOR_NAMES   = [s[0] for s in _SECTORS]
_SECTOR_CENTRES = np.array([s[1] for s in _SECTORS])


def deg_to_sector(degrees: float) -> str:
    """Convert degrees true to the nearest 16-point compass label."""
    degrees = float(degrees) % 360.0
    deltas = np.abs((_SECTOR_CENTRES - degrees + 180.0) % 360.0 - 180.0)
    return _SECTOR_NAMES[int(np.argmin(deltas))]


def wind_ok(direction_deg: float, allowed: list[str]) -> bool:
    """True if the wind direction falls within the site's allowed sectors."""
    allowed_upper = {s.upper() for s in allowed}
    return deg_to_sector(direction_deg) in allowed_upper


# ── Per-row derived metrics ──────────────────────────────────────────────────

KMH_TO_KT = 1.0 / 1.852


def _cloud_base_m(temp_2m: float, dew_point_2m: float) -> float:
    """Espy LCL estimate: LCL ≈ 125 × (T − Td) metres AGL."""
    if math.isnan(temp_2m) or math.isnan(dew_point_2m):
        return math.nan
    return max(0.0, 125.0 * (temp_2m - dew_point_2m))


def _thermal_score(cape: float, temp_2m: float, temp_925: float,
                   height_925: float, elevation_m: float) -> float:
    """
    Rough thermal quality 0–3, combining CAPE and surface lapse rate.
    Returns a value in [0, 3].
    """
    cape = 0.0 if math.isnan(cape) else cape

    # CAPE component
    if cape < 20:
        cape_s = 0.0
    elif cape < 100:
        cape_s = 1.0
    elif cape < 400:
        cape_s = 2.0
    else:
        cape_s = 3.0  # strong thermals but overdevelopment risk

    # Surface lapse rate component (temp_2m vs 925 hPa level)
    lapse_s = 1.0  # neutral default when pressure data is missing
    if (not math.isnan(temp_925) and not math.isnan(height_925)
            and height_925 > elevation_m and not math.isnan(temp_2m)):
        dz = height_925 - elevation_m          # metres
        dt = temp_2m - temp_925               # °C (surface minus upper)
        lapse = dt / dz * 1000.0              # °C per km
        # Dry adiabatic = ~9.8 °C/km; good convective ≥ 7 °C/km
        if lapse > 8.0:
            lapse_s = 3.0
        elif lapse > 6.0:
            lapse_s = 2.0
        elif lapse > 4.0:
            lapse_s = 1.0
        else:
            lapse_s = 0.0

    return min(3.0, (cape_s + lapse_s) / 2.0)


def hour_metrics(row: pd.Series, site: dict) -> dict:
    """Compute all flying-relevant metrics for a single hourly row."""

    def _f(key: str) -> float:
        v = row.get(key, math.nan)
        if v is None:
            return math.nan
        try:
            fv = float(v)
            return math.nan if math.isnan(fv) else fv
        except (TypeError, ValueError):
            return math.nan

    wind_dir  = _f("wind_direction_10m")
    wind_kmh  = _f("wind_speed_10m")
    gust_kmh  = _f("wind_gusts_10m")
    t2m       = _f("temperature_2m")
    td2m      = _f("dew_point_2m")
    cape_val  = _f("cape");  cape_val  = 0.0 if math.isnan(cape_val) else cape_val
    precip_p  = _f("precipitation_probability"); precip_p = 0.0 if math.isnan(precip_p) else precip_p
    cloud_tot = _f("cloud_cover")
    cloud_low = _f("cloud_cover_low")
    bl_h      = _f("boundary_layer_height")
    t925      = _f("temperature_925hPa")
    h925      = _f("geopotential_height_925hPa")
    elevation = float(site.get("launch_height") or 0)

    wind_spd_kt = wind_kmh * KMH_TO_KT  if not math.isnan(wind_kmh)  else math.nan
    gusts_kt    = gust_kmh * KMH_TO_KT  if not math.isnan(gust_kmh)  else math.nan
    cb_m        = _cloud_base_m(t2m, td2m)
    ts          = _thermal_score(cape_val, t2m, t925, h925, elevation)
    w_ok        = wind_ok(wind_dir, site.get("wind_directions", [])) if not math.isnan(wind_dir) else False

    return {
        "wind_dir_deg":    wind_dir,
        "wind_sector":     deg_to_sector(wind_dir) if not math.isnan(wind_dir) else "?",
        "wind_ok":         w_ok,
        "wind_speed_kt":   wind_spd_kt,
        "gusts_kt":        gusts_kt,
        "cloud_base_m":    cb_m,
        "bl_height_m":     bl_h,
        "cape":            cape_val,
        "thermal_score":   ts,
        "precip_prob":     precip_p,
        "cloud_cover":     cloud_tot,
        "cloud_cover_low": cloud_low,
    }


# ── Type-specific scorers ────────────────────────────────────────────────────

def _score_termalling(m: dict) -> float:
    """Thermal/XC soaring: needs thermals, flyable cloud base, moderate wind."""
    score, total = 0.0, 0.0

    # Wind direction (critical: wrong wind → no ridge or thermal trigger)
    total += 3.0
    score += 3.0 if m["wind_ok"] else 0.0

    # Wind speed ≤ 18 kt
    total += 2.0
    ws = m["wind_speed_kt"]
    if not math.isnan(ws):
        score += 2.0 if ws <= 12 else 1.0 if ws <= 18 else 0.0

    # Gusts ≤ 22 kt
    total += 1.0
    g = m["gusts_kt"]
    if not math.isnan(g):
        score += 1.0 if g <= 18 else 0.5 if g <= 22 else 0.0

    # Cloud base > 800 m AGL (need altitude for thermals)
    total += 2.0
    cb = m["cloud_base_m"]
    if not math.isnan(cb):
        score += 2.0 if cb > 1200 else 1.5 if cb > 800 else 0.5 if cb > 500 else 0.0

    # Thermal quality (CAPE + lapse rate)
    total += 2.0
    score += min(2.0, m["thermal_score"] / 3.0 * 2.0)
    if m["cape"] > 800:
        score -= 1.5  # overdevelopment penalty

    # Precipitation probability
    total += 2.0
    pp = m["precip_prob"]
    score += 2.0 if pp < 10 else 1.0 if pp < 20 else -1.0 if pp >= 40 else 0.0

    # Total cloud cover < 70 %
    total += 1.0
    cc = m["cloud_cover"]
    if not math.isnan(cc):
        score += 1.0 if cc < 50 else 0.5 if cc < 70 else 0.0

    return max(0.0, score / total * 10.0) if total > 0 else 0.0


def _score_soaring(m: dict) -> float:
    """Ridge/dynamic soaring: needs correct wind direction and consistent speed."""
    score, total = 0.0, 0.0

    # Wind direction (very critical for ridge soaring)
    total += 4.0
    score += 4.0 if m["wind_ok"] else 0.0

    # Wind speed in sweet-spot 10–20 kt
    total += 2.0
    ws = m["wind_speed_kt"]
    if not math.isnan(ws):
        score += 2.0 if 10 <= ws <= 20 else 1.0 if 8 <= ws <= 25 else 0.0

    # Gusts ≤ 30 kt
    total += 1.0
    g = m["gusts_kt"]
    if not math.isnan(g):
        score += 1.0 if g <= 22 else 0.5 if g <= 30 else 0.0

    # Cloud base > 400 m AGL
    total += 1.0
    cb = m["cloud_base_m"]
    if not math.isnan(cb):
        score += 1.0 if cb > 600 else 0.5 if cb > 400 else 0.0

    # Precipitation probability
    total += 2.0
    pp = m["precip_prob"]
    score += 2.0 if pp < 10 else 1.0 if pp < 20 else -1.0 if pp >= 40 else 0.0

    # Total cloud cover < 80 %
    total += 1.0
    cc = m["cloud_cover"]
    if not math.isnan(cc):
        score += 1.0 if cc < 60 else 0.5 if cc < 80 else 0.0

    return max(0.0, score / total * 10.0) if total > 0 else 0.0


def _score_tow(m: dict) -> float:
    """Aerotow: needs calm, predictable conditions. Wind direction less critical."""
    score, total = 0.0, 0.0

    # Wind direction (preferred but not mandatory for tow)
    total += 1.0
    score += 1.0 if m["wind_ok"] else 0.4

    # Wind speed ≤ 15 kt (calm preferred for safe tow)
    total += 3.0
    ws = m["wind_speed_kt"]
    if not math.isnan(ws):
        score += 3.0 if ws <= 10 else 2.0 if ws <= 15 else 1.0 if ws <= 20 else 0.0

    # Gusts ≤ 18 kt (critical: turbulence on tow is dangerous)
    total += 2.0
    g = m["gusts_kt"]
    if not math.isnan(g):
        score += 2.0 if g <= 14 else 1.0 if g <= 18 else -1.0 if g > 22 else 0.0

    # Cloud base > 300 m AGL (need safe tow altitude)
    total += 2.0
    cb = m["cloud_base_m"]
    if not math.isnan(cb):
        score += 2.0 if cb > 600 else 1.5 if cb > 400 else 0.5 if cb > 300 else 0.0

    # Precipitation probability
    total += 2.0
    pp = m["precip_prob"]
    score += 2.0 if pp < 5 else 1.0 if pp < 10 else -1.0 if pp >= 20 else 0.0

    # Total cloud cover < 50 % (good visibility for tow pilots)
    total += 1.0
    cc = m["cloud_cover"]
    if not math.isnan(cc):
        score += 1.0 if cc < 40 else 0.5 if cc < 60 else 0.0

    return max(0.0, score / total * 10.0) if total > 0 else 0.0


_SCORERS = {
    "termalling": _score_termalling,
    "soaring":    _score_soaring,
    "tow":        _score_tow,
}


def score_hour(row: pd.Series, site: dict) -> tuple[dict, float]:
    """Score one hourly row for the site's flying type. Returns (metrics, score 0–10)."""
    ftype  = site.get("type", "termalling").lower()
    scorer = _SCORERS.get(ftype, _score_termalling)
    m      = hour_metrics(row, site)
    return m, scorer(m)


def score_day(hourly_day: pd.DataFrame, site: dict) -> dict:
    """
    Aggregate hourly scores for one day to a daily assessment.
    hourly_day: subset of hourly_df for a single date, filtered to flying hours.
    """
    if hourly_day.empty:
        return {"score": math.nan, "verdict": "no-data", "n_hours": 0,
                "hour_scores": [], "hour_metrics": []}

    # Drop hours where wind speed is absent (beyond model forecast horizon)
    hourly_day = hourly_day[hourly_day["wind_speed_10m"].notna()]
    if hourly_day.empty:
        return {"score": math.nan, "verdict": "no-data", "n_hours": 0,
                "hour_scores": [], "hour_metrics": []}

    results      = [score_hour(row, site) for _, row in hourly_day.iterrows()]
    metrics_list = [r[0] for r in results]
    scores       = [r[1] for r in results]
    avg_score    = float(np.mean(scores))
    wind_ok_frac = sum(1 for m in metrics_list if m["wind_ok"]) / len(metrics_list)

    def _mean(key: str) -> float:
        vals = [float(m[key]) for m in metrics_list
                if isinstance(m[key], (int, float, np.floating))
                and not math.isnan(float(m[key]))]
        return float(np.mean(vals)) if vals else math.nan

    if avg_score >= 7.0 and wind_ok_frac >= 0.5:
        verdict = "fly"
    elif avg_score >= 4.5 or (avg_score >= 3.5 and wind_ok_frac >= 0.5):
        verdict = "marginal"
    else:
        verdict = "no-go"

    return {
        "score":        avg_score,
        "verdict":      verdict,
        "wind_ok_pct":  wind_ok_frac,
        "wind_speed_kt":  _mean("wind_speed_kt"),
        "gusts_kt":       _mean("gusts_kt"),
        "cloud_base_m":   _mean("cloud_base_m"),
        "bl_height_m":    _mean("bl_height_m"),
        "cape":           _mean("cape"),
        "precip_prob":    _mean("precip_prob"),
        "cloud_cover":    _mean("cloud_cover"),
        "thermal_score":  _mean("thermal_score"),
        "n_hours":      len(hourly_day),
        "hour_scores":  scores,
        "hour_metrics": metrics_list,
    }


def score_all_days(hourly_df: pd.DataFrame, site: dict, timezone: str) -> dict[str, dict]:
    """
    Score each date in hourly_df over the flying window (10:00–16:00 local).
    Returns dict keyed by "YYYY-MM-DD" date strings.
    """
    local_times = hourly_df["time"].dt.tz_convert(timezone)
    flying_mask = local_times.dt.hour.between(10, 16)
    flying_df   = hourly_df[flying_mask].copy()
    flying_df["_date"] = local_times[flying_mask].dt.date.values

    results: dict[str, dict] = {}
    for date, group in flying_df.groupby("_date"):
        results[str(date)] = score_day(group.drop(columns=["_date"]), site)
    return results


# ── Streak + ranking ─────────────────────────────────────────────────────────

def best_streak(daily_scores: dict[str, dict],
                threshold: float = 6.0) -> tuple[str | None, int]:
    """
    Find the best consecutive-flyable-days run in the forecast.
    Returns (start_date_str, streak_length).
    """
    dates = sorted(daily_scores.keys())
    best_start, best_len = None, 0
    cur_start,  cur_len  = None, 0

    for date in dates:
        if daily_scores[date]["score"] >= threshold:
            if cur_len == 0:
                cur_start = date
            cur_len += 1
            if cur_len > best_len:
                best_len, best_start = cur_len, cur_start
        else:
            cur_len, cur_start = 0, None

    return best_start, best_len


def ensemble_daily_scores(
    per_model_scores: dict[str, dict[str, dict]],
) -> dict[str, dict]:
    """
    Average daily scores across models to produce an ensemble forecast.

    Parameters
    ----------
    per_model_scores : {model_name: {date_str: score_dict}}

    Returns
    -------
    {date_str: score_dict} — same shape as ``score_all_days()``, with an
    extra ``"per_model"`` key showing each model's raw score.
    """
    all_dates = sorted({d for scores in per_model_scores.values() for d in scores})
    result: dict[str, dict] = {}

    for date in all_dates:
        day_scores = [
            per_model_scores[m][date]
            for m in per_model_scores
            if date in per_model_scores[m]
            and per_model_scores[m][date]["verdict"] != "no-data"
        ]
        if not day_scores:
            continue

        avg_score    = float(np.mean([s["score"] for s in day_scores]))
        wind_ok_vals = [s["wind_ok_pct"] for s in day_scores
                        if "wind_ok_pct" in s and not math.isnan(s["wind_ok_pct"])]
        wind_ok_pct  = float(np.mean(wind_ok_vals)) if wind_ok_vals else 0.0

        if avg_score >= 7.0 and wind_ok_pct >= 0.5:
            verdict = "fly"
        elif avg_score >= 4.5 or (avg_score >= 3.5 and wind_ok_pct >= 0.5):
            verdict = "marginal"
        else:
            verdict = "no-go"

        def _avg(key: str) -> float:
            vals = [float(s[key]) for s in day_scores
                    if key in s and not math.isnan(float(s[key]))]
            return float(np.mean(vals)) if vals else math.nan

        result[date] = {
            "score":         avg_score,
            "verdict":       verdict,
            "wind_ok_pct":   wind_ok_pct,
            "wind_speed_kt": _avg("wind_speed_kt"),
            "gusts_kt":      _avg("gusts_kt"),
            "cloud_base_m":  _avg("cloud_base_m"),
            "bl_height_m":   _avg("bl_height_m"),
            "cape":          _avg("cape"),
            "precip_prob":   _avg("precip_prob"),
            "cloud_cover":   _avg("cloud_cover"),
            "thermal_score": _avg("thermal_score"),
            "n_hours":       day_scores[0].get("n_hours", 0),
            "per_model":     {
                m: per_model_scores[m][date]["score"]
                for m in per_model_scores
                if date in per_model_scores[m]
                and per_model_scores[m][date]["verdict"] != "no-data"
            },
        }
    return result


def rank_sites(all_results: list[dict]) -> list[dict]:
    """
    Sort sites by streak_len DESC, then avg_score DESC.
    Each element of all_results must contain 'site' and 'daily_scores' keys.
    Returns the same list enriched with 'streak_start', 'streak_len', 'avg_score'.
    """
    enriched = []
    for r in all_results:
        ds     = r["daily_scores"]
        scores = [ds[d]["score"] for d in ds]
        start, length = best_streak(ds)
        enriched.append({
            **r,
            "streak_start": start,
            "streak_len":   length,
            "avg_score":    float(np.mean(scores)) if scores else 0.0,
        })
    return sorted(enriched, key=lambda x: (-x["streak_len"], -x["avg_score"]))
