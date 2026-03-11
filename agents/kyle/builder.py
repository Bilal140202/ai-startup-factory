"""
Kyle: Builds real apps.
1. Read problem (with GitHub refs Liam found)
2. Fetch reference repo code snippets from GitHub
3. AI generates full working code using refs as context
4. Create GitHub repo + push
5. Netlify CLI: create site + deploy
6. Save URL → Vera asks for your approval
"""

import sys
sys.path.insert(0, "agents")

import requests, json, os, re, subprocess, datetime, shutil
from shared import ai

GH_TOKEN        = os.environ["GITHUB_TOKEN"]
GH_USER         = os.environ["GITHUB_USERNAME"]
NETLIFY_TOKEN   = os.environ["NETLIFY_AUTH_TOKEN"]

WEEKLY_LIMIT = 5

def load(path):
    if not os.path.exists(path): return []
    with open(path) as f: return json.load(f)

def load_one(path, default=None):
    if not os.path.exists(path): return default
    with open(path) as f: return json.load(f)

def save(path, data):
    with open(path,"w") as f: json.dump(data, f, indent=2)

def set_state(s): save("data/pipeline_state.json", s)

def weekly_count():
    apps = load("data/app_database.json")
    week = datetime.datetime.utcnow().isocalendar()[1]
    return sum(
        1 for a in apps
        if datetime.datetime.fromisoformat(a["created"]).isocalendar()[1] == week
    )

def pick_problem():
    for p in load("data/problems.json"):
        if p.get("status") == "pending": return p
    return None

def mark_problem(title, status):
    problems = load("data/problems.json")
    for p in problems:
        if p["title"] == title: p["status"] = status
    save("data/problems.json", problems)

def run_cmd(cmd, cwd=None, capture=True):
    result = subprocess.run(cmd, shell=True, capture_output=capture, text=True, cwd=cwd)
    if result.returncode != 0:
        print(f"  CMD stderr: {result.stderr[:400]}")
    return result

# ── Fetch reference code from GitHub ─────────────────────────
def fetch_repo_snippet(full_name, default_branch="main"):
    """Fetch key files from a reference repo to give AI context."""
    snippets = []
    # Try to get the main entry file
    for filename in ["index.html","app.py","main.py","index.js","README.md"]:
        url = f"https://raw.githubusercontent.com/{full_name}/{default_branch}/{filename}"
        try:
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                snippets.append(f"--- {filename} ---\n{r.text[:1500]}")
                break
        except: pass
    return "\n\n".join(snippets)

def gather_reference_context(github_refs):
    """Build a context string from reference repos for the AI prompt."""
    if not github_refs: return ""
    context_parts = []
    for ref in github_refs[:3]:
        snippet = fetch_repo_snippet(ref.get("full_name",""), ref.get("default_branch","main"))
        if snippet:
            context_parts.append(
                f"Reference repo: {ref['repo_url']}\nDescription: {ref['description']}\n{snippet}"
            )
    if not context_parts: return ""
    return "Here are existing open-source tools solving similar problems — use their patterns and structure as inspiration:\n\n" + "\n\n===\n\n".join(context_parts)

# ── Code generation ───────────────────────────────────────────
def extract_code(raw, fence="html"):
    pattern = rf"```{fence}\n?(.*?)```"
    match = re.search(pattern, raw, re.DOTALL)
    if match: return match.group(1).strip()
    return re.sub(r"```[a-z]*\n?","",raw).replace("```","").strip()

def build_html_tool(problem, ref_context):
    prompt = f"""
Build a complete, working single-file HTML tool.

Problem: {problem['idea']}
Target user: {problem.get('target_user','general users')}
Pitch: {problem.get('elevator_pitch','')}
Tool name: {problem['product_name']}

{ref_context}

Requirements:
- Single self-contained HTML file (inline CSS + JS only)
- Fully functional core feature — no placeholder buttons
- Beautiful modern UI: dark theme, gradient accents, smooth interactions
- Mobile responsive
- Clear input → output flow

Return ONLY the complete HTML inside ```html fences.
"""
    return extract_code(ai(prompt, model_hint="smart", max_tokens=4000), "html"), "index.html"

def build_python_webapp(problem, ref_context):
    prompt = f"""
Build a complete Python Flask web app.

Problem: {problem['idea']}
Target user: {problem.get('target_user','general users')}
App name: {problem['product_name']}

{ref_context}

Requirements:
- app.py with Flask routes, fully functional logic
- templates/index.html with beautiful modern UI (inline CSS)
- requirements.txt: flask, gunicorn only
- No database, no heavy deps

Return JSON only (no markdown fences):
{{
  "app_py": "<full app.py>",
  "index_html": "<full templates/index.html>",
  "requirements": "flask\\ngunicorn"
}}
"""
    raw = ai(prompt, model_hint="smart", max_tokens=4000)
    raw = re.sub(r"```[a-z]*\n?","",raw).replace("```","").strip()
    return json.loads(raw), "python"

def build_react_app(problem, ref_context):
    prompt = f"""
Build a complete single-file React app (CDN, no build step).

Problem: {problem['idea']}
Target user: {problem.get('target_user','general users')}
App name: {problem['product_name']}

{ref_context}

Requirements:
- Single index.html using React + ReactDOM + Babel via CDN
- Fully functional core feature
- Beautiful modern UI with inline styles
- No build step

Return ONLY the HTML inside ```html fences.
"""
    return extract_code(ai(prompt, model_hint="smart", max_tokens=4000), "html"), "index.html"

def write_netlify_toml(tmp_dir, app_type):
    if app_type == "python-webapp":
        content = '[build]\n  command = "pip install -r requirements.txt"\n  publish = "."\n\n[build.environment]\n  PYTHON_VERSION = "3.11"\n'
    else:
        content = '[build]\n  publish = "."\n'
    with open(f"{tmp_dir}/netlify.toml","w") as f: f.write(content)

# ── GitHub repo ───────────────────────────────────────────────
def sanitize_repo_name(name):
    """
    GitHub repo names: alphanumeric, hyphens, underscores only.
    Max 100 chars. Cannot start/end with hyphen.
    """
    import re as _re
    name = name.lower().strip()
    name = _re.sub(r"[^a-z0-9\-_]", "-", name)   # replace invalid chars
    name = _re.sub(r"-{2,}", "-", name)             # collapse multiple hyphens
    name = name.strip("-")                          # strip leading/trailing hyphens
    name = name[:80]                                # leave room for collision suffix
    if not name:
        name = "ai-tool"
    return name

def repo_exists(name):
    r = requests.get(
        f"https://api.github.com/repos/{GH_USER}/{name}",
        headers={"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github+json"}
    )
    return r.status_code == 200

def unique_repo_name(base_name):
    """Append -2, -3 etc. until we find a name that doesn't exist."""
    candidate = sanitize_repo_name(base_name)
    if not repo_exists(candidate):
        return candidate
    suffix = 2
    while suffix < 20:
        candidate = f"{sanitize_repo_name(base_name)}-{suffix}"
        if not repo_exists(candidate):
            return candidate
        suffix += 1
    # Last resort: append timestamp
    import datetime as _dt
    ts = _dt.datetime.utcnow().strftime("%m%d%H%M")
    return f"{sanitize_repo_name(base_name)}-{ts}"

def create_github_repo(name, description):
    safe_name = unique_repo_name(name)
    if safe_name != name:
        print(f"  Repo name sanitized/deduplicated: '{name}' → '{safe_name}'")
    r = requests.post(
        "https://api.github.com/user/repos",
        json={"name": safe_name, "description": description[:255], "public": True, "auto_init": False},
        headers={"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github+json"}
    )
    if r.status_code == 201:
        return safe_name, f"https://github.com/{GH_USER}/{safe_name}"
    if r.status_code == 422:
        # Exists but we didn't catch it above — just use it
        print(f"  Repo '{safe_name}' already exists, reusing.")
        return safe_name, f"https://github.com/{GH_USER}/{safe_name}"
    raise Exception(f"GitHub repo creation failed: {r.status_code} {r.text}")

def push_to_github(tmp_dir, safe_name):
    remote = f"https://{GH_USER}:{GH_TOKEN}@github.com/{GH_USER}/{safe_name}.git"
    run_cmd("git init",                                             cwd=tmp_dir)
    run_cmd('git config user.email "kyle@ai-factory.bot"',         cwd=tmp_dir)
    run_cmd('git config user.name "Kyle Builder"',                 cwd=tmp_dir)
    run_cmd("git add -A",                                           cwd=tmp_dir)
    run_cmd(f'git commit -m "🚀 Initial build: {safe_name}"',      cwd=tmp_dir)
    run_cmd("git branch -M main",                                  cwd=tmp_dir)
    run_cmd(f"git remote add origin {remote}",                     cwd=tmp_dir)
    run_cmd("git push -u origin main --force",                     cwd=tmp_dir)

# ── Netlify deploy ────────────────────────────────────────────
def netlify_deploy(tmp_dir, site_name):
    """
    Create Netlify site and deploy prod. Returns live URL.
    Handles CLI output that may contain warnings/logs before the JSON blob.
    """
    # Step 1: create the site
    create_result = run_cmd(
        f"netlify sites:create --name {site_name} --auth {NETLIFY_TOKEN}",
        cwd=tmp_dir
    )
    print(f"  Netlify site created: {create_result.stdout[:200]}")

    # Step 2: deploy with --json and robustly parse the URL
    deploy_result = run_cmd(
        f"netlify deploy --prod --dir=. --site={site_name} --auth={NETLIFY_TOKEN} --json",
        cwd=tmp_dir
    )

    url = None
    stdout = deploy_result.stdout or ""

    # The CLI may print non-JSON lines before the JSON object — find the first { ... }
    json_match = re.search(r'\{.*\}', stdout, re.DOTALL)
    if json_match:
        try:
            deploy_data = json.loads(json_match.group(0))
            # Netlify CLI returns either 'url' or 'deploy_url' depending on version
            url = (
                deploy_data.get("url")
                or deploy_data.get("deploy_url")
                or deploy_data.get("ssl_url")
            )
        except json.JSONDecodeError:
            pass

    if not url:
        print(f"  ⚠️  Could not parse Netlify URL from output, using default.")
        url = f"https://{site_name}.netlify.app"

    print(f"  ✓ Netlify URL: {url}")
    return url

# ── Main ──────────────────────────────────────────────────────
def main():
    from vera.gatekeeper import request_kyle_approval, send_confirmation, send_error

    if weekly_count() >= WEEKLY_LIMIT:
        print("⚠️  Weekly build limit (5) reached.")
        return

    problem = pick_problem()
    if not problem:
        print("No pending problems.")
        return

    name     = problem["product_name"]
    app_type = problem.get("product_type","html-tool")
    desc     = problem.get("elevator_pitch", problem["idea"])
    tmp_dir  = f"/tmp/kyle-{name}"

    set_state("building")
    print(f"🔨 Kyle: Building '{name}' ({app_type})...")

    if os.path.exists(tmp_dir): shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir)

    try:
        # 1. Gather reference code context
        refs = problem.get("github_refs", [])
        print(f"  Fetching code context from {len(refs)} reference repos...")
        ref_context = gather_reference_context(refs)

        # 2. Generate code
        print("  Generating code with AI...")
        if app_type == "python-webapp":
            data, _ = build_python_webapp(problem, ref_context)
            os.makedirs(f"{tmp_dir}/templates", exist_ok=True)
            with open(f"{tmp_dir}/app.py","w")                   as f: f.write(data["app_py"])
            with open(f"{tmp_dir}/templates/index.html","w")     as f: f.write(data["index_html"])
            with open(f"{tmp_dir}/requirements.txt","w")         as f: f.write(data["requirements"])
        elif app_type == "react-app":
            code, fname = build_react_app(problem, ref_context)
            with open(f"{tmp_dir}/{fname}","w") as f: f.write(code)
        else:
            code, fname = build_html_tool(problem, ref_context)
            with open(f"{tmp_dir}/{fname}","w") as f: f.write(code)

        # 3. netlify.toml + README
        write_netlify_toml(tmp_dir, app_type)
        with open(f"{tmp_dir}/README.md","w") as f:
            f.write(f"# {name}\n\n{desc}\n\nBuilt by AI Startup Factory 🤖\n")

        # 4. Create GitHub repo + push
        print(f"  Creating GitHub repo: {GH_USER}/{name}...")
        safe_name, gh_url = create_github_repo(name, desc)
        push_to_github(tmp_dir, safe_name)
        print(f"  ✓ Pushed to {gh_url}")

        # 5. Netlify deploy (use safe_name so site name matches repo)
        print(f"  Deploying to Netlify...")
        netlify_url = netlify_deploy(tmp_dir, safe_name)
        print(f"  ✓ Live at {netlify_url}")

        # 6. Save to factory repo
        dest = f"generated/{safe_name}"
        if os.path.exists(dest): shutil.rmtree(dest)
        shutil.copytree(tmp_dir, dest)

        app_entry = {
            "name":          name,
            "idea":          problem["idea"],
            "product_type":  app_type,
            "elevator_pitch":desc,
            "target_user":   problem.get("target_user",""),
            "github_url":    gh_url,
            "netlify_url":   netlify_url,
            "reddit_url":    problem.get("url",""),
            "created":       str(datetime.datetime.utcnow()),
            "status":        "awaiting_approval"
        }

        # 7. Ask for your approval via Discord
        print("  Asking Vera to send Discord approval...")
        _, approved = request_kyle_approval(app_entry)

        if approved:
            app_entry["status"] = "approved"
            apps = load("data/app_database.json")
            apps.append(app_entry)
            save("data/app_database.json", apps)
            mark_problem(problem["title"], "built")
            set_state("idle")  # Nick triggers off app_database.json
            print(f"  ✅ Approved. Nick will pick this up.")
        else:
            print("  ⏰ No approval. Marking problem as skipped.")
            mark_problem(problem["title"], "skipped")
            set_state("idle")

    except Exception as e:
        print(f"❌ Kyle build failed: {e}")
        send_error(f"Kyle failed to build '{name}': {e}")
        mark_problem(problem["title"], "failed")
        set_state("idle")

if __name__ == "__main__":
    main()

