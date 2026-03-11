"""
Liam: Market research + idea discovery + validation.
Scrapes Reddit, HackerNews, and GitHub Issues.
No Reddit API. No posting.
"""

import sys
sys.path.insert(0, "agents")

import requests, json, os, time, datetime, re
from bs4 import BeautifulSoup
from shared import ai


GH_TOKEN = os.environ["GITHUB_TOKEN"]
GH_USER  = os.environ["GITHUB_USERNAME"]

HEADERS = {"User-Agent": "ai-startup-factory-liam/5.0"}

SUBREDDITS = [
    "SideProject","Entrepreneur","startups","webdev",
    "SaaS","productivity","automation","nocode",
    "MachineLearning","artificial","ChatGPT"
]

KEYWORDS = [
    "tool","automate","looking for","need a",
    "is there a way","app that","wish there was",
    "anyone built","why isn't there","can someone make",
    "would pay for","anyone know a","feature request"
]


# ─────────────────────────────────────────
# File helpers
# ─────────────────────────────────────────

def load(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)

def load_one(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)

def save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def set_state(s):
    save("data/pipeline_state.json", s)

def get_state():
    return load_one("data/pipeline_state.json", "idle")


# ─────────────────────────────────────────
# Repo detection
# ─────────────────────────────────────────

def fetch_my_repos():

    repos, page = [], 1

    while True:

        r = requests.get(
            f"https://api.github.com/users/{GH_USER}/repos?per_page=100&page={page}",
            headers={"Authorization": f"token {GH_TOKEN}"}
        )

        data = r.json()

        if not data:
            break

        repos.extend(data)

        if len(data) < 100:
            break

        page += 1

    return repos


def find_existing_tool(problem_text, repos):

    repo_list = "\n".join(
        [f"- {r['name']}: {r.get('description','')}" for r in repos[:80]]
    )

    prompt = f"""
I have these GitHub repos:

{repo_list}

Problem:

{problem_text[:400]}

Does any repo already solve this?

Return JSON:
{{"match": true/false, "repo_name": "<name>", "repo_url": "<url>"}}
"""

    try:

        raw = ai(prompt, model_hint="fast")

        raw = re.sub(r"```[a-z]*\n?","",raw).replace("```","").strip()

        data = json.loads(raw)

        if data.get("match"):
            return data.get("repo_url"), data.get("repo_name")

    except:
        pass

    return None, None


# ─────────────────────────────────────────
# Reddit scraping
# ─────────────────────────────────────────

def scrape_reddit():

    ideas = []

    for sub in SUBREDDITS:

        print("Scanning r/" + sub)

        try:

            url = f"https://www.reddit.com/r/{sub}/top.json?t=week&limit=50"

            r = requests.get(url, headers=HEADERS)

            posts = r.json()["data"]["children"]

            for p in posts:

                d = p["data"]

                text = d["title"] + " " + (d.get("selftext") or "")

                if not detect_problem(text):
                    continue

                ideas.append({
                    "title": d["title"],
                    "text": (d.get("selftext") or "")[:500],
                    "url": "https://reddit.com" + d["permalink"],
                    "score": d["ups"] + d["num_comments"],
                    "sub": sub,
                    "source": "reddit"
                })

            time.sleep(1)

        except Exception as e:

            print("reddit scrape error:", e)

    return ideas


# ─────────────────────────────────────────
# HackerNews scraping
# ─────────────────────────────────────────

def scrape_hackernews():

    ideas = []

    try:

        html = requests.get(
            "https://news.ycombinator.com/ask",
            headers=HEADERS
        ).text

        soup = BeautifulSoup(html, "html.parser")

        rows = soup.select(".athing")

        for row in rows:

            title_el = row.select_one(".titleline a")

            if not title_el:
                continue

            title = title_el.text

            if not detect_problem(title):
                continue

            ideas.append({
                "title": title,
                "text": "",
                "url": title_el["href"],
                "score": 0,
                "sub": "ask-hn",
                "source": "hackernews"
            })

    except Exception as e:

        print("hn scrape error:", e)

    return ideas


# ─────────────────────────────────────────
# GitHub Issues scraping
# ─────────────────────────────────────────

def scrape_github_issues():

    ideas = []

    queries = [
        "looking for tool",
        "feature request",
        "is there a way",
        "any tool that",
        "wish there was"
    ]

    for q in queries:

        try:

            url = f"https://github.com/search?q={q.replace(' ','+')}&type=issues"

            html = requests.get(url, headers=HEADERS).text

            soup = BeautifulSoup(html, "html.parser")

            issues = soup.select(".issue-list-item")

            for issue in issues[:10]:

                title_el = issue.select_one("a")

                if not title_el:
                    continue

                title = title_el.text.strip()

                if not detect_problem(title):
                    continue

                ideas.append({
                    "title": title,
                    "text": "",
                    "url": "https://github.com" + title_el["href"],
                    "score": 0,
                    "sub": "github-issues",
                    "source": "github"
                })

        except Exception as e:

            print("github issue scrape error:", e)

    return ideas


# ─────────────────────────────────────────
# Detection
# ─────────────────────────────────────────

def detect_problem(text):

    text = text.lower()

    return any(k in text for k in KEYWORDS)


def already_in_pipeline(title):

    for p in load("data/problems.json"):
        if title.lower() in p["title"].lower():
            return True

    for p in load("data/app_database.json"):
        if title.lower() in p.get("idea","").lower():
            return True

    for p in load("data/research_cache.json"):
        if title.lower() in p.get("title","").lower():
            return True

    return False


# ─────────────────────────────────────────
# GitHub saturation
# ─────────────────────────────────────────

def github_saturated(query):

    try:

        r = requests.get(
            f"https://api.github.com/search/repositories?q={query}",
            headers={"Authorization": f"token {GH_TOKEN}"}
        )

        return r.json().get("total_count", 0) > 30

    except:

        return False


# ─────────────────────────────────────────
# GitHub reference repos
# ─────────────────────────────────────────

def find_github_codebase(problem_text):

    prompt = f"""
Generate two GitHub search queries for open-source tools solving this problem:

{problem_text[:300]}

Return JSON:
{{"queries":["query1","query2"]}}
"""

    try:

        raw = ai(prompt, model_hint="fast")

        raw = re.sub(r"```[a-z]*\n?","",raw).replace("```","").strip()

        queries = json.loads(raw).get("queries", [])

    except:

        queries = [problem_text[:40]]

    refs = []

    for q in queries[:2]:

        try:

            r = requests.get(
                f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=3",
                headers={"Authorization": f"token {GH_TOKEN}"}
            )

            for repo in r.json().get("items", []):

                refs.append({
                    "repo_url": repo["html_url"],
                    "description": repo.get("description",""),
                    "stars": repo["stargazers_count"]
                })

        except:
            pass

    return refs[:5]


# ─────────────────────────────────────────
# AI idea validation
# ─────────────────────────────────────────

def validate_idea(title, text):

    prompt = f"""
Evaluate this as a micro SaaS idea.

Title: {title}
Context: {text[:500]}

Return JSON only:

{{
"score":1-10,
"validated":true/false,
"product_type":"html-tool|python-webapp|react-app",
"product_name":"slug-name",
"elevator_pitch":"one sentence",
"target_user":"who"
}}
"""

    try:

        raw = ai(prompt, model_hint="fast")

        raw = re.sub(r"```[a-z]*\n?","",raw).replace("```","").strip()

        return json.loads(raw)

    except:

        return None


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────

def run():

    from vera.gatekeeper import request_liam_approval, send_confirmation

    state = get_state()

    print("Liam starting, state:", state)

    if state != "idle":

        print("Pipeline busy")

        return


    print("Fetching repos")

    my_repos = fetch_my_repos()


    reddit = scrape_reddit()

    hn = scrape_hackernews()

    github = scrape_github_issues()


    raw_ideas = reddit + hn + github


    raw_ideas = sorted(raw_ideas, key=lambda x: x["score"], reverse=True)[:20]


    best = None


    for idea in raw_ideas:

        if already_in_pipeline(idea["title"]):
            continue

        existing_url, existing_name = find_existing_tool(
            idea["title"], my_repos
        )

        if existing_url:
            continue

        if github_saturated(idea["title"]):
            continue


        result = validate_idea(idea["title"], idea["text"])


        if result and result.get("validated"):

            refs = find_github_codebase(idea["title"])


            best = {

                "title": idea["title"],
                "idea": idea["title"],
                "url": idea["url"],
                "score": idea["score"],
                "sub": idea["sub"],
                "ai_score": result["score"],
                "product_type": result["product_type"],
                "product_name": result["product_name"],
                "elevator_pitch": result["elevator_pitch"],
                "target_user": result["target_user"],
                "github_refs": refs,
                "status": "pending",
                "created": str(datetime.datetime.utcnow())

            }

            break


    if not best:

        print("No good ideas")

        send_confirmation("Liam ran but found no strong ideas.")

        return


    print("Best idea:", best["product_name"])


    msg_id, approved = request_liam_approval(best)


    if approved:

        problems = load("data/problems.json")

        problems.append(best)

        save("data/problems.json", problems)


        cache = load("data/research_cache.json")

        cache.append({

            "title": best["title"],
            "cached_at": str(datetime.datetime.utcnow())

        })

        save("data/research_cache.json", cache[-200:])


        set_state("idle")

        print("Idea saved, Kyle will trigger")


    else:

        print("Idea rejected")

        set_state("idle")


if __name__ == "__main__":

    run()
