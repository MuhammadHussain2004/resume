#!/usr/bin/env python3
"""
Analyzes the GitHub account's public + private repos and asks Claude to
refresh the Projects / Technical Skills / Summary sections of the resume
LaTeX source to reflect the latest work. Only overwrites the .tex file if
Claude actually returns a materially different document; the caller (the
GitHub Actions workflow) decides whether to recompile the PDF and commit.
"""

import base64
import json
import os
import re
import sys
from datetime import datetime, timezone

import requests
from anthropic import Anthropic

GITHUB_USERNAME = os.environ["GITHUB_USERNAME"]
GH_READ_TOKEN = os.environ["GH_READ_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
RESUME_PATH = os.environ.get("RESUME_TEX_PATH", "Muhammad_Hussain_Resume.tex")
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
MAX_REPOS = int(os.environ.get("MAX_REPOS", "15"))

GITHUB_API = "https://api.github.com"
HEADERS = {
    "Authorization": f"Bearer {GH_READ_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def gh_get(path, params=None):
    resp = requests.get(f"{GITHUB_API}{path}", headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_repo_summaries():
    repos = gh_get(
        f"/users/{GITHUB_USERNAME}/repos",
        params={"per_page": 100, "sort": "pushed", "direction": "desc", "type": "owner"},
    )
    repos = [r for r in repos if not r.get("fork")]
    repos = repos[:MAX_REPOS]

    summaries = []
    for repo in repos:
        name = repo["name"]
        readme_excerpt = ""
        try:
            readme = gh_get(f"/repos/{GITHUB_USERNAME}/{name}/readme")
            content = base64.b64decode(readme["content"]).decode("utf-8", errors="ignore")
            readme_excerpt = content[:1500]
        except requests.HTTPError:
            pass

        try:
            languages = gh_get(f"/repos/{GITHUB_USERNAME}/{name}/languages")
        except requests.HTTPError:
            languages = {}

        summaries.append(
            {
                "name": name,
                "description": repo.get("description") or "",
                "url": repo["html_url"],
                "homepage": repo.get("homepage") or "",
                "topics": repo.get("topics") or [],
                "languages": list(languages.keys()),
                "stars": repo.get("stargazers_count", 0),
                "pushed_at": repo.get("pushed_at"),
                "created_at": repo.get("created_at"),
                "readme_excerpt": readme_excerpt,
            }
        )
    return summaries


def build_prompt(resume_tex, repo_summaries):
    system = (
        "You are maintaining a LaTeX resume for a full-stack software engineer. "
        "You will be given the CURRENT resume .tex source and a JSON snapshot of "
        "the person's GitHub repositories (from the GitHub API). Your job is to "
        "decide whether the resume needs updating, and if so, return the FULL "
        "updated .tex file.\n\n"
        "Rules:\n"
        "- Preserve the LaTeX preamble, custom commands, and overall structure exactly.\n"
        "- Only touch the Projects, Technical Skills, and Summary sections. "
        "Never invent or alter Education, Certifications, Experience, or the "
        "contact-info header unless the GitHub data gives explicit, unambiguous "
        "evidence of a change there.\n"
        "- Projects section: keep at most 4 of the strongest / most recent "
        "projects. Prefer repos with real substance (a description, a README, "
        "meaningful code) over trivial/empty ones. Each project keeps the "
        "existing \\resumeProjectHeading / \\resumeItemListStart pattern, with "
        "GitHub link (and live demo link via `homepage` if present).\n"
        "- Write bullet points the way a strong resume does: concrete, "
        "quantified where the README/description supports it, action-verb-led. "
        "Never fabricate metrics, users, or outcomes that aren't evidenced in "
        "the repo data.\n"
        "- Technical Skills: merge in genuinely new languages/frameworks seen "
        "across repos; do not remove skills just because a repo aged out of "
        "the top list.\n"
        "- If nothing meaningfully changed since the current resume, return the "
        "resume completely UNCHANGED, byte for byte.\n"
        "- Output ONLY the raw .tex file content. No markdown fences, no "
        "commentary, no explanation before or after."
    )

    user = (
        f"CURRENT RESUME (.tex):\n{resume_tex}\n\n"
        f"GITHUB SNAPSHOT (as of {datetime.now(timezone.utc).isoformat()}):\n"
        f"{json.dumps(repo_summaries, indent=2)}"
    )
    return system, user


def strip_code_fences(text):
    text = text.strip()
    match = re.match(r"^```(?:latex|tex)?\n(.*)\n```$", text, re.DOTALL)
    return match.group(1) if match else text


def main():
    with open(RESUME_PATH, "r", encoding="utf-8") as f:
        current_tex = f.read()

    repo_summaries = fetch_repo_summaries()
    system, user = build_prompt(current_tex, repo_summaries)

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    updated_tex = strip_code_fences(response.content[0].text)

    if not updated_tex.strip().startswith("\\documentclass"):
        print("Model output did not look like a valid .tex file; skipping update.", file=sys.stderr)
        print(updated_tex[:2000], file=sys.stderr)
        sys.exit(1)

    changed = updated_tex.strip() != current_tex.strip()
    if changed:
        with open(RESUME_PATH, "w", encoding="utf-8") as f:
            f.write(updated_tex)
        print("Resume updated.")
    else:
        print("No changes needed.")

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as f:
            f.write(f"RESUME_CHANGED={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    main()
