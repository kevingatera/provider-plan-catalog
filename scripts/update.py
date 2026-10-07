#!/usr/bin/env python3
"""Update public plan facts from the provider's published documentation."""
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

SOURCE = "https://opencode.ai/docs/go/"
ROOT = Path(__file__).resolve().parents[1]


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.text = []
        self.table = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        self.text.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def money(value):
    if value == "-":
        return None
    if value.lower() == "free":
        return 0
    if not re.fullmatch(r"\$[0-9]+(?:\.[0-9]+)?", value):
        raise ValueError("unrecognized currency value")
    return float(value[1:])


def parse_opencode(html):
    parser = Tables()
    parser.feed(html)
    header = ["Model", "Input", "Output", "Cached Read", "Cached Write", "Monthly limit"]
    tables = [table for table in parser.tables if table and table[0] == header]
    if len(tables) != 2:
        raise ValueError("expected separate Go and Go Plus price tables")
    text = " ".join(" ".join(parser.text).split())
    windows = re.search(r"5-hour\s*[—:-]\s*(\d+)%.*?weekly\s*[—:-]\s*(\d+)%.*?monthly\s*[—:-]\s*(\d+)%", text, re.I)
    if windows is None:
        raise ValueError("unrecognized usage window rule")
    fractions = [int(windows.group(i)) / 100 for i in (1, 2, 3)]
    if not 0 < fractions[0] <= fractions[1] <= fractions[2] == 1:
        raise ValueError("invalid usage window fractions")
    plans = []
    for plan_id, table in zip(("go", "go-plus"), tables):
        models = []
        for row in table[1:]:
            if len(row) != 6:
                raise ValueError("unexpected model price row")
            unlimited = row[5].lower().startswith("unlimited")
            models.append({
                "name": row[0],
                "token_prices_usd_per_million": {
                    "input": money(row[1]), "output": money(row[2]),
                    "cache_read": money(row[3]), "cache_write": money(row[4]),
                },
                "monthly_allowance_usd": None if unlimited else money(row[5]),
                "unlimited_promotion": unlimited,
            })
        if len(models) < 10:
            raise ValueError("incomplete model price table")
        plans.append({"id": plan_id, "provider": "opencode-go", "models": models,
                      "windows": dict(zip(("five_hour_fraction", "weekly_fraction", "monthly_fraction"), fractions)),
                      "scope": "provider-defined", "currency": "USD"})
    if [m["name"] for m in plans[0]["models"]] != [m["name"] for m in plans[1]["models"]]:
        raise ValueError("plan model lists differ; review the source before publishing")
    return plans


def main():
    request = urllib.request.Request(SOURCE, headers={"User-Agent": "provider-plan-catalog/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("source document too large")
    html = data.decode("utf-8")
    plans = parse_opencode(html)
    now = datetime.now(timezone.utc)
    catalog = {"version": 1, "observed_at": now.isoformat(),
               "expires_at": (now + timedelta(hours=48)).isoformat(),
               "sources": [{"url": SOURCE, "sha256": hashlib.sha256(data).hexdigest()}],
               "plans": plans}
    output = ROOT / "public" / "catalog.json"
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(catalog, indent=2) + "\n")
    temporary.replace(output)
    print(f"Validated {len(plans)} plans and {sum(len(p['models']) for p in plans)} model price rows")


if __name__ == "__main__":
    main()
