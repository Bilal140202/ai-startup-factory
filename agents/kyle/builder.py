"""
Kyle: builds real apps from approved problems.
"""

import sys
sys.path.insert(0, "agents")

import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile

import requests

from shared import ai, extract_json


GH_TOKEN = os.environ["GITHUB_TOKEN"]
GH_USER = os.environ["GITHUB_USERNAME"]
NETLIFY_TOKEN = os.environ["NETLIFY_AUTH_TOKEN"]
FACTORY_REPO = os.environ.get("FACTORY_REPO_NAME", "ai-startup-factory")

WEEKLY_LIMIT = 5


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


def weekly_count():
    apps = load("data/app_database.json")
    week = datetime.datetime.utcnow().isocalendar()[1]
    return sum(
        1 for app in apps
        if datetime.datetime.fromisoformat(app["created"]).isocalendar()[1] == week
    )


def pick_problem():
    for problem in load("data/problems.json"):
        if problem.get("status") == "pending":
            return problem
    return None


def mark_problem(title, status):
    problems = load("data/problems.json")
    for problem in problems:
        if problem["title"] == title:
            problem["status"] = status
    save("data/problems.json", problems)


def run_cmd(cmd, cwd=None, capture=True):
    result = subprocess.run(cmd, shell=True, capture_output=capture, text=True, cwd=cwd)
    if result.returncode != 0:
        print(f"  CMD stderr: {(result.stderr or '')[:400]}")
    return result


def run_cmd_checked(cmd, cwd=None, capture=True):
    result = run_cmd(cmd, cwd=cwd, capture=capture)
    if result.returncode != 0:
        error_text = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Command failed: {cmd}\n{error_text[:500]}")
    return result


def sanitize_repo_name(name):
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\-_]", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    name = name[:80]
    return name or "ai-tool"


def repo_full_name(ref):
    full_name = (ref.get("full_name") or "").strip()
    if full_name:
        return full_name

    repo_url = (ref.get("repo_url") or "").strip()
    match = re.search(r"github\.com/([^/]+/[^/#?]+)", repo_url)
    if match:
        return match.group(1)

    return ""


def fetch_repo_snippet(full_name, default_branch="main"):
    snippets = []
    for filename in ["index.html", "app.py", "main.py", "index.js", "README.md"]:
        url = f"https://raw.githubusercontent.com/{full_name}/{default_branch}/{filename}"
        try:
            response = requests.get(url, timeout=8)
            if response.status_code == 200:
                snippets.append(f"--- {filename} ---\n{response.text[:1500]}")
                break
        except Exception:
            pass
    return "\n\n".join(snippets)


def gather_reference_context(github_refs):
    if not github_refs:
        return ""

    parts = []
    for ref in github_refs[:3]:
        full_name = repo_full_name(ref)
        if not full_name:
            continue
        snippet = fetch_repo_snippet(full_name, ref.get("default_branch", "main"))
        if not snippet:
            continue
        parts.append(
            f"Reference repo: {ref.get('repo_url','')}\n"
            f"Repository: {full_name}\n"
            f"Description: {ref.get('description','')}\n"
            f"{snippet}"
        )

    if not parts:
        return ""

    return (
        "Here are existing open-source tools solving similar problems. "
        "Use their patterns and structure as inspiration, not as code to copy.\n\n"
        + "\n\n===\n\n".join(parts)
    )


def extract_code(raw, fence="html"):
    match = re.search(rf"```{fence}\n?(.*?)```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    return re.sub(r"```[a-z]*\n?", "", raw).replace("```", "").strip()


def build_html_tool(problem, ref_context):
    prompt = f"""
Build a complete, working single-file HTML tool.

Problem: {problem['idea']}
Target user: {problem.get('target_user', 'general users')}
Pitch: {problem.get('elevator_pitch', '')}
Tool name: {problem['product_name']}

{ref_context}

Requirements:
- Single self-contained HTML file with inline CSS and JS only
- Fully functional core feature, no placeholder buttons
- Clear input to output flow
- Strong visual design and mobile responsiveness

Return ONLY the complete HTML inside ```html fences.
"""
    return extract_code(ai(prompt, model_hint="smart", max_tokens=4000), "html"), "index.html"


def build_python_webapp(problem, ref_context):
    prompt = f"""
Build a complete Python Flask web app.

Problem: {problem['idea']}
Target user: {problem.get('target_user', 'general users')}
App name: {problem['product_name']}

{ref_context}

Requirements:
- app.py with Flask routes and functional logic
- templates/index.html with strong UI
- requirements.txt containing flask and gunicorn only
- No database and no heavy dependencies

Return JSON only:
{{
  "app_py": "<full app.py>",
  "index_html": "<full templates/index.html>",
  "requirements": "flask\\ngunicorn"
}}
"""
    return extract_json(ai(prompt, model_hint="smart", max_tokens=4000)), "python"


def build_react_app(problem, ref_context):
    prompt = f"""
Build a complete single-file React app with CDN scripts and no build step.

Problem: {problem['idea']}
Target user: {problem.get('target_user', 'general users')}
App name: {problem['product_name']}

{ref_context}

Requirements:
- Single index.html using React, ReactDOM, and Babel via CDN
- Fully functional core feature
- Strong visual design with inline styles

Return ONLY the HTML inside ```html fences.
"""
    return extract_code(ai(prompt, model_hint="smart", max_tokens=4000), "html"), "index.html"


def write_netlify_toml(tmp_dir, app_type):
    if app_type == "python-webapp":
        content = (
            '[build]\n'
            '  command = "pip install -r requirements.txt"\n'
            '  publish = "."\n\n'
            '[build.environment]\n'
            '  PYTHON_VERSION = "3.11"\n'
        )
    else:
        content = '[build]\n  publish = "."\n'

    with open(os.path.join(tmp_dir, "netlify.toml"), "w", encoding="utf-8") as f:
        f.write(content)


def validate_generated_output(app_type, tmp_dir):
    if app_type in ["html-tool", "react-app"]:
        path = os.path.join(tmp_dir, "index.html")
        if not os.path.exists(path):
            raise ValueError("Generated app is missing index.html.")
        with open(path, encoding="utf-8") as f:
            html = f.read().lower()
        if "<html" not in html or "<script" not in html:
            raise ValueError("Generated HTML is missing core structure or logic.")
        if app_type == "react-app" and "react" not in html:
            raise ValueError("Generated React app output does not include React.")
        return

    if app_type == "python-webapp":
        app_path = os.path.join(tmp_dir, "app.py")
        index_path = os.path.join(tmp_dir, "templates", "index.html")
        req_path = os.path.join(tmp_dir, "requirements.txt")
        for path in [app_path, index_path, req_path]:
            if not os.path.exists(path):
                raise ValueError(f"Generated Python app is missing {os.path.basename(path)}.")

        with open(app_path, encoding="utf-8") as f:
            app_code = f.read().lower()
        with open(index_path, encoding="utf-8") as f:
            html = f.read().lower()
        with open(req_path, encoding="utf-8") as f:
            requirements = f.read().lower()

        if "flask" not in app_code or ("@app.route" not in app_code and "app.route(" not in app_code):
            raise ValueError("Generated Flask app is missing routing.")
        if "<form" not in html and "<input" not in html and "<textarea" not in html:
            raise ValueError("Generated template does not include an input flow.")
        if "flask" not in requirements or "gunicorn" not in requirements:
            raise ValueError("Generated requirements.txt is incomplete.")
        return

    raise ValueError(f"Unsupported app type: {app_type}")


def repo_exists(name):
    response = requests.get(
        f"https://api.github.com/repos/{GH_USER}/{name}",
        headers={"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github+json"},
        timeout=15,
    )
    return response.status_code == 200


def unique_repo_name(base_name):
    candidate = sanitize_repo_name(base_name)
    if not repo_exists(candidate):
        return candidate

    suffix = 2
    while suffix < 20:
        candidate = f"{sanitize_repo_name(base_name)}-{suffix}"
        if not repo_exists(candidate):
            return candidate
        suffix += 1

    ts = datetime.datetime.utcnow().strftime("%m%d%H%M")
    return f"{sanitize_repo_name(base_name)}-{ts}"


def generated_app_url(safe_name):
    return f"https://github.com/{GH_USER}/{FACTORY_REPO}/tree/main/generated/{safe_name}"


def create_github_repo(name, description):
    safe_name = unique_repo_name(name)
    if safe_name != name:
        print(f"  Repo name sanitized or deduplicated: '{name}' -> '{safe_name}'")

    response = requests.post(
        "https://api.github.com/user/repos",
        json={"name": safe_name, "description": description[:255], "public": True, "auto_init": False},
        headers={"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github+json"},
        timeout=20,
    )

    if response.status_code == 201:
        return safe_name, f"https://github.com/{GH_USER}/{safe_name}", True
    if response.status_code == 422:
        return safe_name, f"https://github.com/{GH_USER}/{safe_name}", True
    if response.status_code in [401, 403]:
        print("  External repo creation is not permitted for this token. Using factory repo storage instead.")
        return safe_name, generated_app_url(safe_name), False

    raise RuntimeError(f"GitHub repo creation failed: {response.status_code} {response.text}")


def push_to_github(tmp_dir, safe_name):
    remote = f"https://{GH_USER}:{GH_TOKEN}@github.com/{GH_USER}/{safe_name}.git"
    run_cmd_checked("git init", cwd=tmp_dir)
    run_cmd_checked('git config user.email "kyle@ai-factory.bot"', cwd=tmp_dir)
    run_cmd_checked('git config user.name "Kyle Builder"', cwd=tmp_dir)
    run_cmd_checked("git add -A", cwd=tmp_dir)
    run_cmd_checked(f'git commit -m "Initial build: {safe_name}"', cwd=tmp_dir)
    run_cmd_checked("git branch -M main", cwd=tmp_dir)
    run_cmd_checked(f"git remote add origin {remote}", cwd=tmp_dir)
    run_cmd_checked("git push -u origin main --force", cwd=tmp_dir)


def netlify_deploy(tmp_dir, site_name):
    create_result = run_cmd(
        f"netlify sites:create --name {site_name} --auth {NETLIFY_TOKEN}",
        cwd=tmp_dir,
    )
    create_error = (create_result.stderr or "").lower()
    if create_result.returncode != 0 and "already exists" not in create_error:
        raise RuntimeError(f"Netlify site creation failed: {(create_result.stderr or create_result.stdout or '').strip()[:500]}")

    deploy_result = run_cmd_checked(
        f"netlify deploy --prod --dir=. --site={site_name} --auth={NETLIFY_TOKEN} --json",
        cwd=tmp_dir,
    )

    stdout = deploy_result.stdout or ""
    match = re.search(r"\{.*\}", stdout, re.DOTALL)
    if match:
        try:
            deploy_data = json.loads(match.group(0))
            url = deploy_data.get("url") or deploy_data.get("deploy_url") or deploy_data.get("ssl_url")
            if url:
                return url
        except json.JSONDecodeError:
            pass

    fallback_url = f"https://{site_name}.netlify.app"
    print(f"  Could not parse Netlify JSON cleanly, using {fallback_url}")
    return fallback_url


def main():
    from vera.gatekeeper import request_kyle_approval, send_error

    if weekly_count() >= WEEKLY_LIMIT:
        print("Weekly build limit reached.")
        return

    problem = pick_problem()
    if not problem:
        print("No pending problems.")
        return

    name = problem["product_name"]
    app_type = problem.get("product_type", "html-tool")
    desc = problem.get("elevator_pitch", problem["idea"])
    tmp_dir = os.path.join(tempfile.gettempdir(), f"kyle-{sanitize_repo_name(name)}")

    set_state("building")
    print(f"Building '{name}' ({app_type})")

    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir)
    os.makedirs("generated", exist_ok=True)

    try:
        refs = problem.get("github_refs", [])
        ref_context = gather_reference_context(refs)

        if app_type == "python-webapp":
            data, _ = build_python_webapp(problem, ref_context)
            os.makedirs(os.path.join(tmp_dir, "templates"), exist_ok=True)
            with open(os.path.join(tmp_dir, "app.py"), "w", encoding="utf-8") as f:
                f.write(data["app_py"])
            with open(os.path.join(tmp_dir, "templates", "index.html"), "w", encoding="utf-8") as f:
                f.write(data["index_html"])
            with open(os.path.join(tmp_dir, "requirements.txt"), "w", encoding="utf-8") as f:
                f.write(data["requirements"])
        elif app_type == "react-app":
            code, filename = build_react_app(problem, ref_context)
            with open(os.path.join(tmp_dir, filename), "w", encoding="utf-8") as f:
                f.write(code)
        else:
            code, filename = build_html_tool(problem, ref_context)
            with open(os.path.join(tmp_dir, filename), "w", encoding="utf-8") as f:
                f.write(code)

        validate_generated_output(app_type, tmp_dir)
        write_netlify_toml(tmp_dir, app_type)

        with open(os.path.join(tmp_dir, "README.md"), "w", encoding="utf-8") as f:
            f.write(f"# {name}\n\n{desc}\n\nBuilt by AI Startup Factory\n")

        safe_name, gh_url, external_repo = create_github_repo(name, desc)

        if external_repo:
            push_to_github(tmp_dir, safe_name)

        netlify_url = netlify_deploy(tmp_dir, safe_name)

        dest = os.path.join("generated", safe_name)
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.copytree(tmp_dir, dest)

        app_entry = {
            "name": name,
            "idea": problem["idea"],
            "product_type": app_type,
            "elevator_pitch": desc,
            "target_user": problem.get("target_user", ""),
            "github_url": gh_url,
            "netlify_url": netlify_url,
            "reddit_url": problem.get("url", ""),
            "signal_score": problem.get("signal_score", 0),
            "created": str(datetime.datetime.utcnow()),
            "status": "awaiting_approval",
        }

        _, approved = request_kyle_approval(app_entry)
        if approved:
            app_entry["status"] = "approved"
            apps = load("data/app_database.json")
            apps.append(app_entry)
            save("data/app_database.json", apps)
            mark_problem(problem["title"], "built")
            set_state("idle")
        else:
            mark_problem(problem["title"], "skipped")
            set_state("idle")

    except Exception as exc:
        print(f"Kyle build failed: {exc}")
        send_error(f"Kyle failed to build '{name}': {exc}")
        mark_problem(problem["title"], "failed")
        set_state("idle")


if __name__ == "__main__":
    main()
