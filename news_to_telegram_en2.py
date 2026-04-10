import requests
import json
import os
import re
import time
import html
from datetime import datetime, timedelta, timezone

from googletrans import Translator


BOT_TOKEN = os.environ["BOT_TOKEN_EN_2"].strip()
CHAT_ID = os.environ["CHAT_ID_EN_2"].strip()
X_BEARER_TOKEN = os.environ["X_BEARER_TOKEN"].strip()

STATE_FILE = "seen_x_posts_ko.json"

QUIET_HOUR_START = 21   # 21:00 KST
QUIET_HOUR_END = 6      # 06:00 KST

MAX_ITEMS_PER_RUN = 10
MAX_POSTS_PER_USER = 5
MAX_TELEGRAM_MESSAGE_LENGTH = 3800

SEND_INTERVAL_SECONDS = 2
MAX_RETRY = 5
REQUEST_TIMEOUT = 30

translator = Translator()

TRACKED_USERS = [
    {"name": "Elon Musk", "username": "elonmusk"},
    {"name": "Tim Cook", "username": "tim_cook"},
    {"name": "Sam Altman", "username": "sama"},
    {"name": "Sundar Pichai", "username": "sundarpichai"},
    {"name": "Narendra Modi", "username": "narendramodi"},
    {"name": "Donald Trump", "username": "realDonaldTrump"},
]


def x_headers():
    return {
        "Authorization": f"Bearer {X_BEARER_TOKEN}",
        "Content-Type": "application/json",
    }


def load_seen():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
        except Exception as e:
            print(f"load_seen error: {e}")
    return set()


def save_seen(seen):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(seen)), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"save_seen error: {e}")


def is_quiet_time_kst() -> bool:
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    hour = now_kst.hour
    return hour >= QUIET_HOUR_START or hour < QUIET_HOUR_END


def format_date(date_str: str) -> str:
    if not date_str:
        return "Unknown"

    patterns = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
    ]

    for pattern in patterns:
        try:
            dt = datetime.strptime(date_str, pattern)
            return dt.strftime("%d %b %Y (%a)")
        except Exception:
            pass

    return date_str


def clean_text(text: str) -> str:
    if not text:
        return ""

    text = html.unescape(text)
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def shorten(text: str, limit: int = 280) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def translate_to_korean(text: str) -> str:
    if not text:
        return ""
    try:
        result = translator.translate(text, dest="ko")
        return result.text.strip()
    except Exception as e:
        print(f"translate error: {e}")
        return text


def get_user_ids(users):
    usernames = ",".join([u["username"] for u in users])
    url = "https://api.x.com/2/users/by"
    params = {
        "usernames": usernames,
        "user.fields": "username,name",
    }

    resp = requests.get(url, headers=x_headers(), params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    user_map = {}
    for user in data.get("data", []):
        user_map[user["username"].lower()] = {
            "id": user["id"],
            "name": user.get("name", ""),
            "username": user.get("username", ""),
        }

    return user_map


def fetch_user_posts(user_id: str):
    url = f"https://api.x.com/2/users/{user_id}/tweets"
    params = {
        "max_results": MAX_POSTS_PER_USER,
        "tweet.fields": "created_at,public_metrics,lang",
        "exclude": "replies,retweets",
    }

    resp = requests.get(url, headers=x_headers(), params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", [])


def build_post_link(username: str, post_id: str) -> str:
    return f"https://x.com/{username}/status/{post_id}"


def score_post(post_text: str, user_name: str) -> int:
    text = post_text.lower()
    score = 0

    important_patterns = [
        r"\bai\b", r"\bchip\b", r"\bsemiconductor\b", r"\btesla\b", r"\bspacex\b",
        r"\bapple\b", r"\bgoogle\b", r"\bmicrosoft\b", r"\bopenai\b",
        r"\bchina\b", r"\bus\b", r"\busa\b", r"\brussia\b", r"\bindia\b",
        r"\bpolicy\b", r"\btariff\b", r"\btrade\b", r"\benergy\b", r"\blng\b",
        r"\belection\b", r"\bmarket\b", r"\bfed\b", r"\binterest rate\b",
    ]

    for pattern in important_patterns:
        if re.search(pattern, text, re.I):
            score += 2

    # 길이가 너무 짧은 포스트는 우선순위 낮춤
    if len(post_text) < 40:
        score -= 1

    # 주요 인물 가중치
    if user_name in ["Elon Musk", "Donald Trump"]:
        score += 2
    elif user_name in ["Sam Altman", "Tim Cook", "Sundar Pichai", "Narendra Modi"]:
        score += 1

    return score


def deduplicate_and_sort(items, seen):
    result = []
    local_seen = set()
    person_counts = {}

    for item in items:
        if item["uid"] in seen or item["uid"] in local_seen:
            continue

        # 한 사람당 최대 2개까지만
        count = person_counts.get(item["person"], 0)
        if count >= 2:
            continue

        local_seen.add(item["uid"])
        person_counts[item["person"]] = count + 1
        result.append(item)

    result.sort(key=lambda x: x["score"], reverse=True)
    return result[:MAX_ITEMS_PER_RUN]


def fetch_all_posts():
    all_items = []

    user_map = get_user_ids(TRACKED_USERS)

    for tracked in TRACKED_USERS:
        username = tracked["username"].lower()
        person_name = tracked["name"]

        if username not in user_map:
            print(f"user not found: {username}")
            continue

        user_id = user_map[username]["id"]
        real_username = user_map[username]["username"]

        try:
            posts = fetch_user_posts(user_id)
            print(f"Fetched {len(posts)} posts from @{real_username}")

            for post in posts:
                post_id = post.get("id")
                text = clean_text(post.get("text", ""))
                created_at = post.get("created_at", "")

                if not post_id or not text:
                    continue

                link = build_post_link(real_username, post_id)
                translated_text = translate_to_korean(shorten(text, 300))

                item = {
                    "uid": f"{real_username}|{post_id}",
                    "person": person_name,
                    "username": real_username,
                    "post_id": post_id,
                    "text": text,
                    "text_ko": translated_text,
                    "created_at": created_at,
                    "date_text": format_date(created_at),
                    "link": link,
                    "score": score_post(text, person_name),
                }

                all_items.append(item)

            time.sleep(1)

        except Exception as e:
            print(f"fetch_user_posts error for @{real_username}: {e}")

    return all_items


def format_message_item(item):
    person = html.escape(item["person"])
    date_text = html.escape(item["date_text"] or "Unknown")
    text_ko = html.escape(item["text_ko"] or item["text"])
    username = html.escape(item["username"])

    lines = [
        f"{person}",
        f"{date_text}",
        f'<a href="{item["link"]}">{text_ko}</a>',
        f"Account: @{username}",
    ]

    return "\n".join(lines)


def chunk_messages(items):
    temp_chunks = []
    current_parts = []
    current_length = 0

    for item in items:
        item_text = format_message_item(item)

        if current_parts:
            add_len = len("\n\n") + len(item_text)
        else:
            add_len = len("📰 Social Watch\n\n") + len(item_text)

        if current_parts and current_length + add_len > MAX_TELEGRAM_MESSAGE_LENGTH:
            temp_chunks.append(current_parts)
            current_parts = [item_text]
            current_length = len("📰 Social Watch\n\n") + len(item_text)
        else:
            current_parts.append(item_text)
            if len(current_parts) == 1:
                current_length = len("📰 Social Watch\n\n") + len(item_text)
            else:
                current_length += len("\n\n") + len(item_text)

    if current_parts:
        temp_chunks.append(current_parts)

    messages = []
    total = len(temp_chunks)

    if total == 1:
        body = "\n\n".join(temp_chunks[0])
        messages.append("📰 Social Watch\n\n" + body)
    else:
        for idx, chunk in enumerate(temp_chunks, start=1):
            body = "\n\n".join(chunk)
            messages.append(f"📰 Social Watch {idx}/{total}\n\n" + body)

    return messages


def send_telegram_message(text: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            print(f"telegram status={resp.status_code}, body={resp.text[:500]}")

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
                print(f"429 retry_after={retry_after}")
                time.sleep(retry_after + 1)
                continue

            return False

        except Exception as e:
            print(f"Telegram send error (attempt {attempt}): {e}")
            time.sleep(3)

    return False


def main():
    print("=== START ===")

    if is_quiet_time_kst():
        print("Quiet hours in KST. Skip sending.")
        return

    seen = load_seen()
    print(f"Loaded seen count: {len(seen)}")

    items = fetch_all_posts()
    print(f"Fetched raw items: {len(items)}")

    items = deduplicate_and_sort(items, seen)
    print(f"Items after dedup/sort: {len(items)}")

    if not items:
        print("No new direct social posts found.")
        return

    messages = chunk_messages(items)
    print(f"Message chunks: {len(messages)}")

    all_sent = True
    for msg in messages:
        ok = send_telegram_message(msg)
        if not ok:
            all_sent = False
            break

    if all_sent:
        for item in items:
            seen.add(item["uid"])
        save_seen(seen)

    print(f"Done. Sent {len(items) if all_sent else 0} items.")


if __name__ == "__main__":
    main()
