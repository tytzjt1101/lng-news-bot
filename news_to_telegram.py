import feedparser
import requests
import json
import os
import re
import time
import html
from urllib.parse import quote_plus
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
CHAT_ID = os.environ["CHAT_ID"].strip()

HL = "ko"
GL = "KR"
CEID = "KR:ko"

STATE_FILE = "seen.json"

QUIET_HOUR_START = 21
QUIET_HOUR_END = 6

MAX_ITEMS_PER_RUN = 10
MAX_ENTRIES_PER_KEYWORD = 10
MAX_AGE_DAYS = 30

SEND_INTERVAL_SECONDS = 2
MAX_RETRY = 5
REQUEST_TIMEOUT = 20

MAX_TELEGRAM_MESSAGE_LENGTH = 3800

KEYWORDS = [
    "LNG",
    "호르무즈",
    "카타르 LNG",
    "Shell LNG",
    "Wael Sawan",
    "인도네시아 LNG",
    "Tangguh LNG",
    "호주 LNG",
    "미국 LNG",
    "LNG 가격",
]

PREFERRED_SOURCES = [
    "Reuters",
    "Bloomberg",
    "Financial Times",
    "ICIS",
    "S&P Global",
    "Platts",
    "Argus",
    "로이터",
    "블룸버그",
    "연합뉴스",
]

HIGH_PATTERNS = [
    r"\boutage\b", r"\bshutdown\b", r"\bforce majeure\b", r"\bdisruption\b",
    r"\bfire\b", r"\bexplosion\b", r"\bexport ban\b", r"\bsanctions?\b",
    r"\bdelay\b", r"\bstrike\b", r"\bhormuz\b", r"\bpanama canal\b",
    r"가동중단", r"운영중단", r"셧다운", r"화재", r"폭발",
    r"공급차질", r"수출중단", r"제재", r"봉쇄", r"호르무즈",
]

MEDIUM_PATTERNS = [
    r"\bexport\b", r"\bimports?\b", r"\bdemand\b", r"\bsupply\b",
    r"\bcargo\b", r"\bfreight\b", r"\bshipping\b", r"\bjkm\b",
    r"\bttf\b", r"\bhenry hub\b", r"\bpolicy\b",
    r"수출", r"수입", r"수요", r"공급", r"운송", r"선적", r"정책", r"가격",
]

BLOCK_PATTERNS = [
    r"\bstock\b", r"\bshares\b", r"\bdividend\b", r"\bearnings\b",
    r"\bcrypto\b", r"\bbitcoin\b", r"\betf\b", r"\bforex\b",
    r"주가", r"배당", r"실적", r"코인", r"비트코인", r"ETF",
]


def google_news_rss_url(keyword: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(keyword)}&hl={HL}&gl={GL}&ceid={CEID}"


def load_seen() -> set:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            pass
    return set()


def save_seen(seen_set: set):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_set), f, ensure_ascii=False, indent=2)


def normalize_title(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text.lower())
    text = re.sub(r"[^\w\s가-힣]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_html_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def is_quiet_time_kst():
    now = datetime.now(timezone(timedelta(hours=9))).hour
    return now >= QUIET_HOUR_START or now < QUIET_HOUR_END


def get_source(entry):
    if hasattr(entry, "source") and entry.source:
        return entry.source.get("title", "")
    title = entry.get("title", "")
    return title.split(" - ")[-1] if " - " in title else ""


def is_preferred_source(source):
    return any(x.lower() in source.lower() for x in PREFERRED_SOURCES)


def is_recent_entry(entry):
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        dt = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
        return datetime.now(timezone.utc) - dt <= timedelta(days=MAX_AGE_DAYS)
    return True


def get_importance(title, summary, source):
    text = f"{title} {summary}".lower()
    score = (2 if is_preferred_source(source) else 0)
    if any(re.search(p, text) for p in HIGH_PATTERNS):
        score += 3
    elif any(re.search(p, text) for p in MEDIUM_PATTERNS):
        score += 1
    return "🔴 HIGH" if score >= 5 else "🟠 MEDIUM" if score >= 2 else "🟢 LOW"


def is_valid_news(title, summary, keyword):
    text = f"{title} {summary} {keyword}".lower()
    related = ["lng","gas","천연가스","호르무즈","카타르","shell","인도네시아","호주","미국","가격","price","jkm"]
    return any(x in text for x in related) and not any(re.search(p, text) for p in BLOCK_PATTERNS)


def fetch_news():
    items = []
    for kw in KEYWORDS:
        feed = feedparser.parse(google_news_rss_url(kw))
        for entry in feed.entries[:MAX_ENTRIES_PER_KEYWORD]:
            title = entry.get("title", "")
            link = entry.get("link", "")
            summary = clean_html_text(entry.get("summary", ""))
            if not title or not link:
                continue
            if not is_recent_entry(entry):
                continue
            if not is_valid_news(title, summary, kw):
                continue

            items.append({
                "uid": f"{link}|{normalize_title(title)}",
                "title": title,
                "link": link,
                "source": get_source(entry),
                "keyword": kw,
                "published": entry.get("published", ""),
                "importance": get_importance(title, summary, get_source(entry)),
            })
        time.sleep(1)
    return items


def deduplicate_and_sort(items, seen):
    result = []
    seen_titles = set()

    for item in items:
        if item["uid"] in seen:
            continue
        if item["title"] in seen_titles:
            continue
        seen_titles.add(item["title"])
        result.append(item)

    result.sort(key=lambda x: ("HIGH" in x["importance"], is_preferred_source(x["source"])), reverse=True)
    return result[:MAX_ITEMS_PER_RUN]


def format_single_item(item):
    return "\n".join([
        item["importance"],
        f"Published: {html.escape(item['published'] or 'Unknown')}",
        f'<a href="{item["link"]}">{html.escape(item["title"])}</a>',
        f"Source: {html.escape(item['source'] or 'Unknown')}",
        f"Keyword: {html.escape(item['keyword'])}",
    ])


def chunk_messages(items):
    chunks = []
    current = []
    length = 0

    for item in items:
        text = format_single_item(item)
        add_len = len(text) + (2 if current else 0)

        if current and length + add_len > MAX_TELEGRAM_MESSAGE_LENGTH:
            chunks.append(current)
            current = [text]
            length = len(text)
        else:
            current.append(text)
            length += add_len

    if current:
        chunks.append(current)

    messages = []

    if len(chunks) == 1:
        messages.append("📰 LNG News Digest\n\n" + "\n\n".join(chunks[0]))
    else:
        for i, chunk in enumerate(chunks, 1):
            messages.append(f"📰 LNG News Digest (Part {i})\n\n" + "\n\n".join(chunk))

    return messages


def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}

    for _ in range(MAX_RETRY):
        r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            time.sleep(SEND_INTERVAL_SECONDS)
            return True
        if r.status_code == 429:
            time.sleep(10)
    return False


def main():
    if is_quiet_time_kst():
        return

    seen = load_seen()
    new_seen = set(seen)

    items = deduplicate_and_sort(fetch_news(), seen)

    if not items:
        save_seen(new_seen)
        return

    messages = chunk_messages(items)

    for msg in messages:
        if not send_telegram(msg):
            break

    for item in items:
        new_seen.add(item["uid"])

    save_seen(new_seen)


if __name__ == "__main__":
    main()
