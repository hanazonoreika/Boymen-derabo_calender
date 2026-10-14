#!/usr/bin/env python3
"""Fetch public BOYS AND MEN / でらボ schedule pages into data/events.json.

Principles:
- Never infer a year or event date from an article publication date.
- Determine member from the event title/detail page, not a whole month of text.
- Crawl BOYS AND MEN month pages individually.
- Keep each source independent; one blocked source must not stop the others.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin, urldefrag, urlparse

import requests
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).date()
START = date(TODAY.year - 1, TODAY.month, min(TODAY.day, monthrange(TODAY.year - 1, TODAY.month)[1]))
END = date(TODAY.year + 1, TODAY.month, min(TODAY.day, monthrange(TODAY.year + 1, TODAY.month)[1]))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
}
TIMEOUT = 25
MEMBERS = ["辻本達規", "田村侑久", "本田剛文", "平松賢人", "吉原雅斗"]
BOYS_BASE = "https://boysandmen.jp"
BOYS_CALENDAR = BOYS_BASE + "/vertical_calendar"
DERA_BASE = "https://dxboys.bitfan.id"
DERA_SCHEDULE = DERA_BASE + "/schedules/menu/184780"
DERA_NEWS = DERA_BASE + "/contents/menu/184779"
SKIP_TITLE = [
    "パワープレイソングに決定", "レギュラー出演情報", "前月へ", "次月へ",
    "Powered by", "ログイン", "Login", "SCHEDULE", "NEWS",
]

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def get_soup(url: str) -> BeautifulSoup:
    response = SESSION.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return BeautifulSoup(response.text, "html.parser")


def normalize(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split())


def parse_full_date(text: str):
    """Parse only a full year/month/day date; do not use publication timestamps as event dates."""
    text = normalize(text)
    patterns = [
        r"(20\d{2})\s*[年/.\-]\s*(\d{1,2})\s*[月/.\-]\s*(\d{1,2})\s*日?",
        r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                continue
    return None


def event_date_from_detail(soup: BeautifulSoup, title: str):
    # Title first, then visible schedule content. Exclude metadata that usually holds publication date.
    d = parse_full_date(title)
    if d:
        return d
    for selector in ["main", "article", ".schedule", ".schedule-detail", ".contents", "body"]:
        node = soup.select_one(selector)
        if not node:
            continue
        clone_text = normalize(node.get_text(" ", strip=True))
        # The first full date on a schedule detail page is generally the scheduled date.
        # For NEWS pages this function is called only if title is date-bearing or the URL is /schedules/.
        d = parse_full_date(clone_text)
        if d:
            return d
    return None


def member_for(title: str, detail_text: str = "") -> str:
    """Use the title as the main evidence; don't let unrelated month-wide text choose a member."""
    title = normalize(title)
    title_matches = [member for member in MEMBERS if member in title]
    if len(title_matches) == 1:
        return title_matches[0]
    if len(title_matches) > 1:
        return "その他"
    # Only use detail text when it's a single-event detail page, and only if exactly one member is named.
    detail_matches = [member for member in MEMBERS if member in normalize(detail_text)]
    if len(detail_matches) == 1:
        return detail_matches[0]
    return "グループ全体" if not title_matches else "その他"


def classify(text: str) -> str:
    text = normalize(text)
    if any(x in text for x in ["特典会", "お渡し会", "サイン会", "リミスタ"]):
        return "特典会"
    if any(x in text for x in ["ラジオ", "RADIO", "FM "]):
        return "ラジオ"
    if any(x in text for x in ["テレビ", "TV出演", "TBS", "東海テレビ", "NHK", "BS日テレ"]):
        return "テレビ"
    if any(x in text for x in ["舞台", "ミュージカル"]):
        return "舞台"
    if any(x in text for x in ["ライブ", "コンサート", "単独公演"]):
        return "ライブ"
    if any(x in text for x in ["配信", "NATS LIVE", "YouTube"]):
        return "配信"
    if any(x in text for x in ["リリース", "発売記念", "発売キャンペーン"]):
        return "リリース"
    return "イベント"


def stable_id(source: str, d: date, title: str, url: str) -> str:
    raw = f"{source}|{d.isoformat()}|{normalize(title)}|{url}"
    return source + "-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def make_event(source: str, d: date, title: str, url: str, detail_text: str = ""):
    title = normalize(title)
    if not title or len(title) < 4 or title.startswith("▼"):
        return None
    if any(x.lower() in title.lower() for x in SKIP_TITLE):
        return None
    if not START <= d <= END:
        return None
    if source == "boys" and "bitfan.id" in url:
        return None
    member = member_for(title, detail_text)
    return {
        "id": stable_id(source, d, title, url),
        "date": d.isoformat(),
        "time": "",
        "title": title,
        "member": member,
        "type": classify(title),
        "place": "",
        "url": url,
        "notes": "公式ページから自動取得。出演者・日時・会場はリンク先で確認してください。",
        "source": source,
        "origin": "official",
        "unconfirmed": False,
    }


def month_urls():
    year, month = START.year, START.month
    while (year, month) <= (END.year, END.month):
        yield f"{BOYS_CALENDAR}/{year}/{month}"
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1


def nearest_day_heading(anchor):
    """Find the nearest preceding explicit day heading in DOM order."""
    for previous in anchor.find_all_previous(string=True):
        text = normalize(str(previous))
        if text.startswith("▼"):
            d = parse_full_date(text)
            if d:
                return d
        # Stop once we've crossed into an earlier daily block.
        d = parse_full_date(text)
        if d and re.search(r"\b20\d{2}\b", text) and len(text) < 35:
            return d
    return None


def scrape_boys_month(url: str):
    soup = get_soup(url)
    found = {}
    for anchor in soup.select("a[href]"):
        title = normalize(anchor.get_text(" ", strip=True))
        href = urldefrag(urljoin(url, anchor.get("href", "")))[0]
        if not title or len(title) < 5 or not href.startswith("https://"):
            continue
        if urlparse(href).netloc not in {"boysandmen.jp", "www.boysandmen.jp"}:
            continue
        # The day heading itself is not an event link. Also skip month-navigation anchors.
        if title.startswith("▼") or title in {"前月へ", "今月", "次月へ"}:
            continue
        if any(x in href.lower() for x in ["/login", "/privacy", "/terms"]):
            continue
        d = parse_full_date(title) or nearest_day_heading(anchor)
        if not d:
            continue
        # Regular monthly campaign announcements are not daily events.
        if "パワープレイソングに決定" in title:
            continue
        item = make_event("boys", d, title, href)
        if item:
            found[(item["date"], item["title"], item["url"])] = item
    return list(found.values()), len(normalize(soup.get_text(" ", strip=True)))


def scrape_boys():
    events, ok_pages, errors = [], 0, []
    urls = list(month_urls())
    for url in urls:
        try:
            items, chars = scrape_boys_month(url)
            events.extend(items)
            ok_pages += 1
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
            print(f"WARN BOYS {url}: {exc}", file=sys.stderr)
    # De-duplicate the same event linked from more than one monthly page.
    unique = {}
    for item in events:
        unique[(item["date"], item["title"].casefold(), item["url"])] = item
    return list(unique.values()), {
        "ok": ok_pages > 0,
        "count": len(unique),
        "pages_ok": ok_pages,
        "pages_tried": len(urls),
        "errors": errors[:8],
        "url": BOYS_CALENDAR,
    }


def collect_bitfan_links(soup, page_url):
    results = []
    for a in soup.select("a[href]"):
        title = normalize(a.get_text(" ", strip=True))
        href = urldefrag(urljoin(page_url, a.get("href", "")))[0]
        if not title or len(title) < 5 or not href.startswith(DERA_BASE):
            continue
        path = urlparse(href).path
        if not (path.startswith("/schedules/") or path.startswith("/contents/")):
            continue
        if "/menu/" in path:
            continue
        if any(x in title for x in ["Powered by", "一覧", "もっと見る"]):
            continue
        results.append((title, href))
    # Preserve first occurrence, but don't assume page/article publication date is event date.
    return list(dict.fromkeys(results))


def scrape_bitfan_index(url: str, source_key: str, page_limit: int = 3):
    events, report_errors, visited = [], [], set()
    # Try the provided index plus pagination pages. Page count is deliberately bounded.
    index_urls = [url]
    if "contents/menu" in url:
        index_urls += [url + ("&" if "?" in url else "?") + f"page={page}" for page in range(2, page_limit + 1)]
    links = []
    pages_ok = 0
    for index_url in index_urls:
        try:
            soup = get_soup(index_url)
            pages_ok += 1
            links.extend(collect_bitfan_links(soup, index_url))
        except Exception as exc:
            report_errors.append(f"{index_url}: {type(exc).__name__}: {exc}")
            print(f"WARN Bitfan index {index_url}: {exc}", file=sys.stderr)
    links = list(dict.fromkeys(links))
    # Visit event detail pages. Date must be an actual schedule date, not the post timestamp.
    for link_title, detail_url in links[:160]:
        if detail_url in visited:
            continue
        visited.add(detail_url)
        is_schedule = "/schedules/" in urlparse(detail_url).path
        try:
            detail = get_soup(detail_url)
            h1 = detail.select_one("h1")
            title = normalize(h1.get_text(" ", strip=True)) if h1 else link_title
            if not title or title in {"SCHEDULE", "NEWS"}:
                title = link_title
            body = normalize(detail.get_text(" ", strip=True))
            # A date-bearing title is safest. For schedule detail pages, parse visible schedule text.
            d = parse_full_date(title)
            if not d and is_schedule:
                d = event_date_from_detail(detail, title)
            # News detail pages without a full date in the event title are not assigned the post date.
            if not d:
                continue
            item = make_event("dera", d, title, detail_url, body)
            if item:
                events.append(item)
        except Exception as exc:
            report_errors.append(f"{detail_url}: {type(exc).__name__}: {exc}")
    unique = {}
    for item in events:
        unique[(item["date"], item["title"].casefold(), item["url"])] = item
    return list(unique.values()), {
        "ok": pages_ok > 0,
        "count": len(unique),
        "index_pages_ok": pages_ok,
        "detail_pages_found": len(links),
        "detail_pages_checked": len(visited),
        "errors": report_errors[:8],
        "url": url,
    }


def main():
    all_events = []
    report = {}

    boys_events, boys_report = scrape_boys()
    all_events.extend(boys_events)
    report["BOYS AND MEN公式"] = boys_report

    for label, url in [
        ("でらボ公式スケジュール", DERA_SCHEDULE),
        ("でらボ公式NEWS", DERA_NEWS),
    ]:
        try:
            items, stats = scrape_bitfan_index(url, "dera")
            all_events.extend(items)
            report[label] = stats
        except Exception as exc:
            report[label] = {"ok": False, "count": 0, "error": f"{type(exc).__name__}: {exc}", "url": url}
            print(f"WARN {label}: {exc}", file=sys.stderr)

    unique = {}
    for item in all_events:
        unique[(item["date"], item["title"].casefold(), item["url"])] = item
    events = sorted(unique.values(), key=lambda x: (x["date"], x["time"], x["title"].casefold()))

    output = {
        "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "range": {"from": START.isoformat(), "to": END.isoformat()},
        "sources": report,
        "events": events,
    }
    import os
    os.makedirs("data", exist_ok=True)
    with open("data/events.json", "w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)

    print(f"Wrote {len(events)} events")
    for label, stats in report.items():
        print(f"- {label}: ok={stats.get('ok')} count={stats.get('count')} "
              f"pages={stats.get('pages_ok', stats.get('index_pages_ok', '-'))}")
    if not any(stats.get("ok") for stats in report.values()):
        sys.exit("All official sources failed; check network/site markup.")


if __name__ == "__main__":
    main()
