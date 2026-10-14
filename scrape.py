#!/usr/bin/env python3
"""Best-effort public-page scraper. Never invents dates; logs failures per source."""
import json, re, sys, os, hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST).date()
START = NOW.replace(year=NOW.year - 1, day=min(NOW.day, 28) if NOW.month == 2 else NOW.day)
try:
    END = NOW.replace(year=NOW.year + 1)
except ValueError:
    END = NOW.replace(year=NOW.year + 1, day=28)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BoimenEventCalendar/1.0; public schedule aggregation)"}
SOURCES = [
    {"key": "boys", "label": "BOYS AND MEN公式", "url": "https://boysandmen.jp/vertical_calendar"},
    {"key": "dera", "label": "でらボ公式", "url": "https://dxboys.bitfan.id/schedules/menu/184780"},
    {"key": "dera_home", "label": "でらボ公式NEWS", "url": "https://dxboys.bitfan.id/"},
]
MEMBERS = ["辻本達規", "田村侑久", "本田剛文", "平松賢人", "吉原雅斗"]

def parse_date(text):
    m = re.search(r'(20\d{2})[年/.\-]\s*(\d{1,2})[月/.\-]\s*(\d{1,2})日?', text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except ValueError:
            pass
    return None

def member_for(title):
    """出演者判定はリンクのタイトルだけを使い、ページ周辺の別人名を拾わない。"""
    found = [m for m in MEMBERS if m in title]
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        return "グループ全体"
    # 個人名がタイトルにない告知は、誤って特定メンバーに割り当てない
    return "グループ全体"

def classify(text):
    if any(x in text for x in ["ラジオ", "FM ", "RADIO"]): return "ラジオ"
    if any(x in text for x in ["テレビ", "TV", "TV出演", "MEDIA TV"]): return "テレビ"
    if any(x in text for x in ["舞台", "公演"]): return "舞台"
    if any(x in text for x in ["ライブ", "コンサート"]): return "ライブ"
    if any(x in text for x in ["特典会", "お渡し会", "サイン会"]): return "特典会"
    if any(x in text for x in ["リリース", "発売", "配信リリース"]): return "リリース"
    return "イベント"

def scrape(src):
    res = requests.get(src["url"], headers=HEADERS, timeout=25)
    res.raise_for_status()
    res.encoding = res.apparent_encoding or res.encoding
    soup = BeautifulSoup(res.text, "html.parser")
    found = {}
    for a in soup.select("a[href]"):
        title = " ".join(a.get_text(" ", strip=True).split())
        if not title or len(title) < 5:
            continue
        href = urljoin(src["url"], a.get("href", ""))
        if not href.startswith("http"):
            continue

        # 日付探索にはカード周辺を使うが、出演者判定には使わない
        parent = a
        context = title
        for _ in range(3):
            if parent.parent:
                parent = parent.parent
                txt = " ".join(parent.get_text(" ", strip=True).split())
                if len(txt) > len(context) and len(txt) < 1200:
                    context = txt

        date = parse_date(context) or parse_date(title)
        if not date or not (START <= date <= END):
            continue
        if any(x in href.lower() for x in ["/login", "/signup", "/terms", "/privacy"]):
            continue

        item = {
            "id": src["key"] + "-" + date.isoformat() + "-" + hashlib.sha1((href + title).encode("utf-8")).hexdigest()[:10],
            "date": date.isoformat(),
            "time": "",
            "title": title,
            "member": member_for(title),
            "type": classify(title + " " + context),
            "place": "",
            "url": href,
            "notes": "公式ページから自動取得。出演者はタイトルに明記された場合のみ個人に分類します。日時・出演者の詳細はリンク先で確認してください。",
            "source": "dera" if src["key"].startswith("dera") else "boys",
            "origin": "official",
            "unconfirmed": False,
        }
        found[(item["date"], item["title"], item["url"])] = item
    return list(found.values()), len(soup.get_text(" ", strip=True))

def main():
    events, report = [], {}
    for src in SOURCES:
        try:
            items, chars = scrape(src)
            report[src["label"]] = {"ok": True, "count": len(items), "page_chars": chars, "url": src["url"]}
            events.extend(items)
        except Exception as e:
            report[src["label"]] = {"ok": False, "count": 0, "error": str(e), "url": src["url"]}
            print("WARN", src["label"], repr(e), file=sys.stderr)

    unique = {}
    for e in events:
        k = (e["date"], e["title"].strip().lower())
        if k not in unique:
            unique[k] = e
    data = {
        "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "range": {"from": START.isoformat(), "to": END.isoformat()},
        "sources": report,
        "events": sorted(unique.values(), key=lambda x: (x["date"], x["time"], x["title"]))
    }
    os.makedirs("data", exist_ok=True)
    with open("data/events.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("Wrote", len(data["events"]), "events")
    if not any(v.get("ok") for v in report.values()):
        sys.exit("All official sources failed; check source markup/network.")

if __name__ == "__main__":
    main()
