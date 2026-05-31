"""Standalone Skew-T plotter — runs outside the notebook."""
import json, pathlib, requests_cache, numpy as np, pandas as pd
from retry_requests import retry
import openmeteo_requests
import metpy.calc as mpcalc
from metpy.plots import SkewT
from metpy.units import units as munits
import matplotlib.pyplot as plt

# ── Config ────────────────────────────────────────────────────────────────────
with open("sites.json") as f:
    sites = json.load(f)
site = sites[0]
MODEL = "ecmwf_ifs025"
LEVELS = [1000, 975, 950, 925, 900, 850, 800, 700, 600, 500]
TICK_LEVELS = [1000, 925, 850, 800, 700, 600, 500]
p = np.array(LEVELS) * munits.hPa

PRESSURE_VARS = (
    [f"temperature_{lvl}hPa"        for lvl in LEVELS] +
    [f"dew_point_{lvl}hPa"          for lvl in LEVELS] +
    [f"wind_speed_{lvl}hPa"         for lvl in LEVELS] +
    [f"wind_direction_{lvl}hPa"     for lvl in LEVELS] +
    [f"geopotential_height_{lvl}hPa" for lvl in LEVELS]
)

cache_session = requests_cache.CachedSession(".cache", expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)

params = {
    "latitude":  site["coordinates"][0],
    "longitude": site["coordinates"][1],
    "hourly":    PRESSURE_VARS,
    "models":    MODEL,
    "forecast_days": 5,
}
responses = openmeteo.weather_api("https://api.open-meteo.com/v1/forecast", params=params)
response  = responses[0]

timezone = response.Timezone()
if isinstance(timezone, bytes):
    timezone = timezone.decode()
timezone_abbr = response.TimezoneAbbreviation()
if isinstance(timezone_abbr, bytes):
    timezone_abbr = timezone_abbr.decode()

hourly     = response.Hourly()
times      = pd.date_range(
    start   = pd.to_datetime(hourly.Time(),    unit="s", utc=True),
    end     = pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
    freq    = pd.Timedelta(seconds=hourly.Interval()),
    inclusive="left",
)
data = {"time": times}
for j, var in enumerate(PRESSURE_VARS):
    data[var] = hourly.Variables(j).ValuesAsNumpy()

hourly_df = pd.DataFrame(data)
local_hour = hourly_df["time"].dt.tz_convert(timezone).dt.hour
hourly_df  = hourly_df[local_hour.between(10, 16)].reset_index(drop=True)

# ── Skew-T plots ──────────────────────────────────────────────────────────────
df = hourly_df.copy()
df["local_time"] = df["time"].dt.tz_convert(timezone)
df["date"]       = df["local_time"].dt.date
df["hour"]       = df["local_time"].dt.hour

for date in sorted(df["date"].unique()):
    day = df[df["date"] == date].sort_values("hour")
    n   = len(day)

    fig = plt.figure(figsize=(7, n * 5))
    fig.suptitle(
        f"{site['name'].upper()}  ·  {date.strftime('%A %d %B %Y')}  ·  {timezone_abbr}",
        fontsize=12, fontweight="bold",
    )

    for i, (_, row) in enumerate(day.iterrows()):
        skew = SkewT(fig, subplot=(n, 1, i + 1), rotation=45)

        T       = np.array([row[f"temperature_{lvl}hPa"]        for lvl in LEVELS]) * munits.degC
        Td      = np.array([row[f"dew_point_{lvl}hPa"]          for lvl in LEVELS]) * munits.degC
        ws      = np.array([row[f"wind_speed_{lvl}hPa"]         for lvl in LEVELS]) * munits("km/h")
        wd      = np.array([row[f"wind_direction_{lvl}hPa"]     for lvl in LEVELS]) * munits.degrees
        heights = np.array([row[f"geopotential_height_{lvl}hPa"] for lvl in LEVELS])
        u, v    = mpcalc.wind_components(ws.to("kt"), wd)

        skew.plot(p, T,  "r", linewidth=1.5)
        skew.plot(p, Td, "g", linewidth=1.5)
        skew.plot_barbs(p, u, v, barbcolor="navy", linewidth=0.8)
        skew.plot_dry_adiabats(alpha=0.25, linewidth=0.6, colors="darkorange")
        skew.plot_moist_adiabats(alpha=0.25, linewidth=0.6, colors="green")
        skew.plot_mixing_lines(alpha=0.20, linewidth=0.6, colors="blue")

        skew.ax.set_ylim(1000, 500)
        skew.ax.set_xlim(-20, 35)

        skew.ax.set_yticks(TICK_LEVELS)
        tick_heights = [heights[LEVELS.index(lvl)] for lvl in TICK_LEVELS]
        skew.ax.set_yticklabels([
            f"{int(h)} m" if not np.isnan(h) else f"{lvl} hPa"
            for h, lvl in zip(tick_heights, TICK_LEVELS)
        ])
        skew.ax.set_ylabel("Altitude (m ASL)")
        skew.ax.set_title(f"{row['hour']:02d}:00", fontsize=10, pad=4)
        if i < n - 1:
            skew.ax.set_xlabel("")

    fig.tight_layout()
    site_slug = site["name"].lower().replace(" ", "_")
    out_dir   = pathlib.Path("data") / site_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"skewt_{date}.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out}")
