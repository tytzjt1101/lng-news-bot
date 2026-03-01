import feedparser
import requests
import json
import os
import time
from urllib.parse import quote_plus

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# 네가 감시할 키워드 목록 (원하는대로 추가)
KEYWORDS = [
    "LNG",
    "Hormuz Strait",
    "Qatar LNG",
    "JKM",
    "Indonesia LNG export",
    "김지수의 인터스텔라"
]

# 언어/지역 (원하면 ko-KR로 바꿔도 됨)
HL = "ko"
GL = "KR"
CEID = "KR:ko"

STATE_FILE = "seen.json"  # 이미 보낸 링크 저장 (중복 방지)

def google_news_rss_url(keyword: str) -> str:
    q = quote_plus(keyword)
    return f"https://news.google.com/rss/search?q={q}&hl={HL}&gl={GL}&ceid={CEID}"

def load_seen():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(seen_set):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen_set)), f, ensure_ascii=False, indent=2)

def send_telegram(text: str):
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

        # 최신글이 위에 오므로, 보기 좋게 오래된 것부터 전송하려고 reverse
        new_items = []
        for entry in feed.entries[:30]:  # 너무 많으면 스팸되니 상위 30개만
            link = getattr(entry, "link", None)
            title = getattr(entry, "title", "")
            if not link:
                continue
            if link not in seen:
                new_items.append((title, link))

        if new_items:
            for title, link in reversed(new_items):
                msg = f"📰 [{kw}]\n{title}\n{link}"
                send_telegram(msg)
                new_seen.add(link)
                time.sleep(0.3)  # 레이트리밋 완화

    if new_seen != seen:
        save_seen(new_seen)

if __name__ == "__main__":
    main()