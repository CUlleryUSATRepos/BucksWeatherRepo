import json
from datetime import datetime
from weather_core import run_weather_pipeline
from pathlib import Path

def build_dashboard_json(results):
    hourly_df = results["hourly_df"]
    current_df = results["current_df"]
    alerts_df = results["alerts_df"]
    story = results["story"]

    # -------------------------
    # CURRENT CONDITIONS
    # -------------------------
    current = {}

    if not current_df.empty:
        current = {
            "avg_temp": round(current_df["temp"].mean()),
            "avg_humidity": round(current_df["relative_humidity"].mean()),
            "avg_wind": round(current_df["wind_speed_mph"].mean()),
            "conditions": current_df["text_description"].mode().iloc[0]
        }

    # -------------------------
    # ALERTS
    # -------------------------
    alerts = []

    if not alerts_df.empty:
        for _, row in alerts_df.iterrows():
            alerts.append({
                "event": row.get("event"),
                "headline": row.get("headline"),
                "severity": row.get("severity"),
                "effective": str(row.get("effective")),
                "expires": str(row.get("expires")),
            })

    # -------------------------
    # CHART DATA (KEY PART)
    # -------------------------
    chart = []

    grouped = hourly_df.groupby("time").agg({
        "temp": "mean",
        "precip_chance": "mean"
    }).reset_index()

    for _, row in grouped.iterrows():
        chart.append({
            "time": row["time"].isoformat(),
            "temp": round(row["temp"], 1) if row["temp"] is not None else None,
            "precip": round(row["precip_chance"], 1) if row["precip_chance"] is not None else None
        })

    # -------------------------
    # FINAL JSON
    # -------------------------
    dashboard = {
        "generated_at": datetime.now().isoformat(),
        "summary": story,
        "current": current,
        "alerts": alerts,
        "chart": chart
    }

    return dashboard


def main_build():
    print("Running full weather pipeline...")

    results = run_weather_pipeline()
    dashboard = build_dashboard_json(results)

    repo_root = Path(__file__).resolve().parent.parent
    output_path = repo_root / "data" / "dashboard" / "latest.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(dashboard, f, indent=2)

    print(f"Saved dashboard JSON to {output_path}")


if __name__ == "__main__":
    main_build()