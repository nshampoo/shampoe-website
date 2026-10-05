"""Live feed Lambda: gathers the dashboard-of-randomness data and writes /live.json.

Runs every 15 minutes. Each source is fetched independently; one failing (Goodreads
down, Strava not set up yet) leaves its section out instead of failing the whole run.
Standard library + boto3 only, so the folder deploys as a plain zip.
"""

import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import boto3

NEW_YORK = ZoneInfo("America/New_York")
GITHUB_USER = "nshampoo"
GOODREADS_USER = "169418598"
CITIBIKE_DATA = "https://d2g10dtmnepqv0.cloudfront.net/data/live/"
STRAVA_PARAM = "/shampoe-site/strava"
VOLO_STATS_PARAM = "/volo-notifier/stats-table"
# Run maps drop everything within this many meters of the start and finish, so a run
# that starts at home doesn't show where home is.
PRIVACY_RADIUS_M = 400
# Flag football games are logged as "Flag Football". A real game is someone zig-zagging
# on one field (about 1 m/s on average); anything faster is a mislabeled ride, which
# could show a route home, so it is never treated as a game.
GAME_MAX_AVG_SPEED = 2.5

s3 = boto3.client("s3")
ssm = boto3.client("ssm")
dynamodb = boto3.client("dynamodb")


def handler(event, context):
    now = datetime.now(timezone.utc)
    feed = {"updated": now.isoformat(timespec="seconds")}
    for name, fetch in [
        ("github", github),
        ("goodreads", goodreads),
        ("citibike", citibike),
        ("volo", volo),
        ("strava", strava),
    ]:
        try:
            feed[name] = fetch(now)
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: {name} skipped: {e}")
    s3.put_object(
        Bucket=os.environ["BUCKET"],
        Key="live.json",
        Body=json.dumps(feed, separators=(",", ":")).encode(),
        ContentType="application/json",
        CacheControl="public, max-age=300",
    )
    print(json.dumps({k: ("ok" if k in feed else "skipped") for k in ["github", "goodreads", "citibike", "volo", "strava"]}))
    return {"sections": [k for k in feed if k != "updated"]}


# ---------------------------------------------------------------- helpers

def get(url, headers=None, data=None, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "shampoe.com live feed", **(headers or {})}, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_json(url, **kwargs):
    return json.loads(get(url, **kwargs))


# ---------------------------------------------------------------- GitHub

def github(now):
    """Most recently pushed public repos, newest first.

    Uses each repo's pushed_at rather than the public events feed: GitHub delays that feed
    by up to several hours and doesn't guarantee its order, so it can miss today's pushes.
    """
    repos = get_json(f"https://api.github.com/users/{GITHUB_USER}/repos?sort=pushed&direction=desc&per_page=5",
                     headers={"Accept": "application/vnd.github+json"})
    return {"repos": [{"name": r["name"], "url": r["html_url"], "pushed": r["pushed_at"]} for r in repos if r.get("pushed_at")]}


# ---------------------------------------------------------------- Goodreads

def _shelf(shelf, extra=""):
    xml = get(f"https://www.goodreads.com/review/list_rss/{GOODREADS_USER}?shelf={shelf}{extra}")
    books = []
    for item in ET.fromstring(xml).iter("item"):
        text = lambda tag: (item.findtext(tag) or "").strip()  # noqa: E731
        read_at = text("user_read_at")
        books.append({
            "title": re.sub(r"\s*\([^)]*#\d+\)$", "", text("title")),  # "Dune (Dune, #1)" -> "Dune"
            "author": text("author_name"),
            "rating": int(text("user_rating") or 0),
            "cover": text("book_large_image_url") or text("book_medium_image_url"),
            "read": _rss_date(read_at),
            "url": text("link"),
        })
    return books


def _rss_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%a, %d %b %Y %H:%M:%S %z").date().isoformat()
    except ValueError:
        return None


def goodreads(now):
    current = _shelf("currently-reading")
    read = [b for b in _shelf("read", "&sort=date_read&order=d") if b["read"]]
    read.sort(key=lambda b: b["read"], reverse=True)
    total = None
    try:
        page = get(f"https://www.goodreads.com/user/show/{GOODREADS_USER}").decode("utf-8", "replace")
        m = re.search(r"([\d,]+)\s+books", page)
        total = int(m.group(1).replace(",", "")) if m else None
    except Exception:  # noqa: BLE001
        pass
    return {"current": current[:2], "recent": read[:3], "total_read": total}


# ---------------------------------------------------------------- Citi Bike (from Citi Bike Tides' own data)

def citibike(now):
    index = get_json(CITIBIKE_DATA + "index.json")
    # Hour files are named by UTC hour; keep the ones since midnight in New York.
    midnight = now.astimezone(NEW_YORK).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    hours = [h for h in index["hours"] if datetime.strptime(h, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc) >= midnight]
    undocked, latest = 0, {}
    for h in hours:
        data = get_json(CITIBIKE_DATA + f"hours/{h}.json")
        for station, counts in data["bikes"].items():
            prev = None
            for c in counts:
                if c is None:
                    continue
                if prev is not None and c < prev:
                    undocked += prev - c  # a lower bound: two swaps in one minute count once
                prev = c
            if prev is not None:
                latest[station] = prev
    return {
        "undocked_today": undocked,
        "empty_now": sum(1 for c in latest.values() if c == 0),
        "stations": len(latest),
        "bikes_docked_now": sum(latest.values()),
    }


# ---------------------------------------------------------------- Volo drop-ins

def volo(now):
    table = ssm.get_parameter(Name=VOLO_STATS_PARAM)["Parameter"]["Value"]
    since = (now.astimezone(NEW_YORK).date() - timedelta(days=89)).isoformat()
    days, kwargs = [], {"TableName": table}
    while True:
        page = dynamodb.scan(**kwargs)
        for item in page["Items"]:
            days.append({
                "day": item["day"]["S"],
                "total": int(item.get("total", {}).get("N", 0)),
                "football": int(item.get("football", {}).get("N", 0)),
            })
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    days.sort(key=lambda d: d["day"])
    first = days[0]["day"] if days else None
    return {
        "counting_since": first,
        "all_time": {"total": sum(d["total"] for d in days), "football": sum(d["football"] for d in days)},
        "days": [d for d in days if d["day"] >= since],
    }


# ---------------------------------------------------------------- Strava

DEFAULT_NAME = re.compile(r"^(Morning|Afternoon|Lunch|Evening|Night) (Run|Ride|E-Bike Ride|Swim|Walk|Workout|Hike)$")


def _strava_token():
    raw = ssm.get_parameter(Name=STRAVA_PARAM, WithDecryption=True)["Parameter"]["Value"]
    creds = json.loads(raw)
    if creds.get("expires_at", 0) > time.time() + 120:
        return creds["access_token"]
    body = urllib.parse.urlencode({
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": creds["refresh_token"],
    }).encode()
    token = json.loads(get("https://www.strava.com/oauth/token", data=body))
    creds.update(access_token=token["access_token"], refresh_token=token["refresh_token"], expires_at=token["expires_at"])
    # Strava may rotate the refresh token, so save it back.
    ssm.put_parameter(Name=STRAVA_PARAM, Value=json.dumps(creds), Type="SecureString", Overwrite=True)
    return creds["access_token"]


def strava(now):
    token = _strava_token()
    # The tiles cover the last 30 days (a calendar month would read all zeros on the 1st);
    # fetch further back so the latest run and game are found even after a quiet month.
    window_start = now - timedelta(days=30)
    after = int((now - timedelta(days=90)).timestamp())
    acts = get_json(f"https://www.strava.com/api/v3/athlete/activities?per_page=200&after={after}",
                    headers={"Authorization": f"Bearer {token}"})
    acts.sort(key=lambda a: a["start_date"], reverse=True)

    def summary(a, route=None):
        out = {
            "name": a["name"],
            "date": a["start_date_local"][:10],
            "miles": round(a["distance"] / 1609.344, 2),
            "moving_seconds": a["moving_time"],
            # The activity list only sometimes includes calories; kilojoules are not calories.
            "calories": round(a.get("calories") or 0),
            "max_mph": round((a.get("max_speed") or 0) * 2.23694, 1),
        }
        if a["distance"] and a["type"] == "Run":
            out["pace_seconds_per_mile"] = round(a["moving_time"] / (a["distance"] / 1609.344))
        if route == "trimmed":
            out["route"] = trim_ends(decode_polyline((a.get("map") or {}).get("summary_polyline") or ""))
        elif route == "field":
            # The whole game happens on one field, nowhere near home, so it is drawn untrimmed.
            out["route"] = decode_polyline((a.get("map") or {}).get("summary_polyline") or "")
        return out

    run = next((a for a in acts if a["type"] == "Run" and a["distance"] > 3000), None)
    games = [a for a in acts if a["name"].strip().lower() == "flag football"]
    game = next((a for a in games if (a.get("average_speed") or 99) < GAME_MAX_AVG_SPEED), None)

    recent = [a for a in acts if datetime.fromisoformat(a["start_date"].replace("Z", "+00:00")) >= window_start]
    counts = {"rides": 0, "flag_football": 0, "runs": 0, "swims": 0}
    for a in recent:
        if a["name"].strip().lower() == "flag football" and (a.get("average_speed") or 99) < GAME_MAX_AVG_SPEED:
            counts["flag_football"] += 1
        elif a["type"] in ("Ride", "EBikeRide") or a.get("sport_type") in ("EBikeRide", "Ride"):
            counts["rides"] += 1
        elif a["type"] == "Run":
            counts["runs"] += 1
        elif a["type"] == "Swim":
            counts["swims"] += 1

    # Activity title of the month: a custom, one-off title from the last 30 days. Names that
    # repeat (a run club's acronym, "Flag Football") are labels, not jokes, so they're skipped;
    # among the rest the wordiest wins, then the one with the most kudos.
    name_counts = {}
    for a in acts:
        key = a["name"].strip().lower()
        name_counts[key] = name_counts.get(key, 0) + 1
    named = [a for a in recent if not DEFAULT_NAME.match(a["name"]) and name_counts[a["name"].strip().lower()] == 1]
    best = max(named, key=lambda a: (len(a["name"].split()), a.get("kudos_count", 0)), default=None)

    return {
        "latest_run": summary(run, "trimmed") if run else None,
        "latest_game": summary(game, "field") if game else None,
        "month": {"label": "Last 30 days", **counts},
        "title_of_the_month": {"name": best["name"], "date": best["start_date_local"][:10], "type": best.get("sport_type") or best["type"]} if best else None,
    }


def decode_polyline(encoded):
    points, i, lat, lng = [], 0, 0, 0
    while i < len(encoded):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(encoded[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lng += delta
        points.append([round(lat / 1e5, 5), round(lng / 1e5, 5)])
    return points


def _meters(a, b):
    k = math.cos(math.radians((a[0] + b[0]) / 2))
    return 111_320 * math.hypot(a[0] - b[0], (a[1] - b[1]) * k)


def trim_ends(points):
    """Drop points near the start and the finish (privacy)."""
    if len(points) < 3:
        return []
    start, end = points[0], points[-1]
    return [p for p in points if _meters(p, start) > PRIVACY_RADIUS_M and _meters(p, end) > PRIVACY_RADIUS_M]

