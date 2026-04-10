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

HL = "ko"
GL = "KR"
CEID = "KR:ko"

STATE_FILE = "seen_world_ko.json"

QUIET_HOUR_START = 21
QUIET_HOUR_END = 6

MAX_ITEMS_PER_RUN = 10
MAX_ENTRIES_PER_KEYWORD = 10
MAX_AGE_DAYS = 30

SEND_INTERVAL_SECONDS = 2
MAX_RETRY = 5
REQUEST_TIMEOUT = 20
MAX_TELEGRAM_MESSAGE_LENGTH = 3800

MAX_PER_CATEGORY = {
    "geopolitics": 2,
    "economy": 2,
    "energy": 2,
    "tech": 2,
    "supply_chain": 1,
    "climate": 1,
    "culture": 2,
    "lifestyle": 1,
    "health": 1,
    "other": 1,
}

KEYWORDS = [
    # Core
    "war conflict geopolitics",
    "전쟁 분쟁 지정학",
    "sanctions tariffs export ban",
    "제재 관세 수출금지",
    "china us russia middle east",
    "중국 미국 러시아 중동",
    "inflation interest rate central bank",
    "인플레이션 금리 중앙은행",
    "global economy recession",
    "글로벌 경제 침체",
    "oil gas lng energy crisis",
    "원유 가스 LNG 에너지 위기",
    "supply chain shipping logistics",
    "공급망 해운 물류",
    "ai semiconductor technology",
    "AI 반도체 기술",

    # Expansion
    "healthcare biotech pharmaceutical",
    "보건 바이오 제약",
    "education labor market workforce",
    "교육 노동시장 고용",
    "infrastructure construction urban development",
    "인프라 건설 도시개발",
    "environment sustainability carbon",
    "환경 지속가능 탄소",

    # Light politics / diplomacy
    "election political shift diplomacy summit",
    "선거 정치변화 외교 정상회담",

    # Culture
    "art exhibition museum architecture",
    "미술 전시 박물관 건축",
    "classical music opera concert",
    "클래식 음악 오페라 공연",
    "film festival cultural trend",
    "영화제 문화 트렌드",
    "sports major event olympics world cup",
    "스포츠 올림픽 월드컵",

    # Side
    "wine industry vineyard",
    "와인 산업 포도밭",
    "specialty coffee market",
    "스페셜티 커피 시장",

    # Discovery
    "global trends innovation future",
    "세계 변화 트렌드 혁신",
    "emerging markets frontier economy",
    "신흥시장 프론티어 경제",
    "technology breakthrough research",
    "기술 혁신 연구",
    "global risk uncertainty",
    "글로벌 리스크 불확실성",
]

PREFERRED_SOURCES = [
    "Reuters",
    "Bloomberg",
    "Financial Times",
    "The Economist",
    "BBC",
    "BBC News",
    "CNN",
    "AP News",
    "Associated Press",
    "New York Times",
    "Wall Street Journal",
    "WSJ",
    "Al Jazeera",
    "Nikkei",
    "로이터",
    "블룸버그",
    "연합뉴스",
    "BBC News 코리아",
]

HIGH_PATTERNS = [
    # Geopolitics / security
    r"\bwar\b", r"\bconflict\b", r"\battack\b", r"\bmissile\b", r"\bstrike\b",
    r"\bceasefire\b", r"\bsanctions?\b", r"\bcoup\b", r"\bterror\b",
    r"\bexport ban\b", r"\bembargo\b", r"\bmilitary\b",
    r"전쟁", r"분쟁", r"공습", r"공격", r"미사일", r"휴전", r"제재", r"쿠데타", r"봉쇄",

    # Macro / policy
    r"\brecession\b", r"\binflation\b", r"\binterest rate\b", r"\bcentral bank\b",
    r"\btariffs?\b", r"\bpolicy shift\b", r"\bregulation\b",
    r"침체", r"인플레이션", r"금리", r"중앙은행", r"관세", r"규제",

    # Energy / supply
    r"\boutage\b", r"\bshutdown\b", r"\bforce majeure\b", r"\bdisruption\b",
    r"\bexplosion\b", r"\bfire\b", r"\benergy crisis\b",
    r"\bsupply chain\b", r"\bshipping disruption\b", r"\bpanama canal\b", r"\bsuez\b",
    r"가동중단", r"운영중단", r"셧다운", r"폭발", r"화재", r"에너지 위기", r"공급망", r"물류 차질",

    # Climate / health
    r"\bdisaster\b", r"\boutbreak\b", r"\bpandemic\b", r"\bearthquake\b", r"\bflood\b", r"\bwildfire\b",
    r"재난", r"대유행", r"감염병", r"지진", r"홍수", r"산불",
]

MEDIUM_PATTERNS = [
    # Politics / diplomacy
    r"\belection\b", r"\bvote\b", r"\bdiplomacy\b", r"\bsummit\b",
    r"선거", r"투표", r"외교", r"정상회담",

    # Macro / markets
    r"\beconomy\b", r"\bmarket\b", r"\btrade\b", r"\bpolicy\b",
    r"경제", r"시장", r"무역", r"정책",

    # Energy
    r"\boil\b", r"\bgas\b", r"\blng\b", r"\benergy\b", r"\bopec\b",
    r"원유", r"가스", r"엘엔지", r"LNG", r"에너지",

    # Tech
    r"\bai\b", r"\bsemiconductor\b", r"\bchip\b", r"\btechnology\b",
    r"AI", r"반도체", r"칩", r"기술",

    # Supply / climate / health
    r"\bshipping\b", r"\blogistics\b", r"\bclimate\b", r"\bcarbon\b",
    r"\bhealth\b", r"\bbiotech\b",
    r"해운", r"물류", r"기후", r"탄소", r"보건", r"바이오",

    # Culture
    r"\bart\b", r"\bmuseum\b", r"\barchitecture\b", r"\bopera\b", r"\bconcert\b",
    r"\bfilm festival\b", r"\bolympics\b", r"\bworld cup\b",
    r"미술", r"박물관", r"건축", r"오페라", r"공연", r"영화제", r"올림픽", r"월드컵",

    # Lifestyle
    r"\bwine\b", r"\bcoffee\b", r"\bvineyard\b",
    r"와인", r"커피", r"포도밭",
]

BLOCK_PATTERNS = [
    r"\bcelebrity\b", r"\bgossip\b", r"\bscandal\b", r"\breality show\b",
    r"연예", r"가십", r"스캔들",

    r"\btransfer rumor\b", r"\bmatch preview\b", r"\bfantasy\b",
    r"이적설", r"경기 예상", r"판타지",

    r"\bbitcoin\b", r"\bcrypto\b", r"\betf\b", r"\bdividend\b", r"\bstock tips?\b",
    r"비트코인", r"코인", r"ETF", r"배당", r"종목 추천",

    r"\bfashion\b", r"\bmakeup\b", r"\bdating\b", r"\btravel tips\b",
    r"패션", r"메이크업", r"연애", r"여행 팁",
]

MAJOR_SPORTS_PATTERNS = [
    r"\bolympics\b", r"\bworld cup\b", r"\bgrand slam\b", r"\bchampions league\b",
    r"올림픽", r"월드컵", r"그랜드슬램", r"챔피언스리그",
]


def google_news_rss_url(keyword: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(keyword)}&hl={HL}&gl={GL}&ceid={CEID}"


def load_seen() -> set:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as e:
            print(f"[WARN] load_seen failed: {e}")
    return set()


def save_seen(seen_set: set):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(seen_set)), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] save_seen failed: {e}")


def normalize_title(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", (text or "").lower())
    text = re.sub(r"[^\w\s가-힣]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_html_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def format_date(date_str: str) -> str:
    if not date_str:
        return "Unknown"

    patterns = [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ]

    for pattern in patterns:
        try:
            dt = datetime.strptime(date_str, pattern)
            return dt.strftime("%d %b %Y (%a)")
        except Exception:
            pass

    try:
        dt = datetime.strptime(date_str[:25], "%a, %d %b %Y %H:%M:%S")
        return dt.strftime("%d %b %Y (%a)")
    except Exception:
        return date_str


def is_quiet_time_kst() -> bool:
    now = datetime.now(timezone(timedelta(hours=9))).hour
    return now >= QUIET_HOUR_START or now < QUIET_HOUR_END


def get_source(entry):
    try:
        if hasattr(entry, "source") and entry.source:
            return (entry.source.get("title") or "").strip()
    except Exception:
        pass

    title = entry.get("title", "") or ""
    return title.split(" - ")[-1].strip() if " - " in title else ""


def is_preferred_source(source: str) -> bool:
    return any(x.lower() in (source or "").lower() for x in PREFERRED_SOURCES)


def is_recent_entry(entry):
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            dt = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
            return datetime.now(timezone.utc) - dt <= timedelta(days=MAX_AGE_DAYS)
        except Exception:
            return True
    return True


def contains_major_sports_signal(text: str) -> bool:
    return any(re.search(p, text, re.I) for p in MAJOR_SPORTS_PATTERNS)


def is_valid_news(title, summary, keyword):
    text = f"{title} {summary} {keyword}".lower()

    related_keywords = [
        "war", "conflict", "geopolitics", "sanction", "tariff", "economy", "inflation",
        "rate", "central bank", "oil", "gas", "lng", "energy", "ai", "chip", "technology",
        "supply chain", "shipping", "climate", "disaster", "health", "biotech", "art",
        "museum", "architecture", "opera", "concert", "film", "sports", "wine", "coffee",
        "전쟁", "분쟁", "지정학", "제재", "관세", "경제", "인플레이션", "금리", "중앙은행",
        "원유", "가스", "엘엔지", "에너지", "반도체", "기술", "공급망", "해운", "기후", "재난",
        "보건", "바이오", "미술", "박물관", "건축", "오페라", "공연", "영화제", "스포츠",
        "와인", "커피",
    ]

    if not any(x in text for x in related_keywords):
        return False

    if any(re.search(p, text, re.I) for p in BLOCK_PATTERNS):
        if contains_major_sports_signal(text):
            return True
        return False

    return True


def classify_category(item):
    text = f"{item['title']} {item.get('summary', '')}".lower()

    if any(re.search(p, text, re.I) for p in [
        r"\bwar\b", r"\bconflict\b", r"\bsanctions?\b", r"\btariffs?\b",
        r"\bmilitary\b", r"\bmissile\b", r"\bdiplomacy\b", r"\bsummit\b",
        r"전쟁", r"분쟁", r"제재", r"관세", r"미사일", r"외교", r"정상회담"
    ]):
        return "geopolitics"

    if any(re.search(p, text, re.I) for p in [
        r"\binflation\b", r"\binterest rate\b", r"\bcentral bank\b", r"\brecession\b",
        r"\beconomy\b", r"\bmarket\b", r"인플레이션", r"금리", r"중앙은행", r"침체", r"경제", r"시장"
    ]):
        return "economy"

    if any(re.search(p, text, re.I) for p in [
        r"\boil\b", r"\bgas\b", r"\blng\b", r"\benergy\b", r"\bopec\b",
        r"원유", r"가스", r"엘엔지", r"LNG", r"에너지"
    ]):
        return "energy"

    if any(re.search(p, text, re.I) for p in [
        r"\bai\b", r"\bsemiconductor\b", r"\bchip\b", r"\btechnology\b", r"\bbig tech\b",
        r"AI", r"반도체", r"칩", r"기술"
    ]):
        return "tech"

    if any(re.search(p, text, re.I) for p in [
        r"\bsupply chain\b", r"\bshipping\b", r"\blogistics\b", r"\bpanama canal\b", r"\bsuez\b",
        r"공급망", r"해운", r"물류", r"파나마", r"수에즈"
    ]):
        return "supply_chain"

    if any(re.search(p, text, re.I) for p in [
        r"\bclimate\b", r"\bdisaster\b", r"\bearthquake\b", r"\bflood\b", r"\bwildfire\b",
        r"기후", r"재난", r"지진", r"홍수", r"산불"
    ]):
        return "climate"

    if any(re.search(p, text, re.I) for p in [
        r"\bhealth\b", r"\bbiotech\b", r"\bpharmaceutical\b", r"\boutbreak\b", r"\bpandemic\b",
        r"보건", r"바이오", r"제약", r"감염병", r"대유행"
    ]):
        return "health"

    if any(re.search(p, text, re.I) for p in [
        r"\bart\b", r"\bmuseum\b", r"\barchitecture\b", r"\bopera\b", r"\bconcert\b",
        r"\bfilm festival\b", r"\bolympics\b", r"\bworld cup\b",
        r"미술", r"박물관", r"건축", r"오페라", r"공연", r"영화제", r"올림픽", r"월드컵", r"스포츠"
    ]):
        return "culture"

    if any(re.search(p, text, re.I) for p in [
        r"\bwine\b", r"\bcoffee\b", r"\bvineyard\b",
        r"와인", r"커피", r"포도밭"
    ]):
        return "lifestyle"

    return "other"


def extract_topic_signature(title: str) -> str:
    text = normalize_title(title)

    stopwords = {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at",
        "from", "by", "after", "over", "amid", "as", "is", "are",
        "news", "global", "world", "international",
        "세계", "국제", "글로벌", "주요", "뉴스", "관련", "대한"
    }

    tokens = [t for t in text.split() if len(t) > 2 and t not in stopwords]
    return " ".join(tokens[:6])


def topic_overlap(sig1: str, sig2: str) -> bool:
    s1 = set(sig1.split())
    s2 = set(sig2.split())
    if not s1 or not s2:
        return False
    intersection = len(s1 & s2)
    min_size = min(len(s1), len(s2))
    return intersection >= 2 and intersection / min_size >= 0.5


def calculate_score(item, topic_counts):
    title = item["title"]
    summary = item.get("summary", "")
    source = item["source"]
    text = f"{title} {summary}".lower()
    category = item["category"]

    score = 0

    if any(re.search(p, text, re.I) for p in HIGH_PATTERNS):
        score += 5
    elif any(re.search(p, text, re.I) for p in MEDIUM_PATTERNS):
        score += 2

    if is_preferred_source(source):
        score += 3

    impact_patterns = [
        r"\bglobal\b", r"\bworld\b", r"\binternational\b", r"\bmajor\b",
        r"\bcentral bank\b", r"\bsupply chain\b", r"\benergy crisis\b",
        r"글로벌", r"세계", r"국제", r"중앙은행", r"공급망", r"에너지 위기"
    ]
    if any(re.search(p, text, re.I) for p in impact_patterns):
        score += 2

    if category == "culture":
        score += 1

    topic_signature = item["topic_signature"]
    if topic_counts.get(topic_signature, 0) >= 1:
        score -= 3

    low_quality_patterns = [
        r"\bopinion\b", r"\beditorial\b", r"\bcolumn\b", r"\bslideshow\b",
        r"사설", r"칼럼", r"포토", r"화보"
    ]
    if any(re.search(p, text, re.I) for p in low_quality_patterns):
        score -= 2

    return score


def fetch_news():
    items = []

    for kw in KEYWORDS:
        try:
            print(f"[INFO] Fetching: {kw}")
            feed = feedparser.parse(google_news_rss_url(kw))

            for entry in feed.entries[:MAX_ENTRIES_PER_KEYWORD]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                summary = clean_html_text(entry.get("summary", ""))
                source = get_source(entry)
                published_raw = (entry.get("published") or entry.get("updated") or "").strip()

                if not title or not link:
                    continue
                if not is_recent_entry(entry):
                    continue
                if not is_valid_news(title, summary, kw):
                    continue

                item = {
                    "uid": f"{link}|{normalize_title(title)}",
                    "title": title,
                    "title_norm": normalize_title(title),
                    "link": link,
                    "summary": summary,
                    "source": source,
                    "keyword": kw,
                    "published": format_date(published_raw),
                }
                item["category"] = classify_category(item)
                item["topic_signature"] = extract_topic_signature(title)

                items.append(item)

            time.sleep(1)

        except Exception as e:
            print(f"[WARN] Fetch failed for keyword [{kw}]: {e}")

    return items


def deduplicate_initial(items, seen):
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

    return result


def select_top_diverse_items(items):
    topic_counts = {}
    for item in items:
        item["score"] = calculate_score(item, topic_counts)
        topic_counts[item["topic_signature"]] = topic_counts.get(item["topic_signature"], 0) + 1

    items.sort(
        key=lambda x: (
            x["score"],
            1 if is_preferred_source(x["source"]) else 0,
        ),
        reverse=True
    )

    final = []
    category_counts = {}
    selected_signatures = []

    for item in items:
        category = item["category"]
        allowed = MAX_PER_CATEGORY.get(category, 1)

        if category_counts.get(category, 0) >= allowed:
            continue

        too_similar = False
        for sig in selected_signatures:
            if topic_overlap(item["topic_signature"], sig):
                too_similar = True
                break
        if too_similar:
            continue

        final.append(item)
        category_counts[category] = category_counts.get(category, 0) + 1
        selected_signatures.append(item["topic_signature"])

        if len(final) >= MAX_ITEMS_PER_RUN:
            break

    if len(final) < MAX_ITEMS_PER_RUN:
        selected_uids = {x["uid"] for x in final}
        for item in items:
            if item["uid"] in selected_uids:
                continue
            final.append(item)
            selected_uids.add(item["uid"])
            if len(final) >= MAX_ITEMS_PER_RUN:
                break

    return final[:MAX_ITEMS_PER_RUN]


def attach_importance_label(items):
    for item in items:
        if item["score"] >= 8:
            item["importance"] = "🔴 HIGH"
        elif item["score"] >= 4:
            item["importance"] = "🟠 MEDIUM"
        else:
            item["importance"] = "🟢 LOW"
    return items


def format_single_item(item):
    return "\n".join([
        item["importance"],
        html.escape(item["published"] or "Unknown"),
        f'<a href="{item["link"]}">{html.escape(item["title"])}</a>',
        f"Source: {html.escape(item['source'] or 'Unknown')}",
        f"Keyword: {html.escape(item['keyword'])}",
    ])


def chunk_messages(items):
    temp_chunks = []
    current_parts = []
    current_length = 0

    for item in items:
        item_text = format_single_item(item)

        if current_parts:
            add_len = len("\n\n") + len(item_text)
        else:
            add_len = len("📰 세계 주요뉴스 Digest\n\n") + len(item_text)

        if current_parts and current_length + add_len > MAX_TELEGRAM_MESSAGE_LENGTH:
            temp_chunks.append(current_parts)
            current_parts = [item_text]
            current_length = len("📰 세계 주요뉴스 Digest\n\n") + len(item_text)
        else:
            current_parts.append(item_text)
            if len(current_parts) == 1:
                current_length = len("📰 세계 주요뉴스 Digest\n\n") + len(item_text)
            else:
                current_length += len("\n\n") + len(item_text)

    if current_parts:
        temp_chunks.append(current_parts)

    messages = []

    if len(temp_chunks) == 1:
        body = "\n\n".join(temp_chunks[0])
        messages.append("📰 세계 주요뉴스 Digest\n\n" + body)
    else:
        for idx, chunk in enumerate(temp_chunks, start=1):
            body = "\n\n".join(chunk)
            messages.append(f"📰 세계 주요뉴스 Digest (Part {idx})\n\n" + body)

    return messages


def send_telegram(text):
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


def main():
    print("=== START ===")

    if is_quiet_time_kst():
        print("[INFO] Quiet hours in KST. Skip sending.")
        return

    seen = load_seen()
    new_seen = set(seen)

    raw_items = fetch_news()
    print(f"[INFO] Raw items: {len(raw_items)}")

    deduped_items = deduplicate_initial(raw_items, seen)
    print(f"[INFO] Deduped items: {len(deduped_items)}")

    final_items = select_top_diverse_items(deduped_items)
    final_items = attach_importance_label(final_items)
    print(f"[INFO] Final selected items: {len(final_items)}")

    if not final_items:
        print("[INFO] No new world news found.")
        save_seen(new_seen)
        return

    messages = chunk_messages(final_items)
    print(f"[INFO] Message chunks: {len(messages)}")

    all_sent = True
    for msg in messages:
        ok = send_telegram(msg)
        if not ok:
            all_sent = False
            break

    if all_sent:
        for item in final_items:
            new_seen.add(item["uid"])

    save_seen(new_seen)
    print(f"[INFO] Done. Sent {len(final_items) if all_sent else 0} items in {len(messages) if all_sent else 0} message(s).")


if __name__ == "__main__":
    main()
