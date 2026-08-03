"""
Aggregate free public RSS feeds about the Israeli government / politics.
Outputs:
  gov-news.json  — for the mobile module on the dashboard
  gov-news.xml   — RSS 2.0 feed (subscribe in any reader)
  sitemap.xml    — lastmod refresh (best-effort)

Zero cost: only free public RSS endpoints, one pass, polite User-Agent.
"""
from __future__ import annotations

import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import urlparse

import requests

UA = "ElectionMeter/0.2 (+https://NoNOno0100.github.io/election-meter/; gov-news aggregator)"
HEADERS = {"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"}
TIMEOUT = 20
MAX_ITEMS = 40

# Free public RSS sources — government / politics / elections angle
FEEDS = [
    # Kan 11
    ("כאן 11", "https://www.kan.org.il/Rss/?itemType=0"),
    # Ynet politics (if available)
    ("Ynet", "https://www.ynet.co.il/Integration/StoryRss2.xml"),
    # Walla news
    ("וואלה", "https://rss.walla.co.il/feed/1?type=main"),
    # Globes
    ("גלובס", "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=2"),
    # Maariv
    ("מעריב", "https://www.maariv.co.il/Rss/RssFeedsMivzakim"),
    # Israel Hayom
    ("ישראל היום", "https://www.israelhayom.co.il/rss.xml"),
]

# Keywords that keep an item (Hebrew + English). Broad but government-relevant.
KEEP = re.compile(
    r"ממשל|כנסת|שר |שרה |ראש.?הממשל|בחיר|מנדט|קואליצ|אופוזיצ|"
    r"ליכוד|נתניהו|סמוטריץ|בן.?גביר|לפיד|גנץ|בנט|"
    r"תקציב|מדינ|ביטחון|קבינט|ועדת|חוק |הצעת.?חוק|"
    r"government|knesset|minister|election|coalition|netanyahu",
    re.I,
)


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _find(el: ET.Element, *names: str) -> ET.Element | None:
    for n in names:
        found = el.find(n)
        if found is not None:
            return found
        # try without namespace
        for child in el:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == n.split("}")[-1]:
                return child
    return None


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            d = datetime.strptime(raw[:19] + ("Z" if raw.endswith("Z") else ""), fmt[: len(raw)])
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d
        except Exception:
            continue
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", raw)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return None


def fetch_feed(source: str, url: str) -> list[dict]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        print(f"  skip {source}: {e}", file=sys.stderr)
        return []
    try:
        # tolerate encoding issues
        text = r.content.decode(r.encoding or "utf-8", errors="replace")
        root = ET.fromstring(text)
    except Exception as e:
        print(f"  parse fail {source}: {e}", file=sys.stderr)
        return []

    items = []
    # RSS 2.0
    channels = root.findall(".//channel") or ([root] if root.tag.endswith("channel") else [])
    entries = []
    for ch in channels:
        entries.extend(ch.findall("item"))
    # Atom
    if not entries:
        entries = [e for e in root.iter() if e.tag.split("}")[-1] == "entry"]

    for it in entries:
        title = _strip_html(_text(_find(it, "title")))
        link_el = _find(it, "link")
        link = ""
        if link_el is not None:
            link = (link_el.get("href") or _text(link_el) or "").strip()
        if not link:
            guid = _find(it, "guid")
            link = _text(guid)
        desc = _strip_html(_text(_find(it, "description", "summary", "content")))
        pub = _text(_find(it, "pubDate", "published", "updated", "date"))
        dt = _parse_date(pub) or datetime.now(timezone.utc)
        blob = f"{title} {desc}"
        if not title or not link:
            continue
        if not KEEP.search(blob):
            continue
        items.append({
            "title": title[:200],
            "link": link,
            "source": source,
            "summary": desc[:280],
            "published": dt.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "published_ts": int(dt.timestamp()),
        })
    return items


def dedupe(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for it in sorted(items, key=lambda x: -x["published_ts"]):
        key = re.sub(r"\W+", "", it["title"].lower())[:60]
        host = urlparse(it["link"]).netloc
        sig = (key, host)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(it)
        if len(out) >= MAX_ITEMS:
            break
    return out


def write_rss(items: list[dict], path: str = "gov-news.xml") -> None:
    now = datetime.now(timezone.utc)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        "<title>מד הבחירות — חדשות ממשלה ופוליטיקה</title>",
        "<link>https://NoNOno0100.github.io/election-meter/</link>",
        "<description>אגרגציית RSS חינמית: כתבות על הממשלה, הכנסת והבחירות — מתעדכן יומית</description>",
        "<language>he</language>",
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>",
        '<atom:link href="https://NoNOno0100.github.io/election-meter/gov-news.xml" rel="self" type="application/rss+xml"/>',
        "<managingEditor>jelyashar@gmail.com (Joseph Elyashar)</managingEditor>",
        "<webMaster>jelyashar@gmail.com (Joseph Elyashar)</webMaster>",
        "<ttl>60</ttl>",
        "<image>",
        "<url>https://NoNOno0100.github.io/election-meter/icon-192.svg</url>",
        "<title>מד הבחירות</title>",
        "<link>https://NoNOno0100.github.io/election-meter/</link>",
        "</image>",
    ]
    for it in items:
        try:
            dt = datetime.fromisoformat(it["published"])
            pub = format_datetime(dt)
        except Exception:
            pub = format_datetime(now)
        lines += [
            "<item>",
            f"<title>{html.escape(it['title'])}</title>",
            f"<link>{html.escape(it['link'])}</link>",
            f"<guid isPermaLink=\"true\">{html.escape(it['link'])}</guid>",
            f"<pubDate>{pub}</pubDate>",
            f"<source url=\"{html.escape(it['link'])}\">{html.escape(it['source'])}</source>",
            f"<description>{html.escape(it.get('summary') or it['title'])}</description>",
            f"<category>{html.escape(it['source'])}</category>",
            f"<category>ממשלה</category>",
            f"<category>בחירות</category>",
            "</item>",
        ]
    lines += ["</channel>", "</rss>"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_json(items: list[dict], path: str = "gov-news.json") -> None:
    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(items),
        "rss": "gov-news.xml",
        "items": [
            {
                "title": it["title"],
                "link": it["link"],
                "source": it["source"],
                "summary": it.get("summary", ""),
                "published": it["published"],
            }
            for it in items
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def refresh_sitemap(path: str = "sitemap.xml") -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
  <url>
    <loc>https://NoNOno0100.github.io/election-meter/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
    <xhtml:link rel="alternate" hreflang="he" href="https://NoNOno0100.github.io/election-meter/"/>
    <xhtml:link rel="alternate" hreflang="x-default" href="https://NoNOno0100.github.io/election-meter/"/>
  </url>
  <url>
    <loc>https://NoNOno0100.github.io/election-meter/gov-news.xml</loc>
    <lastmod>{today}</lastmod>
    <changefreq>hourly</changefreq>
    <priority>0.85</priority>
  </url>
  <url>
    <loc>https://NoNOno0100.github.io/election-meter/forecast.json</loc>
    <lastmod>{today}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.6</priority>
  </url>
</urlset>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)


def main() -> int:
    print("Fetching government / politics RSS…")
    all_items: list[dict] = []
    for source, url in FEEDS:
        got = fetch_feed(source, url)
        print(f"  {source}: {len(got)} matching items")
        all_items.extend(got)
    items = dedupe(all_items)
    if len(items) < 3:
        print("WARN: fewer than 3 items — writing what we have", file=sys.stderr)
    write_json(items)
    write_rss(items)
    refresh_sitemap()
    print(f"Saved {len(items)} items → gov-news.json + gov-news.xml")
    return 0 if items else 1


if __name__ == "__main__":
    raise SystemExit(main())
