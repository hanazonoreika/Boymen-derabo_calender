
#!/usr/bin/env python3
"""Official event calendar scraper with ticket-period extraction."""

import hashlib
import html
import json
import re
import sys
import os

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin, urldefrag, urlparse, urlencode

import requests
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).date()

START = date(
    TODAY.year - 1, TODAY.month,
    min(TODAY.day, monthrange(TODAY.year - 1, TODAY.month)[1])
)
END = date(
    TODAY.year + 1, TODAY.month,
    min(TODAY.day, monthrange(TODAY.year + 1, TODAY.month)[1])
)

BOYS_BASE = "https://boysandmen.jp"
BOYS_CALENDAR = BOYS_BASE + "/vertical_calendar"

DERA_BASE = "https://dxboys.bitfan.id"
DERA_SCHEDULE = DERA_BASE + "/schedules/menu/184780"
DERA_API_BASE = "https://user-api.bitfan.id"
DERA_API_PAGE = DERA_SCHEDULE

MEMBERS = [
    "辻本達規", "田村侑久", "本田剛文", "平松賢人", "吉原雅斗"
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

DETAIL_CACHE = {}

EXCLUDED_URLS = {
    "https://boysandmen.jp/about/membership",
    "https://boysandmen.jp/about/account",
    "https://boysandmen.jp/about/law",
    "https://boysandmen.jp/help",
    "https://boysandmen.jp/about/payment",
    "https://boysandmen.jp/about/customer_harassment",
}

EXCLUDED_PATHS = (
    "/about", "/help", "/contact", "/faq", "/privacy",
    "/terms", "/law", "/sitemap", "/login", "/signup",
    "/account", "/cart", "/mypage", "/company",
)

SKIP_TITLES = [
    "F.ENT IDについて", "お客さまへのお願い",
    "お支払いについて", "よくあるご質問", "よくある質問",
    "ボイメン☆ファミリーとは", "特商法に基づく表示",
    "お問い合わせ", "お問合せ", "会社概要",
    "プライバシーポリシー", "利用規約", "サイトマップ",
    "ログイン", "ログアウト", "会員登録", "ファンクラブ",
    "Powered by", "前月へ", "次月へ",
    "パワープレイソングに決定", "HOME", "トップページ",
    "SCHEDULE", "NEWS",
]


def normalize(text):
    return " ".join((text or "").replace("\xa0", " ").split())


def get_soup(url):
    response = SESSION.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return BeautifulSoup(response.text, "html.parser")


def parse_full_date(text):
    match = re.search(
        r"(20\d{2})\s*[年/.\-]\s*(\d{1,2})\s*[月/.\-]\s*(\d{1,2})\s*日?",
        normalize(text),
    )
    if not match:
        return None
    try:
        return date(
            int(match.group(1)), int(match.group(2)), int(match.group(3))
        )
    except ValueError:
        return None


def parse_api_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(
            str(value).strip().replace("Z", "+00:00")
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=JST)
        else:
            parsed = parsed.astimezone(JST)
        return parsed
    except (ValueError, TypeError):
        return None


def member_for(title, detail_text=""):
    matches = [m for m in MEMBERS if m in normalize(title)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return "その他"

    matches = [m for m in MEMBERS if m in normalize(detail_text)]
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
    return any(x.casefold() in title.casefold() for x in SKIP_TITLES)


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

    return any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in EXCLUDED_PATHS
    )


def make_event(
    source, event_date, title, url, detail_text="",
    event_time="", place=""
):
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
# 公式詳細ページの本文を取得
# --------------------------------------------------

def extract_page_text(url):
    """詳細ページの文章を取得。取得失敗時は空文字。"""
    if not url or not url.startswith(("https://boysandmen.jp",
                                       "https://www.boysandmen.jp",
                                       DERA_BASE)):
        return ""

    if url in DETAIL_CACHE:
        return DETAIL_CACHE[url]

    try:
        soup = get_soup(url)

        for node in soup.select(
            "script, style, noscript, nav, footer, header, "
            "form, button, .breadcrumb, .breadcrumbs, "
            ".sns-share, .share-buttons"
        ):
            node.decompose()

        lines = []
        for node in soup.find_all(
            ["h1", "h2", "h3", "h4", "p", "li", "dt", "dd", "tr"]
        ):
            line = normalize(node.get_text(" ", strip=True))
            if line and line not in lines:
                lines.append(line)

        if not lines:
            target = soup.body or soup
            lines = [
                normalize(x) for x in target.get_text("\n").splitlines()
                if normalize(x)
            ]

        result = "\n".join(lines).strip()
        if len(result) > 12000:
            result = result[:12000]

        DETAIL_CACHE[url] = result
        return result

    except Exception as exc:
        print(
            f"WARN DETAIL {url}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        DETAIL_CACHE[url] = ""
        return ""


# --------------------------------------------------
# チケット受付期間の抽出
# --------------------------------------------------

DATE_PATTERN = re.compile(
    r"(?P<year>20\d{2})\s*[年/.\-]\s*"
    r"(?P<month>\d{1,2})\s*[月/.\-]\s*"
    r"(?P<day>\d{1,2})\s*日?"
)

TIME_PATTERN = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")

TICKET_WORDS = (
    "受付", "チケット", "抽選", "先着", "販売",
    "プレイガイド", "FC", "ファンクラブ", "先行",
    "申込", "申し込み", "申込み",
)


def date_from_match(match):
    try:
        return date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except (ValueError, TypeError):
        return None


def time_in_text(text):
    matches = list(TIME_PATTERN.finditer(text or ""))
    if not matches:
        return ""
    match = matches[-1]
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def ticket_kind(context):
    text = normalize(context)

    if "FC" in text or "ファンクラブ" in text:
        if "抽選" in text:
            return "FC抽選受付"
        if "先着" in text:
            return "FC先着受付"
        return "FC受付"

    if "一般" in text and "先着" in text:
        return "一般先着販売"
    if "一般" in text and "抽選" in text:
        return "一般抽選受付"
    if "先行" in text and "抽選" in text:
        return "先行抽選受付"
    if "先行" in text and "先着" in text:
        return "先行先着販売"
    if "抽選" in text:
        return "抽選受付"
    if "先着" in text:
        return "先着販売"
    if "一般" in text:
        return "一般販売"
    if "販売" in text:
        return "チケット販売"
    return "チケット受付"


def extract_ticket_periods(detail_text, source, parent_title, source_url):
    """
    本文中のチケット関連箇所から、開始日・終了日が明記された
    期間だけを抽出する。推測で日付を補わない。
    """
    if not detail_text:
        return []

    lines = [
        normalize(line) for line in detail_text.splitlines()
        if normalize(line)
    ]
    found = {}
    used_ranges = set()

    for i in range(len(lines)):
        # 1～3行を連結し、見出しと日付が改行されている場合にも対応
        for span in (1, 2, 3):
            if i + span > len(lines):
                continue

            candidate = " ".join(lines[i:i + span])
            date_matches = list(DATE_PATTERN.finditer(candidate))

            if len(date_matches) < 2:
                continue

            first, second = date_matches[0], date_matches[1]
            separator = candidate[first.end():second.start()]

            # 2つの日付が範囲として書かれているものだけ対象にする
            if not re.search(r"(?:～|〜|~|−|－|–|—|-|から)", separator):
                continue

            start_date = date_from_match(first)
            end_date = date_from_match(second)

            if not start_date or not end_date or end_date < start_date:
                continue

            # 受付・販売などの言葉が近くにあるか確認
            context_lines = lines[max(0, i - 3):min(len(lines), i + span + 3)]
            context = " ".join(context_lines)

            if not any(word in context for word in TICKET_WORDS):
                continue

            # 開催日だけの範囲を誤登録しないため、日付の周辺にも
            # 受付・販売・抽選などの語があることを要求する
            local_context = " ".join(lines[max(0, i - 2):min(len(lines), i + span + 2)])
            if not any(word in local_context for word in TICKET_WORDS):
                continue

            # 受付期間の開始時刻と終了時刻
            between = candidate[first.end():second.start()]
            after_end = candidate[second.end():]
            start_time = time_in_text(between)
            end_time = time_in_text(after_end)

            # 期間が対象年月の範囲と重ならない場合は登録しない
            if end_date < START or start_date > END:
                continue

            kind = ticket_kind(context)
            dedupe_key = (
                source, start_date.isoformat(), end_date.isoformat(),
                kind, parent_title, source_url,
            )
            if dedupe_key in used_ranges:
                continue
            used_ranges.add(dedupe_key)

            notes = [
                f"受付期間：{start_date.isoformat()}"
                + (f" {start_time}" if start_time else "")
                + f" ～ {end_date.isoformat()}"
                + (f" {end_time}" if end_time else ""),
                f"対象イベント：{parent_title}",
            ]

            # 当落発表・支払期限など、本文に明記された行を備考に保存
            for line in context_lines:
                if any(word in line for word in (
                    "当選発表", "当落発表", "当落", "支払期間",
                    "支払期限", "入金期間", "入金期限", "決済期限",
                )):
                    if line not in notes:
                        notes.append(line)

            raw_id = (
                f"ticket|{source}|{start_date.isoformat()}|"
                f"{end_date.isoformat()}|{kind}|{parent_title}|{source_url}"
            )
            ticket_id = hashlib.sha256(
                raw_id.encode("utf-8")
            ).hexdigest()[:16]

            found[dedupe_key] = {
                "id": f"ticket-{ticket_id}",
                "date": start_date.isoformat(),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "time": start_time,
                "title": f"【{kind}】{parent_title}",
                "member": "グループ全体",
                "type": "チケット受付",
                "place": "",
                "url": source_url,
                "notes": "\n".join(notes),
                "source": source,
                "origin": "official",
                "unconfirmed": False,
                "period_type": "ticket",
            }

    return list(found.values())


# --------------------------------------------------
# BOYS AND MEN公式カレンダー
# --------------------------------------------------

def iter_month_urls():
    year, month = START.year, START.month
    while (year, month) <= (END.year, END.month):
        yield f"{BOYS_CALENDAR}/{year}/{month}"
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1


def day_from_panel_id(node):
    match = re.search(
        r"(?:collapse|schedule|day)[-_]?((?:20\d{2})\d{4})",
        node.get("id", ""), re.I
    )
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def nearest_heading_date(anchor):
    for tag in anchor.find_all_previous(
        ["h1", "h2", "h3", "h4", "strong", "b"], limit=20
    ):
        text = normalize(tag.get_text(" ", strip=True))
        if len(text) <= 45:
            parsed = parse_full_date(text)
            if parsed:
                return parsed
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
    all_events = []
    errors = []
    pages_ok = 0
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

    base_events = list(unique.values())

    # チケット受付情報は開催日が近いイベントの詳細ページを確認する。
    # 過去の全イベントを毎回大量取得しないよう、過去30日～未来1年に限定。
    detail_from = TODAY - timedelta(days=30)
    detail_to = END
    candidate_urls = {}

    for item in base_events:
        try:
            event_date = date.fromisoformat(item["date"])
        except (ValueError, TypeError):
            continue

        if detail_from <= event_date <= detail_to:
            if item["url"].startswith(BOYS_BASE + "/contents/"):
                candidate_urls[item["url"]] = item["title"]

    ticket_events = []
    detail_pages_ok = 0

    for detail_url, parent_title in candidate_urls.items():
        detail_text = extract_page_text(detail_url)
        if not detail_text:
            continue

        detail_pages_ok += 1
        ticket_events.extend(
            extract_ticket_periods(
                detail_text, "boys", parent_title, detail_url
            )
        )

    combined = {}
    for item in base_events + ticket_events:
        combined[(item["id"], item["date"], item["title"])] = item

    return list(combined.values()), {
        "ok": pages_ok > 0,
        "count": len(base_events),
        "ticket_periods": len(ticket_events),
        "detail_pages_checked": len(candidate_urls),
        "detail_pages_ok": detail_pages_ok,
        "pages_ok": pages_ok,
        "pages_tried": len(urls),
        "errors": errors[:8],
        "url": BOYS_CALENDAR,
    }


# --------------------------------------------------
# でらボ公式スケジュール API
# --------------------------------------------------

def extract_derabo_detail(url):
    return extract_page_text(url)


def get_derabo_token():
    response = SESSION.get(DERA_API_PAGE, timeout=TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    token_tag = soup.select_one('meta[name="jwt-token"]')

    if not token_tag:
        raise RuntimeError("公式ページにjwt-tokenが見つかりません。")

    token = normalize(token_tag.get("content", ""))
    if not token:
        raise RuntimeError("jwt-tokenのcontentが空です。")

    return token


def iter_derabo_months():
    year, month = START.year, START.month

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
    query = "?" + urlencode({"r": str(token)}) if token else ""
    return f"{DERA_BASE}/schedules/{schedule_id}{query}"


def get_schedules_from_payload(payload):
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
    detail_pages_ok = 0
    ticket_count = 0

    try:
        jwt_token = get_derabo_token()
    except Exception as exc:
        return [], {
            "ok": False, "count": 0, "api_records": 0,
            "months_checked": 0, "requests_ok": 0,
            "detail_pages_ok": 0, "ticket_periods": 0,
            "errors": [f"トークン取得失敗: {type(exc).__name__}: {exc}"],
            "url": DERA_SCHEDULE,
            "api_url": DERA_API_BASE + "/fanclubs/dxboys/schedules",
        }

    api_url = DERA_API_BASE + "/fanclubs/dxboys/schedules"
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
                api_url, params=params, headers=api_headers, timeout=TIMEOUT
            )
            months_checked += 1

            if response.status_code in (401, 403):
                errors.append(
                    f"{params['from_date']}: API認証エラー HTTP "
                    f"{response.status_code}"
                )
                continue

            response.raise_for_status()

            try:
                payload = response.json()
            except ValueError as exc:
                errors.append(
                    f"{params['from_date']}: JSON解析失敗: {exc}"
                )
                continue

            schedules = get_schedules_from_payload(payload)
            requests_ok += 1
            api_records += len(schedules)

            for schedule in schedules:
                if not isinstance(schedule, dict):
                    continue

                title = normalize(
                    html.unescape(str(schedule.get("title") or ""))
                )
                if not title or should_skip_title(title):
                    continue

                start_value = (
                    schedule.get("start_datetime")
                    or schedule.get("start_date")
                )
                start_dt = parse_api_datetime(start_value)

                if start_dt:
                    event_date = start_dt.date()
                    event_time = start_dt.strftime("%H:%M")
                else:
                    event_date = parse_full_date(str(start_value or ""))
                    event_time = ""

                if not event_date:
                    errors.append(f"日付を解析できない予定: {title}")
                    continue

                detail_url = make_derabo_detail_url(schedule)
                end_dt = parse_api_datetime(schedule.get("end_datetime"))
                place = (
                    schedule.get("place")
                    or schedule.get("venue")
                    or schedule.get("location")
                    or ""
                )

                detail_text = extract_derabo_detail(detail_url)
                if detail_text:
                    detail_pages_ok += 1

                item = make_event(
                    "dera", event_date, title, detail_url,
                    detail_text=detail_text,
                    event_time=event_time,
                    place=str(place),
                )

                if item:
                    if end_dt:
                        item["notes"] += (
                            " 終了日時: "
                            + end_dt.strftime("%Y-%m-%d %H:%M")
                            + "。"
                        )

                    if detail_text:
                        item["notes"] += (
                            "\n\n【公式詳細ページの記載】\n" + detail_text
                        )

                    events.append(item)

                periods = extract_ticket_periods(
                    detail_text, "dera", title, detail_url
                )
                events.extend(periods)
                ticket_count += len(periods)

        except Exception as exc:
            errors.append(
                f"{params['from_date']}～{params['to_date']}: "
                f"{type(exc).__name__}: {exc}"
            )
            print(
                f"WARN DERA API {params['from_date']}: {exc}",
                file=sys.stderr,
            )

    unique = {}
    for item in events:
        unique[(item["id"], item["date"], item["title"])] = item

    return list(unique.values()), {
        "ok": requests_ok > 0,
        "count": sum(
            1 for item in unique.values()
            if item.get("period_type") != "ticket"
        ),
        "ticket_periods": sum(
            1 for item in unique.values()
            if item.get("period_type") == "ticket"
        ),
        "api_records": api_records,
        "months_checked": months_checked,
        "requests_ok": requests_ok,
        "detail_pages_ok": detail_pages_ok,
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

    boys_events, report["BOYS AND MEN公式"] = scrape_boys()
    events.extend(boys_events)

    dera_events, report["でらボ公式スケジュール"] = scrape_derabo()
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
        unique[(item["id"], item["date"], item["title"])] = item

    sorted_events = sorted(
        unique.values(),
        key=lambda item: (
            item.get("date", ""),
            item.get("time", ""),
            item.get("title", "").casefold(),
        ),
    )

    data = {
        "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "range": {
            "from": START.isoformat(),
            "to": END.isoformat(),
        },
        "sources": report,
        "events": sorted_events,
    }

    os.makedirs("data", exist_ok=True)

    with open("data/events.json", "w", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2)

    print(f"Wrote {len(sorted_events)} events")

    for name, status in report.items():
        print(
            f"- {name}: "
            f"ok={status.get('ok')} "
            f"count={status.get('count')} "
            f"ticket_periods={status.get('ticket_periods', 0)}"
        )
        print(json.dumps(status, ensure_ascii=False, indent=2))

    if not any(status.get("ok") for status in report.values()):
        sys.exit(
            "All official sources failed; check network or site markup."
        )


if __name__ == "__main__":
    main()
