"""
generate_leads.py

Pulls local businesses with NO website from Google Places API and writes leads.csv.

SETUP (one-time, ~10 min):
1. Go to console.cloud.google.com -> create a project (free)
2. Enable "Places API (New)"
3. Create an API key (APIs & Services -> Credentials)
4. Places API Pro-tier SKUs (Text Search, Nearby Search) give 5,000 free
   events/month as of 2026 -- this script will use a tiny fraction of that
   for a few hundred leads.
5. pip install requests --break-system-packages
6. Set your API key below or as an env var: export GOOGLE_PLACES_API_KEY=xxxx
7. Edit SEARCH_QUERIES and run: python3 generate_leads.py

Output: leads.csv with columns:
  name, category, phone, address, rating, review_snippet, place_id, has_website
(has_website is always "no" -- rows WITH a website are filtered out automatically)
"""

import os
import csv
import time
import requests

API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "PASTE_YOUR_KEY_HERE")

# Edit this list: one query per business type + area you're targeting.
# Keep it specific -- "barber shop in Plainfield IL" beats "business in Plainfield IL".
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


def search_places(query):
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": FIELD_MASK_SEARCH,
    }
    body = {"textQuery": query}
    resp = requests.post(SEARCH_URL, json=body, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json().get("places", [])


def get_details(place_id):
    headers = {
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": FIELD_MASK_DETAILS,
    }
    resp = requests.get(DETAILS_URL.format(place_id=place_id), headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json()


def main():
    if API_KEY == "PASTE_YOUR_KEY_HERE":
        raise SystemExit("Set GOOGLE_PLACES_API_KEY before running.")

    rows = []
    seen_ids = set()

    for query in SEARCH_QUERIES:
        print(f"Searching: {query}")
        try:
            places = search_places(query)
        except requests.HTTPError as e:
            print(f"  skipped ({e})")
            continue

        for p in places:
            place_id = p.get("id")
            if not place_id or place_id in seen_ids:
                continue
            seen_ids.add(place_id)

            # Skip anything that already has a website -- not our lead
            if p.get("websiteUri"):
                continue

            time.sleep(0.1)  # be polite to the API
            try:
                details = get_details(place_id)
            except requests.HTTPError:
                continue

            if details.get("websiteUri"):
                continue  # double-check at the details level

            reviews = details.get("reviews", [])
            snippet = ""
            if reviews:
                snippet = reviews[0].get("text", {}).get("text", "")[:200]

            rows.append({
                "name": details.get("displayName", {}).get("text", ""),
                "category": details.get("primaryTypeDisplayName", {}).get("text", ""),
                "phone": details.get("nationalPhoneNumber", ""),
                "address": details.get("formattedAddress", ""),
                "rating": details.get("rating", ""),
                "review_snippet": snippet,
                "place_id": place_id,
                "has_website": "no",
                "email": "",  # fill manually or via a separate email-finder step
                "demo_url": "",  # filled in by generate_demo_sites.py
            })

    with open("leads.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [
            "name", "category", "phone", "address", "rating",
            "review_snippet", "place_id", "has_website", "email", "demo_url"
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. {len(rows)} no-website leads written to leads.csv")
    print("Next: fill in the 'email' column (a business's site-less listing usually")
    print("still has a phone -- a quick reverse lookup or their Facebook/Instagram")
    print("bio often has an email; this is the one place a little human judgment")
    print("speeds things up, but it's optional -- you can also mail-merge by phone")
    print("via a texting API instead of email if you'd rather stay 100% address-free.")


if __name__ == "__main__":
    main()
