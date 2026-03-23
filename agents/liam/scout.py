"""
Liam — Market Research Agent

Sources scanned:
• Reddit posts
• Reddit comments (primary)
• HackerNews Ask HN
• GitHub Issues feature requests

Outputs:
• best validated idea → Vera approval
• problems.json update
"""

import sys
sys.path.insert(0, "agents")

import requests, json, os, time, datetime, re
from bs4 import BeautifulSoup
from shared import ai, extract_json


GH_TOKEN = os.environ["GITHUB_TOKEN"]
GH_USER  = os.environ["GITHUB_USERNAME"]

HEADERS = {
"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
"Accept-Language": "en-US,en;q=0.9"
}


SUBREDDITS = [
"SideProject","Entrepreneur","startups","webdev",
"SaaS","productivity","automation","nocode",
"MachineLearning","artificial","ChatGPT"
]


KEYWORDS = [
"tool","automate","looking for","need a",
"is there a way","app that","wish there was",
"anyone built","why isn't there","can someone make",
"would pay for","anyone know a","feature request",
"how do i","best way to","any tool","any website",
"any app","recommend tool","help with",
"convert","generate","extract","scrape"
]

PAIN_PATTERNS = [
"looking for","need a","need an","need help","is there a way",
"wish there was","would pay for","feature request","can someone make",
"how do i","best way to","any tool","any website","any app",
"recommend tool","help with","struggling to","takes forever",
"manual process","time consuming","frustrated","pain point",
"annoying to","tired of","keep doing this manually"
]

BUYER_PATTERNS = [
"would pay","paid","paying","team","client","customers",
"workflow","business","agency","sales","support","ops",
"operations","marketing","finance","recruiting","hr"
]

NEGATIVE_PATTERNS = [
"show hn","roast my","i built","i made","launching",
"just shipped","promo","promotion","subscribe","newsletter",
"hiring","job","meme","shitpost","joke","github repo",
"open source release","free credits","discount"
]

TOOL_CONTEXT = [
"workflow","process","dashboard","automation","data","report",
"lead","email","invoice","calendar","crm","document","pdf",
"spreadsheet","customer","content","scrape","extract","generate",
"convert","analyze","summarize","transcribe","integrate"
]

REDDIT_POST_CACHE = None


# ------------------------------------------------
# File helpers
# ------------------------------------------------

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

    with open(path,"w") as f:
        json.dump(data,f,indent=2)


def set_state(s):

    save("data/pipeline_state.json", s)


def get_state():

    return load_one("data/pipeline_state.json","idle")

def safe_get_json(url):

    response = requests.get(
    url,
    headers={**HEADERS, "Accept": "application/json"},
    timeout=20
    )

    response.raise_for_status()

    return response.json()


def safe_get_html(url):

    response = requests.get(
    url,
    headers={**HEADERS, "Accept": "text/html,application/xhtml+xml"},
    timeout=20
    )

    response.raise_for_status()

    if "<html" not in response.text.lower():
        raise ValueError(f"Expected HTML page from {url}")

    return response.text


def clean_text(text):

    text = re.sub(r"\s+"," ", (text or "").strip())
    text = re.sub(r"https?://\S+","", text)
    text = re.sub(r"/u/\w+","", text, flags=re.I)
    text = text.replace("&amp;","&")

    return text.strip(" -|:\n\t")


def sentence_split(text):

    chunks = re.split(r"(?<=[\.\?\!])\s+|\n+", clean_text(text))
    return [c.strip() for c in chunks if c and len(c.strip()) >= 20]


def canonicalize(text):

    text = clean_text(text).lower()
    text = re.sub(r"[^a-z0-9\s]"," ", text)
    text = re.sub(r"\b(a|an|the|to|for|with|and|or|of|in|on|my|our|your)\b"," ", text)
    text = re.sub(r"\s+"," ", text).strip()

    return text


# ------------------------------------------------
# Repo detection
# ------------------------------------------------

def fetch_my_repos():

    repos = []
    page = 1

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
{{"match":true/false,"repo_name":"name","repo_url":"url"}}
"""

    try:

        raw = ai(prompt, model_hint="fast")
        data = extract_json(raw)

        if data.get("match"):
            return data.get("repo_url"), data.get("repo_name")

    except:
        pass

    return None,None


def score_problem_signal(text, source=""):

    text = clean_text(text)
    low = text.lower()
    score = 0
    reasons = []

    if len(low) >= 35:
        score += 1
    else:
        score -= 2
        reasons.append("too_short")

    if any(k in low for k in KEYWORDS):
        score += 2
        reasons.append("keyword")

    if any(k in low for k in PAIN_PATTERNS):
        score += 4
        reasons.append("pain")

    if any(k in low for k in BUYER_PATTERNS):
        score += 2
        reasons.append("buyer")

    if any(k in low for k in TOOL_CONTEXT):
        score += 2
        reasons.append("tool_context")

    if "?" in text:
        score += 1

    if source == "reddit-comment":
        score += 1

    if re.search(r"\b(i|we)\s+(need|want|wish|keep|spend|waste|hate|struggle)\b", low):
        score += 2
        reasons.append("first_person_pain")

    if re.search(r"\b(build|buy|use|pay|replace|automate|track|extract|generate)\b", low):
        score += 1

    if any(k in low for k in NEGATIVE_PATTERNS):
        score -= 5
        reasons.append("noise")

    if len(low) > 600:
        score -= 1

    return score, reasons


def extract_problem_statement(title, text, source):

    candidates = []

    for item in [title, text]:
        for sentence in sentence_split(item):
            signal, _ = score_problem_signal(sentence, source)
            if signal >= 3:
                candidates.append((signal, sentence))

    if not candidates:
        merged = clean_text(f"{title}. {text}")
        return merged[:160], merged[:500]

    candidates.sort(key=lambda x: (-x[0], len(x[1])))
    best_sentence = candidates[0][1]
    context_parts = []

    for _, sentence in candidates[:3]:
        if sentence not in context_parts:
            context_parts.append(sentence)

    summary = clean_text(" ".join(context_parts))[:500]
    short_title = clean_text(best_sentence)[:160]

    return short_title, summary


def build_candidate(title, text, url, score, sub, source):

    title = clean_text(title)
    text = clean_text(text)
    extracted_title, extracted_text = extract_problem_statement(title, text, source)
    combined = clean_text(f"{title}. {text}")
    signal_score, reasons = score_problem_signal(combined, source)

    if signal_score < 4:
        return None

    return {
    "title": extracted_title,
    "text": extracted_text,
    "raw_title": title,
    "raw_text": text[:500],
    "url": url,
    "score": score,
    "signal_score": signal_score,
    "signal_reasons": reasons,
    "rank_score": (signal_score * 100) + max(score, 0),
    "sub": sub,
    "source": source
    }


def extract_numeric_score(text):

    match = re.search(r"(-?\d+)", clean_text(text))

    if match:
        return int(match.group(1))

    return 0


def parse_old_reddit_listing(html, sub):

    soup = BeautifulSoup(html,"html.parser")
    results = []

    for row in soup.select(".thing"):

        title_el = row.select_one("a.title")

        if not title_el:
            continue

        title = clean_text(title_el.get_text(" ", strip=True))
        score_text = row.select_one(".score.unvoted")
        comments_el = row.select_one("a.comments")
        comments_text = comments_el.get_text(" ", strip=True) if comments_el else ""
        comment_count = extract_numeric_score(comments_text)
        score = extract_numeric_score(score_text.get_text(" ", strip=True) if score_text else "")
        permalink = comments_el.get("href","") if comments_el else row.get("data-permalink","")

        if permalink.startswith("/"):
            permalink = "https://old.reddit.com" + permalink

        text_parts = [title]
        tag_text = " ".join(el.get_text(" ", strip=True) for el in row.select(".expando .md p"))

        if tag_text:
            text_parts.append(tag_text)

        results.append({
        "title": title,
        "text": clean_text(" ".join(text_parts)),
        "url": permalink,
        "score": score + comment_count,
        "sub": sub,
        "source": "reddit-post"
        })

    return results


def parse_old_reddit_comments(html, limit=12):

    soup = BeautifulSoup(html,"html.parser")
    comments = []

    for comment in soup.select(".comment"):

        body_el = comment.select_one(".usertext-body .md")

        if not body_el:
            continue

        text = clean_text(body_el.get_text(" ", strip=True))

        if len(text) < 30:
            continue

        comments.append(text)

        if len(comments) >= limit:
            break

    return comments


def fetch_reddit_comment_candidates(posts, max_posts=8, max_comments_per_post=8):

    ideas = []

    for post in sorted(posts, key=lambda x: x["score"], reverse=True)[:max_posts]:

        if not post.get("url"):
            continue

        try:

            html = safe_get_html(post["url"])

            for comment_text in parse_old_reddit_comments(html, limit=max_comments_per_post):

                candidate = build_candidate(
                comment_text[:160],
                comment_text,
                post["url"],
                max(post["score"] // 3, 1),
                post["sub"],
                "reddit-comment"
                )

                if candidate:
                    ideas.append(candidate)

            time.sleep(1)

        except Exception as e:

            print("reddit comment page error:", e)

    return ideas


def fetch_hn_algolia_hits(tags, query=""):

    url = (
    "https://hn.algolia.com/api/v1/search_by_date?"
    f"tags={tags}&query={requests.utils.quote(query)}&hitsPerPage=50"
    )

    try:

        return safe_get_json(url).get("hits", [])

    except Exception as e:

        print("hn algolia error:", e)
        return []


# ------------------------------------------------
# Reddit post scanning
# ------------------------------------------------

def scrape_reddit_posts():

    global REDDIT_POST_CACHE

    if REDDIT_POST_CACHE is not None:
        return list(REDDIT_POST_CACHE)

    ideas = []

    for sub in SUBREDDITS:

        try:

            url = f"https://old.reddit.com/r/{sub}/top/?sort=top&t=week"
            html = safe_get_html(url)
            posts = parse_old_reddit_listing(html, sub)

            for post in posts[:25]:

                candidate = build_candidate(
                post["title"],
                post["text"],
                post["url"],
                post["score"],
                post["sub"],
                post["source"]
                )

                if candidate:
                    ideas.append(candidate)

            time.sleep(1)

        except Exception as e:

            print("reddit post error:",e)

    REDDIT_POST_CACHE = list(ideas)

    return ideas


# ------------------------------------------------
# Reddit comment mining (primary discovery)
# ------------------------------------------------

def scrape_reddit_comments():

    posts = scrape_reddit_posts()
    return fetch_reddit_comment_candidates(posts)


# ------------------------------------------------
# HackerNews
# ------------------------------------------------

def scrape_hackernews():

    ideas = []

    try:

        html = requests.get(
        "https://news.ycombinator.com/ask",
        headers=HEADERS
        ).text

        soup = BeautifulSoup(html,"html.parser")

        rows = soup.select(".athing")

        for row in rows:

            title_el = row.select_one(".titleline a")

            if not title_el:
                continue

            title = title_el.text
            candidate = build_candidate(
            title,
            "",
            title_el["href"],
            0,
            "ask-hn",
            "hackernews"
            )

            if candidate:
                ideas.append(candidate)

    except Exception as e:

        print("hn error:",e)

    for hit in fetch_hn_algolia_hits("story,ask_hn"):

        title = clean_text(hit.get("title") or hit.get("story_title") or "")
        text = clean_text(BeautifulSoup(hit.get("story_text") or "", "html.parser").get_text(" ", strip=True))

        if not title:
            continue

        candidate = build_candidate(
        title,
        text,
        hit.get("url") or hit.get("story_url") or f"https://news.ycombinator.com/item?id={hit.get('objectID','')}",
        int(hit.get("points") or 0) + int(hit.get("num_comments") or 0),
        "ask-hn",
        "hackernews"
        )

        if candidate:
            ideas.append(candidate)

    for keyword in ["need tool", "manual process", "would pay", "feature request", "how do you automate"]:

        for hit in fetch_hn_algolia_hits("comment", keyword):

            comment_text = clean_text(BeautifulSoup(hit.get("comment_text") or "", "html.parser").get_text(" ", strip=True))

            if not comment_text:
                continue

            candidate = build_candidate(
            comment_text[:160],
            comment_text,
            hit.get("story_url") or f"https://news.ycombinator.com/item?id={hit.get('story_id','')}",
            int(hit.get("points") or 0),
            "hn-comments",
            "hackernews-comment"
            )

            if candidate:
                ideas.append(candidate)

    return ideas


# ------------------------------------------------
# GitHub Issues
# ------------------------------------------------

def scrape_github_issues():

    ideas = []

    queries = [
    "feature request",
    "looking for tool",
    "wish there was",
    "any tool that",
    "is there a way"
    ]

    for q in queries:

        try:

            url = f"https://github.com/search?q={q.replace(' ','+')}&type=issues"

            html = requests.get(url,headers=HEADERS).text

            soup = BeautifulSoup(html,"html.parser")

            issues = soup.select(".issue-list-item")

            for issue in issues[:10]:

                title_el = issue.select_one("a")

                if not title_el:
                    continue

                title = title_el.text.strip()
                candidate = build_candidate(
                title,
                "",
                "https://github.com"+title_el["href"],
                0,
                "github-issues",
                "github"
                )

                if candidate:
                    ideas.append(candidate)

        except Exception as e:

            print("github issue error:",e)

    return ideas


# ------------------------------------------------
# Detection
# ------------------------------------------------

def detect_problem(text):

    score, _ = score_problem_signal(text)
    return score >= 4


def already_in_pipeline(title):

    title_key = canonicalize(title)

    for p in load("data/problems.json"):

        if title_key and (title_key in canonicalize(p.get("title","")) or canonicalize(p.get("title","")) in title_key):
            return True

    for p in load("data/app_database.json"):

        idea_key = canonicalize(p.get("idea",""))
        if title_key and (title_key in idea_key or idea_key in title_key):
            return True

    for p in load("data/research_cache.json"):

        cache_key = canonicalize(p.get("title",""))
        if title_key and (title_key in cache_key or cache_key in title_key):
            return True

    return False


# ------------------------------------------------
# GitHub saturation
# ------------------------------------------------

def github_saturated(query):

    try:

        r = requests.get(
        f"https://api.github.com/search/repositories?q={query}",
        headers={"Authorization":f"token {GH_TOKEN}"}
        )

        return r.json().get("total_count",0) > 30

    except:

        return False


# ------------------------------------------------
# GitHub reference repos
# ------------------------------------------------

def find_github_codebase(problem_text):

    prompt = f"""
Generate two GitHub search queries for open-source tools solving this:

{problem_text[:300]}

Return JSON:
{{"queries":["query1","query2"]}}
"""

    try:

        raw = ai(prompt,model_hint="fast")
        queries = extract_json(raw).get("queries",[])

    except:

        queries = [problem_text[:40]]

    refs = []

    for q in queries[:2]:

        try:

            r = requests.get(
            f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=3",
            headers={"Authorization":f"token {GH_TOKEN}"}
            )

            for repo in r.json().get("items",[]):

                refs.append({

                "repo_url":repo["html_url"],
                "full_name":repo["full_name"],
                "default_branch":repo.get("default_branch","main"),
                "description":repo.get("description",""),
                "stars":repo["stargazers_count"]

                })

        except:
            pass

    return refs[:5]


# ------------------------------------------------
# AI validation
# ------------------------------------------------

def validate_idea(title,text):

    prompt = f"""
You are validating startup opportunities from scraped internet discussions.
Reject vague chatter, memes, personal one-off problems, and requests that do not imply a reusable product.

Evaluate this candidate.

Title: {title}
Context: {text[:500]}

Return JSON:

{{
"score":1-10,
"validated":true/false,
"problem_summary":"one sentence",
"product_type":"html-tool|python-webapp|react-app",
"product_name":"slug",
"elevator_pitch":"one sentence",
"target_user":"who",
"why_now":"short reason"
}}
"""

    try:

        raw = ai(prompt,model_hint="fast")
        return extract_json(raw)

    except:

        return None


# ------------------------------------------------
# MAIN
# ------------------------------------------------

def run():

    from vera.gatekeeper import request_liam_approval, send_confirmation

    state = get_state()

    print("Liam starting:",state)

    if state != "idle":
        return


    print("Fetching repos")

    repos = fetch_my_repos()


    ideas = []

    ideas += scrape_reddit_posts()

    ideas += scrape_reddit_comments()

    ideas += scrape_hackernews()

    ideas += scrape_github_issues()


    unique = {}

    for idea in ideas:

        key = canonicalize(idea["title"])

        if not key:
            continue

        current = unique.get(key)

        if not current or idea["rank_score"] > current["rank_score"]:
            unique[key] = idea

    ideas = sorted(unique.values(), key=lambda x: x["rank_score"], reverse=True)[:25]


    best = None
    best_total = -1


    for idea in ideas:

        if already_in_pipeline(idea["title"]):
            continue

        if github_saturated(idea["title"]):
            continue

        existing_url,_ = find_existing_tool(idea["title"],repos)

        if existing_url:
            continue

        result = validate_idea(idea["title"],idea["text"])

        if result and result.get("validated"):

            refs = find_github_codebase(idea["title"])
            total_score = (idea["signal_score"] * 2) + int(result.get("score", 0))

            candidate = {

            "title":idea["title"],
            "idea":result.get("problem_summary") or idea["title"],
            "url":idea["url"],
            "score":idea["score"],
            "signal_score":idea["signal_score"],
            "sub":idea["sub"],
            "ai_score":result["score"],
            "product_type":result["product_type"],
            "product_name":result["product_name"],
            "elevator_pitch":result["elevator_pitch"],
            "target_user":result["target_user"],
            "why_now":result.get("why_now",""),
            "github_refs":refs,
            "status":"pending",
            "created":str(datetime.datetime.utcnow())

            }

            if total_score > best_total:
                best = candidate
                best_total = total_score


    if not best:

        send_confirmation("Factory update: Liam ran but found no strong ideas.")
        return


    msg_id,approved = request_liam_approval(best)


    if approved:

        problems = load("data/problems.json")

        problems.append(best)

        save("data/problems.json",problems)

        set_state("idle")

        print("Idea approved → Kyle will start")

    else:

        set_state("idle")



if __name__ == "__main__":
    run()
