"""
generate_demo_sites.py

Reads leads.csv (from generate_leads.py), builds one demo HTML site per
business from a template, and deploys each to Netlify automatically via
the Netlify API. Writes the live URL back into leads.csv.

SETUP (one-time, ~5 min):
1. Create a free Netlify account -> User settings -> Applications ->
   New access token
2. pip install requests --break-system-packages
3. export NETLIFY_TOKEN=xxxx
4. python3 generate_demo_sites.py

Netlify's API deploy flow needs a zip of the site per deploy. This script
builds a single index.html per lead and deploys it as its own Netlify site
(one site per business = one clean subdomain per demo, e.g.
lincoln-way-barber-shop.netlify.app).
"""

import os
import csv
import io
import time
import zipfile
import requests

NETLIFY_TOKEN = os.environ.get("NETLIFY_TOKEN", "PASTE_YOUR_TOKEN_HERE")
NETLIFY_API = "https://api.netlify.com/api/v1"

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name} | {category}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, Georgia, serif; color: #222; line-height: 1.6; }}
  header {{ background: #1a1a1a; color: #fff; padding: 60px 20px; text-align: center; }}
  header h1 {{ font-size: 2.2rem; margin-bottom: 10px; }}
  header p {{ opacity: 0.8; font-size: 1.1rem; }}
  .cta {{ display: inline-block; margin-top: 20px; background: #d4a24e;
          color: #1a1a1a; padding: 14px 28px; border-radius: 6px;
          font-weight: bold; text-decoration: none; }}
  section {{ max-width: 780px; margin: 0 auto; padding: 50px 20px; }}
  h2 {{ font-size: 1.5rem; margin-bottom: 16px; border-bottom: 2px solid #d4a24e;
        display: inline-block; padding-bottom: 6px; }}
  .review {{ background: #f7f5f0; border-left: 4px solid #d4a24e; padding: 16px;
             margin: 16px 0; font-style: italic; }}
  .info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 20px; }}
  .info-box {{ background: #f7f5f0; padding: 16px; border-radius: 6px; }}
  footer {{ text-align: center; padding: 40px 20px; background: #1a1a1a; color: #999; }}
  .banner {{ background: #d4a24e; color: #1a1a1a; text-align: center; padding: 10px;
             font-weight: bold; font-size: 0.9rem; }}
</style>
</head>
<body>
  <div class="banner">This is a free demo built for {name} — nothing is live under your name yet.</div>
  <header>
    <h1>{name}</h1>
    <p>{category}{address_line}</p>
    <a class="cta" href="{claim_link}">Claim This Site — $299 + $29/mo</a>
  </header>

  <section>
    <h2>About</h2>
    <p>{name} serves the local community with quality {category_lower}.
    Right now, searches for "{category} near me" don't lead here — this page
    fixes that.</p>
  </section>

  {reviews_section}

  <section>
    <h2>Info</h2>
    <div class="info-grid">
      <div class="info-box"><strong>Phone</strong><br>{phone}</div>
      <div class="info-box"><strong>Address</strong><br>{address}</div>
    </div>
  </section>

  <section style="text-align:center;">
    <h2>Like it?</h2>
    <p>Click below and it's live under your name this week. $299 once,
    $29/mo covers hosting and any change you ever want.</p>
    <a class="cta" href="{claim_link}">Claim This Site</a>
    <p style="margin-top:16px; font-size:0.9rem; color:#777;">
    Don't want it? Ignore this — nothing happens, no charge, ever.</p>
  </section>

  <footer>Built as a free demo. Not affiliated with {name} until claimed.</footer>
</body>
</html>
"""

REVIEW_BLOCK = """  <section>
    <h2>What people are saying</h2>
    <div class="review">"{snippet}"</div>
  </section>
"""

# Reads from the STRIPE_PAYMENT_LINK env var / GitHub Secret so you never
# have to hand-edit this file. Falls back to a placeholder until it's set --
# demos will still deploy, the "Claim" button just won't work yet.
CLAIM_LINK = os.environ.get("STRIPE_PAYMENT_LINK", "https://buy.stripe.com/PASTE_YOUR_PAYMENT_LINK")


def slugify(name):
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")[:40]


def build_html(row):
    reviews_section = ""
    if row.get("review_snippet"):
        reviews_section = REVIEW_BLOCK.format(snippet=row["review_snippet"])

    return TEMPLATE.format(
        name=row["name"],
        category=row.get("category", "local business") or "local business",
        category_lower=(row.get("category") or "local business").lower(),
        address=row.get("address", ""),
        address_line=f" · {row['address']}" if row.get("address") else "",
        phone=row.get("phone", "Call for details"),
        reviews_section=reviews_section,
        claim_link=CLAIM_LINK,
    )


def deploy_to_netlify(site_name, html):
    # 1. Create the site
    resp = requests.post(
        f"{NETLIFY_API}/sites",
        headers={"Authorization": f"Bearer {NETLIFY_TOKEN}"},
        json={"name": site_name},
        timeout=20,
    )
    if resp.status_code not in (200, 201):
        print(f"  site create failed for {site_name}: {resp.text[:200]}")
        return None
    site = resp.json()
    site_id = site["site_id"]

    # 2. Zip the single index.html and deploy it
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("index.html", html)
    buf.seek(0)

    deploy_resp = requests.post(
        f"{NETLIFY_API}/sites/{site_id}/deploys",
        headers={
            "Authorization": f"Bearer {NETLIFY_TOKEN}",
            "Content-Type": "application/zip",
        },
        data=buf.read(),
        timeout=30,
    )
    if deploy_resp.status_code not in (200, 201):
        print(f"  deploy failed for {site_name}: {deploy_resp.text[:200]}")
        return None

    return site.get("ssl_url") or site.get("url")


def main():
    if NETLIFY_TOKEN == "PASTE_YOUR_TOKEN_HERE":
        raise SystemExit("Set NETLIFY_TOKEN before running.")

    with open("leads.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("leads.csv has no rows yet -- nothing to deploy this run.")
        print("This usually means generate_leads.py's search queries didn't")
        print("turn up any no-website businesses this time. Check that step's")
        print("log output above, and see SEARCH_QUERIES in generate_leads.py.")
        return

    for i, row in enumerate(rows):
        if row.get("demo_url"):
            continue  # already built
        html = build_html(row)
        slug = slugify(row["name"]) or f"demo-{i}"
        print(f"Deploying {row['name']} -> {slug}")
        url = deploy_to_netlify(slug, html)
        if url:
            row["demo_url"] = url
            print(f"  live: {url}")
        time.sleep(1)  # avoid hammering Netlify's API

    with open("leads.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print("\nDone. leads.csv updated with live demo_url per business.")


if __name__ == "__main__":
    main()
