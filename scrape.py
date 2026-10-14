#!/usr/bin/env python3
"""BOYS AND MEN / でらボ 公式予定取得プログラム"""

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

START = date(
    TODAY.year - 1,
    TODAY.month,
    min(TODAY.day, monthrange(TODAY.year - 1, TODAY.month)[1]),
)
END = date(
    TODAY.year + 1,
    TODAY.month,
    min(TODAY.day, monthrange(TODAY.year + 1, TODAY.month)[1]),
)

BOYS_BASE = "https://boysandmen.jp"
BOYS_CALENDAR = BOYS_BASE + "/vertical_calendar"
DERA_BASE = "https://dxboys.bitfan.id"
DERA_SCHEDULE = DERA_BASE + "/schedules/menu/184780"

MEMBERS = [
    "辻本達規",
    "田村侑久",
    "本田剛文",
    "平松賢人",
    "吉原雅斗",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)
TIMEOUT = 25

# 予定ではない共通メニュー・案内ページ
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
EXCLUDED_URLS = {
    "https://boysandmen.jp/about/membership",
    "https://boysandmen.jp/about/account",
    "https://boysandmen.jp/about/law",
    "https://boysandmen.jp/help",
    "https://boysandmen.jp/about/payment",
    "https://boysandmen.jp/about/customer_harassment",
}

# 予定ではないリンク名
SKIP_TITLES = [
    "F.ENT IDについて",
    "お客さまへのお願い",
    "お支払いについて",
    "よくあるご質問",
    "よくある質問",
    "ボイメン☆ファミリーとは",
    "特商法に基づく表示",
    "お問い合わせ",
    "お問合せ",
    "会社概要",
    "プライバシーポリシー",
    "利用規約",
    "サイトマップ",
    "ログイン",
    "ログアウト",
    "会員登録",
    "ファンクラブ",
    "Powered by",
    "前月へ",
    "次月へ",
    "パワープレイソングに決定",
    "HOME",
    "トップページ",
    "SCHEDULE",
    "NEWS",
]


def normalize(text):
    return " ".join((text or "").replace("\xa0", " ").split())


def get_soup(url):
    response = SESSION.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = (
        response.apparent_encoding or response.encoding
    )
    return BeautifulSoup(response.text, "html.parser")


def parse_full_date(text):
    """年・月・日が明記された日付だけを認識する。"""
    text = normalize(text)

    pattern = (
        r"(20\d{2})\s*[年/.\-]\s*"
        r"(\d{1,2})\s*[月/.\-]\s*"
        r"(\d{1,2})\s*日?"
    )

    match = re.search(pattern, text)

    if not match:
        return None

    try:
        return date(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )
    except ValueError:
        return None


def member_for(title, detail_text=""):
    """タイトルを優先し、ページ全体からメンバーを誤判定しない。"""
    title = normalize(title)

    matches = [m for m in MEMBERS if m in title]

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        return "その他"

    # 個別イベントの詳細ページに限り、本文も確認する。
    matches = [
        m for m in MEMBERS
        if m in normalize(detail_text)
    ]

    if len(matches) == 1:
        return matches[0]

    return "グループ全体"


def classify(text):
    text = normalize(text)

    if any(x in text for x in [
        "特典会", "お渡し会", "サイン会", "リミスタ"
    ]):
        return "特典会"

    if any(x in text for x in ["ラジオ", "RADIO", "FM "]):
        return "ラジオ"

    if any(x in text for x in [
        "テレビ", "TV出演", "NHK", "東海テレビ", "TBS"
    ]):
        return "テレビ"

    if any(x in text for x in ["舞台", "ミュージカル"]):
        return "舞台"

    if any(x in text for x in [
        "ライブ", "コンサート", "単独公演"
    ]):
        return "ライブ"

    if any(x in text for x in ["配信", "YouTube"]):
        return "配信"

    if any(x in text for x in ["リリース", "発売記念"]):
        return "リリース"

    return "イベント"


def is_skipped_title(title):
    title = normalize(title)

    if not title or len(title) < 4:
        return True

    if title.startswith("▼"):
        return True

    return any(
        word.casefold() in title.casefold()
        for word in SKIP_TITLES
    )


def is_excluded_boys_url(url):
    parsed = urlparse(url)

    if parsed.netloc.lower() not in {
        "boysandmen.jp",
        "www.boysandmen.jp",
    }:
        return True

    path = parsed.path.rstrip("/") or "/"

    # カレンダー自体へのリンクはイベントではない
    if path == "/vertical_calendar":
        return True

    if path.startswith("/vertical_calendar/"):
        return True

    # サイト共通の案内・アカウントページを除外
    for prefix in EXCLUDED_PATHS:
        if path == prefix or path.startswith(prefix + "/"):
            return True

    return False


def make_event(source, event_date, title, url, detail_text=""):
    title = normalize(title)

    if is_skipped_title(title):
        return None

    if not START <= event_date <= END:
            return None

        if source == "boys" and is_excluded_boys_url(url):
            return None

        if source == "boys" and url.rstrip("/") in EXCLUDED_URLS:
            return None

    raw_id = (
        f"{source}|{event_date.isoformat()}|{title}|{url}"
    )
    event_id = hashlib.sha256(
        raw_id.encode("utf-8")
    ).hexdigest()[:16]

    return {
        "id": f"{source}-{event_id}",
        "date": event_date.isoformat(),
        "time": "",
        "title": title,
        "member": member_for(title, detail_text),
        "type": classify(title),
        "place": "",
        "url": url,
        "notes": (
            "公式ページから自動取得。"
            "日時・出演者・会場はリンク先で確認してください。"
        ),
        "source": source,
        "origin": "official",
        "unconfirmed": False,
    }


def iter_month_urls():
    """対象期間の月別カレンダーURLを作る。"""
    year, month = START.year, START.month

    while (year, month) <= (END.year, END.month):
        yield f"{BOYS_CALENDAR}/{year}/{month}"

        if month == 12:
            year += 1
            month = 1
        else:
            month += 1


def get_day_container(anchor):
    """
    日付ごとのカレンダー領域を探す。
    ページ全体やフッターから日付を拾わない。
    """
    node = anchor

    for _ in range(7):
        if node is None:
            break

        node_id = node.get("id", "")

        match = re.search(
            r"(?:collapse|schedule|day)[-_]?"
            r"((?:20\d{2})\d{4})",
            node_id,
            re.IGNORECASE,
        )

        if match:
            try:
                event_date = datetime.strptime(
                    match.group(1), "%Y%m%d"
                ).date()

                return node, event_date
            except ValueError:
                pass

        node = node.parent

    return None, None


def nearest_day_heading(anchor):
    """
    リンクの直前にある、明示的な日付見出しだけを探す。
    """
    tags = anchor.find_all_previous(
        ["h1", "h2", "h3", "h4", "strong", "b"],
        limit=20,
    )

    for tag in tags:
        text = normalize(tag.get_text(" ", strip=True))

        if len(text) > 45:
            continue

        event_date = parse_full_date(text)

        if event_date:
            return event_date

    return None


def scrape_boys_month(url):
    soup = get_soup(url)
    found = {}

    # まず日付ごとのパネルを探す
    panels = []

    for node in soup.find_all(id=True):
        match = re.search(
            r"(?:collapse|schedule|day)[-_]?"
            r"((?:20\d{2})\d{4})",
            node.get("id", ""),
            re.IGNORECASE,
        )

        if not match:
            continue

        try:
            event_date = datetime.strptime(
                match.group(1), "%Y%m%d"
            ).date()
            panels.append((node, event_date))
        except ValueError:
            continue

    if panels:
        # パネル内のリンクだけを候補にする
        for panel, event_date in panels:
            for anchor in panel.select("a[href]"):
                title = normalize(
                    anchor.get_text(" ", strip=True)
                )

                event_url = urldefrag(
                    urljoin(url, anchor.get("href", ""))
                )[0]

                if not title or is_skipped_title(title):
                    continue

                if not event_url.startswith("https://"):
                    continue

                if is_excluded_boys_url(event_url):
                    continue

                item = make_event(
                    "boys", event_date, title, event_url
                )

                if item:
                    key = (
                        item["date"],
                        item["title"],
                        item["url"],
                    )
                    found[key] = item

    else:
        # 日付パネルを認識できない場合の安全側の処理。
        # 親要素全体の文章から日付を推測しない。
        for anchor in soup.select("a[href]"):
            title = normalize(
                anchor.get_text(" ", strip=True)
            )

            event_url = urldefrag(
                urljoin(url, anchor.get("href", ""))
            )[0]

            if not title or is_skipped_title(title):
                continue

            if not event_url.startswith("https://"):
                continue

            if is_excluded_boys_url(event_url):
                continue

            event_date = parse_full_date(title)

            if not event_date:
                event_date = nearest_day_heading(anchor)

            if not event_date:
                continue

            item = make_event(
                "boys", event_date, title, event_url
            )

            if item:
                key = (
                    item["date"],
                    item["title"],
                    item["url"],
                )
                found[key] = item

    return list(found.values())


def scrape_boys():
    all_events = []
    errors = []
    pages_ok = 0
    urls = list(iter_month_urls())

    for url in urls:
        try:
            items = scrape_boys_month(url)
            all_events.extend(items)
            pages_ok += 1

        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
            print(f"WARN BOYS {url}: {exc}", file=sys.stderr)

    unique = {}

    for item in all_events:
        key = (
            item["date"],
            item["title"].casefold(),
            item["url"],
        )
        unique[key] = item

    return list(unique.values()), {
        "ok": pages_ok > 0,
        "count": len(unique),
        "pages_ok": pages_ok,
        "pages_tried": len(urls),
        "errors": errors[:8],
        "url": BOYS_CALENDAR,
    }


def collect_bitfan_links(soup, page_url):
    links = []

    for anchor in soup.select("a[href]"):
        title = normalize(anchor.get_text(" ", strip=True))

        href = urldefrag(
            urljoin(page_url, anchor.get("href", ""))
        )[0]

        if not title or len(title) < 4:
            continue

        if not href.startswith(DERA_BASE):
            continue

        path = urlparse(href).path

        # NEWS記事は開催日と掲載日を区別できないため除外
        if not path.startswith("/schedules/"):
            continue

        if "/menu/" in path:
            continue

        if is_skipped_title(title):
            continue

        links.append((title, href))

    return list(dict.fromkeys(links))


def get_detail_date(soup, title):
    # タイトルに開催日が明記されている場合
    event_date = parse_full_date(title)

    if event_date:
        return event_date

    # 個別スケジュールページの日時欄を優先
    for selector in [
        "time[datetime]",
        ".schedule-date",
        ".event-date",
        ".date",
    ]:
        node = soup.select_one(selector)

        if not node:
            continue

        if node.name == "time" and node.get("datetime"):
            event_date = parse_full_date(node["datetime"])
        else:
            event_date = parse_full_date(
                node.get_text(" ", strip=True)
            )

        if event_date:
            return event_date

    # ページ全体の日付は掲載日と混同するため使用しない
    return None


def scrape_derabo():
    events = []
    errors = []

    try:
        soup = get_soup(DERA_SCHEDULE)
    except Exception as exc:
        return [], {
            "ok": False,
            "count": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "url": DERA_SCHEDULE,
        }

    links = collect_bitfan_links(soup, DERA_SCHEDULE)
    checked = 0

    for link_title, detail_url in links[:150]:
        try:
            detail = get_soup(detail_url)
            checked += 1

            heading = detail.select_one("h1")
            title = (
                normalize(heading.get_text(" ", strip=True))
                if heading
                else link_title
            )

            if not title:
                title = link_title

            event_date = get_detail_date(detail, title)

            # 日付を確定できない予定は登録しない
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
        "ok": True,
        "count": len(unique),
        "detail_links_found": len(links),
        "detail_pages_checked": checked,
        "errors": errors[:8],
        "url": DERA_SCHEDULE,
    }


def main():
    events = []
    report = {}

    boys_events, boys_status = scrape_boys()
    events.extend(boys_events)
    report["BOYS AND MEN公式"] = boys_status

    dera_events, dera_status = scrape_derabo()
    events.extend(dera_events)
    report["でらボ公式スケジュール"] = dera_status

    # NEWS記事の掲載日を開催日として誤登録しない
    report["でらボ公式NEWS"] = {
        "ok": True,
        "count": 0,
        "note": (
            "NEWS記事の掲載日とイベント開催日を"
            "混同しないため、自動登録対象外です。"
        ),
        "url": DERA_BASE + "/",
    }

    unique = {}

    for item in events:
        key = (
            item["date"],
            item["title"].casefold(),
            item["url"],
        )
        unique[key] = item

    sorted_events = sorted(
        unique.values(),
        key=lambda item: (
            item["date"],
            item["time"],
            item["title"].casefold(),
        ),
    )

    data = {
        "updated_at": datetime.now(JST).isoformat(
            timespec="seconds"
        ),
        "range": {
            "from": START.isoformat(),
            "to": END.isoformat(),
        },
        "sources": report,
        "events": sorted_events,
    }

    import os

    os.makedirs("data", exist_ok=True)

    with open(
        "data/events.json", "w", encoding="utf-8"
    ) as output:
        json.dump(
            data,
            output,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Wrote {len(sorted_events)} events")

    for name, status in report.items():
        print(
            f"- {name}: "
            f"ok={status.get('ok')} "
            f"count={status.get('count')}"
        )

    if not any(status.get("ok") for status in report.values()):
        sys.exit(
            "All official sources failed; "
            "check network or site markup."
        )


if __name__ == "__main__":
    main()
