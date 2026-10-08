"""
Har run par queue/ se agle REELS_PER_RUN reels uthata hai aur
ACCOUNTS_JSON ke sabhi accounts par same caption ke sath upload karta hai.
Progress state.json me save hota hai (jo account fail hua, agle run me retry hoga).
"""
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

API = "https://graph.facebook.com/v21.0"
ROOT = Path(__file__).parent
QUEUE = ROOT / "queue"
STATE_FILE = ROOT / "state.json"
REELS_PER_RUN = int(os.getenv("REELS_PER_RUN", "2"))
VIDEO_EXT = (".mp4", ".mov")


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


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


def main():
    accounts = load_accounts()
    print(f"{len(accounts)} accounts mile:")
    for a in accounts:
        print(f"  - {a['name']} ({a['ig_user_id']})")
    if os.getenv("LIST_ONLY", "").lower() == "true":
        return
    if not accounts:
        sys.exit("Koi account nahi mila. Token/permissions check karo.")
    names = [a["name"] for a in accounts]
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.getenv("GITHUB_REF_NAME", "main")

    state = load_state()
    folders = sorted(p for p in QUEUE.iterdir() if p.is_dir()) if QUEUE.exists() else []

    pending = []
    for folder in folders:
        done = state.get(folder.name, [])
        if all(n in done for n in names):
            continue
        if find_video(folder) and (folder / "caption.txt").exists():
            pending.append(folder)
        if len(pending) == REELS_PER_RUN:
            break

    if not pending:
        print("Queue khaali hai - koi nayi reel nahi mili.")
        return

    failures = 0
    for folder in pending:
        video = find_video(folder)
        caption = (folder / "caption.txt").read_text(encoding="utf-8").strip()
        video_url = (
            f"https://raw.githubusercontent.com/{repo}/{branch}/queue/"
            f"{quote(folder.name)}/{quote(video.name)}"
        )
        print(f"\n=== Reel {folder.name} ===\n{video_url}")

        done = state.setdefault(folder.name, [])
        for acc in accounts:
            if acc["name"] in done:
                continue
            try:
                media_id = post_reel(acc, video_url, caption)
                done.append(acc["name"])
                save_state(state)
                print(f"[OK]   {acc['name']} -> {media_id}")
            except Exception as e:
                failures += 1
                print(f"[FAIL] {acc['name']}: {e}")
            time.sleep(5)

    if failures:
        print(f"\n{failures} upload fail hue (agle run me retry honge).")
        sys.exit(1)


if __name__ == "__main__":
    main()
