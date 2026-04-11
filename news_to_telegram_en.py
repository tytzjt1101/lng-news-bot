# 미국·중국·일본·인도·싱가포르·동남아·유럽·중동·중남미·아프리카 뉴스

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

# 지역별 내부 검색 키워드
REGION_KEYWORDS = {
    "us": [
        "미국 정치 경제 외교",
        "미국 연준 금리 관세",
        "미국 빅테크 AI 반도체",
        "미국 무역 정책 제조업",
    ],
    "china": [
        "중국 경제 부동산 산업정책",
        "중국 외교 미중갈등 반도체",
        "중국 경기부양 수출 내수",
    ],
    "japan": [
        "일본 경제 엔화 반도체 정책",
        "일본 정치 외교 방위",
    ],
    "india": [
        "인도 경제 제조업 인프라",
        "인도 외교 정책 산업",
    ],
    "singapore": [
        "싱가포르 경제 금융 정책",
        "싱가포르 항만 물류 에너지",
        "싱가포르 반도체 산업 투자",
    ],
    "sea_other": [
        "인도네시아 베트남 태국 말레이시아 필리핀 경제 정치",
        "동남아 공급망 제조업 외교",
        "인도네시아 베트남 에너지 인프라",
    ],
    "europe": [
        "유럽 경기 산업 규제",
        "EU 독일 프랑스 영국 정책",
        "유럽 중앙은행 방산 에너지",
    ],
    "middle_east": [
        "중동 이란 사우디 이스라엘 에너지",
        "호르무즈 석유 LNG 외교",
        "중동 전쟁 휴전 제재",
    ],
    "latam": [
        "브라질 멕시코 아르헨티나 정치 경제",
        "중남미 자원 통화 대선",
        "브라질 멕시코 산업 무역",
    ],
    "africa": [
        "아프리카 쿠데타 광물 인프라 에너지",
        "나이지리아 남아공 이집트 에티오피아 경제",
        "아프리카 항만 자원 중국 투자",
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

# 지역별 대표 국가/단어 매칭
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
    ],
    "europe": [
        r"\b유럽\b", r"\beu\b", r"\beurope\b", r"\b유럽연합\b",
        r"\b독일\b", r"\b프랑스\b", r"\b영국\b", r"\b이탈리아\b", r"\b스페인\b",
        r"\bgermany\b", r"\bfrance\b", r"\buk\b", r"\bitaly\b", r"\bspain\b",
        r"\becb\b", r"\b브뤼셀\b", r"\bbrussels\b",
    ],
    "middle_east": [
        r"\b중동\b", r"\b이란\b", r"\b사우디\b", r"\b이스라엘\b", r"\b카타르\b", r"\buae\b",
        r"\bira[nq]\b", r"\bsaudi\b", r"\bisrael\b", r"\bqatar\b", r"\babu dhabi\b",
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

# 한국 중심 기사 감점/제외용
KOREA_HEAVY_PATTERNS = [
    r"\b한국\b", r"\b국내\b", r"\b우리나라\b", r"\b정부\b", r"\b원화\b", r"\b코스피\b",
    r"\b삼성\b", r"\b현대\b", r"\bsk\b", r"\blg\b", r"\b한국은행\b",
    r"\bkorea\b", r"\bsouth korea\b", r"\bkospi\b",
    r"한국에 미치는", r"국내 영향", r"한국 증시", r"한국 수출", r"국내 업계",
]

# 예외적으로 허용할 수 있는 국제 사건
KOREA_EXCEPTION_PATTERNS = [
    r"\b한미\b", r"\b한중\b", r"\b한일\b", r"\b정상회담\b", r"\b외교\b",
    r"\bkorea-us\b", r"\bkorea china\b", r"\bkorea japan\b",
]

# 중요 이벤트
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

# 출처 우선순위
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

# 초대형 사건 보너스 슬롯
ALLOW_BONUS_GLOBAL_SLOT = True
BONUS_GLOBAL_SLOT_COUNT = 2

# 지역 미달 허용
ALLOW_REGION_UNDERFILL = True

# 쿼리당 최대 기사 수
MAX_ENTRIES_PER_KEYWORD = 8

# =========================
# HELPERS
# =========================
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

def parse_entry_datetime(entry) -> datetime | None:
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

def is_today_kst(entry_dt: datetime | None) -> bool:
    if not entry_dt:
        return False
    return entry_dt.astimezone(KST).date() == datetime.now(KST).date()

def contains_any_pattern(text: str, patterns: list[str]) -> bool:
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

def guess_region(title: str, summary: str, keyword: str) -> str | None:
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
    if contains_any_pattern(text, KOREA_EXCEPTION_PATTERNS):
        return False
    return contains_any_pattern(text, KOREA_HEAVY_PATTERNS)

def is_event_worthy(title: str, summary: str, keyword: str) -> bool:
    text = get_text_blob(title, summary, keyword)

    if contains_any_pattern(text, BLOCK_PATTERNS):
        return False

    # 이벤트 중심: high면 통과, medium만 있으면 소극적 허용
    if contains_any_pattern(text, HIGH_PATTERNS):
        return True

    if contains_any_pattern(text, MEDIUM_PATTERNS):
        # medium 기사라도 지역/국가 맥락이 분명할 때만
        region = guess_region(title, summary, keyword)
        return region is not None

    return False

def classify_category(item) -> str:
    text = get_text_blob(item["title"], item.get("summary", ""))

    if contains_any_pattern(text, [
        r"\bwar\b", r"\bconflict\b", r"\bsanctions?\b", r"\btariffs?\b", r"\bmilitary\b",
        r"\bmissile\b", r"\bdiplomacy\b", r"\bsummit\b",
        r"전쟁", r"분쟁", r"제재", r"관세", r"미사일", r"외교", r"정상회담"
    ]):
        return "geopolitics"

    if contains_any_pattern(text, [
        r"\binflation\b", r"\binterest rate\b", r"\bcentral bank\b", r"\brecession\b",
        r"\beconomy\b", r"\bmarket\b", r"인플레이션", r"금리", r"중앙은행", r"침체", r"경제", r"시장"
    ]):
        return "economy"

    if contains_any_pattern(text, [
        r"\boil\b", r"\bgas\b", r"\blng\b", r"\benergy\b", r"\bopec\b",
        r"원유", r"가스", r"\bLNG\b", r"에너지"
    ]):
        return "energy"

    if contains_any_pattern(text, [
        r"\bai\b", r"\bsemiconductor\b", r"\bchip\b", r"\btechnology\b",
        r"AI", r"반도체", r"칩", r"기술"
    ]):
        return "tech"

    return "other"

def calculate_score(item, selected_signatures=None):
    title = item["title"]
    summary = item.get("summary", "")
    source = item["source"]
    text = get_text_blob(title, summary)
    score = 0

    # 중요 이벤트
    if contains_any_pattern(text, HIGH_PATTERNS):
        score += 8
    elif contains_any_pattern(text, MEDIUM_PATTERNS):
        score += 3

    # 출처
    tier = source_tier(source)
    if tier == 1:
        score += 4
    elif tier == 2:
        score += 2

    # 한국 중심 기사 감점
    if is_korea_heavy_news(title, summary):
        score -= 6

    # 저품질 감점
    if contains_any_pattern(text, LOW_QUALITY_PATTERNS):
        score -= 3

    # 글로벌 영향 키워드
    if contains_any_pattern(text, [
        r"\bglobal\b", r"\bworld\b", r"\binternational\b", r"\bmajor\b",
        r"\bcentral bank\b", r"\bsupply chain\b", r"\benergy crisis\b",
        r"글로벌", r"세계", r"국제", r"중앙은행", r"공급망", r"에너지 위기",
    ]):
        score += 2

    # 지역성이 분명하면 가점
    if item.get("region"):
        score += 2

    # 같은 사건 반복 감점
    if selected_signatures:
        for sig in selected_signatures:
            if topic_overlap(item["topic_signature"], sig):
                score -= 5
                break

    return score

def prune_seen_today_only(seen_map: dict) -> dict:
    today_str = datetime.now(KST).strftime("%Y-%m-%d")
    return {k: v for k, v in seen_map.items() if v == today_str}

def build_uid(link: str, title: str) -> str:
    return f"{link}|{normalize_title(title)}"

def short_summary(text: str, max_len: int = 110) -> str:
    text = clean_html_text(text)
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "..."

# =========================
# FETCH
# =========================
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
                    if not is_today_kst(entry_dt):
                        continue
                    if not is_event_worthy(title, summary, kw):
                        continue

                    guessed_region = guess_region(title, summary, kw)

                    # 검색 region과 실제 region이 너무 다르면 제외
                    # 단, 쿼리상 region을 전혀 못 잡은 경우는 query region 사용
                    final_region = guessed_region or region
                    if guessed_region and guessed_region != region:
                        # 미국 쿼리에서 중국 기사가 잡히는 식의 오염 방지
                        continue

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
                        "region": final_region,
                    }
                    item["category"] = classify_category(item)
                    item["topic_signature"] = extract_topic_signature(title)
                    items.append(item)

                time.sleep(1)

            except Exception as e:
                print(f"[WARN] Fetch failed for [{region}] {kw}: {e}")

    return items

# =========================
# FILTER / DEDUPE
# =========================
def deduplicate_initial(items, seen_map):
    result = []
    local_uids = set()
    local_titles = set()
    today_str = datetime.now(KST).strftime("%Y-%m-%d")

    for item in items:
        uid = item["uid"]

        if seen_map.get(uid) == today_str:
            continue
        if uid in local_uids:
            continue
        if item["title_norm"] in local_titles:
            continue

        local_uids.add(uid)
        local_titles.add(item["title_norm"])
        result.append(item)

    return result

def deduplicate_by_topic(items):
    final = []
    selected_signatures = []

    # 일단 고득점순 정렬
    for item in items:
        item["score"] = calculate_score(item, selected_signatures=None)

    items = sorted(
        items,
        key=lambda x: (
            x["score"],
            -source_tier(x["source"]),
            x["published_dt"],
        ),
        reverse=True,
    )

    for item in items:
        too_similar = False
        for sig in selected_signatures:
            if topic_overlap(item["topic_signature"], sig):
                too_similar = True
                break

        if too_similar:
            continue

        final.append(item)
        selected_signatures.append(item["topic_signature"])

    return final

# =========================
# SELECTION
# =========================
def pick_region_items(items):
    region_selected = {region: [] for region in REGION_QUOTA.keys()}
    region_candidates = {region: [] for region in REGION_QUOTA.keys()}

    # 지역별 분배
    for item in items:
        region = item.get("region")
        if region in region_candidates:
            region_candidates[region].append(item)

    # 지역별 정렬
    for region, candidates in region_candidates.items():
        selected_signatures = []
        for item in candidates:
            item["score"] = calculate_score(item, selected_signatures)
        candidates.sort(
            key=lambda x: (
                x["score"],
                -source_tier(x["source"]),
                x["published_dt"],
            ),
            reverse=True,
        )

        picked = []
        for item in candidates:
            if len(picked) >= REGION_QUOTA[region]:
                break

            # 같은 지역 내 같은 사건 중복 방지
            if any(topic_overlap(item["topic_signature"], p["topic_signature"]) for p in picked):
                continue

            # 너무 한국 영향 해설 중심이면 제외
            if is_korea_heavy_news(item["title"], item["summary"]):
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

        if any(topic_overlap(item["topic_signature"], s) for s in [e["topic_signature"] for e in extras]):
            continue
        if any(topic_overlap(item["topic_signature"], s) for s in selected_signatures):
            continue
        if is_korea_heavy_news(item["title"], item["summary"]):
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

# =========================
# FORMAT
# =========================
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
    current = "📰 세계 지역별 주요뉴스 Digest (당일 기사만)\n\n"

    for entry_type, payload in grouped_entries:
        if entry_type == "header":
            block = f"{payload}\n"
        else:
            block = format_single_item(payload) + "\n"

        # 헤더/아이템 사이 공백
        block = block + "\n"

        if len(current) + len(block) > MAX_TELEGRAM_MESSAGE_LENGTH:
            messages.append(current.rstrip())
            current = "📰 세계 지역별 주요뉴스 Digest (당일 기사만)\n\n" + block
        else:
            current += block

    if current.strip():
        messages.append(current.rstrip())

    return messages

# =========================
# TELEGRAM
# =========================
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

# =========================
# MAIN
# =========================
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

    deduped_items = deduplicate_by_topic(deduped_items)
    print(f"[INFO] Deduped by topic items: {len(deduped_items)}")

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

    # score / importance 정리
    selected_signatures = []
    for item in final_items:
        item["score"] = calculate_score(item, selected_signatures)
        selected_signatures.append(item["topic_signature"])
    final_items = attach_importance_label(final_items)

    # region_selected / extras에 score 반영된 객체 다시 반영
    final_uid_map = {x["uid"]: x for x in final_items}
    for region in list(region_selected.keys()):
        region_selected[region] = [final_uid_map[x["uid"]] for x in region_selected[region] if x["uid"] in final_uid_map]
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
    print(f"[INFO] Done. Sent {len(final_items) if all_sent else 0} items in {len(messages) if all_sent else 0} message(s).")

if __name__ == "__main__":
    main()
