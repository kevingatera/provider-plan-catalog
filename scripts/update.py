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
PRICE_HEADER = ["Model", "Input", "Output", "Cached Read", "Cached Write", "Monthly limit"]
PLAN_IDS = ("go", "go-plus")
# Promotions render as <del>$30</del> <strong>$60</strong><br/><small>2x · Limited time</small>.
PROMOTION_NOTE = re.compile(r"(\d+)x\W*limited time", re.I)
# Tier and peak splits are published as a parenthesised suffix, e.g. "Qwen3.7 Plus (> 256K tokens)".
VARIANT_LABEL = re.compile(r"(?P<base>.+?)\s*\((?P<variant>[^()]+)\)")


class Cell:
    """A table cell split into visible value, struck-through text and <small> notes."""

    def __init__(self):
        self.parts = {"value": [], "struck": [], "note": []}

    def text(self, part="value"):
        return " ".join("".join(self.parts[part]).split())


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.text = []
        self.table = None
        self.row = None
        self.cell = None
        self.struck_depth = 0
        self.note_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = Cell()
        elif tag in ("del", "s"):
            self.struck_depth += 1
        elif tag == "small":
            self.note_depth += 1

    def handle_data(self, data):
        self.text.append(data)
        if self.cell is not None:
            if self.struck_depth:
                self.cell.parts["struck"].append(data)
            elif self.note_depth:
                self.cell.parts["note"].append(data)
            else:
                self.cell.parts["value"].append(data)

    def handle_endtag(self, tag):
        if tag in ("del", "s") and self.struck_depth:
            self.struck_depth -= 1
        elif tag == "small" and self.note_depth:
            self.note_depth -= 1
        elif tag in ("td", "th") and self.cell is not None:
            self.row.append(self.cell)
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
        raise ValueError(f"unrecognized currency value {value!r}")
    return float(value[1:])


def token_price(cell, column, model):
    if cell.text("struck") or cell.text("note"):
        raise ValueError(f"unexpected annotation in {column} price for {model!r}")
    return money(cell.text())


def monthly_limit(cell, model):
    """Return (allowance, unlimited, standard_allowance, multiplier) for a Monthly limit cell."""
    value, struck, note = cell.text(), cell.text("struck"), cell.text("note")
    if value.lower().startswith("unlimited"):
        if struck:
            raise ValueError(f"unexpected struck-through limit for {model!r}")
        return None, True, None, None
    if not struck:
        if note:
            raise ValueError(f"unexpected note in monthly limit for {model!r}: {note!r}")
        return money(value), False, None, None
    # A limited-time promotion shows the standard limit struck through, then the promoted limit.
    promotion = PROMOTION_NOTE.fullmatch(note)
    if promotion is None:
        raise ValueError(f"unrecognized promotion label for {model!r}: {note!r}")
    standard, current, multiplier = money(struck), money(value), int(promotion.group(1))
    if standard is None or current is None or current != standard * multiplier:
        raise ValueError(f"promotion for {model!r} does not match its {multiplier}x label")
    return current, False, standard, multiplier


def split_label(label):
    match = VARIANT_LABEL.fullmatch(label)
    if match is None:
        return label, None
    return match["base"], match["variant"]


def parse_price_row(row):
    if len(row) != len(PRICE_HEADER):
        raise ValueError(f"unexpected model price row with {len(row)} cells")
    name = row[0].text()
    if not name:
        raise ValueError("model price row without a name")
    base_name, variant = split_label(name)
    allowance, unlimited, standard, multiplier = monthly_limit(row[5], name)
    return {
        "name": name,
        "base_name": base_name,
        "variant": variant,
        "token_prices_usd_per_million": {
            "input": token_price(row[1], "input", name),
            "output": token_price(row[2], "output", name),
            "cache_read": token_price(row[3], "cache read", name),
            "cache_write": token_price(row[4], "cache write", name),
        },
        "monthly_allowance_usd": allowance,
        "base_monthly_allowance_usd": standard,
        "limited_time_multiplier": multiplier,
        "unlimited_promotion": unlimited,
    }


def parse_opencode(html):
    parser = Tables()
    parser.feed(html)
    price_tables = [t for t in parser.tables if t and [c.text() for c in t[0]] == PRICE_HEADER]
    if len(price_tables) != len(PLAN_IDS):
        raise ValueError(
            f"expected {len(PLAN_IDS)} price tables with columns {PRICE_HEADER}, found {len(price_tables)}")
    text = " ".join(" ".join(parser.text).split())
    windows = re.search(r"5-hour\s*[—:-]\s*(\d+)%.*?weekly\s*[—:-]\s*(\d+)%.*?monthly\s*[—:-]\s*(\d+)%", text, re.I)
    if windows is None:
        raise ValueError("usage window rule not found in the page text")
    fractions = [int(windows.group(i)) / 100 for i in (1, 2, 3)]
    if not 0 < fractions[0] <= fractions[1] <= fractions[2] == 1:
        raise ValueError("invalid usage window fractions")
    plans = []
    for plan_id, table in zip(PLAN_IDS, price_tables):
        models = [parse_price_row(row) for row in table[1:]]
        if len(models) < 10:
            raise ValueError("incomplete model price table")
        names = [m["name"] for m in models]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate model price rows in the {plan_id} table")
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
    try:
        plans = parse_opencode(html)
    except ValueError as error:
        raise SystemExit(f"Refusing to publish: unrecognized layout at {SOURCE}: {error}") from error
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
