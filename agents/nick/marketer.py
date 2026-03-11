"""
Nick: Creates marketing content and publishes it.
Generates blog + tweet thread + LinkedIn post.
Sends content file to Vera for approval.
If approved → publishes via Postiz.
"""

import sys
sys.path.insert(0, "agents")

import json, os, re, datetime, requests
from shared import ai


GH_USER = os.environ["GITHUB_USERNAME"]
REPO    = os.environ.get("FACTORY_REPO_NAME", "ai-startup-factory")

POSTIZ_KEY = os.environ.get("POSTIZ_API_KEY", "")
POSTIZ_URL = os.environ.get("POSTIZ_BASE_URL", "https://app.postiz.com/api")


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def load(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)

def save(path, data):
    with open(path,"w") as f:
        json.dump(data, f, indent=2)

def set_state(s):
    save("data/pipeline_state.json", s)

def already_marketed(name):
    return os.path.exists(f"marketing/{name}.json")


# ─────────────────────────────────────────
# Postiz publishing
# ─────────────────────────────────────────

def post_via_postiz(content, platform="twitter"):

    if not POSTIZ_KEY:
        print("Postiz key missing, skipping publish")
        return

    try:

        r = requests.post(
            f"{POSTIZ_URL}/posts",
            json={
                "content": content,
                "platform": platform,
                "schedule": "now"
            },
            headers={
                "Authorization": f"Bearer {POSTIZ_KEY}",
                "Content-Type": "application/json"
            },
            timeout=10
        )

        r.raise_for_status()

        print(f"✓ Posted to {platform}")

    except Exception as e:

        print(f"Postiz failed ({platform}): {e}")


# ─────────────────────────────────────────
# Content generation
# ─────────────────────────────────────────

def generate_content(app):

    name    = app["name"]
    idea    = app["idea"]
    pitch   = app.get("elevator_pitch", idea)
    user    = app.get("target_user","developers")
    url     = app.get("netlify_url","#")
    gh_url  = app.get("github_url","#")

    # Blog
    blog = ai(f"""
Write a compelling 400 word blog post launching this tool.

Tool: {name}
Problem: {idea}
Pitch: {pitch}
User: {user}
URL: {url}

Structure:
headline
pain
solution
3 benefits
call to action

Use markdown.
""", model_hint="smart", max_tokens=1200)


    # Tweet thread
    tweet_raw = ai(f"""
Write a 3 tweet launch thread.

Tool: {name}
Problem: {idea}
URL: {url}

Return JSON:
{{"tweet1":"...","tweet2":"...","tweet3":"..."}}

Max 240 chars each.
""", model_hint="fast")


    try:

        tweet_raw = re.sub(r"```[a-z]*\n?","",tweet_raw).replace("```","").strip()

        tweets = json.loads(tweet_raw)

    except:

        tweets = {
            "tweet1": f"🚀 {name}: {pitch}",
            "tweet2": idea[:200],
            "tweet3": f"Free tool: {url}"
        }


    # LinkedIn
    linkedin = ai(f"""
Write a 200 word LinkedIn launch post.

Tool: {name}
Problem: {idea}
URL: {url}

Tone: professional but conversational.
Max 3 hashtags at end.
""", model_hint="fast", max_tokens=500)


    return {

        "app_name": name,
        "netlify_url": url,
        "github_url": gh_url,
        "idea": idea,

        "blog_post": blog,

        "tweet_thread":
            f"{tweets['tweet1']}\n\n{tweets['tweet2']}\n\n{tweets['tweet3']}",

        "linkedin": linkedin,

        "status": "pending",

        "created": str(datetime.datetime.utcnow())

    }


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────

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


        print(f"✍️ Nick creating marketing for {name}")

        set_state("creating_content")

        try:

            content = generate_content(app)

            path = f"marketing/{name}.json"

            save(path, content)

            print(f"Content saved → {path}")


            gh_file_url = f"https://github.com/{GH_USER}/{REPO}/blob/main/{path}"


            _, approved = request_nick_approval(name, gh_file_url)


            if approved:

                fresh = load(path)

                fresh["status"] = "approved"

                save(path, fresh)


                print("Publishing marketing...")


                post_via_postiz(fresh["tweet_thread"], "twitter")

                if fresh.get("linkedin"):
                    post_via_postiz(fresh["linkedin"], "linkedin")


                for a in apps:
                    if a["name"] == name:
                        a["status"] = "marketed"

                save("data/app_database.json", apps)


                set_state("idle")

                send_confirmation(
                    f"✅ Marketing published for '{name}'. Liam will start the next research cycle."
                )


                print(f"✓ {name} marketing complete")


            else:

                print(f"Approval timed out for {name}")

                set_state("idle")


        except Exception as e:

            print(f"Nick failed for {name}: {e}")

            send_error(f"Nick marketing failed for '{name}': {e}")

            set_state("idle")


if __name__ == "__main__":
    main()
