"""Live feed Lambda: gathers the dashboard-of-randomness data and writes /live.json.

Runs every 15 minutes. Each source is fetched independently; one failing (Strava down,
say) leaves its section out instead of failing the whole run. The feed also tracks how
long each source has been working or down, and emails once a source is down for 2 hours.
Standard library + boto3 only, so the folder deploys as a plain zip.
"""

import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import boto3

NEW_YORK = ZoneInfo("America/New_York")
GITHUB_USER = "nshampoo"
GOODREADS_PARAM = "/shampoe-site/goodreads"
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
# A source has to be down this long before it emails, so a flaky minute stays quiet.
ALERT_AFTER = timedelta(hours=2)
LABELS = {"github": "GitHub", "goodreads": "Goodreads", "citibike": "Citi Bike", "volo": "Volo", "strava": "Strava", "aws": "AWS bill"}

s3 = boto3.client("s3")
ssm = boto3.client("ssm")
dynamodb = boto3.client("dynamodb")
ce = boto3.client("ce")
sns = boto3.client("sns")


def handler(event, context):
    now = datetime.now(timezone.utc)
    prev = previous_feed()
    feed = {"updated": now.isoformat(timespec="seconds")}
    errors = {}
    for name, fetch in [
        ("github", github),
        ("goodreads", goodreads),
        ("citibike", citibike),
        ("volo", volo),
        ("strava", strava),
        ("aws", lambda now: aws_cost(now, prev)),
    ]:
        try:
            feed[name] = fetch(now)
        except Exception as e:  # noqa: BLE001
            errors[name] = str(e)
            print(f"WARNING: {name} skipped: {e}")
    feed["health"], alerts = health(prev.get("health") or {}, errors, now)
    for subject, message in alerts:
        try:
            sns.publish(TopicArn=os.environ["ALERTS_TOPIC"], Subject=subject, Message=message)
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: alert not sent: {e}")
    s3.put_object(
        Bucket=os.environ["BUCKET"],
        Key="live.json",
        Body=json.dumps(feed, separators=(",", ":")).encode(),
        ContentType="application/json",
        CacheControl="public, max-age=300",
    )
    print(json.dumps({k: ("skipped" if k in errors else "ok") for k in LABELS}))
    return {"sections": [k for k in feed if k not in ("updated", "health")]}


def previous_feed():
    try:
        return json.loads(s3.get_object(Bucket=os.environ["BUCKET"], Key="live.json")["Body"].read())
    except s3.exceptions.NoSuchKey:
        return {}


def health(prev, errors, now):
    """Each source's state and when it last changed, plus the emails to send.

    Down sources email once after ALERT_AFTER, and again when they recover. Error text
    only goes in the email, since live.json is public.
    """
    out, alerts = {}, []
    for name, label in LABELS.items():
        ok = name not in errors
        last = prev.get(name) or {}
        if last.get("ok") == ok:
            state = dict(last)
        else:
            state = {"ok": ok, "since": now.isoformat(timespec="seconds")}
            if ok and last.get("alerted"):
                alerts.append((f"shampoe.com: {label} is working again", f"{label} is back on the dashboard after being down since {last['since']}."))
        if not ok and not state.get("alerted") and now - datetime.fromisoformat(state["since"]) >= ALERT_AFTER:
            state["alerted"] = True
            alerts.append((f"shampoe.com: {label} is down", f"{label} has been failing since {state['since']}.\n\nLatest error: {errors[name]}"))
        out[name] = state
    return out, alerts


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

def goodreads(now):
    """Books from the latest Goodreads CSV export, saved by scripts/goodreads.py.

    Goodreads dropped its RSS feeds on 2026-10-27, so this is no longer automatic.
    """
    return json.loads(ssm.get_parameter(Name=GOODREADS_PARAM)["Parameter"]["Value"])


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


# ---------------------------------------------------------------- AWS cost

def aws_cost(now, prev):
    """Whole-account spend: this month so far and the last 13 months in total.

    Cost Explorer charges $0.01 per call, so the last result is reused until the UTC
    day changes: about 30 calls a month instead of ~2,900 at the feed's 15-minute pace.
    """
    today = now.date()
    last = prev.get("aws")
    if last and last.get("as_of") == today.isoformat():
        return last
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": date(today.year - 1, today.month, 1).isoformat(), "End": (today + timedelta(days=1)).isoformat()},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )
    return summarize_cost(resp["ResultsByTime"], today)


def summarize_cost(months, today):
    amounts = [(m["TimePeriod"]["Start"][:7], float(m["Total"]["UnblendedCost"]["Amount"])) for m in months]
    spent = [month for month, amount in amounts if amount >= 0.005]
    return {
        "as_of": today.isoformat(),
        "month": round(amounts[-1][1], 2) if amounts else 0,
        "total": round(sum(amount for _, amount in amounts), 2),
        "since": spent[0] if spent else None,
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

