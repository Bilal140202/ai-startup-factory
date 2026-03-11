"""
Liam: Market research + idea validation + Reddit replies + Postiz posting.
Triggered by pipeline_state.json == 'idle' (event-driven, not cron).
"""

import sys
sys.path.insert(0, "agents")

import requests, json, os, time, datetime, re
import praw
from shared import ai

GH_TOKEN   = os.environ["GITHUB_TOKEN"]
GH_USER    = os.environ["GITHUB_USERNAME"]
REDDIT_ID     = os.environ["REDDIT_CLIENT_ID"]
REDDIT_SECRET = os.environ["REDDIT_CLIENT_SECRET"]
REDDIT_USER   = os.environ["REDDIT_USERNAME"]
REDDIT_PASS   = os.environ["REDDIT_PASSWORD"]
REDDIT_UA     = os.environ.get("REDDIT_USER_AGENT", "ai-factory-liam/3.0")
POSTIZ_KEY    = os.environ.get("POSTIZ_API_KEY", "")
POSTIZ_URL    = os.environ.get("POSTIZ_BASE_URL", "https://app.postiz.com/api")

SUBREDDITS = [
    "SideProject","Entrepreneur","startups","webdev",
    "SaaS","productivity","automation","nocode",
    "MachineLearning","artificial","ChatGPT"
]
KEYWORDS = [
    "tool","automate","looking for","need a",
    "is there a way","app that","wish there was",
    "anyone built","why isn't there","can someone make",
    "would pay for","anyone know a"
]

# ── Helpers ──────────────────────────────────────────────────
def load(path):
    if not os.path.exists(path): return []
    with open(path) as f: return json.load(f)

def load_one(path, default=None):
    if not os.path.exists(path): return default
    with open(path) as f: return json.load(f)

def save(path, data):
    with open(path,"w") as f: json.dump(data, f, indent=2)

def set_state(s): save("data/pipeline_state.json", s)
def get_state():  return load_one("data/pipeline_state.json", "idle")

# ── Reddit client ─────────────────────────────────────────────
def reddit_client():
    return praw.Reddit(
        client_id=REDDIT_ID,
        client_secret=REDDIT_SECRET,
        username=REDDIT_USER,
        password=REDDIT_PASS,
        user_agent=REDDIT_UA
    )

# ── My existing repos check ───────────────────────────────────
def fetch_my_repos():
    """Fetch all public repos for GH_USER."""
    repos, page = [], 1
    while True:
        r = requests.get(
            f"https://api.github.com/users/{GH_USER}/repos?per_page=100&page={page}",
            headers={"Authorization": f"token {GH_TOKEN}"}
        )
        data = r.json()
        if not data: break
        repos.extend(data)
        if len(data) < 100: break
        page += 1
    return repos

def find_existing_tool(problem_text, repos):
    """
    Ask AI: does any of my repos already solve this problem?
    Returns (repo_url, repo_name) or (None, None).
    """
    repo_list = "\n".join([f"- {r['name']}: {r.get('description','')}" for r in repos[:80]])
    prompt = f"""
I have these GitHub repos:
{repo_list}

Problem from Reddit: {problem_text[:400]}

Does any of my repos already solve this exact problem?
Reply JSON only: {{"match": true/false, "repo_name": "<name or null>", "repo_url": "<url or null>"}}
"""
    try:
        raw = ai(prompt, model_hint="fast")
        raw = re.sub(r"```[a-z]*\n?","",raw).replace("```","").strip()
        data = json.loads(raw)
        if data.get("match"):
            return data.get("repo_url"), data.get("repo_name")
    except: pass
    return None, None

# ── Natural Reddit reply ──────────────────────────────────────
REPLY_TEMPLATES = [
    "I ran into the same problem recently while building something.\n\nEnded up making a small free tool for it:\n{url}\n\nMaybe it helps someone here.",
    "Had the exact same headache a while back.\n\nbuilt this out of frustation lol:\n{url}\n\nhope it helps",
    "Not sure if this is exactly what you need but I made something similar:\n{url}\n\nits free, might be worth a look",
    "saw this and thought of something i made last month\n{url}\n\nshould cover most of what ur describing",
    "this might be a bit overkill but i built this for the same reason:\n{url}\n\nlemme know if it dosent work for you",
]

import random

def craft_reply(url, problem_text):
    """Pick a natural-sounding template, add minor typos for authenticity."""
    template = random.choice(REPLY_TEMPLATES)
    reply = template.format(url=url)
    return reply

def post_reddit_reply(submission_url, reply_text):
    """Post a reply to a Reddit thread."""
    try:
        reddit = reddit_client()
        submission = reddit.submission(url=submission_url)
        submission.reply(reply_text)
        print(f"  ✓ Reddit reply posted to {submission_url}")
        time.sleep(2)
    except Exception as e:
        print(f"  ⚠️  Reddit reply failed: {e}")

# ── GitHub saturation check ───────────────────────────────────
def github_saturated(query):
    try:
        r = requests.get(
            f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc",
            headers={"Authorization": f"token {GH_TOKEN}"},
            timeout=8
        )
        return r.json().get("total_count", 0) > 30
    except: return False

# ── Mine GitHub for reusable code ────────────────────────────
def find_github_codebase(problem_text):
    """
    Search GitHub for existing open-source tools related to the problem.
    Returns list of {repo_url, description, stars} for Kyle to use as reference.
    """
    prompt = f"""
Extract 2-3 short GitHub search queries (max 4 words each) to find existing open-source tools for this problem:
{problem_text[:300]}
Reply JSON only: {{"queries": ["query1","query2","query3"]}}
"""
    try:
        raw = ai(prompt, model_hint="fast")
        raw = re.sub(r"```[a-z]*\n?","",raw).replace("```","").strip()
        queries = json.loads(raw).get("queries", [])
    except:
        queries = [problem_text[:40]]

    refs = []
    for q in queries[:3]:
        try:
            r = requests.get(
                f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=3",
                headers={"Authorization": f"token {GH_TOKEN}"},
                timeout=8
            )
            for repo in r.json().get("items", []):
                refs.append({
                    "repo_url":    repo["html_url"],
                    "description": repo.get("description",""),
                    "stars":       repo["stargazers_count"],
                    "default_branch": repo.get("default_branch","main"),
                    "full_name":   repo["full_name"]
                })
            time.sleep(0.5)
        except: pass

    # Deduplicate
    seen, out = set(), []
    for r in refs:
        if r["repo_url"] not in seen:
            seen.add(r["repo_url"])
            out.append(r)
    return out[:5]

# ── AI idea validation ────────────────────────────────────────
def validate_idea(title, text):
    prompt = f"""
Evaluate this Reddit post as a micro-SaaS / tool idea:

Title: {title}
Context: {text[:500]}

Reply JSON only (no markdown):
{{
  "score": <1-10>,
  "validated": <true if score>=7>,
  "product_type": <"html-tool"|"python-webapp"|"react-app">,
  "product_name": "<short-slug-lowercase-hyphens>",
  "elevator_pitch": "<one sentence>",
  "target_user": "<who>"
}}
"""
    try:
        raw = ai(prompt, model_hint="fast")
        raw = re.sub(r"```[a-z]*\n?","",raw).replace("```","").strip()
        return json.loads(raw)
    except: return None

def detect_problem(text):
    return any(k in text.lower() for k in KEYWORDS)

def already_in_pipeline(title):
    for p in load("data/problems.json"):
        if title.lower() in p["title"].lower(): return True
    for p in load("data/app_database.json"):
        if title.lower() in p.get("idea","").lower(): return True
    for p in load("data/research_cache.json"):
        if title.lower() in p.get("title","").lower(): return True
    return False

# ── Postiz social posting ─────────────────────────────────────
def post_via_postiz(content, platform="twitter"):
    if not POSTIZ_KEY:
        print("  Postiz key not set, skipping.")
        return
    try:
        r = requests.post(
            f"{POSTIZ_URL}/posts",
            json={"content": content, "platform": platform, "schedule": "now"},
            headers={"Authorization": f"Bearer {POSTIZ_KEY}", "Content-Type": "application/json"},
            timeout=10
        )
        r.raise_for_status()
        print(f"  ✓ Posted to {platform}")
    except Exception as e:
        print(f"  Postiz failed ({platform}): {e}")

def process_marketing_queue():
    """Post Nick's approved content + reply to original Reddit threads."""
    queue = load("data/marketing_queue.json")
    changed = False
    for item in queue:
        if item.get("status") != "approved":
            continue
        # Social posts
        post_via_postiz(item.get("tweet",""), "twitter")
        time.sleep(1)
        if item.get("linkedin"):
            post_via_postiz(item.get("linkedin",""), "linkedin")
            time.sleep(1)
        # Reddit reply
        reddit_url  = item.get("reddit_url")
        netlify_url = item.get("netlify_url","")
        if reddit_url and netlify_url:
            reply = craft_reply(netlify_url, item.get("idea",""))
            post_reddit_reply(reddit_url, reply)
        item["status"]    = "posted"
        item["posted_at"] = str(datetime.datetime.utcnow())
        changed = True
    if changed:
        save("data/marketing_queue.json", queue)

# ── Main ──────────────────────────────────────────────────────
def run():
    from vera.gatekeeper import request_liam_approval, send_confirmation, send_error

    state = get_state()
    print(f"🔍 Liam starting. Pipeline state: {state}")

    # If there's approved marketing to post, do that first
    process_marketing_queue()

    if state != "idle":
        print(f"  Pipeline busy ({state}), skipping new research.")
        return

    print("  Fetching my existing repos for tool matching...")
    my_repos = fetch_my_repos()

    # ── Scrape Reddit ─────────────────────────────────────────
    raw_ideas, existing_tool_replies = [], []

    reddit = reddit_client()
    for sub in SUBREDDITS:
        print(f"  Scanning r/{sub}...")
        try:
            subreddit = reddit.subreddit(sub)
            for post in subreddit.top(time_filter="week", limit=50):
                text = post.title + " " + (post.selftext or "")
                if not detect_problem(text): continue
                if already_in_pipeline(post.title): continue

                # Check if I already have a tool for this
                existing_url, existing_name = find_existing_tool(text, my_repos)
                if existing_url:
                    # Prefer the Netlify URL if this tool is already in our database
                    tool_live_url = existing_url  # default to GitHub URL
                    for built_app in load("data/app_database.json"):
                        if built_app.get("name","").lower() == (existing_name or "").lower():
                            tool_live_url = built_app.get("netlify_url", existing_url)
                            break
                    # Queue a Reddit reply pointing to the live tool
                    existing_tool_replies.append({
                        "reddit_url": f"https://www.reddit.com{post.permalink}",
                        "tool_url":   tool_live_url,
                        "idea":       post.title
                    })
                    print(f"    → Existing tool match: {existing_name} → {tool_live_url}")
                    continue

                if github_saturated(post.title): continue

                raw_ideas.append({
                    "title":  post.title,
                    "text":   (post.selftext or "")[:500],
                    "url":    f"https://www.reddit.com{post.permalink}",
                    "score":  post.score + post.num_comments,
                    "sub":    sub
                })
            time.sleep(2)   # stay well under Reddit's rate limit (60 req/min)
        except Exception as e:
            print(f"  r/{sub} failed: {e}")

    # Reply to threads where we already have a tool
    for rep in existing_tool_replies:
        reply = craft_reply(rep["tool_url"], rep["idea"])
        post_reddit_reply(rep["reddit_url"], reply)

    # ── Validate new ideas ────────────────────────────────────
    raw_ideas = sorted(raw_ideas, key=lambda x: x["score"], reverse=True)[:20]
    print(f"  Validating {len(raw_ideas)} candidate ideas...")

    best = None
    for idea in raw_ideas:
        result = validate_idea(idea["title"], idea["text"])
        if result and result.get("validated"):
            # Find GitHub reference repos for Kyle
            refs = find_github_codebase(idea["title"])
            entry = {
                "title":          idea["title"],
                "idea":           idea["title"],
                "url":            idea["url"],
                "score":          idea["score"],
                "sub":            idea["sub"],
                "ai_score":       result["score"],
                "product_type":   result["product_type"],
                "product_name":   result["product_name"],
                "elevator_pitch": result["elevator_pitch"],
                "target_user":    result["target_user"],
                "github_refs":    refs,
                "status":         "pending",
                "created":        str(datetime.datetime.utcnow())
            }
            best = entry
            break
        time.sleep(0.3)

    if not best:
        print("  No high-quality ideas found this cycle.")
        send_confirmation("Liam completed a research cycle — no validated ideas found. Will retry next trigger.")
        return

    # ── Send to Vera for your approval ────────────────────────
    print(f"  Best idea: {best['product_name']} (score {best['ai_score']}/10)")
    print("  Sending to Vera for Discord approval...")

    msg_id, approved = request_liam_approval(best)

    if approved:
        problems = load("data/problems.json")
        problems.append(best)
        save("data/problems.json", problems)

        cache = load("data/research_cache.json")
        cache.append({"title": best["title"], "cached_at": str(datetime.datetime.utcnow())})
        save("data/research_cache.json", cache[-200:])

        set_state("idle")  # Kyle's workflow triggers off problems.json change
        print(f"  ✅ Approved. Saved to problems.json. Kyle will trigger automatically.")
    else:
        print("  ⏰ No approval received in time window. Skipping this idea.")
        send_confirmation(f"Idea '{best['product_name']}' was not approved in time — skipped. Liam will find a new one next trigger.")
        set_state("idle")

if __name__ == "__main__":
    run()

