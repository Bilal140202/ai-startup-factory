"""
Nick: Creates marketing content for newly approved apps.
Writes blog + tweet thread + LinkedIn → saves JSON to repo.
Sends the JSON file path to Vera for your approval.
"""

import sys
sys.path.insert(0, "agents")

import json, os, re, datetime
from shared import ai

GH_USER = os.environ["GITHUB_USERNAME"]
REPO    = os.environ.get("FACTORY_REPO_NAME", "ai-startup-factory")

def load(path):
    if not os.path.exists(path): return []
    with open(path) as f: return json.load(f)

def save(path, data):
    with open(path,"w") as f: json.dump(data, f, indent=2)

def set_state(s): save("data/pipeline_state.json", s)

def already_marketed(name):
    return os.path.exists(f"marketing/{name}.json")

def generate_content(app):
    name    = app["name"]
    idea    = app["idea"]
    pitch   = app.get("elevator_pitch", idea)
    user    = app.get("target_user","professionals")
    url     = app.get("netlify_url","#")
    gh_url  = app.get("github_url","#")

    # Blog post
    blog = ai(f"""
Write a compelling 400-word blog post for this tool:
Tool: {name} | Problem: {idea} | Pitch: {pitch} | User: {user} | URL: {url}
Structure: hook headline, pain (2 paragraphs), solution, 3 benefit bullets, CTA.
Tone: conversational, no fluff. Use markdown.
""", model_hint="smart", max_tokens=1200)

    # Tweet thread
    tweet_raw = ai(f"""
Write a 3-tweet launch thread:
Tool: {name} | Problem: {idea} | URL: {url}
Reply JSON only: {{"tweet1":"...","tweet2":"...","tweet3":"..."}}
Each tweet max 240 chars.
""", model_hint="fast")
    try:
        tweet_raw = re.sub(r"```[a-z]*\n?","",tweet_raw).replace("```","").strip()
        tweets = json.loads(tweet_raw)
    except:
        tweets = {"tweet1": f"🚀 {name}: {pitch}", "tweet2": idea[:200], "tweet3": f"Free: {url}"}

    # LinkedIn
    linkedin = ai(f"""
Write a 200-250 word LinkedIn post launching {name}.
Problem: {idea} | URL: {url}
Warm professional tone. Personal hook. Max 3 hashtags at end.
""", model_hint="fast", max_tokens=500)

    return {
        "app_name":     name,
        "netlify_url":  url,
        "github_url":   gh_url,
        "reddit_url":   app.get("reddit_url",""),
        "idea":         idea,
        "blog_post":    blog,
        "tweet_thread": f"{tweets['tweet1']}\n\n{tweets['tweet2']}\n\n{tweets['tweet3']}",
        "linkedin":     linkedin,
        "status":       "pending",
        "created":      str(datetime.datetime.utcnow())
    }

def main():
    from vera.gatekeeper import request_nick_approval, send_confirmation, send_error

    os.makedirs("marketing", exist_ok=True)
    apps = load("data/app_database.json")

    for app in apps:
        if app.get("status") != "approved": continue
        name = app["name"]
        if already_marketed(name): continue

        print(f"✍️  Nick: Creating content for {name}...")
        set_state("creating_content")

        try:
            content = generate_content(app)

            # Save to repo so you can edit via GitHub UI
            content_path = f"marketing/{name}.json"
            save(content_path, content)
            print(f"  Content saved to {content_path}")

            # GitHub raw URL for the file
            gh_file_url = f"https://github.com/{GH_USER}/{REPO}/blob/main/{content_path}"

            # Ask for your approval
            _, approved = request_nick_approval(name, gh_file_url)

            if approved:
                # Re-load in case you edited the file
                fresh = load(content_path)
                fresh["status"] = "approved"
                save(content_path, fresh)

                # Add to Liam's posting queue
                queue = load("data/marketing_queue.json")
                queue.append({
                    "name":        name,
                    "tweet":       fresh["tweet_thread"],
                    "linkedin":    fresh["linkedin"],
                    "reddit_url":  fresh.get("reddit_url",""),
                    "netlify_url": fresh.get("netlify_url",""),
                    "idea":        fresh.get("idea",""),
                    "status":      "approved",
                    "created":     str(datetime.datetime.utcnow())
                })
                save("data/marketing_queue.json", queue)

                # Mark app as fully done
                for a in apps:
                    if a["name"] == name: a["status"] = "marketed"
                save("data/app_database.json", apps)

                set_state("idle")
                send_confirmation(f"✅ Full cycle complete for '{name}'! Liam will post everything and start a new search.")
                print(f"  ✅ '{name}' queued for posting. New search cycle will begin.")
            else:
                print(f"  ⏰ Nick approval timed out for {name}.")
                set_state("idle")

        except Exception as e:
            print(f"  ❌ Nick failed for {name}: {e}")
            send_error(f"Nick content creation failed for '{name}': {e}")
            set_state("idle")

if __name__ == "__main__":
    main()

