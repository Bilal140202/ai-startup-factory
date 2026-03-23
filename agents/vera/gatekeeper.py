"""
Vera: sends approval requests to Discord and polls for owner replies.
"""

import json
import os
import time

import requests


DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_CHANNEL = os.environ["DISCORD_APPROVAL_CHANNEL_ID"]
DISCORD_USER_ID = os.environ["DISCORD_OWNER_USER_ID"]

BASE = "https://discord.com/api/v10"
HEADERS = {
    "Authorization": f"Bot {DISCORD_TOKEN}",
    "Content-Type": "application/json",
}


def load(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def set_state(state):
    with open("data/pipeline_state.json", "w", encoding="utf-8") as f:
        json.dump(state, f)


def clear_pending():
    save("data/pending_approval.json", {})


def send_message(content, embed=None):
    payload = {"content": content}
    if embed:
        payload["embeds"] = [embed]

    response = requests.post(
        f"{BASE}/channels/{DISCORD_CHANNEL}/messages",
        json=payload,
        headers=HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["id"]


def get_recent_messages(after_id):
    response = requests.get(
        f"{BASE}/channels/{DISCORD_CHANNEL}/messages?after={after_id}&limit=20",
        headers=HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def is_valid_approval(message, request_message_id):
    if str(message.get("author", {}).get("id")) != str(DISCORD_USER_ID):
        return False

    content = (message.get("content") or "").strip().lower()
    if content != "approve":
        return False

    message_reference = message.get("message_reference") or {}
    referenced = str(message_reference.get("message_id") or "")
    if referenced and referenced != str(request_message_id):
        return False

    return True


def poll_for_approval(message_id, timeout_seconds=300):
    deadline = time.time() + timeout_seconds
    print(f"Polling for approval for message {message_id} with timeout {timeout_seconds}s")

    while time.time() < deadline:
        time.sleep(15)
        for message in get_recent_messages(message_id):
            if is_valid_approval(message, message_id):
                clear_pending()
                print("Approval received.")
                return True

    return False


def request_liam_approval(idea):
    set_state("awaiting_liam_approval")
    save("data/pending_approval.json", {"stage": "liam", "idea": idea})

    embed = {
        "title": f"New Idea: {idea['product_name']}",
        "color": 0x5865F2,
        "fields": [
            {"name": "Problem", "value": idea["idea"][:300], "inline": False},
            {"name": "Elevator Pitch", "value": idea.get("elevator_pitch", ""), "inline": False},
            {"name": "Target User", "value": idea.get("target_user", ""), "inline": True},
            {"name": "AI Score", "value": str(idea.get("ai_score", "?")), "inline": True},
            {"name": "App Type", "value": idea.get("product_type", ""), "inline": True},
            {"name": "Source", "value": idea.get("url", ""), "inline": False},
        ],
        "footer": {"text": "Reply with exactly 'approve' to continue."},
    }

    msg_id = send_message(f"<@{DISCORD_USER_ID}> Liam found a new idea. Approve to build?", embed)
    return msg_id, poll_for_approval(msg_id)


def request_kyle_approval(app):
    set_state("awaiting_kyle_approval")
    save("data/pending_approval.json", {"stage": "kyle", "app": app})

    embed = {
        "title": f"Kyle built: {app['name']}",
        "color": 0x57F287,
        "fields": [
            {"name": "Idea", "value": app["idea"][:300], "inline": False},
            {"name": "GitHub", "value": app.get("github_url", ""), "inline": False},
            {"name": "Live URL", "value": app.get("netlify_url", ""), "inline": False},
            {"name": "App Type", "value": app.get("product_type", ""), "inline": True},
        ],
        "footer": {"text": "Check the app, then reply with exactly 'approve'."},
    }

    msg_id = send_message(f"<@{DISCORD_USER_ID}> Kyle finished a build. Approve for marketing?", embed)
    return msg_id, poll_for_approval(msg_id)


def request_nick_approval(app_name, json_gh_url):
    set_state("awaiting_nick_approval")
    save("data/pending_approval.json", {"stage": "nick", "app_name": app_name})

    embed = {
        "title": f"Nick's content ready: {app_name}",
        "color": 0xFEE75C,
        "fields": [
            {"name": "Content file", "value": json_gh_url, "inline": False},
        ],
        "footer": {"text": "Review the file, then reply with exactly 'approve'."},
    }

    msg_id = send_message(f"<@{DISCORD_USER_ID}> Nick's marketing content is ready. Review and approve?", embed)
    return msg_id, poll_for_approval(msg_id)


def send_confirmation(text):
    send_message(f"Factory update: {text}")


def send_error(text):
    send_message(f"Factory error: {text}")


if __name__ == "__main__":
    send_message("AI Startup Factory connected. Vera is online.")
    print("Vera: Discord ping sent.")
