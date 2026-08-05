"""
generate_demo_sites.py

Reads leads.csv (from generate_leads.py), builds one demo HTML site per
business from a template, and deploys each to Netlify automatically via
the Netlify API (using Netlify's "digest deploy" method -- the same one
their own dashboard/CLI uses, so files get served with the correct
content-type and actually render instead of showing as raw text).

Netlify rate-limits how fast a fresh account can create new sites/deploys.
Rather than fight that with clever retries, this script only deploys a
small batch per run and leaves the rest for the next scheduled run (it
always skips rows that already have a demo_url, so nothing is lost or
duplicated -- it just catches up over a few days).

SETUP (one-time, ~5 min):
1. Create a free Netlify account -> User settings -> Applications ->
   New access token
2. pip install requests --break-system-packages
3. export NETLIFY_TOKEN=xxxx
4. python3 generate_demo_sites.py
"""

import os
import csv
import time
import hashlib
import requests

NETLIFY_TOKEN = os.environ.get("NETLIFY_TOKEN", "PASTE_YOUR_TOKEN_HERE")
NETLIFY_API = "https://api.netlify.com/api/v1"

# How many NEW sites to create per run. Keep this low -- Netlify rate-limits
# rapid site creation hard on fresh accounts. Leftover leads roll over to
# the next scheduled run automatically.
MAX_DEPLOYS_PER_RUN = 5
SECONDS_BETWEEN_DEPLOYS = 5
RETRY_ON_429 = 2          # how many times to retry a single deploy on rate-limit
RETRY_WAIT_SECONDS = 20   # how long to wait before each retry

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


def post_with_retry(url, **kwargs):
    attempt = 0
    while True:
        resp = requests.post(url, timeout=kwargs.pop("timeout", 20), **kwargs)
        if resp.status_code == 429 and attempt < RETRY_ON_429:
            attempt += 1
            print(f"  rate-limited, waiting {RETRY_WAIT_SECONDS}s (retry {attempt}/{RETRY_ON_429})")
            time.sleep(RETRY_WAIT_SECONDS)
            continue
        return resp


def deploy_to_netlify(site_name, html):
    # 1. Create the site
    resp = post_with_retry(
        f"{NETLIFY_API}/sites",
        headers={"Authorization": f"Bearer {NETLIFY_TOKEN}"},
        json={"name": site_name},
    )
    if resp.status_code not in (200, 201):
        print(f"  site create failed for {site_name}: {resp.text[:200]}")
        return None
    site = resp.json()
    site_id = site["site_id"]

    # 2. Digest deploy: tell Netlify what file + hash we want to publish
    content_bytes = html.encode("utf-8")
    sha1 = hashlib.sha1(content_bytes).hexdigest()

    deploy_resp = post_with_retry(
        f"{NETLIFY_API}/sites/{site_id}/deploys",
        headers={
            "Authorization": f"Bearer {NETLIFY_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"files": {"/index.html": sha1}},
    )
    if deploy_resp.status_code not in (200, 201):
        print(f"  deploy create failed for {site_name}: {deploy_resp.text[:200]}")
        return None
    deploy = deploy_resp.json()
    deploy_id = deploy["id"]

    # 3. Upload the actual file content if Netlify says it needs it
    if sha1 in deploy.get("required", []):
        upload_resp = requests.put(
            f"{NETLIFY_API}/deploys/{deploy_id}/files/index.html",
            headers={
                "Authorization": f"Bearer {NETLIFY_TOKEN}",
                "Content-Type": "application/octet-stream",
            },
            data=content_bytes,
            timeout=30,
        )
        if upload_resp.status_code not in (200, 201):
            print(f"  file upload failed for {site_name}: {upload_resp.text[:200]}")
            return None

    return site.get("ssl_url") or site.get("url")


def main():
    if NETLIFY_TOKEN == "PASTE_YOUR_TOKEN_HERE":
        raise SystemExit("Set NETLIFY_TOKEN before running.")

    with open("leads.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("leads.csv has no rows yet -- nothing to deploy this run.")
        return

    deployed_this_run = 0
    remaining = sum(1 for r in rows if not r.get("demo_url"))
    print(f"{remaining} leads still need a demo. Deploying up to {MAX_DEPLOYS_PER_RUN} this run.")

    for i, row in enumerate(rows):
        if row.get("demo_url"):
            continue  # already built
        if deployed_this_run >= MAX_DEPLOYS_PER_RUN:
            break

        html = build_html(row)
        slug = slugify(row["name"]) or f"demo-{i}"
        print(f"Deploying {row['name']} -> {slug}")
        url = deploy_to_netlify(slug, html)
        if url:
            row["demo_url"] = url
            print(f"  live: {url}")
        deployed_this_run += 1
        time.sleep(SECONDS_BETWEEN_DEPLOYS)

    with open("leads.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    still_left = sum(1 for r in rows if not r.get("demo_url"))
    print(f"\nDone this run. {still_left} leads still without a demo -- they'll")
    print("pick up automatically on the next scheduled run.")


if __name__ == "__main__":
    main()
