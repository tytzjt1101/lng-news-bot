import requests
import json
import os
import re
import time
import html
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ.get("BOT_TOKEN_EN_2", "").strip()
CHAT_ID = os.environ.get("CHAT_ID_EN_2", "").strip()
X_BEARER_TOKEN = os.environ.get("X_BEARER_TOKEN", "").strip()

STATE_FILE = "seen_x_posts.json"

QUIET_HOUR_START = 21
QUIET_HOUR_END = 6

MAX_ITEMS_PER_RUN = 10
MAX_POSTS_PER_USER = 5
MAX_ITEMS_PER_USER_AFTER_DEDUP = 2
MAX_TELEGRAM_MESSAGE_LENGTH = 3800

SEND_INTERVAL_SECONDS = 2
MAX_RETRY = 5
REQUEST_TIMEOUT = 30

USE_X = bool(X_BEARER_TOKEN)
USE_TELEGRAM = bool(BOT_TOKEN and CHAT_ID)

TRACKED_USERS = [
    {"name": "Elon Musk", "username": "elonmusk"},
    {"name": "Tim Cook", "username": "tim_cook"},
    {"name": "Sam Altman", "username": "sama"},
    {"name": "Sundar Pichai", "username": "sundarpichai"},
]


def x_headers():
    if not USE_X:
        return {}
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
            print(f"[WARN] Failed to load {STATE_FILE}: {e}")
    return set()


def save_seen(seen):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(seen)), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] Failed to save {STATE_FILE}: {e}")


def is_quiet_time_kst():
    now = datetime.now(timezone(timedelta(hours=9))).hour
    return now >= QUIET_HOUR_START or now < QUIET_HOUR_END


def format_date(date_str):
    if not date_str:
        return ""

    formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%d %b %Y (%a)")
        except Exception:
            pass

    return date_str


def clean_text(text):
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def safe_get(url, headers=None, params=None, timeout=REQUEST_TIMEOUT):
    try:
        r = requests.get(url, headers=headers, params=params, timeout=timeout)
        return r
    except requests.RequestException as e:
        print(f"[WARN] GET request failed: {url} | {e}")
        return None


def safe_post(url, json_payload=None, timeout=REQUEST_TIMEOUT):
    try:
        r = requests.post(url, json=json_payload, timeout=timeout)
        return r
    except requests.RequestException as e:
        print(f"[WARN] POST request failed: {url} | {e}")
        return None


def get_user_ids():
    if not USE_X:
        return {}

    usernames = ",".join([u["username"] for u in TRACKED_USERS])
    url = "https://api.x.com/2/users/by"

    params = {
        "usernames": usernames,
        "user.fields": "username,name",
    }

    r = safe_get(url, headers=x_headers(), params=params)
    if r is None:
        return {}

    if r.status_code != 200:
        print(f"[WARN] get_user_ids failed: {r.status_code} | {r.text}")
        return {}

    try:
        data = r.json()
    except Exception as e:
        print(f"[WARN] get_user_ids json parse failed: {e}")
        return {}

    result = {}
    for u in data.get("data", []):
        username = (u.get("username") or "").lower().strip()
        user_id = (u.get("id") or "").strip()
        if username and user_id:
            result[username] = user_id

    return result


def fetch_posts(user_id):
    if not USE_X:
        return []

    url = f"https://api.x.com/2/users/{user_id}/tweets"

    params = {
        "max_results": MAX_POSTS_PER_USER,
        "tweet.fields": "created_at",
        "exclude": "replies,retweets",
    }

    r = safe_get(url, headers=x_headers(), params=params)
    if r is None:
        return []

    if r.status_code != 200:
        print(f"[WARN] fetch_posts failed for user_id={user_id}: {r.status_code} | {r.text}")
        return []

    try:
        data = r.json()
    except Exception as e:
        print(f"[WARN] fetch_posts json parse failed for user_id={user_id}: {e}")
        return []

    posts = data.get("data", [])
    if not isinstance(posts, list):
        return []

    return posts


def build_link(username, tweet_id):
    return f"https://x.com/{username}/status/{tweet_id}"


def score(text, name):
    s = 0
    lower = text.lower()

    keywords = [
        "ai", "chip", "tesla", "spacex",
        "apple", "google", "microsoft",
        "china", "us", "russia", "india",
        "policy", "market", "energy"
    ]

    for k in keywords:
        if k in lower:
            s += 1

    if name == "Elon Musk":
        s += 2

    return s


def fetch_all():
    if not USE_X:
        print("[INFO] X_BEARER_TOKEN not set -> skipping X fetch")
        return []

    items = []
    user_ids = get_user_ids()

    if not user_ids:
        print("[INFO] No user IDs fetched from X API")
        return []

    for u in TRACKED_USERS:
        username = u["username"].lower().strip()
        name = u["name"]

        user_id = user_ids.get(username)
        if not user_id:
            print(f"[WARN] user id not found for @{username}")
            continue

        posts = fetch_posts(user_id)

        for p in posts:
            text = clean_text(p.get("text", ""))
            tweet_id = str(p.get("id", "")).strip()
            created_at = p.get("created_at", "")

            if not text or not tweet_id:
                continue

            items.append({
                "uid": f"{username}|{tweet_id}",
                "name": name,
                "username": username,
                "text": text,
                "date": format_date(created_at),
                "link": build_link(username, tweet_id),
                "score": score(text, name),
            })

        time.sleep(1)

    return items


def dedup_sort(items, seen):
    result = []
    local = set()
    count = {}

    for i in items:
        uid = i["uid"]
        name = i["name"]

        if uid in seen or uid in local:
            continue

        if count.get(name, 0) >= MAX_ITEMS_PER_USER_AFTER_DEDUP:
            continue

        local.add(uid)
        count[name] = count.get(name, 0) + 1
        result.append(i)

    result.sort(key=lambda x: x["score"], reverse=True)
    return result[:MAX_ITEMS_PER_RUN]


def format_item(i):
    body = html.escape(i["text"])
    return "\n".join([
        i["name"],
        i["date"],
        f'<a href="{i["link"]}">{body}</a>',
        f"@{i['username']}"
    ]).strip()


def chunk(items):
    chunks = []
    current = []
    length = 0

    for i in items:
        t = format_item(i)
        add_len = len(t) + (2 if current else 0)

        if current and length + add_len > MAX_TELEGRAM_MESSAGE_LENGTH:
            chunks.append(current)
            current = [t]
            length = len(t)
        else:
            current.append(t)
            length += add_len

    if current:
        chunks.append(current)

    result = []
    total = len(chunks)

    if total == 1:
        result.append("📰 Social Watch\n\n" + "\n\n".join(chunks[0]))
    else:
        for idx, c in enumerate(chunks, 1):
            result.append(f"📰 Social Watch {idx}/{total}\n\n" + "\n\n".join(c))

    return result


def send(msg):
    if not USE_TELEGRAM:
        print("[WARN] BOT_TOKEN_EN_2 or CHAT_ID_EN_2 not set -> skipping Telegram send")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    for attempt in range(1, MAX_RETRY + 1):
        r = safe_post(url, json_payload=payload)

        if r is not None and r.status_code == 200:
            time.sleep(SEND_INTERVAL_SECONDS)
            return True

        status = r.status_code if r is not None else "NO_RESPONSE"
        body = r.text if r is not None else ""
        print(f"[WARN] Telegram send failed ({attempt}/{MAX_RETRY}): {status} | {body}")
        time.sleep(3)

    return False


def main():
    if is_quiet_time_kst():
        print("[INFO] Quiet time in KST -> exiting")
        return

    seen = load_seen()

    items = fetch_all()
    items = dedup_sort(items, seen)

    if not items:
        print("[INFO] No new items")
        return

    msgs = chunk(items)

    all_sent = True
    for m in msgs:
        if not send(m):
            all_sent = False
            break

    if not all_sent:
        print("[WARN] Some messages failed to send -> not updating seen")
        return

    for i in items:
        seen.add(i["uid"])

    save_seen(seen)
    print(f"[INFO] Done. Sent {len(items)} items.")


if __name__ == "__main__":
    main()
