#!/usr/bin/env python3
"""
Analyzes the GitHub account (repos, profile bio, profile README) and asks
Gemini to refresh ANY resume section — Summary, Education, Certifications,
Experience, Projects, Technical Skills — wherever the GitHub data gives clear,
unambiguous evidence of a change. Only overwrites the .tex file if Gemini
actually returns a materially different document; the caller (the GitHub
Actions workflow) decides whether to recompile the PDF and commit.
"""

import base64
import json
import os
import re
import sys
from datetime import datetime, timezone

import requests

GITHUB_USERNAME = os.environ["GITHUB_USERNAME"]
GH_READ_TOKEN = os.environ["GH_READ_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
RESUME_PATH = os.environ.get("RESUME_TEX_PATH", "Muhammad_Hussain_Resume.tex")
MAX_REPOS = int(os.environ.get("MAX_REPOS", "20"))

GITHUB_API = "https://api.github.com"
GH_HEADERS = {
    "Authorization": f"Bearer {GH_READ_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def resolve_model():
    """Gemini model names change over time, so rather than hardcode one,
    discover what this API key can actually use and pick a cost-effective
    ("flash") model that supports generateContent. Set GEMINI_MODEL to
    override."""
    if os.environ.get("GEMINI_MODEL"):
        return os.environ["GEMINI_MODEL"]

    resp = requests.get(
        f"{GEMINI_API_BASE}/models", params={"key": GEMINI_API_KEY}, timeout=30
    )
    resp.raise_for_status()
    models = resp.json().get("models", [])
    candidates = [
        m["name"].split("/")[-1]
        for m in models
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]
    if not candidates:
        raise RuntimeError("No Gemini models available for this API key support generateContent.")

    def rank(name):
        score = 0
        if "flash" in name:
            score -= 2
        if "pro" in name:
            score -= 1
        if "exp" in name or "preview" in name or "thinking" in name:
            score += 5
        if "vision" in name or "embedding" in name or "tts" in name or "image" in name:
            score += 10
        return score

    candidates.sort(key=rank)
    return candidates[0]


def gh_get(path, params=None):
    resp = requests.get(f"{GITHUB_API}{path}", headers=GH_HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_profile():
    """Bio/company/location from the account, plus the special profile README
    repo (github.com/<user>/<user>) many developers use to list current work,
    certifications, and experience."""
    profile = {}
    try:
        user = gh_get(f"/users/{GITHUB_USERNAME}")
        profile["bio"] = user.get("bio") or ""
        profile["company"] = user.get("company") or ""
        profile["location"] = user.get("location") or ""
        profile["blog"] = user.get("blog") or ""
    except requests.HTTPError:
        pass

    try:
        readme = gh_get(f"/repos/{GITHUB_USERNAME}/{GITHUB_USERNAME}/readme")
        content = base64.b64decode(readme["content"]).decode("utf-8", errors="ignore")
        profile["profile_readme"] = content[:4000]
    except requests.HTTPError:
        profile["profile_readme"] = ""

    return profile


def fetch_repo_summaries():
    repos = gh_get(
        f"/users/{GITHUB_USERNAME}/repos",
        params={"per_page": 100, "sort": "pushed", "direction": "desc", "type": "owner"},
    )
    repos = [r for r in repos if not r.get("fork") and r["name"] != GITHUB_USERNAME]
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


def build_prompt(resume_tex, profile, repo_summaries):
    system = (
        "You are maintaining a LaTeX resume for a full-stack software "
        "engineer. You will be given the CURRENT resume .tex source and a "
        "JSON snapshot of the person's GitHub account (profile bio, their "
        "profile README, and their repositories). Your job is to decide "
        "whether the resume needs updating, and if so, return the FULL "
        "updated .tex file.\n\n"
        "Rules:\n"
        "- Preserve the LaTeX preamble, custom commands, and overall "
        "document structure exactly.\n"
        "- ANY section may be updated — Summary, Education, Certifications, "
        "Experience, Projects, Technical Skills — but ONLY when the GitHub "
        "snapshot gives clear, unambiguous evidence for that specific "
        "change. If a section has no supporting evidence in the data, leave "
        "it completely untouched. Never fabricate degrees, employers, dates, "
        "metrics, or outcomes that aren't evidenced in the data. Never touch "
        "the contact-info header (name/phone/email/links) unless the GitHub "
        "profile data explicitly gives a new value for one of those exact "
        "fields.\n"
        "- Projects section: keep at most 4 of the strongest / most recent "
        "projects. Prefer repos with real substance (a description, a "
        "README, meaningful code) over trivial/empty ones. Each project "
        "keeps the existing \\resumeProjectHeading / \\resumeItemListStart "
        "pattern, with GitHub link (and live demo link via `homepage` if "
        "present).\n"
        "- Write bullet points the way a strong resume does: concrete, "
        "quantified where the README/description supports it, "
        "action-verb-led.\n"
        "- Technical Skills: merge in genuinely new languages/frameworks "
        "seen across repos; do not remove skills just because a repo aged "
        "out of the top list.\n"
        "- Education/Certifications/Experience: only add or edit an entry "
        "if the profile bio or profile README explicitly states something "
        "new (e.g. a newly listed certification, a new job/role, a new "
        "degree status). Otherwise leave these sections exactly as they "
        "are.\n"
        "- If nothing meaningfully changed since the current resume, return "
        "the resume completely UNCHANGED, byte for byte.\n"
        "- Output ONLY the raw .tex file content. No markdown fences, no "
        "commentary, no explanation before or after."
    )

    user = (
        f"CURRENT RESUME (.tex):\n{resume_tex}\n\n"
        f"GITHUB PROFILE:\n{json.dumps(profile, indent=2)}\n\n"
        f"GITHUB REPOSITORIES (as of {datetime.now(timezone.utc).isoformat()}):\n"
        f"{json.dumps(repo_summaries, indent=2)}"
    )
    return system, user


def strip_code_fences(text):
    text = text.strip()
    match = re.match(r"^```(?:latex|tex)?\n(.*)\n```$", text, re.DOTALL)
    return match.group(1) if match else text


def call_gemini(model, system, user):
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.3},
    }
    resp = requests.post(
        f"{GEMINI_API_BASE}/models/{model}:generateContent",
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {json.dumps(data)[:1000]}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    if not text.strip():
        raise RuntimeError(f"Gemini returned empty text: {json.dumps(data)[:1000]}")
    return text


def main():
    with open(RESUME_PATH, "r", encoding="utf-8") as f:
        current_tex = f.read()

    model = resolve_model()
    print(f"Using Gemini model: {model}")

    profile = fetch_profile()
    repo_summaries = fetch_repo_summaries()
    system, user = build_prompt(current_tex, profile, repo_summaries)

    raw_output = call_gemini(model, system, user)
    updated_tex = strip_code_fences(raw_output)

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
