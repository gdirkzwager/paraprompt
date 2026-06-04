"""
forecast_fetcher.py — fetch fresh forecasts from Open-Meteo for all sites.

Always pulls live data (1-hour request cache via requests_cache).
Saves each fetch to data/<site_name>_<timestamp>.json.
"""
from __future__ import annotations

import json
import pathlib
import time
from datetime import datetime

import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry

# ── API configuration ────────────────────────────────────────────────────────

# Available models (Europe):
#   "best_match"      – Open-Meteo seamless blend (default)
#   "ecmwf_ifs025"    – ECMWF IFS 0.25°, global, 6-hourly analysis
#   "icon_eu"         – DWD ICON-EU 0.0625°, best resolution for Europe
#   "icon_d2"         – DWD ICON-D2 0.02°, Germany/Alps/BeNeLux only, 2 km
#   "arome_france"    – Météo-France AROME 0.025°, France + neighbours
#   "gfs_seamless"    – NOAA GFS, global
MODELS: list[str] = ["ecmwf_ifs025", "icon_eu"]

PRESSURE_LEVELS = [1000, 975, 950, 925, 900, 850, 800, 700, 600, 500]
_PRESSURE_VARS  = [
    "temperature", "dew_point", "relative_humidity",
    "wind_speed", "wind_direction", "geopotential_height", "cloud_cover",
]

HOURLY_PARAMS: list[str] = [
    # Surface wind
    "wind_speed_10m", "wind_speed_80m", "wind_speed_120m", "wind_speed_180m",
    "wind_direction_10m", "wind_direction_80m", "wind_direction_120m", "wind_direction_180m",
    "wind_gusts_10m",
    # Temperature / humidity
    "temperature_2m", "temperature_80m", "temperature_120m", "temperature_180m",
    "dew_point_2m", "apparent_temperature", "relative_humidity_2m",
    # Pressure & thermodynamics
    "pressure_msl", "surface_pressure",
    "cape", "lifted_index", "convective_inhibition",
    "freezing_level_height", "boundary_layer_height",
    # Cloud cover
    "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    "visibility",
    # Precipitation
    "precipitation", "rain", "showers", "snowfall", "precipitation_probability",
    "weather_code",
    # Solar radiation
    "shortwave_radiation", "direct_radiation", "direct_normal_irradiance",
    "diffuse_radiation", "is_day",
    # Pressure-level sounding variables (for Skew-T)
    *[f"{var}_{lvl}hPa" for lvl in PRESSURE_LEVELS for var in _PRESSURE_VARS],
]

DAILY_PARAMS: list[str] = [
    "temperature_2m_max", "temperature_2m_min",
    "wind_speed_10m_max", "wind_gusts_10m_max", "wind_direction_10m_dominant",
    "precipitation_sum", "rain_sum", "showers_sum", "precipitation_probability_max",
    "weather_code",
    "sunrise", "sunset", "daylight_duration", "sunshine_duration",
    "uv_index_max", "shortwave_radiation_sum",
]

FORECAST_DAYS = 7


# ── Client factory ───────────────────────────────────────────────────────────

def _make_client() -> openmeteo_requests.Client:
    cache   = requests_cache.CachedSession(".cache", expire_after=3600)
    session = retry(cache, retries=5, backoff_factor=0.2)
    return openmeteo_requests.Client(session=session)


# ── Single-site fetch ────────────────────────────────────────────────────────

def fetch_site(site: dict,
               model: str = MODELS[0],
               client: openmeteo_requests.Client | None = None) -> dict:
    """
    Fetch a fresh 7-day forecast for *site* using *model*.

    Returns a dict with keys:
        site, meta, hourly_df, daily_df, timezone, file
    """
    if client is None:
        client = _make_client()

    lat, lon = site["coordinates"]

    responses = client.weather_api(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude":       lat,
            "longitude":      lon,
            "hourly":         HOURLY_PARAMS,
            "daily":          DAILY_PARAMS,
            "models":         model,
            "wind_speed_unit": "kmh",
            "forecast_days":  FORECAST_DAYS,
            "timezone":       "auto",
        },
    )
    response = responses[0]

    timezone = response.Timezone()
    if isinstance(timezone, bytes):
        timezone = timezone.decode()
    timezone_abbr = response.TimezoneAbbreviation()
    if isinstance(timezone_abbr, bytes):
        timezone_abbr = timezone_abbr.decode()

    # ── Hourly DataFrame ─────────────────────────────────────────────────────
    hourly = response.Hourly()
    hourly_df = pd.DataFrame({
        "time": pd.date_range(
            start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=hourly.Interval()),
            inclusive="left",
        ),
        **{name: hourly.Variables(i).ValuesAsNumpy()
           for i, name in enumerate(HOURLY_PARAMS)},
    })

    # ── Daily DataFrame ──────────────────────────────────────────────────────
    daily = response.Daily()
    daily_df = pd.DataFrame({
        "time": pd.date_range(
            start=pd.to_datetime(daily.Time(), unit="s", utc=True),
            end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=daily.Interval()),
            inclusive="left",
        ),
        **{name: daily.Variables(i).ValuesAsNumpy()
           for i, name in enumerate(DAILY_PARAMS)},
    })

    meta = {
        "latitude":          response.Latitude(),
        "longitude":         response.Longitude(),
        "elevation":         response.Elevation(),
        "timezone":          timezone,
        "timezone_abbr":     timezone_abbr,
        "utc_offset_seconds": response.UtcOffsetSeconds(),
        "model":             model,
    }

    # ── Persist to disk ──────────────────────────────────────────────────────
    site_slug = site["name"].lower().replace(" ", "_")
    out_dir   = pathlib.Path("data") / site_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file  = out_dir / f"{site_slug}_{timestamp}.json"

    with open(out_file, "w") as fh:
        json.dump(
            {
                "site":   site,
                "meta":   meta,
                "hourly": json.loads(hourly_df.to_json(orient="records", date_format="iso")),
                "daily":  json.loads(daily_df.to_json(orient="records", date_format="iso")),
            },
            fh,
            indent=2,
        )

    return {
        "site":      site,
        "meta":      meta,
        "hourly_df": hourly_df,
        "daily_df":  daily_df,
        "timezone":  timezone,
        "file":      str(out_file),
    }


# ── All-sites fetch ──────────────────────────────────────────────────────────

def fetch_all_sites(sites_file: str = "sites.json") -> list[dict]:
    """
    Fetch fresh forecasts for every site in *sites_file*, across all MODELS.

    Returns a list of dicts, one per site::

        {
            "site":   {...},
            "models": {
                "<model>": {
                    "meta": {...}, "hourly_df": df, "daily_df": df,
                    "timezone": str, "file": str
                },
                ...
            }
        }
    """
    with open(sites_file) as fh:
        sites = json.load(fh)

    client  = _make_client()
    results = []
    for i, site in enumerate(sites):
        if i > 0:
            time.sleep(2)  # avoid Open-Meteo per-minute rate limit
        print(f"  {site['name']}:")
        model_data: dict[str, dict] = {}
        for model in MODELS:
            print(f"    [{model}] …", end=" ", flush=True)
            result = fetch_site(site, model, client)
            print(f"saved → {result['file']}")
            model_data[model] = {k: v for k, v in result.items() if k != "site"}
        results.append({"site": site, "models": model_data})

    return results
