"""
Nick: creates marketing content and publishes it.
"""

import sys
sys.path.insert(0, "agents")

import datetime
import json
import os
import re

import requests

from shared import ai, extract_json


GH_USER = os.environ["GITHUB_USERNAME"]
REPO = os.environ.get("FACTORY_REPO_NAME", "ai-startup-factory")

POSTIZ_KEY = os.environ.get("POSTIZ_API_KEY", "")
POSTIZ_URL = os.environ.get("POSTIZ_BASE_URL", "https://app.postiz.com/api").rstrip("/")


def load(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def set_state(state):
    save("data/pipeline_state.json", state)


def already_marketed(name):
    return os.path.exists(os.path.join("marketing", f"{name}.json"))


def clean_text(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def validate_content(content):
    if len(clean_text(content.get("blog_post", ""))) < 200:
        raise ValueError("Blog post is too short.")
    if len(clean_text(content.get("tweet_thread", ""))) < 40:
        raise ValueError("Tweet thread is too short.")
    if len(clean_text(content.get("linkedin", ""))) < 80:
        raise ValueError("LinkedIn post is too short.")
    if not clean_text(content.get("netlify_url", "")):
        raise ValueError("Marketing content is missing the product URL.")


def post_via_postiz(content, platform="twitter"):
    if not POSTIZ_KEY:
        print("Postiz key missing, skipping publish")
        return False

    response = requests.post(
        f"{POSTIZ_URL}/posts",
        json={"content": content, "platform": platform, "schedule": "now"},
        headers={
            "Authorization": f"Bearer {POSTIZ_KEY}",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    response.raise_for_status()
    print(f"Posted to {platform}")
    return True


def generate_content(app):
    name = app["name"]
    idea = app["idea"]
    pitch = app.get("elevator_pitch", idea)
    user = app.get("target_user", "developers")
    url = app.get("netlify_url", "#")
    gh_url = app.get("github_url", "#")

    blog = ai(
        f"""
Write a compelling 450 word launch blog post.

Tool: {name}
Problem: {idea}
Pitch: {pitch}
User: {user}
URL: {url}

Structure:
- headline
- pain
- solution
- benefits
- who should use it
- call to action

Use markdown.
""",
        model_hint="smart",
        max_tokens=1400,
    )

    tweet_data = {
        "tweet1": f"{name}: {pitch}",
        "tweet2": idea[:220],
        "tweet3": f"Try it here: {url}",
    }
    try:
        tweet_data = extract_json(
            ai(
                f"""
Write a 3 tweet launch thread.

Tool: {name}
Problem: {idea}
Pitch: {pitch}
URL: {url}

Return JSON:
{{"tweet1":"...","tweet2":"...","tweet3":"..."}}

Max 240 chars each.
""",
                model_hint="fast",
                max_tokens=500,
            )
        )
    except Exception:
        pass

    linkedin = ai(
        f"""
Write a 220 word LinkedIn launch post.

Tool: {name}
Problem: {idea}
Pitch: {pitch}
Target user: {user}
URL: {url}

Tone: professional but conversational.
Max 3 hashtags at end.
""",
        model_hint="fast",
        max_tokens=700,
    )

    content = {
        "app_name": name,
        "netlify_url": url,
        "github_url": gh_url,
        "idea": idea,
        "blog_post": blog,
        "tweet_thread": f"{tweet_data['tweet1']}\n\n{tweet_data['tweet2']}\n\n{tweet_data['tweet3']}",
        "linkedin": linkedin,
        "status": "pending",
        "created": str(datetime.datetime.utcnow()),
    }
    validate_content(content)
    return content


def main():
    from vera.gatekeeper import request_nick_approval, send_confirmation, send_error

    os.makedirs("marketing", exist_ok=True)
    apps = load("data/app_database.json")

    for app in apps:
        if app.get("status") != "approved":
            continue

        name = app["name"]
        if already_marketed(name):
            continue

        print(f"Creating marketing for {name}")
        set_state("creating_content")

        try:
            content = generate_content(app)
            path = os.path.join("marketing", f"{name}.json")
            save(path, content)

            gh_file_url = f"https://github.com/{GH_USER}/{REPO}/blob/main/{path.replace(os.sep, '/')}"
            _, approved = request_nick_approval(name, gh_file_url)

            if approved:
                fresh = load(path)
                fresh["status"] = "approved"
                save(path, fresh)

                post_via_postiz(fresh["tweet_thread"], "twitter")
                if fresh.get("linkedin"):
                    post_via_postiz(fresh["linkedin"], "linkedin")

                for item in apps:
                    if item["name"] == name:
                        item["status"] = "marketed"

                save("data/app_database.json", apps)
                set_state("idle")
                send_confirmation(f"Marketing published for '{name}'. Liam can continue.")
            else:
                set_state("idle")

        except Exception as exc:
            print(f"Nick failed for {name}: {exc}")
            send_error(f"Nick marketing failed for '{name}': {exc}")
            set_state("idle")


if __name__ == "__main__":
    main()
