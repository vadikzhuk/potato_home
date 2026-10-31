"""Today's weather from Open-Meteo (https://open-meteo.com): free, no API key needed.

Only what fits a small strip: the weather now, and today's high, low and chance of rain.
"""

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
TEXT_STYLE = "︎"  # asks the browser to draw the symbol as text, not as a colour emoji


def fetch(config: dict) -> dict:
    place = config["weather"]
    params = {
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "timezone": config["timezone"],
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": 1,
        "wind_speed_unit": "ms",
    }
    response = httpx.get(URL, params=params, timeout=15)
    response.raise_for_status()
    return parse(response.json(), place["name"])


def parse(raw: dict, place: str) -> dict:
    """Turn Open-Meteo's answer into what the page shows."""
    current = raw["current"]
    symbol, text = describe(current["weather_code"])
    daily = raw["daily"]

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
        "today": {
            "max": round(daily["temperature_2m_max"][0]),
            "min": round(daily["temperature_2m_min"][0]),
            "rain": daily["precipitation_probability_max"][0],
        },
    }


def describe(code: int) -> tuple[str, str]:
    symbol, text = CODES.get(code, ("?", f"Code {code}"))
    return symbol + TEXT_STYLE, text
