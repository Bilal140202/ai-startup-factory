"""
Vera: Sends approval requests to Discord and polls for responses.
Uses Discord REST API only — no persistent bot needed.
Runs as a GitHub Actions job step.

Approval flow:
  - Vera posts an embed to a Discord channel with an approve button
  - Since Discord interactions need a hosted bot, Vera uses a simpler pattern:
    she posts the request, then polls a dedicated #approvals channel for
    a reply message containing just "approve" (from you).
  - Timeout: 24 hours. If no reply, pipeline pauses until next trigger.
"""

import os, json, time, requests, sys, datetime

DISCORD_TOKEN   = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_CHANNEL = os.environ["DISCORD_APPROVAL_CHANNEL_ID"]  # your approvals channel ID
DISCORD_USER_ID = os.environ["DISCORD_OWNER_USER_ID"]        # your Discord user ID (for DM ping)

BASE = "https://discord.com/api/v10"
HEADERS = {
    "Authorization": f"Bot {DISCORD_TOKEN}",
    "Content-Type":  "application/json"
}

def load(path):
    if not os.path.exists(path): return {}
    with open(path) as f: return json.load(f)

def save(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def set_state(state):
    with open("data/pipeline_state.json","w") as f:
        json.dump(state, f)

def send_message(content, embed=None):
    payload = {"content": content}
    if embed:
        payload["embeds"] = [embed]
    r = requests.post(f"{BASE}/channels/{DISCORD_CHANNEL}/messages",
                      json=payload, headers=HEADERS)
    r.raise_for_status()
    return r.json()["id"]

def get_recent_messages(after_id):
    r = requests.get(
        f"{BASE}/channels/{DISCORD_CHANNEL}/messages?after={after_id}&limit=20",
        headers=HEADERS
    )
    r.raise_for_status()
    return r.json()

def poll_for_approval(message_id, timeout_seconds=300):
    """
    Poll the channel for a reply containing 'approve' after message_id.
    In production this runs for up to timeout_seconds.
    GitHub Actions job has a 6hr limit; for 24hr approval windows
    re-trigger via a scheduled workflow that checks pending_approval.json.
    """
    deadline = time.time() + timeout_seconds
    print(f"  Polling for approval (timeout {timeout_seconds}s)...")
    while time.time() < deadline:
        time.sleep(15)
        msgs = get_recent_messages(message_id)
        for msg in msgs:
            # Only accept replies from the owner
            if str(msg["author"]["id"]) == str(DISCORD_USER_ID):
                if "approve" in msg["content"].lower():
                    print("  ✅ Approval received.")
                    return True
    return False

# ── Stage-specific senders ───────────────────────────────────

def request_liam_approval(idea):
    """Ask owner to approve a validated idea before Kyle builds it."""
    set_state("awaiting_liam_approval")
    save("data/pending_approval.json", {"stage": "liam", "idea": idea})

    embed = {
        "title": f"🔍 New Idea: {idea['product_name']}",
        "color": 0x5865F2,
        "fields": [
            {"name": "Problem",       "value": idea["idea"][:300],           "inline": False},
            {"name": "Elevator Pitch","value": idea.get("elevator_pitch",""),"inline": False},
            {"name": "Target User",   "value": idea.get("target_user",""),   "inline": True},
            {"name": "AI Score",      "value": str(idea.get("ai_score","?")),  "inline": True},
            {"name": "App Type",      "value": idea.get("product_type",""),  "inline": True},
            {"name": "Source",        "value": idea.get("url",""),           "inline": False},
        ],
        "footer": {"text": "Reply 'approve' to send to Kyle. No reply = skip."}
    }
    msg_id = send_message(f"<@{DISCORD_USER_ID}> **Liam found a new idea. Approve to build?**", embed)
    print(f"  Discord message sent (id={msg_id})")
    return msg_id, poll_for_approval(msg_id)

def request_kyle_approval(app):
    """Ask owner to approve the built app before Nick creates content."""
    set_state("awaiting_kyle_approval")
    save("data/pending_approval.json", {"stage": "kyle", "app": app})

    embed = {
        "title": f"🔨 Kyle built: {app['name']}",
        "color": 0x57F287,
        "fields": [
            {"name": "Idea",        "value": app["idea"][:300],         "inline": False},
            {"name": "GitHub",      "value": app.get("github_url",""),  "inline": False},
            {"name": "Live URL",    "value": app.get("netlify_url",""), "inline": False},
            {"name": "App Type",    "value": app.get("product_type",""),"inline": True},
        ],
        "footer": {"text": "Check the live URL. Reply 'approve' to send to Nick for marketing."}
    }
    msg_id = send_message(f"<@{DISCORD_USER_ID}> **Kyle finished a build. Approve for marketing?**", embed)
    return msg_id, poll_for_approval(msg_id)

def request_nick_approval(app_name, json_gh_url):
    """Ask owner to approve Nick's content (edit JSON on GitHub if needed, then approve)."""
    set_state("awaiting_nick_approval")
    save("data/pending_approval.json", {"stage": "nick", "app_name": app_name})

    embed = {
        "title": f"✍️ Nick's content ready: {app_name}",
        "color": 0xFEE75C,
        "fields": [
            {"name": "Content file (edit on GitHub if needed)",
             "value": json_gh_url, "inline": False},
        ],
        "footer": {"text": "Edit the file on GitHub if needed, then reply 'approve' to post everything."}
    }
    msg_id = send_message(f"<@{DISCORD_USER_ID}> **Nick's marketing content is ready. Review & approve?**", embed)
    return msg_id, poll_for_approval(msg_id)

def send_confirmation(text):
    send_message(f"✅ **Factory update:** {text}")

def send_error(text):
    send_message(f"❌ **Factory error:** {text}")

if __name__ == "__main__":
    # Quick test — sends a ping to Discord
    send_message("🏭 AI Startup Factory connected. Vera is online.")
    print("Vera: Discord ping sent.")

