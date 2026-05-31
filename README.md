# paraprompt 🪂

A paragliding weather forecast notebook that fetches multi-model NWP data from [Open-Meteo](https://open-meteo.com), scores each flying day per site, and generates a self-contained HTML report.

Sites covered include thermalling sites in the Belgian Ardennes, the Eifel and Sauerland (Germany), and coastal soaring sites on the French Channel coast.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Repository Structure](#repository-structure)
3. [Configuration](#configuration)
   - [Adding / editing sites](#adding--editing-sites)
   - [Choosing forecast models](#choosing-forecast-models)
4. [How It Works](#how-it-works)
5. [Meteorological Parameters](#meteorological-parameters)
   - [Wind](#wind)
   - [Cloud Base (LCL)](#cloud-base-lcl)
   - [Boundary Layer Height](#boundary-layer-height)
   - [CAPE — Convective Available Potential Energy](#cape--convective-available-potential-energy)
   - [Lapse Rate](#lapse-rate)
   - [Precipitation Probability](#precipitation-probability)
   - [Cloud Cover](#cloud-cover)
   - [Lifted Index](#lifted-index)
6. [Scoring System](#scoring-system)
   - [Termalling](#termalling)
   - [Soaring (ridge / dynamic)](#soaring-ridge--dynamic)
   - [Aerotow](#aerotow)
7. [Multi-Model Ensemble](#multi-model-ensemble)
8. [Reading the Plots](#reading-the-plots)
   - [Site Detail Chart (3-row figure)](#site-detail-chart-3-row-figure)
   - [Skew-T Log-P Sounding](#skew-t-log-p-sounding)
   - [Ranking Table](#ranking-table)

---

## Quick Start

```bash
# 1. Create a virtual environment
python -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
uv pip install openmeteo-requests requests-cache retry-requests \
               numpy pandas matplotlib metpy

# 3. Open the notebook
jupyter lab paraprompt.ipynb
```

Run cells sequentially. The dashboard section (from cell 10 onwards) fetches live
forecasts, scores all sites, renders charts, and exports an HTML report to `reports/`.

---

## Repository Structure

```
paraprompt/
├── paraprompt.ipynb       # Main notebook — exploration + dashboard
├── forecast_fetcher.py    # Fetches Open-Meteo API for all sites / all models
├── forecast_engine.py     # Pure-function scoring library (no I/O)
├── sites.json             # Site registry (coordinates, wind dirs, type, …)
├── run_skewt.py           # Standalone Skew-T script (single site)
├── data/                  # Auto-generated fetch cache (git-ignored)
├── reports/               # Auto-generated HTML reports (git-ignored)
└── .gitignore
```

---

## Configuration

### Adding / editing sites

Edit `sites.json`. Each entry looks like:

```json
{
    "name": "Revin",
    "coordinates": [49.948313, 4.62444],
    "wind_directions": ["SE", "SSE", "S", "SSW", "SW"],
    "launch_height": 370,
    "type": "termalling",
    "url": "https://bvvf.be/flying_sites/revin"
}
```

| Field | Description |
|---|---|
| `name` | Display name — used for file names and chart titles |
| `coordinates` | `[latitude, longitude]` in decimal degrees |
| `wind_directions` | Compass sectors that work for this site. Uses 16-point notation: N, NNE, NE, ENE, E, ESE, SE, SSE, S, SSW, SW, WSW, W, WNW, NW, NNW |
| `launch_height` | Launch altitude in metres ASL — used for lapse-rate calculation |
| `type` | `"termalling"`, `"soaring"`, or `"tow"` — selects the scoring function |
| `url` | Optional link to the site's official page |

### Choosing forecast models

In `forecast_fetcher.py`:

```python
MODELS: list[str] = ["ecmwf_ifs025", "icon_eu"]
```

Add or remove model IDs. All listed models are fetched and scored independently;
the dashboard shows the ensemble average plus each model's individual score.

| Model | Resolution | Strengths |
|---|---|---|
| `ecmwf_ifs025` | 0.25° / ~28 km | Global, reliable at synoptic scale |
| `icon_eu` | 0.0625° / ~7 km | Best resolution for Europe |
| `icon_d2` | 0.02° / ~2 km | Germany / Alps / BeNeLux only |
| `arome_france` | 0.025° / ~2.5 km | France and immediate neighbours |
| `best_match` | Varies | Open-Meteo auto-blend |
| `gfs_seamless` | ~13 km | Global, NOAA |

---

## How It Works

```
sites.json
    │
    ▼
forecast_fetcher.py  ──►  Open-Meteo API  (one request per site × model)
    │                      7-day hourly + daily variables
    │                      saved to data/<site>/<site>_<timestamp>.json
    ▼
forecast_engine.py
    │  score_all_days()   — scores every day, 10:00–16:00 local
    │  ensemble_daily_scores() — averages scores across models
    │  rank_sites()       — sorts by streak → avg score
    ▼
paraprompt.ipynb
    ├── ranking HTML table
    ├── 3-row detail figure per site
    ├── Skew-T sounding drill-down
    └── self-contained HTML report  →  reports/forecast_report_<date>.html
```

The flying window is **10:00–16:00 local time** — hourly scores outside this window
are ignored. The window was chosen to cover the typical thermal day in Central Europe
(thermals trigger late morning, overdevelopment risk rises after mid-afternoon).

---

## Meteorological Parameters

### Wind

Wind is the single most important parameter for paragliding.

**Wind direction** is checked against the site's `wind_directions` list using a
16-point compass rose. A wind from an incorrect direction means no ridge lift and
no thermal trigger from the correct aspect — the site simply doesn't work.

**Wind speed** thresholds (in knots, converted from km/h):

| Speed | Meaning |
|---|---|
| < 8 kt | Too light for ridge soaring; thermals may be broken |
| 8–12 kt | Ideal for thermalling |
| 12–18 kt | Strong for thermalling, acceptable for soaring |
| 18–25 kt | Challenging — gusty, turbulent, launch difficult |
| > 25 kt | Dangerous — do not fly |

**Gusts** are the peak wind speed in the preceding hour at 10 m AGL. A large
spread between mean wind and gusts (gust factor > 1.4×) indicates mechanical
turbulence or convective mixing — both dangerous near launch.

**Wind shear** — the difference in speed or direction between the surface and
higher pressure levels — is visible on the Skew-T plot. Strong shear above the
boundary layer can cause rotor turbulence under cloud base.

---

### Cloud Base (LCL)

The **Lifting Condensation Level (LCL)** is estimated using the Espy rule:

$$\text{LCL (m AGL)} = 125 \times (T_{2m} - T_{d,2m})$$

where $T_{2m}$ is the 2 m air temperature and $T_{d,2m}$ is the 2 m dew point.
The larger the dew-point depression (dry air), the higher the cloud base.

| Cloud Base AGL | Meaning for Paragliding |
|---|---|
| < 300 m | Flying in or just below cloud — dangerous, illegal in many countries |
| 300–500 m | Very low; XC impossible, short local flights only |
| 500–800 m | Marginal; limited climb height |
| 800–1200 m | Good thermalling altitude, XC possible |
| > 1200 m | Excellent — high cloudbase, long XC potential |

In the detail chart the red dashed line marks 500 m and the green dashed line
marks 800 m. Good flying days have the blue cloud-base fill well above the green
line.

---

### Boundary Layer Height

The **planetary boundary layer (BL)** is the well-mixed layer of the atmosphere
above the surface, driven by solar heating. Thermals rise through the BL and
stop at the BL top (the thermal ceiling).

| BL Height ASL | Meaning |
|---|---|
| < 800 m ASL | Weak convection — thermals shallow, short climbs |
| 800–1500 m ASL | Moderate day — usable climbs |
| 1500–2500 m ASL | Good thermalling day — significant altitude gain |
| > 2500 m ASL | Strong day — watch for overdevelopment |

In the detail chart the orange line traces the BL height through the flying window.
A BL height that rises steeply through the morning and peaks around 13:00–14:00
is the classic signature of a good thermal day.

Note: the BL height is absolute altitude (ASL), while the cloud base is relative
(AGL). Subtract the site's launch height to compare them directly.

---

### CAPE — Convective Available Potential Energy

CAPE measures the energy available for convective lift. It is the area between
the environmental temperature profile and the temperature of a rising air parcel
on a Skew-T diagram. Units are **J/kg**.

| CAPE (J/kg) | Meaning for Paragliding |
|---|---|
| 0–50 | Stable — no thermals, or very weak broken thermals |
| 50–200 | Weak convection — gentle thermals, low overdevelopment risk |
| 200–500 | Moderate thermals — good XC day, watch for cumulus building |
| 500–1000 | Strong thermals — fast climbs, but significant Cu-nim risk |
| > 1000 | Very unstable — high risk of overdevelopment, thunderstorms, abort |

**Low CAPE (< 50 J/kg)**: the atmosphere is stable. Thermals are weak or absent.
Good for soaring on ridge sites where you don't need thermals, but poor for
thermalling and XC.

**High CAPE (> 800 J/kg)**: the atmosphere is very unstable. Thermals will be
strong and fast but the day is likely to overdevelop into cumulonimbus (Cu-nim /
thunderstorms) during the afternoon. The scoring model applies a penalty above
800 J/kg because the overdevelopment risk outweighs the thermal strength.

In the detail chart CAPE is shown as red bars. The two dashed lines mark 300 J/kg
(moderate onset) and 800 J/kg (overdevelopment penalty threshold).

---

### Lapse Rate

The **lapse rate** is how quickly temperature drops with altitude. The scoring
engine derives a surface lapse rate by comparing the 2 m temperature to the
925 hPa pressure level temperature and the geopotential height of that level.

| Lapse Rate (°C/km) | Meaning |
|---|---|
| < 4 | Stable/inverted — thermals suppressed by inversion |
| 4–6 | Conditionally stable — weak thermals |
| 6–8 | Near dry-adiabatic — good convective day |
| > 8 | Super-adiabatic — explosive thermals, instability |

The dry adiabatic lapse rate is ~9.8 °C/km. When the environmental lapse rate
approaches this value, thermals rise freely without entraining much surrounding
air — you get strong, well-organised thermal columns.

---

### Precipitation Probability

The probability (%) that at least 0.1 mm of precipitation falls in a given hour.

| Precip % | Meaning |
|---|---|
| < 10 % | Dry — full score |
| 10–20 % | Low risk — slight penalty |
| 20–40 % | Moderate risk — significant penalty |
| > 40 % | High risk — strong negative score contribution |

Even moderate rain probability matters in paragliding: wet gliders fly poorly,
visibility drops, and convective showers can arrive fast. In the detail chart
the blue line (right-hand axis) shows precipitation probability; the dashed
reference line is at 20 %.

---

### Cloud Cover

| Layer | Altitude | Paragliding Impact |
|---|---|---|
| `cloud_cover_low` | < 3 km | Most critical — fog and stratus suppress thermals, reduce visibility at flying altitude |
| `cloud_cover_mid` | 3–8 km | Moderate impact — shading reduces thermal trigger, but flying is generally still possible |
| `cloud_cover_high` | > 8 km | Cirrus — little direct impact on flying |
| `cloud_cover` | Total | Used in scoring: > 70 % for thermalling is penalised |

---

### Lifted Index

The **Lifted Index (LI)** measures the temperature difference between a parcel
lifted from the surface to 500 hPa and the environmental temperature at 500 hPa.

| LI | Interpretation |
|---|---|
| > +2 | Stable — thermals unlikely |
| 0 to +2 | Slightly unstable — weak thermals |
| -2 to 0 | Moderately unstable — good thermals |
| -4 to -2 | Very unstable — strong thermals, Cu-nim possible |
| < -4 | Extremely unstable — severe convection, do not fly |

---

## Scoring System

Each hourly row in the 10:00–16:00 flying window is scored 0–10 and the mean
is taken as the daily score.

### Verdicts

| Score | Verdict | Display |
|---|---|---|
| ≥ 7.0 and wind OK ≥ 50 % of hours | Fly | 🟢 green |
| ≥ 4.5 | Marginal | 🟡 amber |
| < 4.5 | No-go | 🔴 red |

### Termalling

Suitable for sites where pilots use solar thermals to climb and travel XC.

| Criterion | Weight | Notes |
|---|---|---|
| Wind direction correct | 3/10 | Dominant factor |
| Wind speed ≤ 18 kt | 2/10 | Penalty above 18 kt |
| Gusts ≤ 22 kt | 1/10 | |
| Cloud base > 800 m AGL | 2/10 | 1200 m+ for full score |
| Thermal quality (CAPE + lapse rate) | 2/10 | Penalty if CAPE > 800 J/kg |
| Precipitation probability | 2/10 | Penalty above 20 % |
| Total cloud cover < 70 % | 1/10 | |

### Soaring (ridge / dynamic)

Suitable for coastal or ridge sites where pilots use orographic lift.
Wind direction and consistent speed are paramount.

| Criterion | Weight | Notes |
|---|---|---|
| Wind direction correct | 4/10 | Highest weight |
| Wind speed 10–20 kt | 2/10 | Sweet-spot range |
| Gusts ≤ 30 kt | 1/10 | |
| Cloud base > 400 m AGL | 1/10 | |
| Precipitation probability | 2/10 | |
| Total cloud cover < 80 % | 1/10 | |

### Aerotow

Suitable for flat-land tow sites. Wind direction is a preference rather than
a hard requirement; calm, predictable conditions matter most.

| Criterion | Weight | Notes |
|---|---|---|
| Wind direction correct | 1/10 | Preferred but not critical |
| Wind speed ≤ 15 kt | 3/10 | Calm preferred for safe tow |
| Gusts ≤ 18 kt | 2/10 | Critical — turbulence on tow is dangerous |
| Cloud base > 300 m AGL | 2/10 | |
| Precipitation probability | 2/10 | Stricter — penalty above 10 % |
| Total cloud cover < 50 % | 1/10 | |

---

## Multi-Model Ensemble

Each model is fetched and scored independently. The displayed score is the
**unweighted average** across all configured models.

```
daily_score = mean(ecmwf_score, icon_score, …)
```

The individual model scores are shown in the ranking table (small text below
the coloured badge) and in the detail chart title line
(`ecmw: 4.2  icon: 6.0`). Large disagreement between models (e.g. one says
fly, the other says no-go) should be treated as forecast uncertainty — the day
is marginal regardless of the ensemble mean.

---

## Reading the Plots

### Site Detail Chart (3-row figure)

One figure per site, N columns (one per forecast day).

**Row 1 — Wind**

```
▓▓▓▓▓▓  bars: wind speed in knots
  ▼ ▼ ▼  gusts line (dashed)
──────── orange dashed = 18 kt warning
──────── red dashed    = 25 kt danger
```

- **Green bar** = wind direction is correct for this site
- **Red bar** = wind direction is wrong — the site will not work
- **Gusts above the orange line** = challenging, expect turbulence near launch
- **Gusts above the red line** = dangerous, do not fly

The column title shows the date, verdict and ensemble score, plus the
per-model breakdown (`ecmw: 4.2  icon: 6.0`).

**Row 2 — Cloud Base and Boundary Layer**

```
░░░░░░░░  blue fill = cloud base AGL (LCL estimate, metres)
  ●─●─●   orange line = boundary layer height (m AGL)
  - - -   red dashed  = 500 m AGL
  ─ ─ ─   green dashed = 800 m AGL
```

- **Blue fill below the red line**: cloud base under 500 m — very limited
  flying, cloud-flying risk
- **Blue fill between red and green**: 500–800 m — marginal, short flights
- **Blue fill above the green line**: > 800 m — usable for XC thermalling
- **Orange BL line rising steeply** through the morning = thermals are
  developing; where BL and cloud base converge is where cumulus clouds will
  form

**Row 3 — CAPE and Precipitation**

```
▓▓▓▓▓▓  red bars  = CAPE (J/kg, left axis)
  ■─■─■  blue line = precipitation probability % (right axis)
  - - -  tomato dashed = 300 J/kg
  ─ ─ ─  red dashed    = 800 J/kg (overdevelopment threshold)
  ·····  blue dotted   = 20 % precip probability warning
```

- **Short red bars (< 200 J/kg)**: stable day — if other parameters are good,
  a soaring day is possible but thermalling will be weak
- **Red bars between the two dashed lines (200–800 J/kg)**: sweet spot for
  thermalling — meaningful thermals without overdevelopment risk
- **Red bars above the upper dashed line (> 800 J/kg)**: overdevelopment and
  Cu-nim risk — score is penalised
- **Blue line above 20 %**: increasing shower risk — treat the day with caution
- **Blue line near 80–100 %**: rain almost certain during the flying window

### Skew-T Log-P Sounding

One plot per flying-window hour for a chosen site and date.

```
Vertical axis:  atmospheric pressure (hPa), relabelled with altitude (m ASL)
Horizontal axis: temperature (°C), skewed 45° to the right

Red line   = temperature profile
Green line = dew point profile
Navy barbs = wind speed and direction at each pressure level
```

**How to read it for paragliding:**

- **Temperature–dew point spread**: the gap between red and green lines. A large
  gap (dry air) = high cloud base. Lines converging = clouds forming at that
  level.
- **Kink or isothermal layer in the red line (temperature inversion)**: where
  temperature stops falling or increases with altitude. Thermals cannot penetrate
  an inversion — it acts as a ceiling.
- **Dry adiabats (orange, dashed)**: the path a dry thermal parcel would follow
  if it rose from the surface. Where the red environmental temperature line crosses
  a dry adiabat from right to left = the lifting condensation level = cloud base.
- **Moist adiabats (green, dashed)**: the path inside a cloud. Diverging from dry
  adiabats = latent heat release = self-sustaining convection.
- **Wind barbs**: each barb symbol shows direction (the barb points into the wind)
  and speed (full barb = 10 kt, half barb = 5 kt, pennant = 50 kt). Backing with
  altitude (veering anti-clockwise) can indicate an approaching front. Strong
  directional shear between launch altitude and flying altitude means turbulent
  conditions.

### Ranking Table

Sites are sorted by **best consecutive flyable-days streak** (score ≥ 6), then
by average score over the full forecast window.

| Column | Description |
|---|---|
| Streak | Number of consecutive flyable days in the forecast (green ≥ 3d, amber 1–2d, grey 0d) |
| Best window | Start date of the best streak |
| Avg | Mean ensemble score across all forecast days |
| Per-day cells | Coloured badge = ensemble score; small text below = per-model scores |
| Wind kt | Mean wind speed over flying window (all days) |
| Gusts kt | Mean gust speed |
| CB m | Mean cloud base AGL (m) |
| CAPE | Mean CAPE (J/kg) |
| PP % | Mean precipitation probability |
