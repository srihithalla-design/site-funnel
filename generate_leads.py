"""
generate_leads.py

Pulls local businesses with NO website from Google Places API and writes
leads.csv. MERGES with any existing leads.csv instead of overwriting it --
businesses already in the file (matched by place_id) are left untouched,
so their demo_url / email / status never get wiped by a later run. Only
genuinely new businesses get appended.

SETUP (one-time, ~10 min):
1. Go to console.cloud.google.com -> create a project (free)
2. Enable "Places API (New)"
3. Create an API key (APIs & Services -> Credentials)
4. Places API Pro-tier SKUs (Text Search, Nearby Search) give 5,000 free
   events/month as of 2026 -- this script will use a tiny fraction of that.
5. pip install requests --break-system-packages
6. Set your API key below or as an env var: export GOOGLE_PLACES_API_KEY=xxxx
7. Edit SEARCH_QUERIES and run: python3 generate_leads.py

Output: leads.csv with columns:
  name, category, phone, address, rating, review_snippet, place_id, has_website, email, demo_url
"""

import os
import csv
import time
import requests

API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "PASTE_YOUR_KEY_HERE")

# Edit this list: one query per business type + area you're targeting.
# Once your first batch is mostly deployed, widen this to new towns/categories
# to keep fresh leads flowing in.
SEARCH_QUERIES = [
    "barber shop in Plainfield IL",
    "bakery in Plainfield IL",
    "auto detailing in Plainfield IL",
    "lawn care in Plainfield IL",
    "nail salon in Plainfield IL",
    "coffee shop in Shorewood IL",
    "barber shop in Oswego IL",
    "bakery in Romeoville IL",
]

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

FIELD_MASK_SEARCH = "places.id,places.displayName,places.formattedAddress,places.websiteUri"
FIELD_MASK_DETAILS = (
    "id,displayName,formattedAddress,nationalPhoneNumber,rating,"
    "reviews,websiteUri,primaryTypeDisplayName"
)

FIELDNAMES = ["name", "category", "phone", "address", "rating",
              "review_snippet", "place_id", "has_website", "email", "demo_url"]


def load_existing_leads():
    if not os.path.exists("leads.csv"):
        return {}, []
    with open("leads.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_place_id = {r["place_id"]: r for r in rows if r.get("place_id")}
    return by_place_id, rows


def search_places(query):
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": FIELD_MASK_SEARCH,
    }
    body = {"textQuery": query}
    resp = requests.post(SEARCH_URL, json=body, headers=headers, timeout=20)
    if resp.status_code != 200:
        print(f"  API error {resp.status_code}: {resp.text[:300]}")
    resp.raise_for_status()
    return resp.json().get("places", [])


def get_details(place_id):
    headers = {
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": FIELD_MASK_DETAILS,
    }
    resp = requests.get(DETAILS_URL.format(place_id=place_id), headers=headers, timeout=20)
    if resp.status_code != 200:
        print(f"  details API error {resp.status_code}: {resp.text[:300]}")
    resp.raise_for_status()
    return resp.json()


def main():
    if API_KEY == "PASTE_YOUR_KEY_HERE":
        raise SystemExit("Set GOOGLE_PLACES_API_KEY before running.")

    existing_by_id, existing_rows = load_existing_leads()
    print(f"Loaded {len(existing_rows)} existing leads from leads.csv (will not be touched).")

    new_rows = []
    seen_ids = set(existing_by_id.keys())
    total_found = 0
    total_with_website = 0
    total_already_known = 0

    for query in SEARCH_QUERIES:
        print(f"Searching: {query}")
        try:
            places = search_places(query)
        except requests.HTTPError as e:
            print(f"  skipped query ({e})")
            continue

        print(f"  {len(places)} results returned")
        total_found += len(places)

        for p in places:
            place_id = p.get("id")
            if not place_id:
                continue
            if place_id in seen_ids:
                if place_id in existing_by_id:
                    total_already_known += 1
                continue
            seen_ids.add(place_id)

            if p.get("websiteUri"):
                total_with_website += 1
                continue

            time.sleep(0.1)
            try:
                details = get_details(place_id)
            except requests.HTTPError:
                continue

            if details.get("websiteUri"):
                total_with_website += 1
                continue

            reviews = details.get("reviews", [])
            snippet = ""
            if reviews:
                snippet = reviews[0].get("text", {}).get("text", "")[:200]

            new_rows.append({
                "name": details.get("displayName", {}).get("text", ""),
                "category": details.get("primaryTypeDisplayName", {}).get("text", ""),
                "phone": details.get("nationalPhoneNumber", ""),
                "address": details.get("formattedAddress", ""),
                "rating": details.get("rating", ""),
                "review_snippet": snippet,
                "place_id": place_id,
                "has_website": "no",
                "email": "",
                "demo_url": "",
            })

    print(f"\nSummary: {total_found} places seen, {total_already_known} already in leads.csv, "
          f"{total_with_website} had a website, {len(new_rows)} brand-new leads added.")

    all_rows = existing_rows + new_rows

    with open("leads.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"leads.csv now has {len(all_rows)} total leads ({len(new_rows)} new this run).")


if __name__ == "__main__":
    main()
