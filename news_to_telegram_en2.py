import requests
import json
import os
import re
import time
import html
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ["BOT_TOKEN_EN_2"].strip()
CHAT_ID = os.environ["CHAT_ID_EN_2"].strip()
X_BEARER_TOKEN = os.environ["X_BEARER_TOKEN"].strip()

STATE_FILE = "seen_x_posts.json"

QUIET_HOUR_START = 21
QUIET_HOUR_END = 6

MAX_ITEMS_PER_RUN = 10
MAX_POSTS_PER_USER = 5
MAX_TELEGRAM_MESSAGE_LENGTH = 3800

SEND_INTERVAL_SECONDS = 2
MAX_RETRY = 5
REQUEST_TIMEOUT = 30

TRACKED_USERS = [
    {"name": "Elon Musk", "username": "elonmusk"},
    {"name": "Tim Cook", "username": "tim_cook"},
    {"name": "Sam Altman", "username": "sama"},
    {"name": "Sundar Pichai", "username": "sundarpichai"},
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
                return set(json.load(f))
        except:
            pass
    return set()


def save_seen(seen):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f)


def is_quiet_time_kst():
    now = datetime.now(timezone(timedelta(hours=9))).hour
    return now >= QUIET_HOUR_START or now < QUIET_HOUR_END


def format_date(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%fZ")
        return dt.strftime("%d %b %Y (%a)")
    except:
        return date_str


def clean_text(text):
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_user_ids():
    usernames = ",".join([u["username"] for u in TRACKED_USERS])
    url = "https://api.x.com/2/users/by"

    params = {
        "usernames": usernames,
        "user.fields": "username,name",
    }

    r = requests.get(url, headers=x_headers(), params=params)
    data = r.json()

    result = {}
    for u in data.get("data", []):
        result[u["username"].lower()] = u["id"]

    return result


def fetch_posts(user_id):
    url = f"https://api.x.com/2/users/{user_id}/tweets"

    params = {
        "max_results": MAX_POSTS_PER_USER,
        "tweet.fields": "created_at",
        "exclude": "replies,retweets",
    }

    r = requests.get(url, headers=x_headers(), params=params)
    return r.json().get("data", [])


def build_link(username, tweet_id):
    return f"https://x.com/{username}/status/{tweet_id}"


def score(text, name):
    s = 0

    keywords = [
        "ai", "chip", "tesla", "spacex",
        "apple", "google", "microsoft",
        "china", "us", "russia", "india",
        "policy", "market", "energy"
    ]

    for k in keywords:
        if k in text.lower():
            s += 1

    if name == "Elon Musk":
        s += 2

    return s


def fetch_all():
    items = []
    user_ids = get_user_ids()

    for u in TRACKED_USERS:
        username = u["username"]
        name = u["name"]

        if username not in user_ids:
            continue

        posts = fetch_posts(user_ids[username])

        for p in posts:
            text = clean_text(p.get("text", ""))
            tweet_id = p.get("id")

            if not text:
                continue

            items.append({
                "uid": f"{username}|{tweet_id}",
                "name": name,
                "username": username,
                "text": text,
                "date": format_date(p.get("created_at", "")),
                "link": build_link(username, tweet_id),
                "score": score(text, name)
            })

        time.sleep(1)

    return items


def dedup_sort(items, seen):
    result = []
    local = set()
    count = {}

    for i in items:
        if i["uid"] in seen or i["uid"] in local:
            continue

        if count.get(i["name"], 0) >= 2:
            continue

        local.add(i["uid"])
        count[i["name"]] = count.get(i["name"], 0) + 1
        result.append(i)

    result.sort(key=lambda x: x["score"], reverse=True)
    return result[:MAX_ITEMS_PER_RUN]


def format_item(i):
    return "\n".join([
        i["name"],
        i["date"],
        f'<a href="{i["link"]}">{html.escape(i["text"])}</a>',
        f"@{i['username']}"
    ])


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
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
    }

    for _ in range(MAX_RETRY):
        r = requests.post(url, json=payload)

        if r.status_code == 200:
            time.sleep(SEND_INTERVAL_SECONDS)
            return True

        time.sleep(3)

    return False


def main():
    if is_quiet_time_kst():
        return

    seen = load_seen()

    items = fetch_all()
    items = dedup_sort(items, seen)

    if not items:
        return

    msgs = chunk(items)

    for m in msgs:
        if not send(m):
            return

    for i in items:
        seen.add(i["uid"])

    save_seen(seen)


if __name__ == "__main__":
    main()
