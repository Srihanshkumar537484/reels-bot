"""
Instagram Reels auto poster.

Har run me queue/ ke sabse naye REELS_PER_RUN folders (jaise 001, 002) uthata hai
aur WINDOW_START-WINDOW_END (IST) ke beech sabhi accounts par same caption ke sath
post karta hai. Reel 1 pehle sab accounts par, phir reel 2 sab accounts par.
Nayi reels (003, 004...) daalte hi wo apne aap purani ki jagah le leti hain.
"""
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests

API = "https://graph.facebook.com/v21.0"
IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).parent
QUEUE = ROOT / "queue"
VIDEO_EXT = (".mp4", ".mov")

REELS_PER_RUN = int(os.getenv("REELS_PER_RUN", "2"))
WINDOW_START = os.getenv("WINDOW_START", "").strip()  # IST, jaise "09:00"
WINDOW_END = os.getenv("WINDOW_END", "").strip()      # IST, jaise "10:00"


def now():
    return datetime.now(IST)


def sleep_until(target):
    secs = (target - now()).total_seconds()
    if secs > 0:
        time.sleep(secs)


def api(method, path, token, **kwargs):
    r = requests.request(
        method,
        f"{API}/{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
        **kwargs,
    )
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    if r.status_code >= 400 or "error" in data:
        raise RuntimeError(json.dumps(data.get("error", data)))
    return data


def post_reel(account, video_url, caption):
    ig_id, token = account["ig_user_id"], account["access_token"]

    container = api(
        "POST", f"{ig_id}/media", token,
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true",
        },
    )["id"]

    # Instagram video process karta hai, status poll karo
    for _ in range(40):  # max ~10 min
        time.sleep(15)
        st = api("GET", container, token, params={"fields": "status_code,status"})
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Processing failed: {st}")
    else:
        raise RuntimeError("Processing timeout")

    return api("POST", f"{ig_id}/media_publish", token, data={"creation_id": container})["id"]


def find_video(folder: Path):
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() in VIDEO_EXT:
            return f
    return None


def load_accounts():
    """ACCOUNTS_JSON ho to wahi use hota hai, warna USER_TOKEN se pages + Instagram accounts khud nikalta hai."""
    raw = os.getenv("ACCOUNTS_JSON", "").strip()
    if raw:
        return json.loads(raw)

    user_token = os.environ["USER_TOKEN"].strip()
    data = api(
        "GET", "me/accounts", user_token,
        params={
            "fields": "name,access_token,instagram_business_account{id,username}",
            "limit": 100,
        },
    )
    only = [x.strip().lower() for x in os.getenv("ONLY_ACCOUNTS", "").split(",") if x.strip()]
    accounts = []
    for page in data.get("data", []):
        ig = page.get("instagram_business_account")
        if not ig:
            print(f"[SKIP] Page '{page['name']}' par Instagram linked nahi hai")
            continue
        label = ig.get("username") or page["name"]
        if only and label.lower() not in only and page["name"].strip().lower() not in only:
            continue
        accounts.append(
            {"name": label, "ig_user_id": ig["id"], "access_token": page["access_token"]}
        )
    return accounts


def latest_reels():
    """Sabse naye REELS_PER_RUN folders (video + caption.txt dono wale), purane-se-naya order me."""
    if not QUEUE.exists():
        return []
    ok = [
        p for p in sorted(QUEUE.iterdir())
        if p.is_dir() and find_video(p) and (p / "caption.txt").exists()
    ]
    return ok[-REELS_PER_RUN:]


def at_today(hhmm):
    h, m = hhmm.split(":")
    return now().replace(hour=int(h), minute=int(m), second=0, microsecond=0)


def try_post(acc, video_url, caption):
    try:
        return post_reel(acc, video_url, caption), None
    except Exception as e:
        print(f"       retry 1 baar ({e})")
        time.sleep(60)
        try:
            return post_reel(acc, video_url, caption), None
        except Exception as e2:
            return None, e2


def main():
    accounts = load_accounts()
    print(f"{len(accounts)} accounts mile:")
    for a in accounts:
        print(f"  - {a['name']} ({a['ig_user_id']})")
    if os.getenv("LIST_ONLY", "").lower() == "true":
        return
    if not accounts:
        sys.exit("Koi account nahi mila. Token/permissions check karo.")

    reels = latest_reels()
    if not reels:
        print("Queue me koi reel (video + caption.txt) nahi mili.")
        return
    print("Is run ki reels:", ", ".join(r.name for r in reels))

    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.getenv("GITHUB_REF_NAME", "main")

    # Task list: reel 1 sab accounts par, phir reel 2 sab accounts par
    tasks = [(r, a) for r in reels for a in accounts]

    scheduled = bool(WINDOW_START and WINDOW_END)
    if scheduled:
        start = at_today(WINDOW_START)
        end = at_today(WINDOW_END)
        if now() < start:
            print(f"Window {WINDOW_START} IST ka wait: {start:%H:%M} tak ruk rahe hain...")
            sleep_until(start)
        begin = now()
        end = max(end, begin + timedelta(minutes=15))  # cron late ho to bhi kam se kam 15 min
        usable = (end - begin).total_seconds() - 180   # last post ke processing ka buffer
        slot = max(20.0, usable / len(tasks))
        print(f"Posting {begin:%H:%M} se {end:%H:%M} IST ke beech, har post ~{slot/60:.1f} min ke gap par")
    else:
        begin, slot = now(), 0  # manual test: jaldi jaldi

    failures = 0
    for i, (folder, acc) in enumerate(tasks):
        if scheduled:
            sleep_until(begin + timedelta(seconds=i * slot + random.uniform(0, 0.5 * slot)))
        elif i:
            time.sleep(random.uniform(5, 20))

        video = find_video(folder)
        caption = (folder / "caption.txt").read_text(encoding="utf-8").strip()
        video_url = (
            f"https://raw.githubusercontent.com/{repo}/{branch}/queue/"
            f"{quote(folder.name)}/{quote(video.name)}"
        )
        media_id, err = try_post(acc, video_url, caption)
        t = now().strftime("%H:%M")
        if err:
            failures += 1
            print(f"[FAIL] {t} reel {folder.name} -> {acc['name']}: {err}")
        else:
            print(f"[OK]   {t} reel {folder.name} -> {acc['name']} ({media_id})")

    if failures:
        print(f"\n{failures} post fail hue.")
        sys.exit(1)


if __name__ == "__main__":
    main()
