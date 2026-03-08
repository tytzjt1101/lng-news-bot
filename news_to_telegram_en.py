import feedparser
import requests
import json
import os
import re
import time
import html
from urllib.parse import quote_plus
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ["BOT_TOKEN_EN"].strip()
CHAT_ID = os.environ["CHAT_ID_EN"].strip()

HL = "en"
GL = "US"
CEID = "US:en"

STATE_FILE = "seen_en.json"

QUIET_HOUR_START = 21
QUIET_HOUR_END = 6

MAX_ITEMS_PER_RUN = 5
MAX_ENTRIES_PER_KEYWORD = 10
MAX_AGE_DAYS = 30

SEND_INTERVAL_SECONDS = 2
MAX_RETRY = 5
REQUEST_TIMEOUT = 20

KEYWORDS = [
    "LNG",
    "LNG supply disruption",
    "LNG outage",
    "Qatar LNG",
    "US LNG export",
    "Shell LNG",
    "Wael Sawan",
]

PREFERRED_SOURCES = [
    "Reuters",
    "Bloomberg",
    "Financial Times",
    "ICIS",
    "S&P Global",
    "Platts",
    "Argus",
]

HIGH_PATTERNS = [
    r"\boutage\b",
    r"\bshutdown\b",
    r"\bforce majeure\b",
    r"\bdisruption\b",
    r"\bfire\b",
    r"\bexplosion\b",
    r"\bexport ban\b",
    r"\bsanctions?\b",
    r"\bdelay\b",
    r"\bstrike\b",
    r"\bhormuz\b",
    r"\bpanama canal\b",
]

MEDIUM_PATTERNS = [
    r"\bexport\b",
    r"\bimports?\b",
    r"\bdemand\b",
    r"\bsupply\b",
    r"\bcargo\b",
    r"\bfreight\b",
    r"\bshipping\b",
    r"\bjkm\b",
    r"\bttf\b",
    r"\bhenry hub\b",
    r"\bpolicy\b",
]

BLOCK_PATTERNS = [
    r"\bstock\b",
    r"\bshares\b",
    r"\bdividend\b",
    r"\bearnings\b",
    r"\bcrypto\b",
    r"\bbitcoin\b",
    r"\betf\b",
    r"\bforex\b",
]


def google_news_rss_url(keyword: str) -> str:
    q = quote_plus(keyword)
    return f"https://news.google.com/rss/search?q={q}&hl={HL}&gl={GL}&ceid={CEID}"


def load_seen() -> set:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
        except Exception as e:
            print(f"[WARN] load_seen failed: {e}")
    return set()


def save_seen(seen_set: set) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(seen_set)), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] save_seen failed: {e}")


def normalize_title(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def clean_html_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def shorten(text: str, limit: int = 220) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def is_quiet_time_kst() -> bool:
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    hour = now_kst.hour
    return hour >= QUIET_HOUR_START or hour < QUIET_HOUR_END


def get_source(entry) -> str:
    try:
        if hasattr(entry, "source") and entry.source:
            return entry.source.get("title", "").strip()
    except Exception:
        pass

    title = entry.get("title", "") or ""
    if " - " in title:
        return title.split(" - ")[-1].strip()

    return ""


def is_preferred_source(source: str) -> bool:
    s = source.lower()
    return any(x.lower() in s for x in PREFERRED_SOURCES)


def is_recent_entry(entry, max_age_days: int = MAX_AGE_DAYS) -> bool:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            published_dt = datetime.fromtimestamp(
                time.mktime(entry.published_parsed),
                tz=timezone.utc,
            )
            return datetime.now(timezone.utc) - published_dt <= timedelta(days=max_age_days)
        except Exception:
            return True
    return True


def get_published_text(entry) -> str:
    return (entry.get("published") or entry.get("updated") or "").strip()


def get_importance(title: str, summary: str, source: str) -> str:
    text = f"{title} {summary}".lower()
    score = 0

    if is_preferred_source(source):
        score += 2

    if any(re.search(p, text, re.I) for p in HIGH_PATTERNS):
        score += 3
    elif any(re.search(p, text, re.I) for p in MEDIUM_PATTERNS):
        score += 1

    if score >= 5:
        return "🔴 HIGH"
    if score >= 2:
        return "🟠 MEDIUM"
    return "🟢 LOW"


def is_valid_news(title: str, summary: str, keyword: str) -> bool:
    text = f"{title} {summary} {keyword}".lower()

    if "lng" not in text and "natural gas" not in text:
        return False

    if any(re.search(p, text, re.I) for p in BLOCK_PATTERNS):
        return False

    return True


def build_uid(link: str, title: str) -> str:
    return f"{link.strip()}|{normalize_title(title)}"


def send_telegram(text: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            print(f"[INFO] telegram status={r.status_code}")

            if r.status_code == 200:
                time.sleep(SEND_INTERVAL_SECONDS)
                return True

            if r.status_code == 429:
                retry_after = 10
                try:
                    data = r.json()
                    retry_after = int(data.get("parameters", {}).get("retry_after", 10))
                except Exception:
                    pass
                print(f"[WARN] 429 Too Many Requests. Sleep {retry_after + 1}s")
                time.sleep(retry_after + 1)
                continue

            print(f"[ERROR] Telegram send failed: {r.status_code} {r.text}")
            return False

        except Exception as e:
            print(f"[WARN] Telegram send error (attempt {attempt}): {e}")
            time.sleep(3)

    return False


def fetch_news():
    items = []

    for kw in KEYWORDS:
        try:
            feed_url = google_news_rss_url(kw)
            print(f"[INFO] Fetching: {kw}")
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:MAX_ENTRIES_PER_KEYWORD]:
                link = (entry.get("link") or "").strip()
                title = (entry.get("title") or "").strip()
                summary = clean_html_text(entry.get("summary", ""))
                source = get_source(entry)
                published = get_published_text(entry)

                if not link or not title:
                    continue

                if not is_recent_entry(entry):
                    continue

                if not is_valid_news(title, summary, kw):
                    continue

                items.append({
                    "uid": build_uid(link, title),
                    "link": link,
                    "title": title,
                    "title_norm": normalize_title(title),
                    "summary": summary,
                    "source": source,
                    "keyword": kw,
                    "published": published,
                    "importance": get_importance(title, summary, source),
                })

            time.sleep(1)

        except Exception as e:
            print(f"[WARN] Fetch failed for keyword [{kw}]: {e}")

    return items


def deduplicate_and_sort(items, seen):
    result = []
    local_uids = set()
    local_titles = set()

    for item in items:
        if item["uid"] in seen:
            continue
        if item["uid"] in local_uids:
            continue
        if item["title_norm"] in local_titles:
            continue

        local_uids.add(item["uid"])
        local_titles.add(item["title_norm"])
        result.append(item)

    def sort_key(x):
        importance_score = 0
        if "HIGH" in x["importance"]:
            importance_score = 2
        elif "MEDIUM" in x["importance"]:
            importance_score = 1

        preferred_score = 1 if is_preferred_source(x["source"]) else 0
        return (importance_score, preferred_score)

    result.sort(key=sort_key, reverse=True)
    return result[:MAX_ITEMS_PER_RUN]


def format_message(item) -> str:
    title = html.escape(item["title"])
    link = item["link"]
    summary = html.escape(shorten(item["summary"]))
    published = html.escape(item["published"]) if item["published"] else ""
    source = html.escape(item["source"] or "Unknown")
    keyword = html.escape(item["keyword"])
    importance = html.escape(item["importance"])

    lines = [
        f"{importance}",
        f'<a href="{link}">{title}</a>',
    ]

    if summary:
        lines.append(f"Summary: {summary}")

    if published:
        lines.append(f"Published: {published}")

    lines.append(f"Source: {source}")
    lines.append(f"Keyword: {keyword}")

    return "\n".join(lines)


def main():
    print("=== START ===")

    if is_quiet_time_kst():
        print("[INFO] Quiet hours in KST. Skip sending.")
        return

    seen = load_seen()
    new_seen = set(seen)

    items = fetch_news()
    print(f"[INFO] Raw items: {len(items)}")

    items = deduplicate_and_sort(items, seen)
    print(f"[INFO] Final items: {len(items)}")

    if not items:
        send_telegram("ℹ️ No new LNG news found.")
        save_seen(new_seen)
        return

    sent = 0
    for item in items:
        msg = format_message(item)
        ok = send_telegram(msg)
        if ok:
            new_seen.add(item["uid"])
            sent += 1

    save_seen(new_seen)
    print(f"[INFO] Done. Sent {sent} items.")


if __name__ == "__main__":
    main()
