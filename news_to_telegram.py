import feedparser
import requests
import json
import os
import re
import time
import html
import hashlib

from urllib.parse import quote_plus
from datetime import datetime, timedelta, timezone
from deep_translator import GoogleTranslator

BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
CHAT_ID = os.environ["CHAT_ID"].strip()

HL = "en"
GL = "US"
CEID = "US:en"

STATE_FILE = "seen.json"

QUIET_HOUR_START = 21
QUIET_HOUR_END = 6

MAX_ITEMS_PER_RUN = 10
MAX_ENTRIES_PER_QUERY = 8
MAX_AGE_DAYS = 30

SEND_INTERVAL_SECONDS = 2
MAX_RETRY = 5
REQUEST_TIMEOUT = 20

MAX_TELEGRAM_MESSAGE_LENGTH = 3800

CATEGORY_QUOTA = {
    "Plant Operations": 2,
    "New Projects / FID": 1,
    "Contract / SPA": 2,
    "Labor / Regulatory Risk": 1,
    "Market / Price": 1,
    "Shipping / Geopolitics": 1,
    "Company / Portfolio": 2,
}

QUERY_GROUPS = {
    "Plant Operations": [
        "LNG plant outage",
        "LNG train shutdown",
        "LNG force majeure",
        "LNG plant restart",
        "liquefaction plant maintenance",
        "LNG production disruption",
    ],
    "New Projects / FID": [
        "LNG final investment decision",
        "LNG FID",
        "LNG project expansion",
        "LNG project commissioning",
        "new liquefaction project",
        "first LNG cargo project",
    ],
    "Contract / SPA": [
        "LNG sale and purchase agreement",
        "LNG SPA",
        "LNG offtake agreement",
        "long-term LNG contract",
        "LNG supply deal",
    ],
    "Labor / Regulatory Risk": [
        "LNG strike",
        "LNG labor dispute",
        "Australia LNG strike",
        "LNG regulatory approval",
        "LNG export permit",
        "LNG environmental approval",
    ],
    "Market / Price": [
        "JKM LNG price",
        "Asia LNG spot price",
        "Europe LNG imports",
        "LNG demand Asia",
        "TTF gas LNG",
    ],
    "Shipping / Geopolitics": [
        "LNG shipping disruption",
        "LNG freight rate",
        "Hormuz LNG",
        "Panama Canal LNG",
        "Red Sea LNG shipping",
    ],
    "Company / Portfolio": [
        "Shell LNG portfolio",
        "QatarEnergy LNG",
        "Cheniere LNG",
        "TotalEnergies LNG",
        "Petronas LNG",
        "Woodside LNG",
        "Chevron LNG",
        "ExxonMobil LNG",
    ],
}

PROJECT_WATCHLIST = [
    "LNG Canada",
    "Golden Pass LNG",
    "Plaquemines LNG",
    "Qatar North Field East",
    "Qatar North Field South",
    "Tangguh LNG",
    "Ichthys LNG",
    "Gorgon LNG",
    "Wheatstone LNG",
    "Prelude FLNG",
    "Darwin LNG",
    "Mozambique LNG",
    "Rovuma LNG",
    "Oman LNG",
    "Freeport LNG",
    "Sabine Pass",
    "Corpus Christi",
    "Cameron LNG",
    "Calcasieu Pass",
    "Arctic LNG 2",
]

PREFERRED_SOURCES = [
    "Reuters",
    "Bloomberg",
    "Financial Times",
    "ICIS",
    "S&P Global",
    "Platts",
    "Argus",
    "LNG Prime",
    "Natural Gas World",
    "Offshore Energy",
    "Upstream",
    "Energy Intelligence",
]

BLOCK_PATTERNS = [
    r"\bcrypto\b",
    r"\bbitcoin\b",
    r"\betf\b",
    r"\bforex\b",
    r"\bdividend\b",
    r"\bshare buyback\b",
]

SOFT_FINANCE_PATTERNS = [
    r"\bstock\b",
    r"\bshares\b",
    r"\bearnings\b",
    r"\bquarterly results\b",
]

ALLOW_FINANCE_IF_CONTAINS = [
    r"\blng production\b",
    r"\blng sales\b",
    r"\blng volume\b",
    r"\bliquefaction\b",
    r"\bportfolio\b",
    r"\bproject\b",
]

HIGH_PATTERNS_BY_CATEGORY = {
    "Plant Operations": [
        r"\boutage\b",
        r"\bshutdown\b",
        r"\bforce majeure\b",
        r"\bfire\b",
        r"\bexplosion\b",
        r"\bdisruption\b",
        r"\brestart delay\b",
        r"\bunplanned\b",
        r"\bmaintenance\b",
    ],
    "New Projects / FID": [
        r"\bFID\b",
        r"final investment decision",
        r"\bsanctioned\b",
        r"\bapproved\b",
        r"\bcommissioning\b",
        r"\bstart[- ]?up\b",
        r"\bfirst LNG\b",
        r"\bexpansion\b",
    ],
    "Contract / SPA": [
        r"\bSPA\b",
        r"sale and purchase agreement",
        r"offtake agreement",
        r"supply agreement",
        r"long[- ]term contract",
        r"supply deal",
    ],
    "Labor / Regulatory Risk": [
        r"\bstrike\b",
        r"\bunion\b",
        r"labor dispute",
        r"regulatory approval",
        r"export permit",
        r"court ruling",
        r"environmental approval",
    ],
    "Market / Price": [
        r"\bJKM\b",
        r"\bTTF\b",
        r"spot price",
        r"price spike",
        r"demand surge",
        r"supply shortage",
        r"imports rise",
    ],
    "Shipping / Geopolitics": [
        r"\bHormuz\b",
        r"Panama Canal",
        r"Red Sea",
        r"freight rate",
        r"shipping disruption",
        r"vessel delay",
    ],
    "Company / Portfolio": [
        r"portfolio",
        r"trading",
        r"supply portfolio",
        r"marketing",
        r"Shell",
        r"QatarEnergy",
        r"Cheniere",
        r"TotalEnergies",
        r"Petronas",
        r"Woodside",
        r"Chevron",
        r"ExxonMobil",
    ],
}

MEDIUM_PATTERNS = [
    r"\bexport\b",
    r"\bimport\b",
    r"\bdemand\b",
    r"\bsupply\b",
    r"\bcargo\b",
    r"\bfreight\b",
    r"\bshipping\b",
    r"\bprice\b",
    r"\bpolicy\b",
    r"\bcapacity\b",
    r"\btrain\b",
]


def google_news_rss_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl={HL}&gl={GL}&ceid={CEID}"
    )


def load_seen() -> set:
    if not os.path.exists(STATE_FILE):
        return set()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return set(data)

    except Exception:
        pass

    return set()


def save_seen(seen_set: set):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen_set)), f, ensure_ascii=False, indent=2)


def clean_html_text(text: str) -> str:
    text = text or ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(text: str) -> str:
    text = clean_html_text(text).lower()
    text = re.sub(r" - [^-]+$", "", text)
    text = re.sub(r"[^\w\s가-힣]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_hash(title: str) -> str:
    normalized = normalize_title(title)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def format_date(date_str: str) -> str:
    if not date_str:
        return "Unknown date"

    try:
        dt = datetime.strptime(date_str[:25], "%a, %d %b %Y %H:%M:%S")
        return dt.strftime("%d %b %Y (%a)")
    except Exception:
        return date_str[:30]


def is_quiet_time_kst() -> bool:
    now_kst = datetime.now(timezone(timedelta(hours=9))).hour
    return now_kst >= QUIET_HOUR_START or now_kst < QUIET_HOUR_END


def get_source(entry) -> str:
    try:
        if hasattr(entry, "source") and entry.source:
            source_title = entry.source.get("title", "")
            if source_title:
                return source_title
    except Exception:
        pass

    title = entry.get("title", "")
    if " - " in title:
        return title.split(" - ")[-1].strip()

    return "Unknown"


def is_preferred_source(source: str) -> bool:
    source = source or ""
    return any(s.lower() in source.lower() for s in PREFERRED_SOURCES)


def is_recent_entry(entry) -> bool:
    try:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            dt = datetime.fromtimestamp(
                time.mktime(entry.published_parsed),
                tz=timezone.utc
            )
            return datetime.now(timezone.utc) - dt <= timedelta(days=MAX_AGE_DAYS)
    except Exception:
        pass

    return True


def detect_project(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()

    for project in PROJECT_WATCHLIST:
        if project.lower() in text:
            return project

    return ""


def is_valid_news(title: str, summary: str, query: str) -> bool:
    text = f"{title} {summary} {query}".lower()

    core_terms = [
        "lng",
        "liquefaction",
        "natural gas",
        "gas",
        "jkm",
        "ttf",
    ]

    if not any(term in text for term in core_terms):
        return False

    if any(re.search(p, text, re.IGNORECASE) for p in BLOCK_PATTERNS):
        return False

    has_soft_finance = any(
        re.search(p, text, re.IGNORECASE) for p in SOFT_FINANCE_PATTERNS
    )

    has_allowed_context = any(
        re.search(p, text, re.IGNORECASE) for p in ALLOW_FINANCE_IF_CONTAINS
    )

    if has_soft_finance and not has_allowed_context:
        return False

    return True


def calculate_score(title, summary, source, category, project):
    text = f"{title} {summary}"

    score = 0

    if is_preferred_source(source):
        score += 2

    if project:
        score += 2

    for pattern in HIGH_PATTERNS_BY_CATEGORY.get(category, []):
        if re.search(pattern, text, re.IGNORECASE):
            score += 3
            break

    for pattern in MEDIUM_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            score += 1
            break

    return score


def get_importance(score: int) -> str:
    if score >= 6:
        return "🔴 HIGH"

    if score >= 3:
        return "🟠 MEDIUM"

    return "🟢 LOW"


def translate_title_to_korean(title: str) -> str:
    """
    번역 실패해도 전체 봇이 죽지 않도록 구성
    """

    try:
        translated = GoogleTranslator(
            source="en",
            target="ko"
        ).translate(title)

        if translated and isinstance(translated, str):
            return translated.strip()

        return title

    except Exception as e:
        print(f"Translation failed: {e}")
        return title


def fetch_news():
    items = []

    for category, queries in QUERY_GROUPS.items():

        for query in queries:

            try:
                feed = feedparser.parse(
                    google_news_rss_url(query)
                )

            except Exception as e:
                print(f"Feed parse failed: {query} / {e}")
                continue

            for entry in feed.entries[:MAX_ENTRIES_PER_QUERY]:

                title = clean_html_text(
                    entry.get("title", "")
                )

                link = entry.get("link", "")

                summary = clean_html_text(
                    entry.get("summary", "")
                )

                source = get_source(entry)

                project = detect_project(title, summary)

                if not title or not link:
                    continue

                if not is_recent_entry(entry):
                    continue

                if not is_valid_news(title, summary, query):
                    continue

                score = calculate_score(
                    title,
                    summary,
                    source,
                    category,
                    project
                )

                uid_base = f"{link}|{title_hash(title)}"

                items.append({
                    "uid": uid_base,
                    "title": title,
                    "korean_title": translate_title_to_korean(title),
                    "link": link,
                    "summary": summary[:300],
                    "source": source,
                    "category": category,
                    "keyword": query,
                    "project": project,
                    "published": format_date(
                        entry.get("published", "")
                    ),
                    "score": score,
                    "importance": get_importance(score),
                    "title_hash": title_hash(title),
                })

            time.sleep(1)

    return items


def deduplicate(items, seen):
    result = []

    used_links = set()
    used_title_hashes = set()

    for item in items:

        if item["uid"] in seen:
            continue

        if item["link"] in used_links:
            continue

        if item["title_hash"] in used_title_hashes:
            continue

        used_links.add(item["link"])
        used_title_hashes.add(item["title_hash"])

        result.append(item)

    return result


def select_by_category_quota(items):
    selected = []

    for category, quota in CATEGORY_QUOTA.items():

        category_items = [
            item for item in items
            if item["category"] == category
        ]

        category_items.sort(
            key=lambda x: (
                x["score"],
                is_preferred_source(x["source"]),
                bool(x["project"]),
            ),
            reverse=True
        )

        selected.extend(category_items[:quota])

    selected.sort(
        key=lambda x: (
            list(CATEGORY_QUOTA.keys()).index(
                x["category"]
            ),
            -x["score"],
        )
    )

    return selected[:MAX_ITEMS_PER_RUN]


def format_single_item(item):

    safe_link = html.escape(
        item["link"],
        quote=True
    )

    safe_title = html.escape(
        item["title"]
    )

    safe_korean_title = html.escape(
        item.get("korean_title") or item["title"]
    )

    safe_source = html.escape(
        item["source"] or "Unknown"
    )

    safe_keyword = html.escape(
        item["keyword"]
    )

    safe_project = html.escape(
        item["project"] or "-"
    )

    safe_category = html.escape(
        item["category"]
    )

    safe_date = html.escape(
        item["published"]
    )

    lines = [
        item["importance"],
        f"<b>[{safe_category}]</b>",
        safe_date,
        f'<a href="{safe_link}">{safe_korean_title}</a>',
        f"Original: {safe_title}",
        f"Source: {safe_source}",
        f"Project: {safe_project}",
        f"Keyword: {safe_keyword}",
    ]

    return "\n".join(lines)


def chunk_messages(items):

    messages = []

    current_blocks = []

    current_length = 0

    header = "📰 LNG Industry Monitor\n\n"

    current_length = len(header)

    for item in items:

        block = format_single_item(item)

        block_len = len(block) + 2

        if (
            current_blocks and
            current_length + block_len >
            MAX_TELEGRAM_MESSAGE_LENGTH
        ):

            messages.append(
                header + "\n\n".join(current_blocks)
            )

            current_blocks = [block]

            current_length = (
                len(header) + len(block)
            )

        else:
            current_blocks.append(block)
            current_length += block_len

    if current_blocks:
        messages.append(
            header + "\n\n".join(current_blocks)
        )

    return messages


def send_telegram(text):

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    for attempt in range(1, MAX_RETRY + 1):

        try:

            response = requests.post(
                url,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 200:
                time.sleep(
                    SEND_INTERVAL_SECONDS
                )
                return True

            if response.status_code == 429:

                retry_after = 10

                try:
                    retry_after = response.json().get(
                        "parameters",
                        {}
                    ).get("retry_after", 10)

                except Exception:
                    pass

                time.sleep(retry_after + 1)

                continue

            if response.status_code in [
                500, 502, 503, 504
            ]:
                time.sleep(5 * attempt)
                continue

            print(
                f"Telegram send failed: "
                f"{response.status_code} "
                f"{response.text}"
            )

            return False

        except requests.exceptions.RequestException as e:

            print(
                f"Telegram request error: {e}"
            )

            time.sleep(5 * attempt)

    return False


def main():

    if is_quiet_time_kst():
        print("Quiet time. Skip.")
        return

    seen = load_seen()

    all_items = fetch_news()

    fresh_items = deduplicate(
        all_items,
        seen
    )

    selected_items = select_by_category_quota(
        fresh_items
    )

    if not selected_items:
        print("No new LNG news.")
        save_seen(seen)
        return

    messages = chunk_messages(
        selected_items
    )

    sent_all = True

    for msg in messages:

        ok = send_telegram(msg)

        if not ok:
            sent_all = False
            break

    if sent_all:

        for item in selected_items:
            seen.add(item["uid"])

        save_seen(seen)

        print(
            f"Sent {len(selected_items)} items."
        )

    else:
        print(
            "Sending failed. "
            "seen.json not updated."
        )


if __name__ == "__main__":
    main()
