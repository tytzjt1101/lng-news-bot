import feedparser
import requests
import json
import os
import re
import time
from urllib.parse import quote_plus
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ["BOT_TOKEN_EN_2"]
CHAT_ID = os.environ["CHAT_ID_EN_2"]

HL = "en"
GL = "US"
CEID = "US:en"
STATE_FILE = "seen_en2.json"

QUIET_HOUR_START = 21   # 21:00 KST
QUIET_HOUR_END = 6      # 06:00 KST
MAX_ITEMS_PER_RUN = 5
SEND_INTERVAL_SECONDS = 2
MAX_RETRY = 5

# 너무 빡세지 않게 완화한 키워드
KEYWORDS = [
    "peru LNG",
    "\"Peru LNG\" fire",
    "\"Peru LNG\" force majeure",
    "\"Peru LNG\" outage",
    "\"Peru LNG\" restart",
]

PREFERRED_SOURCES = ["Reuters", "Bloomberg"]

HIGH_PATTERNS = [
    r"\bforce majeure\b",
    r"\bfire\b",
    r"\boutage\b",
    r"\bshutdown\b",
    r"\bdisruption\b",
    r"\bexplosion\b",
    r"\brestart\b",
]

MEDIUM_PATTERNS = [
    r"\bexport\b",
    r"\bcargo\b",
    r"\bsupply\b",
    r"\bdemand\b",
    r"\bshipment\b",
]

BLOCK_PATTERNS = [
    r"\bstock\b",
    r"\bshares\b",
    r"\bdividend\b",
    r"\bearnings\b",
    r"\bcrypto\b",
    r"\bbitcoin\b",
]


def google_news_rss_url(keyword: str) -> str:
    q = quote_plus(keyword)
    return f"https://news.google.com/rss/search?q={q}&hl={HL}&gl={GL}&ceid={CEID}"


def load_seen():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
        except Exception:
            pass
    return set()


def save_seen(seen):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen)), f, ensure_ascii=False, indent=2)


def normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def clean_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_source(entry) -> str:
    try:
        if hasattr(entry, "source") and entry.source:
            return entry.source.get("title", "").strip()
    except Exception:
        pass
    return ""


def is_quiet_time_kst() -> bool:
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    hour = now_kst.hour
    return hour >= QUIET_HOUR_START or hour < QUIET_HOUR_END


def is_preferred_source(source: str) -> bool:
    s = source.lower()
    return any(x.lower() in s for x in PREFERRED_SOURCES)


def get_importance(title: str, summary: str, source: str):
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
    elif score >= 2:
        return "🟠 MEDIUM"
    else:
        return "🟢 LOW"


def is_valid_news(title: str, summary: str) -> bool:
    text = f"{title} {summary}".lower()

    # 너무 빡세지 않게 완화
    related = (
        "peru lng" in text
        or ("peru" in text and "lng" in text)
        or "pampa melchorita" in text
        or "melchorita" in text
    )

    if not related:
        return False

    if any(re.search(p, text, re.I) for p in BLOCK_PATTERNS):
        return False

    return True


def escape_markdown(text: str) -> str:
    chars = r"_*[]()~`>#+-=|{}.!"
    return "".join("\\" + c if c in chars else c for c in text)


def shorten(text: str, limit: int = 200) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."


def send_telegram_message(text: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": False,
    }

    for _ in range(MAX_RETRY):
        try:
            resp = requests.post(url, json=payload, timeout=30)

            if resp.status_code == 200:
                time.sleep(SEND_INTERVAL_SECONDS)
                return True

            if resp.status_code == 429:
                retry_after = 10
                try:
                    data = resp.json()
                    retry_after = int(data.get("parameters", {}).get("retry_after", 10))
                except Exception:
                    pass
                time.sleep(retry_after + 1)
                continue

            print(f"Telegram send failed: {resp.status_code} {resp.text}")
            return False

        except Exception as e:
            print(f"Telegram send error: {e}")
            time.sleep(3)

    return False


def fetch_news():
    all_items = []

    for keyword in KEYWORDS:
        try:
            feed = feedparser.parse(google_news_rss_url(keyword))

            for entry in feed.entries:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = clean_html(entry.get("summary", ""))
                source = get_source(entry)

                if not title or not link:
                    continue

                if not is_valid_news(title, summary):
                    continue

                uid = normalize(title) + "|" + link

                all_items.append({
                    "uid": uid,
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "source": source,
                    "importance": get_importance(title, summary, source),
                })

            time.sleep(1)

        except Exception as e:
            print(f"RSS fetch error for keyword [{keyword}]: {e}")

    return all_items


def deduplicate_and_sort(items, seen):
    result = []
    local_seen = set()

    for item in items:
        if item["uid"] in seen or item["uid"] in local_seen:
            continue
        local_seen.add(item["uid"])
        result.append(item)

    def sort_key(x):
        priority = 1 if is_preferred_source(x["source"]) else 0
        importance_score = 0
        if "HIGH" in x["importance"]:
            importance_score = 2
        elif "MEDIUM" in x["importance"]:
            importance_score = 1
        return (importance_score, priority)

    result.sort(key=sort_key, reverse=True)
    return result[:MAX_ITEMS_PER_RUN]


def format_message(item):
    title = escape_markdown(item["title"])
    source = escape_markdown(item["source"] or "Unknown")
    summary = escape_markdown(shorten(item["summary"]))
    importance = escape_markdown(item["importance"])
    link = item["link"]

    msg = (
        f"{importance}\n"
        f"*{title}*\n"
        f"Source: {source}\n"
    )

    if summary:
        msg += f"Summary: {summary}\n"

    msg += f"{link}"
    return msg


def main():
    print("=== START ===")

    if is_quiet_time_kst():
        print("Quiet hours in KST. Skip sending.")
        return

    seen = load_seen()
    print(f"Loaded seen count: {len(seen)}")

    items = fetch_news()
    print(f"Fetched raw items: {len(items)}")

    items = deduplicate_and_sort(items, seen)
    print(f"Items after dedup/sort: {len(items)}")

    if not items:
        print("No new Peru LNG news found.")
        send_telegram_message("ℹ️ No new Peru LNG news found.")
        return

    sent = 0
    for item in items:
        print(f"Sending: {item['title']}")
        if send_telegram_message(format_message(item)):
            seen.add(item["uid"])
            sent += 1
        else:
            print(f"Failed to send: {item['title']}")

    save_seen(seen)
    print(f"Done. Sent {sent} items.")


if __name__ == "__main__":
    main()
