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
    return datetime(year, month, day, tzinfo=ZONE)


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


def update(webhook_urls: list[str]) -> None:
    message_parts = []
    for price_area in ("DK1", "DK2"):
        prices = get_prices(price_area)
        message_parts.append(
            f"Tomorrow's electricity prices for {price_area}:\n{format_message(prices)}"
        )
    message = "\n\n".join(message_parts)
    print(message)
    for webhook_url in webhook_urls:
        # One of them failing shouldn't affect the other ones
        try:
            print(f"Posting to {webhook_url}")
            post_message(webhook_url, message)
        except Exception as e:
            print(e)
    set_last_update(datetime.now(ZONE))


def format_message(prices: List[Tuple[str, float]]) -> str:
    lowest_time, lowest_price = min(prices, key=lambda s: s[1])
    highest_time, highest_price = max(prices, key=lambda s: s[1])
    mean = statistics.mean(p[1] for p in prices)
    return f"Lowest price: {lowest_price/1000:.2f} DKK/kWh ({lowest_time})\nHighest price: {highest_price/1000:.2f} DKK/kWh ({highest_time})\nAverage price: {mean/1000:.2f} DKK/kWh"


def post_message(url: str, message: str) -> None:
    # Slack?
    if url.startswith('https://hooks.slack.com'):
        data = {"text": message}
        requests.post(
            url, data=json.dumps(data), headers={"Content-Type": "application/json"}
        )
    # Something else? Must be Mastodon!
    else:
        host_instance, token = url.split('?')
        headers = {'Authorization': 'Bearer ' + token}
        data = {'status': message, 'visibility': 'public'}
        requests.post(
            url=host_instance + '/api/v1/statuses', data=data, headers=headers)


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
        webhook_urls = sys.argv[1:]
        update(webhook_urls)
