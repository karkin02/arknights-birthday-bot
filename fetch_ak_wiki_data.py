"""
Arknights Global Birthday Bot - Data Fetcher (Wiki Source)
--------------------------------------------------------------
Fetches BOTH operator birthdays AND full operator artwork from the
Arknights Terra Wiki's API in a single run, filtered to Global (EN)
operators only.

Sources:
- Birthdays: Characters table (matched via _pageName, since the
  'name' field there stores each character's real/lore name rather
  than their operator codename).
- Art: Full-body character artwork, resolved via "File:{OperatorName}.png"
  (the default splash art file, NOT the small icon).

Outputs:
- birthdays.json     ->  {"OperatorName": "MM-DD"}
- operator_art.json  ->  {"OperatorName": "https://...png"}  (full art)

Run:
    pip install requests
    python fetch_ak_wiki_data.py
"""

import re
import json
import requests

API_URL = "https://arknights.wiki.gg/api.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12
}

BIRTHDAY_OUTPUT_FILE = "data/birthdays.json"
ART_OUTPUT_FILE = "data/operator_art.json"
IMAGE_BATCH_SIZE = 50


# ------------------------------------------------------------------
# Shared helper: paginate through Cargo query results
# ------------------------------------------------------------------
def fetch_all_cargo_rows(tables: str, fields: str, where: str = None) -> list:
    rows = []
    offset = 0
    while True:
        params = {
            "action": "cargoquery",
            "format": "json",
            "tables": tables,
            "fields": fields,
            "limit": "500",
            "offset": str(offset),
        }
        if where:
            params["where"] = where
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        batch = resp.json().get("cargoquery", [])
        if not batch:
            break
        rows.extend(batch)
        offset += 500
        if len(batch) < 500:
            break
    return rows


def is_valid_operator_name(name: str) -> bool:
    """Filter out alt forms (e.g. 'Amiya (Guard)') and placeholder entries."""
    return "(" not in name and "Reserve Operator" not in name


def get_global_operator_names() -> list:
    """Return operator codenames where isCN = False (released on Global)."""
    rows = fetch_all_cargo_rows("Operators", "name,isCN")
    names = [row["title"]["name"] for row in rows if row["title"].get("isCN") == "0"]
    return [n for n in names if is_valid_operator_name(n)]


# ------------------------------------------------------------------
# BIRTHDAYS
# ------------------------------------------------------------------
def convert_date(bday_str: str):
    """Converts 'December 23rd, 1083' or 'March 3rd' into 'MM-DD'."""
    if not bday_str:
        return None
    match = re.match(r"([A-Za-z]+)\s+(\d+)(st|nd|rd|th)?", bday_str)
    if not match:
        return None
    month_name, day = match.group(1), int(match.group(2))
    month = MONTHS.get(month_name)
    if not month:
        return None
    return f"{month:02d}-{day:02d}"


def build_character_birthday_map() -> dict:
    """Map {operator_codename: 'Month Dayth'} using the _pageName trick."""
    rows = fetch_all_cargo_rows("Characters", "_pageName,birthdate")
    birthday_map = {}
    for row in rows:
        info = row["title"]
        page_name = info.get("_pageName", "")
        bday_raw = info.get("birthdate", "")
        op_name = page_name.replace("/Story", "")
        if bday_raw:
            birthday_map[op_name] = bday_raw
    return birthday_map


def build_birthday_dataset(global_names: list) -> dict:
    print("Fetching Characters table (birthdates)...")
    birthday_map = build_character_birthday_map()
    print(f"Found {len(birthday_map)} character birthdate entries.")

    dataset = {}
    for name in global_names:
        bday = convert_date(birthday_map.get(name))
        if bday:
            dataset[name] = bday

    print(f"Birthday dataset: {len(dataset)} Global operators.")
    return dataset


# ------------------------------------------------------------------
# FULL OPERATOR ART (not icons)
# ------------------------------------------------------------------
def batch_resolve_image_urls(file_titles: list) -> dict:
    """Resolve actual hosted image URLs for a list of File: titles, batched."""
    url_map = {}
    for i in range(0, len(file_titles), IMAGE_BATCH_SIZE):
        chunk = file_titles[i : i + IMAGE_BATCH_SIZE]
        params = {
            "action": "query",
            "format": "json",
            "titles": "|".join(chunk),
            "prop": "imageinfo",
            "iiprop": "url",
        }
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
        for page in pages.values():
            title = page.get("title")
            imageinfo = page.get("imageinfo")
            if imageinfo:
                url_map[title] = imageinfo[0]["url"]
    return url_map


def build_art_dataset(global_names: list) -> dict:
    """
    Full-body default splash art is hosted under "File:{OperatorName}.png"
    on the wiki (distinct from the small icon file "File:{OperatorName} icon.png").
    """
    print("Resolving full operator artwork URLs...")
    file_titles = [f"File:{name}.png" for name in global_names]
    resolved_urls = batch_resolve_image_urls(file_titles)

    dataset = {}
    for name in global_names:
        key = f"File:{name}.png"
        image_url = resolved_urls.get(key)
        if image_url:
            dataset[name] = image_url

    print(f"Art dataset: {len(dataset)} operators with full artwork.")
    return dataset


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
if __name__ == "__main__":
    print("Fetching Global operator list...")
    global_names = get_global_operator_names()
    print(f"Found {len(global_names)} Global operator entries.\n")

    birthday_data = build_birthday_dataset(global_names)
    with open(BIRTHDAY_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(birthday_data, f, indent=2, ensure_ascii=False)
    print(f"Saved birthdays to {BIRTHDAY_OUTPUT_FILE}\n")

    art_data = build_art_dataset(global_names)
    with open(ART_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(art_data, f, indent=2, ensure_ascii=False)
    print(f"Saved art to {ART_OUTPUT_FILE}")
