"""
Scrapes all seat polls for the 2026 Israeli election from English Wikipedia
(community-maintained, structured, updated within hours of each poll).

Source: https://en.wikipedia.org/wiki/Opinion_polling_for_the_2026_Israeli_legislative_election
Output: polls.csv — one row per poll: date, pollster, publisher, sample, <party seat columns>
"""
import io
import re
import sys

import pandas as pd
import requests
from bs4 import BeautifulSoup

URL = ("https://en.wikipedia.org/wiki/"
       "Opinion_polling_for_the_2026_Israeli_legislative_election")
HEADERS = {"User-Agent": "ElectionMeter/0.1 (personal research project)"}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}

META_COLS = {"Fieldwork date", "Date", "Polling firm", "Publisher", "Sample size",
             "Lead", "Gov.", "Gov", "Opposition", "Opp.", "Arab", "Others",
             "Other", "Margin of error", "L", "R", "Left", "Right"}


def flatten_columns(cols) -> list[str]:
    out = []
    for c in cols:
        if isinstance(c, tuple):
            parts = [str(x) for x in c if not str(x).startswith("Unnamed")]
            name = parts[-1].strip() if parts else "?"
            name = re.sub(r"\[.*?\]", "", name)
            out.append(re.sub(r"\s+", " ", name.replace("\u2013", "-")).strip())
        else:
            out.append(str(c).strip())
    return out


def parse_date(raw: str, year: int | None) -> str | None:
    """'29-30 Jul' / '29 Jul' / '28 Jun - 1 Jul' / '01 Nov 22' ->
    ISO date of the LAST fieldwork day."""
    raw = str(raw)
    m4 = re.search(r"(\d{1,2})\s*([A-Z][a-z]{2})[a-z]*\s*(\d{4})", raw)
    if m4:
        return f"{m4.group(3)}-{MONTHS[m4.group(2)]:02d}-{int(m4.group(1)):02d}"
    m2 = re.search(r"(\d{1,2})\s*([A-Z][a-z]{2})\s*(\d{2})\b", raw)
    if m2:
        return f"20{m2.group(3)}-{MONTHS[m2.group(2)]:02d}-{int(m2.group(1)):02d}"
    m = re.findall(r"(\d{1,2})\s*([A-Z][a-z]{2})", raw)
    if not m or year is None:
        return None
    day, mon = m[-1]
    return f"{year:04d}-{MONTHS[mon]:02d}-{int(day):02d}"


def parse_seats(val) -> float | None:
    """'22', '26[a]', '3.1%*', '—' -> float seats or None."""
    s = re.sub(r"\[.*?\]", "", str(val)).strip()
    m = re.match(r"^(\d+(?:\.\d+)?)$", s)
    return float(m.group(1)) if m else None


def parse_sample(val) -> float | None:
    m = re.search(r"([\d,]{3,})", str(val))
    return float(m.group(1).replace(",", "")) if m else None


def scrape_html(html: str, default_year: int | None = None) -> pd.DataFrame:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    year = default_year
    for el in soup.find_all(["h2", "h3", "table"]):
        if el.name in ("h2", "h3"):
            txt = el.get_text(" ", strip=True)
            m = re.search(r"^(20\d\d)", txt)
            year = int(m.group(1)) if m else ((default_year if el.name == "h2" else year))
            continue
        if "wikitable" not in (el.get("class") or []):
            continue
        try:
            t = pd.read_html(io.StringIO(str(el)))[0]
        except ValueError:
            continue
        t.columns = flatten_columns(t.columns)
        date_col = ("Fieldwork date" if "Fieldwork date" in t.columns
                    else "Date" if "Date" in t.columns else None)
        if date_col is None or "Polling firm" not in t.columns:
            continue
        for _, r in t.iterrows():
            date = parse_date(r.get(date_col), year)
            firm = str(r.get("Polling firm", "")).strip()
            if not date or not firm or firm.lower() == "nan" \
                    or "election" in firm.lower():
                continue
            row = {"date": date,
                   "pollster": re.sub(r"\[.*?\]", "", firm),
                   "publisher": re.sub(r"\[.*?\]", "", str(r.get("Publisher", ""))),
                   "sample": parse_sample(r.get("Sample size", ""))}
            for col in t.columns:
                if col in META_COLS or col == "?":
                    continue
                seats = parse_seats(r[col])
                if seats is not None:
                    row[col] = seats
            party_sum = sum(v for k, v in row.items()
                            if k not in ("date", "pollster", "publisher", "sample")
                            and isinstance(v, float))
            if 115 <= party_sum <= 125:
                rows.append(row)
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return df.drop_duplicates(subset=["date", "pollster"], keep="first")


def main():
    html = requests.get(URL, headers=HEADERS, timeout=30).text
    df = scrape_html(html)
    df.to_csv("polls.csv", index=False)
    print(f"Saved {len(df)} polls, {df['date'].min()} -> {df['date'].max()}")


if __name__ == "__main__":
    main()
