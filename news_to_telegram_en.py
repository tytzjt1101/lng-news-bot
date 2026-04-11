# 지역별 quota 기반으로 최근 2일 한국어 세계 주요뉴스를 수집·선별해
# 텔레그램으로 보내는 뉴스 다이제스트 봇

import feedparser
import requests
import json
import os
import re
import time
import html
from urllib.parse import quote_plus
from datetime import datetime, timedelta, timezone

# =========================
# ENV
# =========================
BOT_TOKEN = os.environ["BOT_TOKEN_EN"].strip()
CHAT_ID = os.environ["CHAT_ID_EN"].strip()

# 한국어 기사 우선
HL = "ko"
GL = "KR"
CEID = "KR:ko"

STATE_FILE = "seen_world_region_ko_today.json"

# =========================
# BASIC CONFIG
# =========================
KST = timezone(timedelta(hours=9))
UTC = timezone.utc

QUIET_HOUR_START = 21
QUIET_HOUR_END = 6

SEND_INTERVAL_SECONDS = 2
MAX_RETRY = 5
REQUEST_TIMEOUT = 20
MAX_TELEGRAM_MESSAGE_LENGTH = 3800

# 최근 며칠 기사까지 허용할지
LOOKBACK_DAYS = 2

# 테스트용 디버그 모드
# True면 이벤트 필터를 느슨하게 적용
DEBUG_RELAX_MODE = True

# 지역별 목표 기사 수
REGION_QUOTA = {
    "us": 3,
    "china": 2,
    "japan": 1,
    "india": 1,
    "singapore": 1,
    "sea_other": 1,
    "europe": 1,
    "middle_east": 1,
    "latam": 1,
    "africa": 1,
}

# 지역별 검색 키워드
# 기존처럼 "정치 경제 외교" 묶음 대신 짧고 실제 기사형 키워드로 분해
REGION_KEYWORDS = {
    "us": [
        "미국",
        "트럼프",
        "연준",
        "백악관",
        "미국 관세",
        "미국 금리",
        "미국 고용",
        "엔비디아 미국",
    ],
    "china": [
        "중국",
        "시진핑",
        "중국 경기",
        "중국 부동산",
        "중국 수출",
        "중국 경기부양",
        "미중 관세",
    ],
    "japan": [
        "일본",
        "일본은행",
        "엔화",
        "일본 반도체",
        "일본 방위",
    ],
    "india": [
        "인도",
        "모디",
        "인도 제조업",
        "인도 경제",
        "인도 인프라",
    ],
    "singapore": [
        "싱가포르",
        "싱가포르 금융",
        "싱가포르 항만",
        "싱가포르 에너지",
        "싱가포르 반도체",
    ],
    "sea_other": [
        "인도네시아",
        "베트남",
        "태국",
        "말레이시아",
        "필리핀",
        "동남아",
    ],
    "europe": [
        "유럽",
        "EU",
        "독일",
        "프랑스",
        "영국",
        "ECB",
        "유럽 경기",
    ],
    "middle_east": [
        "중동",
        "이란",
        "사우디",
        "이스라엘",
        "카타르",
        "호르무즈",
        "가자",
    ],
    "latam": [
        "브라질",
        "멕시코",
        "아르헨티나",
        "칠레",
        "페루",
        "중남미",
    ],
    "africa": [
        "아프리카",
        "나이지리아",
        "남아공",
        "이집트",
        "에티오피아",
        "케냐",
    ],
}

REGION_LABELS = {
    "us": "🇺🇸 미국",
    "china": "🇨🇳 중국",
    "japan": "🇯🇵 일본",
    "india": "🇮🇳 인도",
    "singapore": "🇸🇬 싱가포르",
    "sea_other": "🌏 기타 동남아",
    "europe": "🇪🇺 유럽",
    "middle_east": "🛢 중동",
    "latam": "🌎 중남미",
    "africa": "🌍 아프리카",
    "global_extra": "🌐 글로벌 추가 주요뉴스",
}

REGION_PATTERNS = {
    "us": [
        r"\b미국\b", r"\b워싱턴\b", r"\b연준\b", r"\b백악관\b", r"\b트럼프\b", r"\b바이든\b",
        r"\busa\b", r"\bunited states\b", r"\bu\.s\.\b", r"\bfed\b", r"\bwhite house\b",
    ],
    "china": [
        r"\b중국\b", r"\b베이징\b", r"\b상하이\b", r"\b시진핑\b",
        r"\bchina\b", r"\bbeijing\b",
    ],
    "japan": [
        r"\b일본\b", r"\b도쿄\b", r"\b엔화\b", r"\b일본은행\b",
        r"\bjapan\b", r"\btokyo\b", r"\bboj\b",
    ],
    "india": [
        r"\b인도\b", r"\b뉴델리\b", r"\b모디\b",
        r"\bindia\b", r"\bnew delhi\b", r"\bmodi\b",
    ],
    "singapore": [
        r"\b싱가포르\b", r"\b싱가폴\b",
        r"\bsingapore\b", r"\bmas\b",
    ],
    "sea_other": [
        r"\b인도네시아\b", r"\b베트남\b", r"\b태국\b", r"\b말레이시아\b", r"\b필리핀\b",
        r"\b자카르타\b", r"\b하노이\b", r"\b방콕\b", r"\b쿠알라룸푸르\b", r"\b마닐라\b",
        r"\bindonesia\b", r"\bvietnam\b", r"\bthailand\b", r"\bmalaysia\b", r"\bphilippines\b",
        r"\bjakarta\b", r"\bhanoi\b", r"\bbangkok\b", r"\bkuala lumpur\b", r"\bmanila\b",
        r"\b동남아\b", r"\basean\b",
    ],
    "europe": [
        r"\b유럽\b", r"\beu\b", r"\beurope\b", r"\b유럽연합\b",
        r"\b독일\b", r"\b프랑스\b", r"\b영국\b", r"\b이탈리아\b", r"\b스페인\b",
        r"\bgermany\b", r"\bfrance\b", r"\buk\b", r"\bitaly\b", r"\bspain\b",
        r"\becb\b", r"\b브뤼셀\b", r"\bbrussels\b",
    ],
    "middle_east": [
        r"\b중동\b", r"\b이란\b", r"\b사우디\b", r"\b이스라엘\b", r"\b카타르\b", r"\buae\b",
        r"\biran\b", r"\biraq\b", r"\bsaudi\b", r"\bisrael\b", r"\bqatar\b", r"\babu dhabi\b",
        r"\b호르무즈\b", r"\btehran\b", r"\briyadh\b", r"\bgaza\b",
    ],
    "latam": [
        r"\b중남미\b", r"\b브라질\b", r"\b멕시코\b", r"\b아르헨티나\b", r"\b칠레\b", r"\b페루\b",
        r"\blatin america\b", r"\bbrasil\b", r"\bbrazil\b", r"\bmexico\b", r"\bargentina\b",
        r"\bchile\b", r"\bperu\b",
    ],
    "africa": [
        r"\b아프리카\b", r"\b나이지리아\b", r"\b남아공\b", r"\b이집트\b", r"\b에티오피아\b", r"\b케냐\b",
        r"\bafrica\b", r"\bnigeria\b", r"\bsouth africa\b", r"\begypt\b", r"\bethiopia\b", r"\bkenya\b",
    ],
}

# 한국 관련 해설형 기사 감점
KOREA_HEAVY_PATTERNS = [
    r"한국에 미치는", r"국내 영향", r"한국 증시", r"한국 수출", r"국내 업계",
    r"코스피", r"원화", r"삼성전자", r"현대차", r"국내 투자자",
]

HIGH_PATTERNS = [
    r"\bwar\b", r"\bconflict\b", r"\battack\b", r"\bmissile\b", r"\bstrike\b",
    r"\bceasefire\b", r"\bsanctions?\b", r"\bcoup\b", r"\btariffs?\b",
    r"\bcentral bank\b", r"\binterest rate\b", r"\binflation\b", r"\brecession\b",
    r"\bexport control\b", r"\bexport ban\b", r"\bembargo\b", r"\bshutdown\b",
    r"\bforce majeure\b", r"\boutage\b", r"\bexplosion\b", r"\bfire\b",
    r"\belection\b", r"\bpolicy shift\b", r"\bregulation\b",
    r"\bsummit\b", r"\bdeal\b", r"\bagreement\b", r"\btrade\b",
    r"전쟁", r"분쟁", r"공격", r"미사일", r"휴전", r"제재", r"관세", r"금리", r"인플레이션",
    r"중앙은행", r"침체", r"수출통제", r"수출금지", r"셧다운", r"가동중단",
    r"폭발", r"화재", r"선거", r"정책 변화", r"규제", r"정상회담", r"합의", r"무역",
]

MEDIUM_PATTERNS = [
    r"\beconomy\b", r"\bmarket\b", r"\bindustry\b", r"\bmanufacturing\b",
    r"\benergy\b", r"\blng\b", r"\boil\b", r"\bgas\b", r"\bsemiconductor\b", r"\bai\b",
    r"경제", r"시장", r"산업", r"제조업", r"에너지", r"LNG", r"원유", r"가스", r"반도체", r"AI",
]

LOW_QUALITY_PATTERNS = [
    r"\bopinion\b", r"\beditorial\b", r"\bcolumn\b", r"\bslideshow\b",
    r"\binterview\b", r"\bpreview\b", r"\bfeature\b",
    r"사설", r"칼럼", r"포토", r"화보", r"인터뷰", r"전망",
]

BLOCK_PATTERNS = [
    r"\bcelebrity\b", r"\bgossip\b", r"\bscandal\b", r"\breality show\b",
    r"\btransfer rumor\b", r"\bmatch preview\b", r"\bfantasy\b",
    r"\bbitcoin\b", r"\bcrypto\b", r"\betf\b", r"\bdividend\b", r"\bstock tips?\b",
    r"\bfashion\b", r"\bmakeup\b", r"\bdating\b", r"\btravel tips\b",
    r"연예", r"가십", r"스캔들", r"이적설", r"경기 예상", r"판타지",
    r"비트코인", r"코인", r"ETF", r"배당", r"종목 추천",
    r"패션", r"메이크업", r"연애", r"여행 팁",
]

TIER1_SOURCES = [
    "Reuters", "로이터",
    "Bloomberg", "블룸버그",
    "연합뉴스",
    "Nikkei", "니케이",
    "Financial Times", "FT",
    "BBC", "AP", "Associated Press",
]

TIER2_SOURCES = [
    "한국경제", "매일경제", "조선비즈", "서울경제", "이데일리",
    "머니투데이", "아시아경제", "중앙일보", "동아일보", "한겨레",
]

ALLOW_BONUS_GLOBAL_SLOT = True
BONUS_GLOBAL_SLOT_COUNT = 2
ALLOW_REGION_UNDERFILL = True
MAX_ENTRIES_PER_KEYWORD = 10

def google_news_rss_url(keyword: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(keyword)}&hl={HL}&gl={GL}&ceid={CEID}"

def load_seen() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            print(f"[WARN] load_seen failed: {e}")
    return {}

def save_seen(seen_map: dict):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(seen_map, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] save_seen failed: {e}")

def normalize_title(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", (text or "").lower())
    text = re.sub(r"[^\w\s가-힣]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def clean_html_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()

def format_date(dt: datetime) -> str:
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")

def is_quiet_time_kst() -> bool:
    now_hour = datetime.now(KST).hour
    return now_hour >= QUIET_HOUR_START or now_hour < QUIET_HOUR_END

def get_source(entry):
    try:
        if hasattr(entry, "source") and entry.source:
            return (entry.source.get("title") or "").strip()
    except Exception:
        pass
    title = entry.get("title", "") or ""
    return title.split(" - ")[-1].strip() if " - " in title else ""

def source_tier(source: str) -> int:
    s = (source or "").lower()
    if any(x.lower() in s for x in TIER1_SOURCES):
        return 1
    if any(x.lower() in s for x in TIER2_SOURCES):
        return 2
    return 3

def parse_entry_datetime(entry):
    try:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            return datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=UTC)
    except Exception:
        pass
    try:
        if hasattr(entry, "updated_parsed") and entry.updated_parsed:
            return datetime.fromtimestamp(time.mktime(entry.updated_parsed), tz=UTC)
    except Exception:
        pass
    return None

def is_within_lookback_kst(entry_dt):
    if not entry_dt:
        return False
    now_kst = datetime.now(KST)
    entry_kst = entry_dt.astimezone(KST)
    return now_kst - entry_kst <= timedelta(days=LOOKBACK_DAYS)

def contains_any_pattern(text: str, patterns) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)

def get_text_blob(title: str, summary: str, keyword: str = "") -> str:
    return f"{title} {summary} {keyword}".strip().lower()

def extract_topic_signature(title: str) -> str:
    text = normalize_title(title)
    stopwords = {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at",
        "from", "by", "after", "over", "amid", "as", "is", "are", "will",
        "news", "global", "world", "international",
        "세계", "국제", "글로벌", "주요", "뉴스", "관련", "대한", "오늘",
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

def guess_region(title: str, summary: str, keyword: str):
    text = get_text_blob(title, summary, keyword)
    region_scores = {}

    for region, patterns in REGION_PATTERNS.items():
        score = 0
        for p in patterns:
            if re.search(p, text, re.I):
                score += 1
        if score > 0:
            region_scores[region] = score

    if not region_scores:
        return None

    return sorted(region_scores.items(), key=lambda x: x[1], reverse=True)[0][0]

def is_korea_heavy_news(title: str, summary: str) -> bool:
    text = get_text_blob(title, summary)
    return contains_any_pattern(text, KOREA_HEAVY_PATTERNS)

def is_event_worthy(title: str, summary: str, keyword: str) -> bool:
    text = get_text_blob(title, summary, keyword)

    if contains_any_pattern(text, BLOCK_PATTERNS):
        return False

    if contains_any_pattern(text, HIGH_PATTERNS):
        return True

    if contains_any_pattern(text, MEDIUM_PATTERNS):
        return True

    return False

def calculate_score(item, selected_signatures=None):
    title = item["title"]
    summary = item.get("summary", "")
    source = item["source"]
    text = get_text_blob(title, summary)
    score = 0

    if contains_any_pattern(text, HIGH_PATTERNS):
        score += 8
    elif contains_any_pattern(text, MEDIUM_PATTERNS):
        score += 3

    tier = source_tier(source)
    if tier == 1:
        score += 4
    elif tier == 2:
        score += 2

    # 한국 해설형은 약한 감점만
    if is_korea_heavy_news(title, summary):
        score -= 2

    if contains_any_pattern(text, LOW_QUALITY_PATTERNS):
        score -= 3

    if contains_any_pattern(text, [
        r"\bglobal\b", r"\bworld\b", r"\binternational\b", r"\bmajor\b",
        r"\bcentral bank\b", r"\bsupply chain\b", r"\benergy crisis\b",
        r"글로벌", r"세계", r"국제", r"중앙은행", r"공급망", r"에너지 위기",
    ]):
        score += 2

    # 지역 추정은 버리는 조건이 아니라 가점용
    guessed = item.get("guessed_region")
    region = item.get("region")
    if guessed and guessed == region:
        score += 3
    elif guessed:
        score += 1

    if selected_signatures:
        for sig in selected_signatures:
            if topic_overlap(item["topic_signature"], sig):
                score -= 5
                break

    return score

def build_uid(link: str, title: str) -> str:
    return f"{link}|{normalize_title(title)}"

def short_summary(text: str, max_len: int = 110) -> str:
    text = clean_html_text(text)
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "..."

def prune_seen_today_only(seen_map: dict) -> dict:
    cutoff = datetime.now(KST) - timedelta(days=LOOKBACK_DAYS)
    kept = {}
    for k, v in seen_map.items():
        try:
            dt = datetime.strptime(v, "%Y-%m-%d")
            dt = datetime(dt.year, dt.month, dt.day, tzinfo=KST)
            if dt >= cutoff:
                kept[k] = v
        except Exception:
            pass
    return kept

def fetch_news():
    items = []

    for region, keywords in REGION_KEYWORDS.items():
        for kw in keywords:
            try:
                print(f"[INFO] Fetching [{region}] {kw}")
                feed = feedparser.parse(google_news_rss_url(kw))

                for entry in feed.entries[:MAX_ENTRIES_PER_KEYWORD]:
                    title = (entry.get("title") or "").strip()
                    link = (entry.get("link") or "").strip()
                    summary = clean_html_text(entry.get("summary", ""))
                    source = get_source(entry)
                    entry_dt = parse_entry_datetime(entry)

                    if not title or not link:
                        continue
                    if not entry_dt:
                        continue
                    if not is_within_lookback_kst(entry_dt):
                        continue

                    if not DEBUG_RELAX_MODE and not is_event_worthy(title, summary, kw):
                        continue

                    guessed_region = guess_region(title, summary, kw)

                    item = {
                        "uid": build_uid(link, title),
                        "title": title,
                        "title_norm": normalize_title(title),
                        "link": link,
                        "summary": summary,
                        "source": source,
                        "keyword": kw,
                        "published_dt": entry_dt,
                        "published": format_date(entry_dt),
                        "region": region,
                        "guessed_region": guessed_region,
                    }
                    item["topic_signature"] = extract_topic_signature(title)
                    items.append(item)

                time.sleep(1)

            except Exception as e:
                print(f"[WARN] Fetch failed for [{region}] {kw}: {e}")

    return items

def deduplicate_initial(items, seen_map):
    result = []
    local_uids = set()
    local_titles = set()

    for item in items:
        uid = item["uid"]

        if uid in seen_map:
            continue
        if uid in local_uids:
            continue
        if item["title_norm"] in local_titles:
            continue

        local_uids.add(uid)
        local_titles.add(item["title_norm"])
        result.append(item)

    return result

def pick_region_items(items):
    region_selected = {region: [] for region in REGION_QUOTA.keys()}
    region_candidates = {region: [] for region in REGION_QUOTA.keys()}

    for item in items:
        region = item.get("region")
        if region in region_candidates:
            region_candidates[region].append(item)

    for region, candidates in region_candidates.items():
        local_candidates = candidates[:]

        for item in local_candidates:
            item["score"] = calculate_score(item)

        local_candidates.sort(
            key=lambda x: (
                x["score"],
                -source_tier(x["source"]),
                x["published_dt"],
            ),
            reverse=True,
        )

        picked = []
        for item in local_candidates:
            if len(picked) >= REGION_QUOTA[region]:
                break

            if any(topic_overlap(item["topic_signature"], p["topic_signature"]) for p in picked):
                continue

            picked.append(item)

        region_selected[region] = picked

    return region_selected

def fill_global_extras(items, region_selected):
    already_uids = set()
    selected_signatures = []

    for picks in region_selected.values():
        for item in picks:
            already_uids.add(item["uid"])
            selected_signatures.append(item["topic_signature"])

    leftovers = []
    for item in items:
        if item["uid"] in already_uids:
            continue
        item["score"] = calculate_score(item, selected_signatures)
        leftovers.append(item)

    leftovers.sort(
        key=lambda x: (
            x["score"],
            -source_tier(x["source"]),
            x["published_dt"],
        ),
        reverse=True,
    )

    extras = []
    for item in leftovers:
        if len(extras) >= BONUS_GLOBAL_SLOT_COUNT:
            break
        if any(topic_overlap(item["topic_signature"], e["topic_signature"]) for e in extras):
            continue
        extras.append(item)

    return extras

def attach_importance_label(items):
    for item in items:
        if item["score"] >= 10:
            item["importance"] = "🔴 HIGH"
        elif item["score"] >= 5:
            item["importance"] = "🟠 MEDIUM"
        else:
            item["importance"] = "🟢 LOW"
    return items

def format_single_item(item):
    lines = [
        item["importance"],
        item["published"],
        f'<a href="{item["link"]}">{html.escape(item["title"])}</a>',
        f"Source: {html.escape(item['source'] or 'Unknown')}",
    ]

    one_line = short_summary(item.get("summary", ""))
    if one_line:
        lines.append(f"Summary: {html.escape(one_line)}")

    return "\n".join(lines)

def flatten_grouped_items(region_selected, extras):
    ordered = []
    region_order = [
        "us", "china", "japan", "india", "singapore",
        "sea_other", "europe", "middle_east", "latam", "africa"
    ]

    for region in region_order:
        items = region_selected.get(region, [])
        if not items and ALLOW_REGION_UNDERFILL:
            continue
        if items:
            ordered.append(("header", REGION_LABELS[region]))
            for item in items:
                ordered.append(("item", item))

    if extras:
        ordered.append(("header", REGION_LABELS["global_extra"]))
        for item in extras:
            ordered.append(("item", item))

    return ordered

def chunk_messages(grouped_entries):
    messages = []
    current = f"📰 세계 지역별 주요뉴스 Digest (최근 {LOOKBACK_DAYS}일)\n\n"

    for entry_type, payload in grouped_entries:
        if entry_type == "header":
            block = f"{payload}\n"
        else:
            block = format_single_item(payload) + "\n"

        block = block + "\n"

        if len(current) + len(block) > MAX_TELEGRAM_MESSAGE_LENGTH:
            messages.append(current.rstrip())
            current = f"📰 세계 지역별 주요뉴스 Digest (최근 {LOOKBACK_DAYS}일)\n\n" + block
        else:
            current += block

    if current.strip():
        messages.append(current.rstrip())

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

    seen_map = prune_seen_today_only(load_seen())
    today_str = datetime.now(KST).strftime("%Y-%m-%d")

    raw_items = fetch_news()
    print(f"[INFO] Raw items: {len(raw_items)}")

    deduped_items = deduplicate_initial(raw_items, seen_map)
    print(f"[INFO] Deduped initial items: {len(deduped_items)}")

    region_selected = pick_region_items(deduped_items)
    total_region_count = sum(len(v) for v in region_selected.values())
    print(f"[INFO] Region selected count: {total_region_count}")

    extras = []
    if ALLOW_BONUS_GLOBAL_SLOT:
        extras = fill_global_extras(deduped_items, region_selected)
    print(f"[INFO] Extra selected count: {len(extras)}")

    final_items = []
    for region, items in region_selected.items():
        final_items.extend(items)
    final_items.extend(extras)

    if not final_items:
        print("[INFO] No valid world news found for today.")
        save_seen(seen_map)
        return

    selected_signatures = []
    for item in final_items:
        item["score"] = calculate_score(item, selected_signatures)
        selected_signatures.append(item["topic_signature"])

    final_items = attach_importance_label(final_items)

    final_uid_map = {x["uid"]: x for x in final_items}
    for region in list(region_selected.keys()):
        region_selected[region] = [
            final_uid_map[x["uid"]]
            for x in region_selected[region]
            if x["uid"] in final_uid_map
        ]
    extras = [final_uid_map[x["uid"]] for x in extras if x["uid"] in final_uid_map]

    grouped_entries = flatten_grouped_items(region_selected, extras)
    messages = chunk_messages(grouped_entries)
    print(f"[INFO] Message chunks: {len(messages)}")

    all_sent = True
    for msg in messages:
        ok = send_telegram(msg)
        if not ok:
            all_sent = False
            break

    if all_sent:
        for item in final_items:
            seen_map[item["uid"]] = today_str

    save_seen(seen_map)
    print(
        f"[INFO] Done. Sent {len(final_items) if all_sent else 0} items "
        f"in {len(messages) if all_sent else 0} message(s)."
    )

if __name__ == "__main__":
    main()
