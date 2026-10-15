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
import os
import sys
import time
import datetime
import json
import requests

API_URL = "https://arknights.wiki.gg/api.php"
HEADERS = {
    "User-Agent": "AKBirthdayBot/1.0 (Discord birthday bot; contact: https://github.com/karkin02)"
}

MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12
}

BIRTHDAY_OUTPUT_FILE = "data/birthdays.json"
ART_OUTPUT_FILE = "data/operator_art.json"
IMAGE_BATCH_SIZE = 50
PAGE_BATCH_SIZE = 20
VALID_BDAY = re.compile(r"^\d{2}-\d{2}$")
MONTH_RE = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?!\d)")


def get_with_retry(params, retries=5):
    for attempt in range(retries):
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)
        if resp.status_code in (429, 500, 502, 503, 504):
            ra = resp.headers.get("Retry-After", "")
            wait = int(ra) if ra.isdigit() else 5 * 2 ** attempt
            print(f"HTTP {resp.status_code}, retrying in {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError(f"Gave up after {retries} tries: HTTP {resp.status_code}")

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
def convert_date(bday_str):
    if not bday_str:
        return None
    m = MONTH_RE.search(bday_str)
    if not m:
        return None
    month, day = MONTHS[m.group(1)], int(m.group(2))
    try:
        datetime.date(2000, month, day)
    except ValueError:
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


def fetch_page_birthdates(names):
    """Fallback: read the birthdate field straight from each operator's wiki page."""
    result = {}
    for i in range(0, len(names), PAGE_BATCH_SIZE):
        chunk = names[i:i + PAGE_BATCH_SIZE]
        params = {
            "action": "query", "format": "json",
            "prop": "revisions", "rvprop": "content", "rvslots": "main",
            "redirects": "1", "titles": "|".join(chunk),
        }
        data = get_with_retry(params).json()
        for page in data.get("query", {}).get("pages", {}).values():
            rev = page.get("revisions")
            if not rev:
                continue
            text = rev[0]["slots"]["main"]["*"]
            m = re.search(r"\|\s*birthdate\s*=\s*([^\n|]*)", text)
            if m:
                result[page["title"]] = m.group(1).strip()
        time.sleep(1)
    return result


def load_existing(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def build_birthday_dataset(global_names):
    print("Fetching Characters table (birthdates)...")
    birthday_map = build_character_birthday_map()
    print(f"Found {len(birthday_map)} character birthdate entries.")

    fresh = {}
    for name in global_names:
        bday = convert_date(birthday_map.get(name))
        if bday:
            fresh[name] = bday

    still_missing = [n for n in global_names if n not in fresh]
    print(f"Checking wiki pages for {len(still_missing)} operators with no table entry...")
    for name, raw in fetch_page_birthdates(still_missing).items():
        bday = convert_date(raw)
        if bday:
            fresh[name] = bday
    
    gset = set(global_names)
    kept = {
        n: v for n, v in load_existing(BIRTHDAY_OUTPUT_FILE).items()
        if n in gset and n not in fresh and VALID_BDAY.match(str(v))
    }
    if kept:
        print(f"Kept {len(kept)} previous entries: {', '.join(kept)}")

    dataset = {**kept, **fresh}
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


def write_json_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
if __name__ == "__main__":
    global_names = get_global_operator_names()
    if not global_names:
        sys.exit("No Global operators returned; aborting.")
    print(f"Found {len(global_names)} Global operator entries.\n")

    birthday_data = build_birthday_dataset(global_names)
    art_data = build_art_dataset(global_names)

    missing_art = [n for n in birthday_data if n not in art_data]
    if missing_art:
        print(f"No art found for: {', '.join(missing_art)}")

    for path, new in [(BIRTHDAY_OUTPUT_FILE, birthday_data), (ART_OUTPUT_FILE, art_data)]:
        old = len(load_existing(path))
        if old and len(new) < old * 0.8:
            sys.exit(f"Refusing to overwrite {path}: {len(new)} new vs {old} existing.")

    write_json_atomic(BIRTHDAY_OUTPUT_FILE, birthday_data)
    write_json_atomic(ART_OUTPUT_FILE, art_data)
    print("Saved birthdays and art.")
