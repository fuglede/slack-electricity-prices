import requests
from datetime import datetime
import json
import os
import pickle
import statistics
import sys
from zoneinfo import ZoneInfo
from typing import List, Optional, Tuple


LAST_UPDATE_FILE = "last_update"
ZONE = ZoneInfo("Europe/Copenhagen")


def get_last_update() -> Optional[datetime]:
    if not os.path.exists(LAST_UPDATE_FILE):
        return None
    with open(LAST_UPDATE_FILE, "rb") as f:
        return pickle.load(f)


def set_last_update(update_time: datetime) -> None:
    with open(LAST_UPDATE_FILE, "wb") as f:
        pickle.dump(update_time, f)


def get_latest_data_date() -> Tuple[int, int, int]:
    url = 'https://api.energidataservice.dk/dataset/Elspotprices?limit=1&filter={"PriceArea":"DK2"}'
    result = requests.get(url).json()
    date_string = result["records"][0]["HourDK"]
    # Example date_string to be parsed: "2022-09-17T23:00:00"
    year, month, day = map(int, date_string.split("T")[0].split("-"))
    return datetime(year, month, day)


def update_available() -> bool:
    # Only update if this is a new day since last we updated
    last_update = get_last_update()
    if not last_update:
        return True
    now = datetime.now(ZONE)
    if (
        last_update.year == now.year
        and last_update.month == now.month
        and last_update.day == now.day
    ):
        return False
    # Only update if there's a chance there's new data (which is normally posted around 12:30 Danish time)
    if now.hour < 12 or (now.hour == 12 and now.minute < 30):
        return False
    # Only update if the new data is for tomorrow
    latest_data_date = get_latest_data_date()
    return latest_data_date > now


def update(webhook_url: str) -> None:
    message_parts = []
    for price_area in ("DK1", "DK2"):
        prices = get_prices(price_area)
        message_parts.append(
            f"Tomorrow's electricity prices for {price_area}:\n{format_message(prices)}"
        )
    message = "\n\n".join(message_parts)
    post_message(webhook_url, message)
    set_last_update(datetime.now(ZONE))


def format_message(prices: List[Tuple[str, float]]) -> str:
    lowest_time, lowest_price = min(prices, key=lambda s: s[1])
    highest_time, highest_price = max(prices, key=lambda s: s[1])
    mean = statistics.mean(p[1] for p in prices)
    return f"Lowest price: {round(lowest_price)} DKK/MWh ({lowest_time})\nHighest price: {round(highest_price)} DKK/MWh ({highest_time})\nAverage price: {round(mean)} DKK/MWh"


def post_message(url: str, message: str) -> None:
    data = {"text": message}
    requests.post(
        url, data=json.dumps(data), headers={"Content-Type": "application/json"}
    )
    print(message)


def parse_price(record) -> float:
    # The DKK price is not updated on weekends, so we rely on the EUR one instead in those cases
    if r := record["SpotPriceDKK"] is not None:
        return r
    # Get a more or less up to date currency rate
    url = "https://cdn.jsdelivr.net/gh/fawazahmed0/currency-api@1/latest/currencies/eur/dkk.json"
    result = requests.get(url).json()
    dkk_per_eur = result["dkk"]
    return record["SpotPriceEUR"] * dkk_per_eur


def get_prices(price_area: str) -> List[Tuple[str, float]]:
    url = (
        "https://api.energidataservice.dk/dataset/Elspotprices?limit=24&filter={%22PriceArea%22:%22"
        + price_area
        + "%22}"
    )
    data = requests.get(url).json()
    return [(d["HourDK"], d["SpotPriceDKK"]) for d in data["records"]]


if __name__ == "__main__":
    if update_available():
        webhook_url = sys.argv[1]
        update(webhook_url)
