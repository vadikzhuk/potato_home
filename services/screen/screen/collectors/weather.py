"""Weather from Open-Meteo (https://open-meteo.com): free, no API key needed."""

from datetime import date

import httpx

URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes -> (symbol, description). The symbols are plain Unicode
# characters, so they show up even on old TV browsers without emoji fonts.
CODES = {
    0: ("☀", "Clear"),
    1: ("☀", "Mainly clear"),
    2: ("⛅", "Partly cloudy"),
    3: ("☁", "Overcast"),
    45: ("≋", "Fog"),
    48: ("≋", "Freezing fog"),
    51: ("☂", "Light drizzle"),
    53: ("☂", "Drizzle"),
    55: ("☂", "Heavy drizzle"),
    56: ("☂", "Freezing drizzle"),
    57: ("☂", "Freezing drizzle"),
    61: ("☂", "Light rain"),
    63: ("☂", "Rain"),
    65: ("☂", "Heavy rain"),
    66: ("☂", "Freezing rain"),
    67: ("☂", "Freezing rain"),
    71: ("❄", "Light snow"),
    73: ("❄", "Snow"),
    75: ("❄", "Heavy snow"),
    77: ("❄", "Snow grains"),
    80: ("☂", "Rain showers"),
    81: ("☂", "Rain showers"),
    82: ("☂", "Heavy showers"),
    85: ("❄", "Snow showers"),
    86: ("❄", "Snow showers"),
    95: ("⚡", "Thunderstorm"),
    96: ("⚡", "Thunderstorm, hail"),
    99: ("⚡", "Thunderstorm, hail"),
}
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TEXT_STYLE = "︎"  # asks the browser to draw the symbol as text, not as a colour emoji


def fetch(config: dict) -> dict:
    place = config["weather"]
    params = {
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "timezone": config["timezone"],
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
        "hourly": "temperature_2m,weather_code,precipitation_probability",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": 5,
        "wind_speed_unit": "ms",
    }
    response = httpx.get(URL, params=params, timeout=15)
    response.raise_for_status()
    return parse(response.json(), place["name"])


def parse(raw: dict, place: str) -> dict:
    """Turn Open-Meteo's answer into what the page shows."""
    current = raw["current"]
    symbol, text = describe(current["weather_code"])

    # Next 24 hours in 3-hour steps, starting after the current hour
    hourly = raw["hourly"]
    this_hour = current["time"][:13] + ":00"  # '2026-10-27T12:15' -> '2026-10-27T12:00'
    start = hourly["time"].index(this_hour) if this_hour in hourly["time"] else 0
    hours = []
    for i in range(start + 3, min(start + 25, len(hourly["time"])), 3):
        hours.append({
            "time": hourly["time"][i][11:16],
            "temp": round(hourly["temperature_2m"][i]),
            "symbol": describe(hourly["weather_code"][i])[0],
            "rain": hourly["precipitation_probability"][i],
        })

    daily = raw["daily"]
    days = []
    for i, day in enumerate(daily["time"]):
        days.append({
            "name": "Today" if i == 0 else DAY_NAMES[date.fromisoformat(day).weekday()],
            "symbol": describe(daily["weather_code"][i])[0],
            "max": round(daily["temperature_2m_max"][i]),
            "min": round(daily["temperature_2m_min"][i]),
            "rain": daily["precipitation_probability_max"][i],
        })

    return {
        "place": place,
        "now": {
            "temp": round(current["temperature_2m"]),
            "feels": round(current["apparent_temperature"]),
            "symbol": symbol,
            "text": text,
            "wind": round(current["wind_speed_10m"]),
            "humidity": current["relative_humidity_2m"],
        },
        "hours": hours,
        "days": days,
    }


def describe(code: int) -> tuple[str, str]:
    symbol, text = CODES.get(code, ("?", f"Code {code}"))
    return symbol + TEXT_STYLE, text
