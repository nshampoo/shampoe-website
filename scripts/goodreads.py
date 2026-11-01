"""Update the Live page's books from a Goodreads export (My Books > Import and export).

Keeps only what the tile shows, so reviews, notes, and the to-read shelf stay private.
The live feed picks it up on its next run.

    AWS_PROFILE=personal python3 scripts/goodreads.py ~/Downloads/goodreads_library_export.csv
"""

import csv
import json
import re
import sys
from datetime import date

PARAM = "/shampoe-site/goodreads"


def book(row):
    isbn = row["ISBN13"].strip('="') or row["ISBN"].strip('="')  # exported as ="9780441013593"
    return {
        "title": re.sub(r"\s*\([^)]*#\d+\)$", "", row["Title"]),  # "Dune (Dune, #1)" -> "Dune"
        "author": row["Author"],
        "rating": int(row["My Rating"] or 0),
        "cover": f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false" if isbn else "",
        "read": row["Date Read"].replace("/", "-") or None,
        "url": f"https://www.goodreads.com/book/show/{row['Book Id']}",
    }


def summarize(rows, exported):
    shelf = lambda name: [r for r in rows if r["Exclusive Shelf"] == name]  # noqa: E731
    read = sorted((book(r) for r in shelf("read") if r["Date Read"]), key=lambda b: b["read"], reverse=True)
    return {
        "current": [book(r) for r in shelf("currently-reading")][:2],
        "recent": read[:3],
        "total_read": len(shelf("read")),
        "exported": exported.isoformat(),
    }


if __name__ == "__main__":
    import boto3

    with open(sys.argv[1], newline="", encoding="utf-8") as f:
        data = summarize(list(csv.DictReader(f)), date.today())
    boto3.client("ssm", region_name="us-east-1").put_parameter(Name=PARAM, Value=json.dumps(data), Type="String", Overwrite=True)
    print(f"Saved {data['total_read']} read, {len(data['current'])} current. Live page updates within 15 minutes.")
