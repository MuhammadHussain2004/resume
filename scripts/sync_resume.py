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
import time
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
    """Returns a list of Gemini model names to try, best candidate first.
    Model availability/names drift over time and old ones get deprecated
    (a 404 with a "no longer available" message, not a clean error code), so
    rather than hardcode one we rank ListModels' output and let the caller
    walk the list until one actually works. Set GEMINI_MODEL to pin one."""
    if os.environ.get("GEMINI_MODEL"):
        return [os.environ["GEMINI_MODEL"]]

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

    version_re = re.compile(r"(\d+)(?:\.(\d+))?")

    def rank(name):
        score = 0
        if "latest" in name:
            score += 1000  # alias that auto-tracks the current model, most future-proof
        match = version_re.search(name)
        if match:
            major = int(match.group(1))
            minor = int(match.group(2) or 0)
            score += major * 100 + minor  # prefer newer versions
        if "flash" in name:
            score += 20
        if "pro" in name:
            score += 10
        if "exp" in name or "preview" in name or "thinking" in name:
            score -= 500  # deprioritize experimental/preview builds
        if any(x in name for x in ("vision", "embedding", "tts", "image", "audio")):
            score -= 10000  # not text-generation models, exclude
        return -score  # sort ascending -> best (highest score) first

    candidates.sort(key=rank)
    return candidates


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
        "Hard rules (a program will mechanically verify these and reject "
        "your output if you break them, so follow them exactly):\n"
        "- Byte-for-byte preserve everything from \\documentclass through "
        "\\begin{document} (the preamble: packages, margins, custom "
        "\\newcommand definitions). Do not add, remove, or reformat any of "
        "it.\n"
        "- Byte-for-byte preserve the \\begin{center}...\\end{center} "
        "contact-info block (name/phone/email/links/location) exactly as "
        "given. Never change it.\n"
        "- Keep exactly these six \\section{} commands, in this order, and "
        "no others: Summary, Education, Certifications, Experience, "
        "Projects, Technical Skills.\n"
        "- Every new fact you add to Technical Skills (a language, "
        "framework, tool, or platform not already present) MUST appear "
        "verbatim (case-insensitive) somewhere in the GITHUB PROFILE or "
        "GITHUB REPOSITORIES JSON below — in a description, README excerpt, "
        "topic, or the languages list. If you cannot point to where a skill "
        "came from in that data, do not add it. Guessing a plausible "
        "tech stack from a project's category (e.g. assuming Redux because "
        "it is a React app) is fabrication — do not do it.\n"
        "- Every project you add or keep in Projects must use one of the "
        "repo `url` values given below verbatim. Never invent a project or "
        "a GitHub link.\n"
        "- Never fabricate degrees, employers, dates, metrics, or outcomes "
        "that aren't evidenced in the data.\n"
        "- The whole resume must keep fitting on ONE page: if you add "
        "content, remove or shorten something of equal or lesser weight so "
        "total length doesn't grow. Do not let Projects exceed 4 entries or "
        "Experience exceed its current entry count.\n"
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


EXPECTED_SECTIONS = [
    "Summary",
    "Education",
    "Certifications",
    "Experience",
    "Projects",
    "Technical Skills",
]

# Words that show up as LaTeX/skills boilerplate rather than an actual claim
# about a technology; excluded from the "was this ever mentioned in the
# GitHub data" fabrication check so they don't cause false-positive rejections.
SKILL_TOKEN_STOPWORDS = {
    "languages", "core cs", "mern", "full-stack", "full stack", "databases",
    "developer tools", "deployment", "cloud", "soft skills",
}


def extract_preamble(tex):
    idx = tex.find("\\begin{document}")
    return tex[:idx] if idx != -1 else tex


def extract_header(tex):
    start = tex.find("\\begin{center}")
    end = tex.find("\\end{center}")
    if start == -1 or end == -1:
        return ""
    return tex[start : end + len("\\end{center}")]


def extract_section_names(tex):
    return re.findall(r"\\section\{([^}]*)\}", tex)


def extract_skill_tokens(tex):
    match = re.search(r"\\section\{Technical Skills\}(.*?)\\end\{itemize\}", tex, re.DOTALL)
    if not match:
        return set()
    body = match.group(1)
    body = re.sub(r"\\textbf\{([^}]*)\}", r"\1", body)  # keep category label text for stopword matching
    body = body.replace("\\\\", ",")
    body = re.sub(r"[\\{}]", " ", body)
    tokens = re.split(r"[,:]", body)
    cleaned = {t.strip() for t in tokens if t.strip()}
    return {t for t in cleaned if t.lower() not in SKILL_TOKEN_STOPWORDS and len(t) > 1}


def extract_project_urls(tex):
    match = re.search(r"\\section\{Projects\}(.*?)(?=\\section\{|\Z)", tex, re.DOTALL)
    if not match:
        return set()
    return set(re.findall(r"https://github\.com/\S+?(?=[}\s])", match.group(1)))


def validate_structure(old_tex, new_tex, source_haystack, known_repo_urls):
    """Mechanically checks the model's output against the hard rules given
    in the prompt. Returns a list of human-readable problems; an empty list
    means the output is safe to accept."""
    problems = []

    if extract_preamble(old_tex) != extract_preamble(new_tex):
        problems.append("The LaTeX preamble (before \\begin{document}) was modified.")

    if extract_header(old_tex) != extract_header(new_tex):
        problems.append("The contact-info header block was modified.")

    new_sections = extract_section_names(new_tex)
    if new_sections != EXPECTED_SECTIONS:
        problems.append(
            f"Section list changed from {EXPECTED_SECTIONS} to {new_sections}."
        )

    old_skills = extract_skill_tokens(old_tex)
    new_skills = extract_skill_tokens(new_tex)
    added_skills = new_skills - old_skills
    haystack_lower = source_haystack.lower()
    unverified_skills = [s for s in added_skills if s.lower() not in haystack_lower]
    if unverified_skills:
        problems.append(
            "New Technical Skills entries with no match anywhere in the fetched "
            f"GitHub data (likely fabricated): {unverified_skills}"
        )

    new_project_urls = extract_project_urls(new_tex)
    bad_urls = [u for u in new_project_urls if u.rstrip("/") not in known_repo_urls]
    if bad_urls:
        problems.append(
            f"Project link(s) not found among this account's actual repos: {bad_urls}"
        )

    return problems


class ModelUnavailable(Exception):
    pass


def call_gemini(model, system, user):
    """Raises ModelUnavailable (caller should try the next candidate) on a
    404, and RuntimeError for anything else (auth/quota/etc, retrying with a
    different model won't help)."""
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.3},
    }

    last_error = None
    for api_version in ("v1beta", "v1"):
        url = f"https://generativelanguage.googleapis.com/{api_version}/models/{model}:generateContent"

        resp = None
        for attempt in range(3):
            resp = requests.post(url, params={"key": GEMINI_API_KEY}, json=payload, timeout=120)
            if resp.status_code in (429, 503) and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            break

        if resp.status_code == 404:
            last_error = f"{api_version}: 404 {resp.text[:500]}"
            continue
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

    raise ModelUnavailable(f"model '{model}' 404'd on both API versions. Last error: {last_error}")


def main():
    with open(RESUME_PATH, "r", encoding="utf-8") as f:
        current_tex = f.read()

    model_candidates = resolve_model()
    print(f"Gemini model candidates (best first): {model_candidates}")

    profile = fetch_profile()
    repo_summaries = fetch_repo_summaries()
    system, user = build_prompt(current_tex, profile, repo_summaries)

    raw_output = None
    errors = []
    for model in model_candidates:
        try:
            raw_output = call_gemini(model, system, user)
            print(f"Used Gemini model: {model}")
            break
        except ModelUnavailable as e:
            print(f"Skipping {model}: {e}")
            errors.append(str(e))
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (429, 503):
                print(f"Skipping {model} (overloaded/rate-limited): {e}")
                errors.append(str(e))
                continue
            raise

    if raw_output is None:
        raise RuntimeError(f"No working Gemini model found among candidates. Errors: {errors}")

    updated_tex = strip_code_fences(raw_output)

    if not updated_tex.strip().startswith("\\documentclass"):
        print("Model output did not look like a valid .tex file; skipping update.", file=sys.stderr)
        print(updated_tex[:2000], file=sys.stderr)
        sys.exit(1)

    updated_tex = updated_tex.strip() + "\n"
    changed = updated_tex != current_tex.strip() + "\n"

    if changed:
        known_repo_urls = {r["url"].rstrip("/") for r in repo_summaries}
        problems = validate_structure(current_tex, updated_tex, user, known_repo_urls)
        if problems:
            print("Rejecting model output — it broke a hard rule:", file=sys.stderr)
            for p in problems:
                print(f"  - {p}", file=sys.stderr)
            print("Leaving the resume unchanged for this run.", file=sys.stderr)
            sys.exit(1)

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
