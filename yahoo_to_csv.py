#!/usr/bin/env python3
"""
Convert saved Yahoo Fantasy Basketball "Players" web pages (.htm / .html)
into one CSV.

Usage:
  uv run yahoo_to_csv.py page1.htm page2.htm page3.html -o players.csv
  uv run yahoo_to_csv.py pages/*.htm                    -o players.csv

Players that appear in more than one file are kept once (first one wins).
The stats are Yahoo's projected season totals for the stat view you saved,
so per-game columns (total / GP) are added too.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

STAT_COLS = ["3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"]
# Trailing columns of each row, in order, right before the spacer cell.
TAIL_COLS = ["GP", "PreRank", "CurRank", "PctRostered", "MPG"] + STAT_COLS
STATUS_CODES = ("GTD", "SUSP", "OFS", "INJ", "NA", "O", "P", "D", "Q")
TEAM_POS_RE = re.compile(r"([A-Z]{2,3}) - ([A-Z,]+)\s*$")


def to_num(s):
    s = (s or "").strip().replace(",", "").rstrip("%")
    if s in ("", "-"):
        return None
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return None


def blank_none(v):
    return "" if v is None else v


# ----------------------------------------------------------------- HTML ----
def parse_html(path):
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    # Pages after the first, saved from Yahoo's "next 25" requests, are JSON
    # wrapping the HTML: {"content": "<escaped html>", ...}
    if text.lstrip().startswith("{"):
        try:
            text = json.loads(text)["content"]
        except (ValueError, KeyError, TypeError):
            pass
    soup = BeautifulSoup(text, "html.parser")
    players = []
    for tr in soup.select("#players-table table tbody tr") or soup.select("table tbody tr"):
        name_a = tr.select_one("a.name")
        if not name_a:
            continue
        tds = tr.find_all("td")
        if len(tds) < 14:
            continue
        status_el = tr.select_one(".ysf-player-status")
        team = pos = ""
        # Several .Fz-xxs spans exist (injury code, team/pos); pick the TEAM - POS one.
        for el in tr.select(".ysf-player-name .Fz-xxs"):
            m = TEAM_POS_RE.search(el.get_text(" ", strip=True))
            if m:
                team, pos = m.group(1), m.group(2)
                break
        tail = [td.get_text(strip=True) for td in tds[-13:-1]]  # drop spacer cell
        inj = status_el.get_text(strip=True) if status_el else ""
        players.append({
            "player_id": name_a.get("data-ys-playerid", ""),
            "name": name_a.get_text(strip=True),
            "team": team,
            "positions": pos,
            "injury": inj if inj in STATUS_CODES else "",
            "roster_status": tds[-14].get_text(strip=True),
            **dict(zip(TAIL_COLS, tail)),
        })
    return players


# ----------------------------------------------------------------- MAIN ----
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--out", default="players.csv")
    args = ap.parse_args()

    merged = {}
    for f in args.files:
        p = Path(f)
        if p.suffix.lower() not in (".htm", ".html"):
            sys.exit(f"{p.name}: only .htm / .html files are supported")
        rows = parse_html(p)
        new = 0
        for r in rows:
            key = r["name"]
            if key not in merged:
                merged[key] = r
                new += 1
        print(f"{p.name}: {len(rows)} players read, {new} new")

    out_cols = ["name", "team", "positions", "injury", "roster_status", "GP", "PreRank",
                "CurRank", "PctRostered", "MPG"] + STAT_COLS + [f"{c}_pg" for c in STAT_COLS]
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=out_cols)
        w.writeheader()
        for r in merged.values():
            row = {k: r.get(k, "") for k in out_cols}
            gp = to_num(r.get("GP"))
            for c in STAT_COLS:
                total = to_num(r.get(c))
                row[c] = blank_none(total)
                row[f"{c}_pg"] = round(total / gp, 2) if total is not None and gp else ""
            row["GP"] = blank_none(gp)
            for c in ("PreRank", "CurRank", "PctRostered", "MPG"):
                row[c] = blank_none(to_num(r.get(c)))
            w.writerow(row)
    print(f"Wrote {len(merged)} players to {args.out}")


if __name__ == "__main__":
    main()
