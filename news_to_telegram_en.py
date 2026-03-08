import feedparser
import requests
import json
import os
import time
from urllib.parse import quote_plus

# EN bot secrets
BOT_TOKEN = os.environ["BOT_TOKEN_EN"]
CHAT_ID = os.environ["CHAT_ID_EN"]

# EN edition of Google News
HL = "en"
GL = "US"
CEID = "US:en"

# EN keywords (원하는대로 나중에 조정)
KEYWORDS = [
    "LNG supply disruption",
    "LNG outage",
    "Qatar LNG",
    "US LNG export",
]

STATE_FILE = "seen_en.json"

def google_news_rss_url(keyword: str) -> str:
    q = quote_plus(keyword)
    return f"https://news.google.com/rss/search?q={q}&hl={HL}&gl={GL}&ceid={CEID}"

def load_seen() -> set:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(seen_set: set) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen_set)), f, ensure_ascii=False, indent=2)

def send_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": False
    }, timeout=20)
    r.raise_for_status()

def main():
    seen = load_seen()
    new_seen = set(seen)

    for kw in KEYWORDS:
        feed_url = google_news_rss_url(kw)
        feed = feedparser.parse(feed_url)

        new_items = []
        for entry in feed.entries[:5]:
            link = getattr(entry, "link", None)
            title = getattr(entry, "title", "")
            if not link:
                continue
            if link not in seen:
                new_items.append((title, link))

        if new_items:
            for title, link in reversed(new_items):
                msg = f"🟦 EN LNG News\n[{kw}]\n{title}\n{link}"
                send_telegram(msg)
                new_seen.add(link)
                time.sleep(0.3)

    # 항상 저장 (첫 실행에서도 파일이 생기게)
    save_seen(new_seen)

if __name__ == "__main__":
    main()
