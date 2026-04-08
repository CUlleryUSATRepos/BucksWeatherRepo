import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from dateutil import parser as dtparser


# =========================================================
# CONFIG
# =========================================================

USER_AGENT = "BucksWeatherScript/1.0 (contact: your_email@example.com)"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/geo+json"}

LOCAL_TZ = ZoneInfo("America/New_York")

LOCATIONS = {
    "Doylestown": {"lat": 40.3101, "lon": -75.1299},
    "Quakertown": {"lat": 40.4418, "lon": -75.3416},
    "Levittown": {"lat": 40.1551, "lon": -74.8288},
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# =========================================================
# HELPERS
# =========================================================

def get_json(url, params=None):
    time.sleep(0.25)
    r = SESSION.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def sentence_case(text):
    if not text:
        return ""
    return text[0].upper() + text[1:]

def parse_iso(dt):
    return dtparser.isoparse(dt)


def to_local(dt):
    return dt.astimezone(LOCAL_TZ)


def to_utc_z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def c_to_f(c):
    if c is None or pd.isna(c):
        return None
    return c * 9 / 5 + 32


def meters_per_second_to_mph(ms):
    if ms is None or pd.isna(ms):
        return None
    return ms * 2.23694


def describe_range(vals, unit="°F", digits=0):
    vals = [v for v in vals if v is not None and pd.notna(v)]
    if not vals:
        return ""
    if digits == 0:
        return f"{round(min(vals))}{unit} to {round(max(vals))}{unit}"
    return f"{round(min(vals), digits)}{unit} to {round(max(vals), digits)}{unit}"


def safe_mean(series):
    series = pd.to_numeric(series, errors="coerce")
    if series.dropna().empty:
        return None
    return series.mean()


def parse_wind_speed_to_max_mph(text):
    if not text or pd.isna(text):
        return None

    nums = re.findall(r"\d+", str(text))
    if not nums:
        return None

    nums = [int(n) for n in nums]
    return max(nums)


def mode_or_blank(series):
    series = series.dropna().astype(str)
    if series.empty:
        return ""
    m = series.mode()
    if m.empty:
        return ""
    return m.iloc[0]


def comfort_label(avg_dewpoint_f):
    if avg_dewpoint_f is None or pd.isna(avg_dewpoint_f):
        return None

    if avg_dewpoint_f < 50:
        return "comfortable"
    elif avg_dewpoint_f < 60:
        return "fairly comfortable"
    elif avg_dewpoint_f < 65:
        return "a little humid"
    elif avg_dewpoint_f < 70:
        return "muggy"
    return "very humid"


def normalize_condition_text(text):
    if not text or pd.isna(text):
        return None

    t = str(text).strip()

    replacements = {
        "Mostly Sunny": "mostly sunny",
        "Sunny": "sunny",
        "Partly Sunny": "partly sunny",
        "Partly Cloudy": "partly cloudy",
        "Mostly Cloudy": "mostly cloudy",
        "Cloudy": "cloudy",
        "Clear": "clear",
        "Mostly Clear": "mostly clear",
        "Chance Showers And Thunderstorms": "a chance of showers and thunderstorms",
        "Chance Showers": "a chance of showers",
        "Slight Chance Showers": "a slight chance of showers",
        "Showers Likely": "showers likely",
        "Rain": "rain",
        "Chance Rain Showers": "a chance of rain showers",
        "Slight Chance Rain Showers": "a slight chance of rain showers",
    }

    return replacements.get(t, t.lower())


def summarize_conditions_by_location(day_df):
    loc_conditions = {}

    for loc in sorted(day_df["location"].dropna().unique()):
        subset = day_df[day_df["location"] == loc]
        condition = mode_or_blank(subset["short_forecast"])
        condition = normalize_condition_text(condition)
        if condition:
            loc_conditions[loc] = condition

    if not loc_conditions:
        return ""

    unique_conditions = list(dict.fromkeys(loc_conditions.values()))

    if len(unique_conditions) == 1:
        return sentence_case(unique_conditions[0])

    condition_to_locs = {}
    for loc, cond in loc_conditions.items():
        condition_to_locs.setdefault(cond, []).append(loc)

    if len(condition_to_locs) == 2:
        parts = []
        for cond, locs in condition_to_locs.items():
            if len(locs) == 1:
                parts.append(f"{cond} in {locs[0]}")
            elif len(locs) == 2:
                parts.append(f"{cond} in {locs[0]} and {locs[1]}")
            else:
                parts.append(f"{cond} across Bucks County")
        return sentence_case(", with ".join(parts))

    parts = []
    ordered_locs = ["Doylestown", "Quakertown", "Levittown"]
    for loc in ordered_locs:
        cond = loc_conditions.get(loc)
        if cond:
            parts.append(f"{cond} in {loc}")

    if not parts:
        return ""
    if len(parts) == 1:
        return sentence_case(parts[0])
    if len(parts) == 2:
        return f"{sentence_case(parts[0])} and {parts[1]}"
    return f"{parts[0].capitalize()}, {parts[1]}, and {parts[2]}"


def find_driest_window(hourly_df, start_hour=6, end_hour=20):
    df = hourly_df.copy()
    df["hour"] = df["time"].dt.hour
    df = df[(df["hour"] >= start_hour) & (df["hour"] < end_hour)].copy()

    if df.empty:
        return None

    summary = (
        df.groupby("time", as_index=False)
        .agg(
            avg_temp=("temp", "mean"),
            avg_pop=("precip_chance", "mean"),
            max_wind=("wind_speed_mph", "max"),
        )
    )

    summary["score"] = (
        summary["avg_pop"].fillna(0) * 2
        + summary["max_wind"].fillna(0) * 0.5
        + (summary["avg_temp"] - 70).abs() * 0.6
    )

    if summary.empty:
        return None

    best = summary.sort_values("score").iloc[0]
    return {
        "time": best["time"],
        "avg_temp": best["avg_temp"],
        "avg_pop": best["avg_pop"],
        "max_wind": best["max_wind"],
    }


# =========================================================
# DATA COLLECTION
# =========================================================

def collect_location_data(name, lat, lon):
    point = get_json(f"https://api.weather.gov/points/{lat},{lon}")["properties"]

    return {
        "name": name,
        "point": point,
        "hourly": get_json(point["forecastHourly"]),
        "forecast": get_json(point["forecast"]),
        "grid": get_json(point["forecastGridData"]),
        "stations": get_json(point["observationStations"])["features"],
    }


def build_hourly_df(payload):
    rows = []

    for p in payload["hourly"]["properties"]["periods"][:72]:
        dt = parse_iso(p["startTime"])

        rows.append({
            "location": payload["name"],
            "time": to_local(dt),
            "temp": p.get("temperature"),
            "precip_chance": (
                p.get("probabilityOfPrecipitation", {}).get("value")
                if p.get("probabilityOfPrecipitation") else None
            ),
            "wind_speed_text": p.get("windSpeed"),
            "wind_speed_mph": parse_wind_speed_to_max_mph(p.get("windSpeed")),
            "wind_direction": p.get("windDirection"),
            "short_forecast": p.get("shortForecast"),
        })

    return pd.DataFrame(rows)


# =========================================================
# OBSERVATIONS
# =========================================================

def pick_station(payload):
    return payload["stations"][0]["properties"]["stationIdentifier"]


def get_obs(station, start=None, end=None, limit=500):
    params = {"limit": limit}
    if start is not None:
        params["start"] = to_utc_z(start)
    if end is not None:
        params["end"] = to_utc_z(end)

    return get_json(
        f"https://api.weather.gov/stations/{station}/observations",
        params=params,
    )["features"]


def obs_to_df(features, loc):
    rows = []

    for f in features:
        p = f["properties"]
        if not p.get("timestamp"):
            continue

        dt = parse_iso(p["timestamp"])

        temp_c = p.get("temperature", {}).get("value")
        dew_c = p.get("dewpoint", {}).get("value")
        humidity = p.get("relativeHumidity", {}).get("value")
        wind_ms = p.get("windSpeed", {}).get("value")
        text_desc = p.get("textDescription")

        rows.append({
            "location": loc,
            "time": to_local(dt),
            "temp": c_to_f(temp_c),
            "dewpoint_f": c_to_f(dew_c),
            "relative_humidity": humidity,
            "wind_speed_mph": meters_per_second_to_mph(wind_ms),
            "text_description": text_desc,
        })

    return pd.DataFrame(rows)


def get_latest_obs_row(payload):
    station = pick_station(payload)
    features = get_obs(station, limit=10)
    obs_df = obs_to_df(features, payload["name"])

    if obs_df.empty:
        return None

    obs_df = obs_df.sort_values("time", ascending=False)
    latest = obs_df.iloc[0].to_dict()
    latest["station"] = station
    return latest


# =========================================================
# ALERTS
# =========================================================

def get_alerts_for_location(lat, lon):
    data = get_json(
        "https://api.weather.gov/alerts/active",
        params={"point": f"{lat},{lon}"}
    )
    features = data.get("features", [])

    rows = []
    for f in features:
        p = f.get("properties", {})
        rows.append({
            "event": p.get("event"),
            "headline": p.get("headline"),
            "severity": p.get("severity"),
            "certainty": p.get("certainty"),
            "urgency": p.get("urgency"),
            "area_desc": p.get("areaDesc"),
            "effective": p.get("effective"),
            "expires": p.get("expires"),
            "description": p.get("description"),
            "instruction": p.get("instruction"),
        })

    return rows


# =========================================================
# SUMMARY BUILDERS
# =========================================================

def build_comparison(hourly_df, payloads):
    all_rows = []

    for loc, payload in payloads.items():
        station = pick_station(payload)

        start = hourly_df["time"].min() - timedelta(days=7)
        end = hourly_df["time"].max() - timedelta(days=7)

        obs = get_obs(station, start, end)
        obs_df = obs_to_df(obs, loc)

        if obs_df.empty:
            continue

        for _, row in hourly_df[hourly_df["location"] == loc].iterrows():
            target = row["time"] - timedelta(days=7)

            obs_df["diff"] = (obs_df["time"] - target).abs()
            best = obs_df.sort_values("diff").head(1)

            if best.empty:
                continue

            obs_temp = best.iloc[0]["temp"]
            if obs_temp is None:
                continue

            all_rows.append({
                "location": loc,
                "time": row["time"],
                "forecast_temp": row["temp"],
                "last_week_temp": obs_temp,
            })

    return pd.DataFrame(all_rows)


def build_daily_summary(hourly_df):
    df = hourly_df.copy()
    df["date"] = df["time"].dt.date
    df["hour"] = df["time"].dt.hour

    daily_rows = []

    for d in sorted(df["date"].unique())[:3]:
        day = df[df["date"] == d].copy()

        day_hours = day[(day["hour"] >= 6) & (day["hour"] < 18)].copy()
        night_hours = day[(day["hour"] < 6) | (day["hour"] >= 18)].copy()

        highs = day_hours.groupby("location")["temp"].max().tolist()
        lows = night_hours.groupby("location")["temp"].min().tolist()

        avg_day_pop = safe_mean(day_hours["precip_chance"])
        max_day_pop = pd.to_numeric(day_hours["precip_chance"], errors="coerce").max()
        max_night_pop = pd.to_numeric(night_hours["precip_chance"], errors="coerce").max()

        max_day_wind = pd.to_numeric(day_hours["wind_speed_mph"], errors="coerce").max()
        max_night_wind = pd.to_numeric(night_hours["wind_speed_mph"], errors="coerce").max()

        day_condition_text = summarize_conditions_by_location(day_hours)
        night_condition_text = summarize_conditions_by_location(night_hours)

        daily_rows.append({
            "date": d,
            "day_name": pd.to_datetime(d).strftime("%A"),
            "high_range": describe_range(highs),
            "low_range": describe_range(lows),
            "avg_day_pop": avg_day_pop,
            "max_day_pop": max_day_pop,
            "max_night_pop": max_night_pop,
            "max_day_wind": max_day_wind,
            "max_night_wind": max_night_wind,
            "day_condition_text": day_condition_text,
            "night_condition_text": night_condition_text,
        })

    return pd.DataFrame(daily_rows)


def build_dewpoint_summary(payloads):
    rows = []
    now_local = datetime.now(LOCAL_TZ)

    for loc, payload in payloads.items():
        dew_values = payload["grid"]["properties"].get("dewpoint", {}).get("values", [])

        for item in dew_values:
            valid = item.get("validTime")
            val_c = item.get("value")

            if valid is None:
                continue

            start_str, _duration = valid.split("/")
            start_dt = to_local(parse_iso(start_str))

            if start_dt < now_local:
                continue

            rows.append({
                "location": loc,
                "time": start_dt,
                "dewpoint_f": c_to_f(val_c),
            })

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("time")



def build_day_sentence(row):
    condition = row["day_condition_text"]
    pop = row["max_day_pop"]
    wind = row["max_day_wind"]

    if condition:
        sentence = f"{row['day_name']}: {condition}, with highs ranging from {row['high_range']}."
    else:
        sentence = f"{row['day_name']}: Highs ranging from {row['high_range']}."

    if pd.notna(pop) and pop >= 20:
        sentence += f" Rain chances may reach about {round(pop)}%."

    if pd.notna(wind) and wind >= 20:
        sentence += f" Winds could gust into the {round(wind)} mph range."

    return sentence


def build_night_sentence(row):
    condition = row["night_condition_text"]
    pop = row["max_night_pop"]
    wind = row["max_night_wind"]

    if condition:
        sentence = f"{row['day_name']} Night: {condition}, with lows ranging from {row['low_range']}."
    else:
        sentence = f"{row['day_name']} Night: Lows ranging from {row['low_range']}."

    if pd.notna(pop) and pop >= 20:
        sentence += f" Rain chances may reach about {round(pop)}% overnight."

    if pd.notna(wind) and wind >= 20:
        sentence += f" Winds may still run up to around {round(wind)} mph."

    return sentence


def build_story(hourly_df, comp_df, current_df, alerts_df, dew_df):
    lines = []
    lines.append("Here’s what the next three days are looking like in Bucks County.\n")

    if not current_df.empty:
        avg_temp = safe_mean(current_df["temp"])
        avg_humidity = safe_mean(current_df["relative_humidity"])
        sky = mode_or_blank(current_df["text_description"])

        parts = []
        if avg_temp is not None:
            parts.append(f"temperatures are averaging around {round(avg_temp)}°F")
        if sky:
            parts.append(f"with {sky.lower()} conditions")
        if avg_humidity is not None:
            parts.append(f"humidity is averaging about {round(avg_humidity)}%")

        if parts:
            lines.append(
                "Right now across Doylestown, Quakertown and Levittown, "
                + ", ".join(parts)
                + ".\n"
            )

    if alerts_df.empty:
        lines.append("There are currently no active weather alerts for the three Bucks County locations in this pull.\n")
    else:
        unique_alerts = alerts_df["event"].dropna().unique().tolist()
        if unique_alerts:
            lines.append(
                f"There are active weather alerts in effect, including: {', '.join(unique_alerts)}.\n"
            )

    daily_df = build_daily_summary(hourly_df)
    for _, row in daily_df.iterrows():
        lines.append(build_day_sentence(row))
        lines.append(build_night_sentence(row) + "\n")

    if not comp_df.empty:
        comp_df = comp_df.copy()
        comp_df["date"] = comp_df["time"].dt.date
        comp_df["hour"] = comp_df["time"].dt.hour

        day_df = comp_df[(comp_df["hour"] >= 6) & (comp_df["hour"] < 18)].copy()
        night_df = comp_df[(comp_df["hour"] < 6) | (comp_df["hour"] >= 18)].copy()

        this_week_highs = day_df.groupby(["location", "date"])["forecast_temp"].max().reset_index()
        last_week_highs = day_df.groupby(["location", "date"])["last_week_temp"].max().reset_index()

        this_week_lows = night_df.groupby(["location", "date"])["forecast_temp"].min().reset_index()
        last_week_lows = night_df.groupby(["location", "date"])["last_week_temp"].min().reset_index()

        this_week_day_avg = this_week_highs["forecast_temp"].mean()
        last_week_day_avg = last_week_highs["last_week_temp"].mean()

        this_week_night_avg = this_week_lows["forecast_temp"].mean()
        last_week_night_avg = last_week_lows["last_week_temp"].mean()

        if pd.notna(this_week_day_avg) and pd.notna(last_week_day_avg):
            lines.append(
                f"Across Doylestown, Quakertown and Levittown, the average daytime high over the next three days is {round(this_week_day_avg)}°F, compared with {round(last_week_day_avg)}°F during the same stretch last week."
            )

        if pd.notna(this_week_night_avg) and pd.notna(last_week_night_avg):
            lines.append(
                f"The average overnight low is {round(this_week_night_avg)}°F, compared with {round(last_week_night_avg)}°F last week."
            )

    if not dew_df.empty:
        avg_dew = safe_mean(dew_df["dewpoint_f"])
        comfort = comfort_label(avg_dew)
        if avg_dew is not None and comfort is not None:
            lines.append(
                f"Average dew points over the next 72 hours come in around {round(avg_dew)}°F, which suggests {comfort} conditions overall."
            )

    best_window = find_driest_window(hourly_df)
    if best_window is not None:
        best_time = pd.to_datetime(best_window["time"])
        hour = best_time.strftime("%I").lstrip("0") or "0"
        time_text = f"{best_time.strftime('%A')} around {hour} {best_time.strftime('%p')}"
        pop_val = 0 if pd.isna(best_window["avg_pop"]) else round(best_window["avg_pop"])
        lines.append(
            f"One of the better outdoor windows looks to be {time_text}, when temperatures should average about {round(best_window['avg_temp'])}°F with rain chances near {pop_val}%."
        )

    return "\n".join(lines)


# =========================================================
# PIPELINE
# =========================================================

def run_weather_pipeline():
    payloads = {}
    hourly_frames = []
    current_rows = []
    alert_rows = []

    for loc, coords in LOCATIONS.items():
        payload = collect_location_data(loc, coords["lat"], coords["lon"])
        payloads[loc] = payload

        hourly_frames.append(build_hourly_df(payload))

        latest_obs = get_latest_obs_row(payload)
        if latest_obs is not None:
            current_rows.append(latest_obs)

        alerts = get_alerts_for_location(coords["lat"], coords["lon"])
        for alert in alerts:
            alert["location"] = loc
            alert_rows.append(alert)

    hourly_df = pd.concat(hourly_frames, ignore_index=True)
    current_df = pd.DataFrame(current_rows)
    alerts_df = pd.DataFrame(alert_rows)

    if not alerts_df.empty:
        dedupe_cols = [c for c in ["event", "headline", "effective", "expires"] if c in alerts_df.columns]
        if dedupe_cols:
            alerts_df = alerts_df.drop_duplicates(subset=dedupe_cols).reset_index(drop=True)

    comp_df = build_comparison(hourly_df, payloads)
    dew_df = build_dewpoint_summary(payloads)
    daily_df = build_daily_summary(hourly_df)
    best_window = find_driest_window(hourly_df)
    story = build_story(hourly_df, comp_df, current_df, alerts_df, dew_df)

    return {
        "hourly_df": hourly_df,
        "current_df": current_df,
        "alerts_df": alerts_df,
        "comp_df": comp_df,
        "dew_df": dew_df,
        "daily_df": daily_df,
        "best_window": best_window,
        "story": story,
    }