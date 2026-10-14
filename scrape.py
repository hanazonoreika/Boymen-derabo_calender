#!/usr/bin/env python3
"""Unofficial calendar scraper. Conservative by design: don't invent event dates."""
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

BOYS_BASE = "https://boysandmen.jp"
BOYS_CALENDAR = BOYS_BASE + "/vertical_calendar"
DERA_BASE = "https://dxboys.bitfan.id"
DERA_SCHEDULE = DERA_BASE + "/schedules/menu/184780"

MEMBERS = ["辻本達規", "田村侑久", "本田剛文", "平松賢人", "吉原雅斗"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
TIMEOUT = 25

# Exact URLs supplied by the user. Trailing slashes are normalized before comparison.
EXCLUDED_URLS = {
    "https://boysandmen.jp/about/membership",
    "https://boysandmen.jp/about/account",
    "https://boysandmen.jp/about/law",
    "https://boysandmen.jp/help",
    "https://boysandmen.jp/about/payment",
    "https://boysandmen.jp/about/customer_harassment",
}

# Entire site-wide information sections should not be treated as event pages.
EXCLUDED_PATHS = (
    "/about",
    "/help",
    "/contact",
    "/faq",
    "/privacy",
    "/terms",
    "/law",
    "/sitemap",
    "/login",
    "/signup",
    "/account",
    "/cart",
    "/mypage",
    "/company",
)

SKIP_TITLES = [
    "F.ENT IDについて", "お客さまへのお願い", "お支払いについて",
    "よくあるご質問", "よくある質問", "ボイメン☆ファミリーとは",
    "特商法に基づく表示", "お問い合わせ", "お問合せ", "会社概要",
    "プライバシーポリシー", "利用規約", "サイトマップ", "ログイン",
    "ログアウト", "会員登録", "ファンクラブ", "Powered by",
    "前月へ", "次月へ", "パワープレイソングに決定",
    "HOME", "トップページ", "SCHEDULE", "NEWS",
]

def normalize(text):
    return " ".join((text or "").replace("\xa0", " ").split())

def get_soup(url):
    response = SESSION.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return BeautifulSoup(response.text, "html.parser")

def parse_full_date(text):
    """Only parse explicit full dates. Never infer dates from publication context."""
    text = normalize(text)
    match = re.search(
        r"(20\d{2})\s*[年/.\-]\s*(\d{1,2})\s*[月/.\-]\s*(\d{1,2})\s*日?",
        text,
    )
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None

def member_for(title, detail_text=""):
    """Prefer the event title so unrelated mentions elsewhere don't override it."""
    title = normalize(title)
    matches = [member for member in MEMBERS if member in title]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return "その他"
    # Detail text is only used for a single-event detail page, never a monthly page.
    matches = [member for member in MEMBERS if member in normalize(detail_text)]
    if len(matches) == 1:
        return matches[0]
    return "グループ全体"

def classify(text):
    text = normalize(text)
    if any(x in text for x in ["特典会", "お渡し会", "サイン会", "リミスタ"]):
        return "特典会"
    if any(x in text for x in ["ラジオ", "RADIO", "FM "]):
        return "ラジオ"
    if any(x in text for x in ["テレビ", "TV出演", "NHK", "東海テレビ", "TBS"]):
        return "テレビ"
    if any(x in text for x in ["舞台", "ミュージカル", "公演"]):
        return "舞台"
    if any(x in text for x in ["ライブ", "コンサート", "単独公演"]):
        return "ライブ"
    if any(x in text for x in ["配信", "YouTube"]):
        return "配信"
    if any(x in text for x in ["リリース", "発売記念"]):
        return "リリース"
    return "イベント"

def should_skip_title(title):
    title = normalize(title)
    if len(title) < 4 or title.startswith("▼"):
        return True
    return any(word.casefold() in title.casefold() for word in SKIP_TITLES)

def is_excluded_boys_url(url):
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"boysandmen.jp", "www.boysandmen.jp"}:
        return True
    path = parsed.path.rstrip("/") or "/"
    normalized_url = f"https://boysandmen.jp{path}"
    if normalized_url in {u.rstrip("/") for u in EXCLUDED_URLS}:
        return True
    if path == "/vertical_calendar" or path.startswith("/vertical_calendar/"):
        return True
    for prefix in EXCLUDED_PATHS:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False

def make_event(source, event_date, title, url, detail_text=""):
    title = normalize(title)
    if should_skip_title(title):
        return None
    if not START <= event_date <= END:
        return None
    if source == "boys" and is_excluded_boys_url(url):
        return None

    raw_id = f"{source}|{event_date.isoformat()}|{title}|{url}"
    event_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16]
    return {
        "id": f"{source}-{event_id}",
        "date": event_date.isoformat(),
        "time": "",
        "title": title,
        "member": member_for(title, detail_text),
        "type": classify(title),
        "place": "",
        "url": url,
        "notes": "公式ページから自動取得。日時・出演者・会場はリンク先で確認してください。",
        "source": source,
        "origin": "official",
        "unconfirmed": False,
    }

def iter_month_urls():
    year, month = START.year, START.month
    while (year, month) <= (END.year, END.month):
        yield f"{BOYS_CALENDAR}/{year}/{month}"
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1

def day_from_panel_id(node):
    node_id = node.get("id", "")
    match = re.search(r"(?:collapse|schedule|day)[-_]?((?:20\d{2})\d{4})", node_id, re.I)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError:
        return None

def nearest_heading_date(anchor):
    # Only explicit date headings; never scan the whole parent or page footer.
    for tag in anchor.find_all_previous(["h1", "h2", "h3", "h4", "strong", "b"], limit=20):
        text = normalize(tag.get_text(" ", strip=True))
        if len(text) <= 45:
            event_date = parse_full_date(text)
            if event_date:
                return event_date
    return None

def scrape_boys_month(url):
    soup = get_soup(url)
    found = {}
    panels = []
    for node in soup.find_all(id=True):
        event_date = day_from_panel_id(node)
        if event_date:
            panels.append((node, event_date))

    if panels:
        # Read only links inside identifiable date panels.
        for panel, event_date in panels:
            for anchor in panel.select("a[href]"):
                title = normalize(anchor.get_text(" ", strip=True))
                event_url = urldefrag(urljoin(url, anchor.get("href", "")))[0]
                if should_skip_title(title) or not event_url.startswith("https://"):
                    continue
                if is_excluded_boys_url(event_url):
                    continue
                item = make_event("boys", event_date, title, event_url)
                if item:
                    found[(item["date"], item["title"], item["url"])] = item
    else:
        # Conservative fallback: title date or nearby explicit heading only.
        # If the page markup doesn't expose a reliable date, don't invent one.
        for anchor in soup.select("a[href]"):
            title = normalize(anchor.get_text(" ", strip=True))
            event_url = urldefrag(urljoin(url, anchor.get("href", "")))[0]
            if should_skip_title(title) or not event_url.startswith("https://"):
                continue
            if is_excluded_boys_url(event_url):
                continue
            event_date = parse_full_date(title) or nearest_heading_date(anchor)
            if not event_date:
                continue
            item = make_event("boys", event_date, title, event_url)
            if item:
                found[(item["date"], item["title"], item["url"])] = item
    return list(found.values())

def scrape_boys():
    all_events, errors, pages_ok = [], [], 0
    urls = list(iter_month_urls())
    for url in urls:
        try:
            all_events.extend(scrape_boys_month(url))
            pages_ok += 1
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
            print(f"WARN BOYS {url}: {exc}", file=sys.stderr)
    unique = {}
    for item in all_events:
        unique[(item["date"], item["title"].casefold(), item["url"])] = item
    return list(unique.values()), {
        "ok": pages_ok > 0,
        "count": len(unique),
        "pages_ok": pages_ok,
        "pages_tried": len(urls),
        "errors": errors[:8],
        "url": BOYS_CALENDAR,
    }
def get_schedule_detail_date(soup, title):
    # タイトルに日付が含まれていれば優先
    event_date = parse_full_date(title)
    if event_date:
        return event_date

    # 個別ページのSCHEDULE欄から開催日を探す
    text = soup.get_text("\n", strip=True)
    lines = [normalize(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    for i, line in enumerate(lines):
        if line.upper() == "SCHEDULE":
            for candidate in lines[i + 1:i + 8]:
                event_date = parse_full_date(candidate)
                if event_date:
                    return event_date

    # ページ内の明示的な日付を探す
    for line in lines:
        event_date = parse_full_date(line)
        if event_date:
            return event_date

    return None
def collect_derabo_schedule_links(soup, page_url):
    links = {}

    for anchor in soup.select("a[href]"):
        href = urldefrag(
            urljoin(page_url, anchor.get("href", ""))
        )[0]
        parsed = urlparse(href)

        if parsed.netloc.lower() not in {
            "dxboys.bitfan.id",
            "www.dxboys.bitfan.id",
        }:
            continue

        # /schedules/数字 の個別ページだけを取得
        match = re.match(r"^/schedules/(\d+)/?$", parsed.path)
        if not match:
            continue

        # クエリ文字列を除いたURLに統一
        detail_url = f"{DERA_BASE}/schedules/{match.group(1)}"

        # リンク文字が空でも捨てない
        title = normalize(anchor.get_text(" ", strip=True))
        if title and should_skip_title(title):
            title = ""

        # 同じURLが複数あれば、文字があるタイトルを優先
        if detail_url not in links or (
            title and not links[detail_url]
        ):
            links[detail_url] = title

    return [(title, href) for href, title in links.items()]


def scrape_derabo():
    events = []
    errors = []
    pages_checked = 0
    links_by_url = {}

    # 予定一覧ページに加えて、公式トップページからも探す
    for list_url in [DERA_SCHEDULE, DERA_BASE + "/"]:
        try:
            soup = get_soup(list_url)
            found = collect_derabo_schedule_links(soup, list_url)

            for title, href in found:
                links_by_url[href] = title

        except Exception as exc:
            errors.append(
                f"{list_url}: {type(exc).__name__}: {exc}"
            )

    # 個別ページを取得し、開催日を確認
    for detail_url, link_title in list(links_by_url.items())[:150]:
        try:
            detail = get_soup(detail_url)
            pages_checked += 1

            heading = detail.select_one("h1")
            title = (
                normalize(heading.get_text(" ", strip=True))
                if heading else link_title
            )

            if not title:
                title = link_title

            event_date = get_schedule_detail_date(detail, title)

            if not event_date:
                # 個別ページの表示テキストからも日付を探す
                text = detail.get_text("\n", strip=True)
                event_date = parse_full_date(text)

            if not event_date:
                continue

            body = normalize(detail.get_text(" ", strip=True))
            item = make_event(
                "dera", event_date, title, detail_url, body
            )

            if item:
                events.append(item)

        except Exception as exc:
            errors.append(
                f"{detail_url}: {type(exc).__name__}: {exc}"
            )

    unique = {}
    for item in events:
        key = (
            item["date"],
            item["title"].casefold(),
            item["url"],
        )
        unique[key] = item

    return list(unique.values()), {
        "ok": bool(links_by_url) and pages_checked > 0,
        "count": len(unique),
        "detail_links_found": len(links_by_url),
        "detail_pages_checked": pages_checked,
        "errors": errors[:8],
        "url": DERA_SCHEDULE,
        "list_pages_checked": [DERA_SCHEDULE, DERA_BASE + "/"],
    }

def main():
    events = []
    report = {}

    boys_events, report["BOYS AND MEN公式"] = scrape_boys()
    events.extend(boys_events)

    dera_events, report["でらボ公式スケジュール"] = scrape_derabo()
    events.extend(dera_events)

    # NEWS publication dates are not event dates, so do not auto-add NEWS items.
    report["でらボ公式NEWS"] = {
        "ok": True,
        "count": 0,
        "note": "NEWS掲載日を開催日と誤認しないため自動登録対象外。",
        "url": DERA_BASE + "/",
    }

    unique = {}
    for item in events:
        unique[(item["date"], item["title"].casefold(), item["url"])] = item
    sorted_events = sorted(
        unique.values(),
        key=lambda item: (item["date"], item["time"], item["title"].casefold()),
    )

    data = {
        "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "range": {"from": START.isoformat(), "to": END.isoformat()},
        "sources": report,
        "events": sorted_events,
    }

    import os
    os.makedirs("data", exist_ok=True)
    with open("data/events.json", "w", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2)

    print(f"Wrote {len(sorted_events)} events")
    for name, status in report.items():
        print(f"- {name}: ok={status.get('ok')} count={status.get('count')}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if not any(status.get("ok") for status in report.values()):
        sys.exit("All official sources failed; check network or site markup.")

if __name__ == "__main__":
    main()
