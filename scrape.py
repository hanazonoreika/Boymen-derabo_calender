#!/usr/bin/env python3
"""Official event calendar scraper."""

import hashlib
import html
import json
import re
import sys
import os

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from urllib.parse import (
    urljoin,
    urldefrag,
    urlparse,
    urlencode,
)

import requests
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).date()

START = date(
    TODAY.year - 1,
    TODAY.month,
    min(
        TODAY.day,
        monthrange(TODAY.year - 1, TODAY.month)[1],
    ),
)

END = date(
    TODAY.year + 1,
    TODAY.month,
    min(
        TODAY.day,
        monthrange(TODAY.year + 1, TODAY.month)[1],
    ),
)

BOYS_BASE = "https://boysandmen.jp"
BOYS_CALENDAR = BOYS_BASE + "/vertical_calendar"

DERA_BASE = "https://dxboys.bitfan.id"
DERA_SCHEDULE = DERA_BASE + "/schedules/menu/184780"

DERA_API_BASE = "https://user-api.bitfan.id"
DERA_API_PAGE = DERA_SCHEDULE

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
        "AppleWebKit/537.36 "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

TIMEOUT = 25

EXCLUDED_URLS = {
    "https://boysandmen.jp/about/membership",
    "https://boysandmen.jp/about/account",
    "https://boysandmen.jp/about/law",
    "https://boysandmen.jp/help",
    "https://boysandmen.jp/about/payment",
    "https://boysandmen.jp/about/customer_harassment",
}

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
    return " ".join(
        (text or "").replace("\xa0", " ").split()
    )


def get_soup(url):
    response = SESSION.get(
        url,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    response.encoding = (
        response.apparent_encoding
        or response.encoding
    )
    return BeautifulSoup(
        response.text,
        "html.parser",
    )


def parse_full_date(text):
    """Parse only an explicit full date."""
    text = normalize(text)

    match = re.search(
        r"(20\d{2})\s*[年/.\-]\s*"
        r"(\d{1,2})\s*[月/.\-]\s*"
        r"(\d{1,2})\s*日?",
        text,
    )

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


def parse_api_datetime(value):
    """Parse an API datetime and normalize it to Japan time."""
    if not value:
        return None

    text = str(value).strip()

    try:
        parsed = datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=JST)
        else:
            parsed = parsed.astimezone(JST)

        return parsed

    except (ValueError, TypeError):
        return None


def member_for(title, detail_text=""):
    title = normalize(title)

    matches = [
        member for member in MEMBERS
        if member in title
    ]

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        return "その他"

    matches = [
        member for member in MEMBERS
        if member in normalize(detail_text)
    ]

    if len(matches) == 1:
        return matches[0]

    return "グループ全体"


def classify(text):
    text = normalize(text)

    if any(
        word in text
        for word in [
            "特典会",
            "お渡し会",
            "サイン会",
            "リミスタ",
        ]
    ):
        return "特典会"

    if any(
        word in text
        for word in ["ラジオ", "RADIO", "FM "]
    ):
        return "ラジオ"

    if any(
        word in text
        for word in [
            "テレビ",
            "TV出演",
            "NHK",
            "東海テレビ",
            "TBS",
        ]
    ):
        return "テレビ"

    if any(
        word in text
        for word in ["舞台", "ミュージカル", "公演"]
    ):
        return "舞台"

    if any(
        word in text
        for word in [
            "ライブ",
            "コンサート",
            "単独公演",
        ]
    ):
        return "ライブ"

    if any(
        word in text
        for word in ["配信", "YouTube"]
    ):
        return "配信"

    if any(
        word in text
        for word in ["リリース", "発売記念"]
    ):
        return "リリース"

    return "イベント"


def should_skip_title(title):
    title = normalize(title)

    if len(title) < 4 or title.startswith("▼"):
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

    normalized_url = f"https://boysandmen.jp{path}"

    if normalized_url in {
        url.rstrip("/")
        for url in EXCLUDED_URLS
    }:
        return True

    if (
        path == "/vertical_calendar"
        or path.startswith("/vertical_calendar/")
    ):
        return True

    for prefix in EXCLUDED_PATHS:
        if path == prefix or path.startswith(prefix + "/"):
            return True

    return False


def make_event(
    source,
    event_date,
    title,
    url,
    detail_text="",
    event_time="",
    place="",
):
    title = normalize(title)

    if should_skip_title(title):
        return None

    if not START <= event_date <= END:
        return None

    if source == "boys" and is_excluded_boys_url(url):
        return None

    raw_id = (
        f"{source}|{event_date.isoformat()}|"
        f"{title}|{url}"
    )

    event_id = hashlib.sha256(
        raw_id.encode("utf-8")
    ).hexdigest()[:16]

    return {
        "id": f"{source}-{event_id}",
        "date": event_date.isoformat(),
        "time": event_time,
        "title": title,
        "member": member_for(title, detail_text),
        "type": classify(title),
        "place": normalize(place),
        "url": url,
        "notes": (
            "公式ページから自動取得。"
            "日時・出演者・会場はリンク先で確認してください。"
        ),
        "source": source,
        "origin": "official",
        "unconfirmed": False,
    }


# --------------------------------------------------
# BOYS AND MEN公式カレンダー
# --------------------------------------------------

def iter_month_urls():
    year = START.year
    month = START.month

    while (year, month) <= (END.year, END.month):
        yield f"{BOYS_CALENDAR}/{year}/{month}"

        if month == 12:
            year += 1
            month = 1
        else:
            month += 1


def day_from_panel_id(node):
    node_id = node.get("id", "")

    match = re.search(
        r"(?:collapse|schedule|day)[-_]?"
        r"((?:20\d{2})\d{4})",
        node_id,
        re.I,
    )

    if not match:
        return None

    try:
        return datetime.strptime(
            match.group(1),
            "%Y%m%d",
        ).date()
    except ValueError:
        return None


def nearest_heading_date(anchor):
    for tag in anchor.find_all_previous(
        ["h1", "h2", "h3", "h4", "strong", "b"],
        limit=20,
    ):
        text = normalize(
            tag.get_text(" ", strip=True)
        )

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
        for panel, event_date in panels:
            for anchor in panel.select("a[href]"):
                title = normalize(
                    anchor.get_text(" ", strip=True)
                )

                event_url = urldefrag(
                    urljoin(
                        url,
                        anchor.get("href", ""),
                    )
                )[0]

                if (
                    should_skip_title(title)
                    or not event_url.startswith("https://")
                ):
                    continue

                if is_excluded_boys_url(event_url):
                    continue

                item = make_event(
                    "boys",
                    event_date,
                    title,
                    event_url,
                )

                if item:
                    found[
                        (
                            item["date"],
                            item["title"],
                            item["url"],
                        )
                    ] = item

    else:
        for anchor in soup.select("a[href]"):
            title = normalize(
                anchor.get_text(" ", strip=True)
            )

            event_url = urldefrag(
                urljoin(
                    url,
                    anchor.get("href", ""),
                )
            )[0]

            if (
                should_skip_title(title)
                or not event_url.startswith("https://")
            ):
                continue

            if is_excluded_boys_url(event_url):
                continue

            event_date = (
                parse_full_date(title)
                or nearest_heading_date(anchor)
            )

            if not event_date:
                continue

            item = make_event(
                "boys",
                event_date,
                title,
                event_url,
            )

            if item:
                found[
                    (
                        item["date"],
                        item["title"],
                        item["url"],
                    )
                ] = item

    return list(found.values())


def scrape_boys():
    all_events = []
    errors = []
    pages_ok = 0

    urls = list(iter_month_urls())

    for url in urls:
        try:
            all_events.extend(
                scrape_boys_month(url)
            )
            pages_ok += 1

        except Exception as exc:
            errors.append(
                f"{url}: {type(exc).__name__}: {exc}"
            )
            print(
                f"WARN BOYS {url}: {exc}",
                file=sys.stderr,
            )

    unique = {}

    for item in all_events:
        unique[
            (
                item["date"],
                item["title"].casefold(),
                item["url"],
            )
        ] = item

    return list(unique.values()), {
        "ok": pages_ok > 0,
        "count": len(unique),
        "pages_ok": pages_ok,
        "pages_tried": len(urls),
        "errors": errors[:8],
        "url": BOYS_CALENDAR,
    }


# --------------------------------------------------
# でらボ公式スケジュール API
# --------------------------------------------------

def get_derabo_token():
    """Read the public calendar page's JWT meta tag."""
    response = SESSION.get(
        DERA_API_PAGE,
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    token_tag = soup.select_one(
        'meta[name="jwt-token"]'
    )

    if not token_tag:
        raise RuntimeError(
            "公式ページにjwt-tokenが見つかりません。"
        )

    token = normalize(
        token_tag.get("content", "")
    )

    if not token:
        raise RuntimeError(
            "jwt-tokenのcontentが空です。"
        )

    return token


def iter_derabo_months():
    """Yield month start and next-month start."""
    year = START.year
    month = START.month

    while (year, month) <= (END.year, END.month):
        month_start = date(year, month, 1)

        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)

        yield month_start, next_month

        year, month = next_month.year, next_month.month


def make_derabo_detail_url(schedule):
    schedule_id = schedule.get("id")

    if schedule_id is None:
        return DERA_SCHEDULE

    token = schedule.get("encoded_repeat_token")

    query = ""

    if token:
        query = "?" + urlencode({"r": str(token)})

    return (
        f"{DERA_BASE}/schedules/{schedule_id}"
        f"{query}"
    )


def get_schedules_from_payload(payload):
    """Support the JSON response shapes used by the API."""
    if isinstance(payload, dict):
        data = payload.get("data", payload)

        if isinstance(data, dict):
            schedules = data.get("schedules")

            if isinstance(schedules, list):
                return schedules

        if isinstance(data, list):
            return data

    return []


def scrape_derabo():
    events = []
    errors = []
    months_checked = 0
    requests_ok = 0
    api_records = 0

    try:
        jwt_token = get_derabo_token()

    except Exception as exc:
        return [], {
            "ok": False,
            "count": 0,
            "api_records": 0,
            "months_checked": 0,
            "requests_ok": 0,
            "errors": [
                f"トークン取得失敗: "
                f"{type(exc).__name__}: {exc}"
            ],
            "url": DERA_SCHEDULE,
            "api_url": (
                DERA_API_BASE
                + "/fanclubs/dxboys/schedules"
            ),
        }

    api_url = (
        DERA_API_BASE
        + "/fanclubs/dxboys/schedules"
    )

    api_headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/json",
        "Referer": DERA_SCHEDULE,
    }

    for month_start, next_month in iter_derabo_months():
        params = {
            "from_date": month_start.isoformat(),
            "to_date": next_month.isoformat(),
        }

        try:
            response = SESSION.get(
                api_url,
                params=params,
                headers=api_headers,
                timeout=TIMEOUT,
            )

            months_checked += 1

            if response.status_code in (401, 403):
                errors.append(
                    f"{params['from_date']}: "
                    f"API認証エラー HTTP "
                    f"{response.status_code}"
                )
                continue

            response.raise_for_status()

            try:
                payload = response.json()
            except ValueError as exc:
                errors.append(
                    f"{params['from_date']}: "
                    f"JSON解析失敗: {exc}"
                )
                continue

            schedules = get_schedules_from_payload(
                payload
            )

            requests_ok += 1
            api_records += len(schedules)

            for schedule in schedules:
                if not isinstance(schedule, dict):
                    continue

                title = normalize(
                    html.unescape(
                        str(schedule.get("title") or "")
                    )
                )

                if not title or should_skip_title(title):
                    continue

                start_value = (
                    schedule.get("start_datetime")
                    or schedule.get("start_date")
                )

                start_dt = parse_api_datetime(
                    start_value
                )

                if start_dt:
                    event_date = start_dt.date()
                    event_time = start_dt.strftime("%H:%M")
                else:
                    event_date = parse_full_date(
                        str(start_value or "")
                    )
                    event_time = ""

                if not event_date:
                    errors.append(
                        f"日付を解析できない予定: {title}"
                    )
                    continue

                detail_url = make_derabo_detail_url(
                    schedule
                )

                end_dt = parse_api_datetime(
                    schedule.get("end_datetime")
                )

                place = (
                    schedule.get("place")
                    or schedule.get("venue")
                    or schedule.get("location")
                    or ""
                )

                item = make_event(
                    "dera",
                    event_date,
                    title,
                    detail_url,
                    detail_text="",
                    event_time=event_time,
                    place=str(place),
                )

                if item:
                    if end_dt:
                        item["notes"] += (
                            " 終了日時: "
                            + end_dt.strftime(
                                "%Y-%m-%d %H:%M"
                            )
                            + "。"
                        )

                    events.append(item)

        except Exception as exc:
            errors.append(
                f"{params['from_date']}～"
                f"{params['to_date']}: "
                f"{type(exc).__name__}: {exc}"
            )

            print(
                "WARN DERA API "
                f"{params['from_date']}: {exc}",
                file=sys.stderr,
            )

    unique = {}

    for item in events:
        unique[
            (
                item["date"],
                item["title"].casefold(),
                item["url"],
            )
        ] = item

    return list(unique.values()), {
        "ok": requests_ok > 0,
        "count": len(unique),
        "api_records": api_records,
        "months_checked": months_checked,
        "requests_ok": requests_ok,
        "errors": errors[:12],
        "url": DERA_SCHEDULE,
        "api_url": api_url,
    }


# --------------------------------------------------
# メイン処理・JSON出力
# --------------------------------------------------

def main():
    events = []
    report = {}

    boys_events, report["BOYS AND MEN公式"] = (
        scrape_boys()
    )
    events.extend(boys_events)

    dera_events, report["でらボ公式スケジュール"] = (
        scrape_derabo()
    )
    events.extend(dera_events)

    report["でらボ公式NEWS"] = {
        "ok": True,
        "count": 0,
        "note": (
            "NEWS掲載日を開催日と誤認しないため"
            "自動登録対象外。"
        ),
        "url": DERA_BASE + "/",
    }

    unique = {}

    for item in events:
        unique[
            (
                item["date"],
                item["title"].casefold(),
                item["url"],
            )
        ] = item

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

    os.makedirs("data", exist_ok=True)

    with open(
        "data/events.json",
        "w",
        encoding="utf-8",
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
        print(
            json.dumps(
                status,
                ensure_ascii=False,
                indent=2,
            )
        )

    if not any(
        status.get("ok")
        for status in report.values()
    ):
        sys.exit(
            "All official sources failed; "
            "check network or site markup."
        )


if __name__ == "__main__":
    main()
