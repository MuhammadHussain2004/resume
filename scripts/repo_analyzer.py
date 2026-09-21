"""Deterministic GitHub repository analysis for resume project ranking."""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import quote

import requests


EXCLUDE_KEYWORDS = re.compile(
    r"\b(learning|practice|tutorial|training|exercise|coursework|assignment|tasks?)\b",
    re.IGNORECASE,
)

MANIFEST_NAMES = {
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "pipfile",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "composer.json",
    "gemfile",
    "go.mod",
    "cargo.toml",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "schema.prisma",
}

SOURCE_EXTENSIONS = {
    ".js", ".jsx", ".ts", ".tsx", ".py", ".java", ".kt", ".kts",
    ".cs", ".cpp", ".cc", ".c", ".h", ".hpp", ".go", ".rs", ".rb",
    ".php", ".vue", ".svelte", ".html", ".css", ".scss", ".sql",
}

CODE_EVIDENCE_EXTENSIONS = {
    ".js", ".jsx", ".ts", ".tsx", ".py", ".java", ".kt", ".kts",
    ".cs", ".cpp", ".cc", ".c", ".go", ".rs", ".rb", ".php", ".vue",
    ".svelte", ".sql",
}

TECHNOLOGIES = {
    "React": ("react", "react-dom"),
    "Next.js": ("next", "nextjs", "next.js"),
    "Vue": ("vue", "nuxt"),
    "Angular": ("@angular/core", "angular"),
    "Svelte": ("svelte", "sveltekit"),
    "Vite": ("vite",),
    "Tailwind CSS": ("tailwindcss", "tailwind css"),
    "Redux Toolkit": ("@reduxjs/toolkit", "redux toolkit"),
    "TypeScript": ("typescript", ".ts ", ".tsx "),
    "Node.js": ("node.js", "nodejs", "node "),
    "Express": ("express",),
    "NestJS": ("@nestjs/core", "nestjs"),
    "FastAPI": ("fastapi",),
    "Django": ("django",),
    "Flask": ("flask",),
    "Spring Boot": ("spring-boot", "spring boot"),
    "ASP.NET": ("asp.net", "microsoft.aspnetcore"),
    "MongoDB": ("mongodb", "mongo db"),
    "Mongoose": ("mongoose",),
    "PostgreSQL": ("postgresql", "postgres", "\"pg\""),
    "MySQL": ("mysql", "mysql2"),
    "SQLite": ("sqlite", "better-sqlite3"),
    "Turso/libSQL": ("turso", "libsql", "@libsql/client"),
    "Prisma": ("prisma", "schema.prisma"),
    "Sequelize": ("sequelize",),
    "Firebase": ("firebase", "firestore"),
    "Supabase": ("supabase",),
    "JWT": ("jsonwebtoken", "jwt", "jose"),
    "OAuth": ("oauth", "next-auth", "auth.js", "passport"),
    "Jest": ("jest",),
    "Vitest": ("vitest",),
    "Playwright": ("playwright",),
    "Cypress": ("cypress",),
    "Pytest": ("pytest",),
    "Docker": ("dockerfile", "docker-compose", "compose.yml"),
    "GitHub Actions": (".github/workflows/",),
    "GraphQL": ("graphql",),
    "Socket.IO": ("socket.io", "socketio", "websocket"),
    "Zod": ("zod",),
    "Stripe": ("stripe",),
}

FRONTEND_TECH = {"React", "Next.js", "Vue", "Angular", "Svelte"}
BACKEND_TECH = {"Node.js", "Express", "NestJS", "FastAPI", "Django", "Flask", "Spring Boot", "ASP.NET"}
DATABASE_TECH = {
    "MongoDB", "Mongoose", "PostgreSQL", "MySQL", "SQLite", "Turso/libSQL",
    "Prisma", "Sequelize", "Firebase", "Supabase",
}
AUTH_TECH = {"JWT", "OAuth"}
TEST_TECH = {"Jest", "Vitest", "Playwright", "Cypress", "Pytest"}

FEATURE_DOMAINS = {
    "administration": ("admin", "dashboard"),
    "analytics": ("analytics", "reporting", "statistics"),
    "catalog/commerce": ("catalog", "product", "cart", "checkout", "order"),
    "payments/subscriptions": ("payment", "stripe", "subscription", "billing"),
    "recommendation engine": ("recommend", "compatibility engine", "suggestion"),
    "uploads/imports": ("upload", "import", "csv", "excel"),
    "email/notifications": ("email", "notification", "resend"),
    "reviews/feedback": ("review", "testimonial", "feedback"),
    "search/filtering": ("search", "filter", "pagination"),
    "workflow/state machine": ("workflow", "complaint", "ticket", "status"),
    "roles/permissions": ("role-based", "rbac", "permission", "admin-only"),
    "third-party integration": ("plugin", "woocommerce", "webhook", "integration"),
    "content/data management": ("notes", "records", "content management"),
}


def _contains_any(text: str, terms: tuple[str, ...] | list[str]) -> bool:
    return any(term in text for term in terms)


def _path_has(paths: list[str], patterns: tuple[str, ...]) -> bool:
    return any(any(pattern in path for pattern in patterns) for path in paths)


def select_code_evidence_paths(tree_entries, limit=14):
    """Choose representative implementation files for grounded resume writing."""
    candidates = []
    for entry in tree_entries:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        lower = path.lower()
        if not any(lower.endswith(ext) for ext in CODE_EVIDENCE_EXTENSIONS):
            continue
        if any(
            excluded in lower
            for excluded in (
                "node_modules/", "vendor/", "dist/", "build/", "coverage/",
                ".min.js", ".bundle.js", "package-lock", "generated/",
            )
        ):
            continue
        if int(entry.get("size") or 0) > 150_000:
            continue

        score = 0
        if _contains_any(lower, ("controller", "service", "model", "schema", "middleware")):
            score += 10
        if _contains_any(
            lower,
            ("route", "database", "server", "api/", "auth", "payment", "analytics", "recommend", "upload", "order", "product", "complaint"),
        ):
            score += 8
        if _contains_any(lower, ("app.", "index.", "main.", "config", "client")):
            score += 5
        if _contains_any(lower, ("pages/", "components/", "hooks/", "store/")):
            score += 3
        if re.search(r"(^|/)(test|tests|__tests__|spec)(/|$)|\.(test|spec)\.", lower):
            score += 2
        depth = lower.count("/")
        candidates.append((score, -depth, -len(lower), path))

    candidates.sort(reverse=True)
    return [item[3] for item in candidates[:limit]]


def _redact_sensitive_assignments(text):
    """Keep code useful to Gemini without forwarding obvious credential values."""
    return re.sub(
        r"(?im)^([^\n]*(?:api[_-]?key|client[_-]?secret|password|access[_-]?token)[^:=\n]*[:=]\s*)[^\s,;]+",
        r"\1<redacted>",
        text,
    )


def _recency_points(pushed_at: str | None) -> int:
    if not pushed_at:
        return 0
    try:
        pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - pushed).days
        return 3 if days < 90 else 2 if days < 365 else 1 if days < 730 else 0
    except ValueError:
        return 0


def analyze_repository(repo, tree_entries, readme, manifest_texts, languages):
    """Analyze a repository from its complete tree and high-value code manifests."""
    paths = [entry.get("path", "").lower() for entry in tree_entries if entry.get("type") == "blob"]
    source_files = sum(1 for path in paths if any(path.endswith(ext) for ext in SOURCE_EXTENSIONS))
    test_files = sum(
        1 for path in paths
        if re.search(r"(^|/)(__tests__|tests?|specs?)(/|$)", path)
        or re.search(r"(\.test|\.spec|_test)\.[a-z0-9]+$", path)
    )

    code_searchable = "\n".join(
        [
            repo.get("name", ""),
            repo.get("description") or "",
            " ".join(repo.get("topics") or []),
            " ".join(languages.keys() if isinstance(languages, dict) else languages),
            "\n".join(paths),
            "\n".join(manifest_texts.values()),
        ]
    ).lower()
    feature_searchable = f"{code_searchable}\n{readme.lower()}"

    technologies = sorted(
        label for label, aliases in TECHNOLOGIES.items() if _contains_any(code_searchable, aliases)
    )
    technology_set = set(technologies)

    static_web_ui = (
        any(path.endswith(".html") for path in paths)
        and any(path.endswith(".css") for path in paths)
        and any(
            path.endswith((".js", ".jsx", ".ts", ".tsx"))
            and not path.startswith(("server/", "backend/", "api/"))
            for path in paths
        )
    )
    frontend = bool(technology_set & FRONTEND_TECH) or static_web_ui or _path_has(
        paths, ("frontend/", "client/", "dashboard/", "widget/", "src/components/", "src/pages/", "src/app/")
    )
    backend = bool(technology_set & BACKEND_TECH) or _path_has(
        paths, ("backend/", "server/", "api/", "controllers/", "routes/", "manage.py")
    )
    database = bool(technology_set & DATABASE_TECH) or _path_has(
        paths, ("schema.prisma", "models/", "migrations/", ".sql")
    )
    auth = bool(technology_set & AUTH_TECH) or _contains_any(
        code_searchable, ("authentication", "authorization", "protected route", "role-based", "rbac", "bcrypt")
    )
    api = backend and (
        _path_has(paths, ("api/", "routes/", "controllers/", "graphql"))
        or _contains_any(code_searchable, ("rest api", "restful", "graphql", "endpoint"))
    )
    testing = bool(technology_set & TEST_TECH) or test_files > 0
    deployment = bool(repo.get("homepage")) or _path_has(
        paths, ("vercel.json", "netlify.toml", "render.yaml", "fly.toml", "railway.json")
    )
    containerized = "Docker" in technology_set
    ci_cd = "GitHub Actions" in technology_set
    security = _contains_any(
        code_searchable, ("helmet", "cors", "rate-limit", "rate limit", "csrf", "zod", "joi", "validation")
    )
    realtime = "Socket.IO" in technology_set
    state_management = _contains_any(code_searchable, ("@reduxjs/toolkit", "redux toolkit", "zustand", "react-query", "tanstack"))
    split_architecture = frontend and backend and _path_has(
        paths, ("frontend/", "client/", "backend/", "server/", "api/")
    )
    full_stack = frontend and backend and database
    feature_domains = sorted(
        label for label, terms in FEATURE_DOMAINS.items() if _contains_any(feature_searchable, terms)
    )

    capabilities = [
        label
        for present, label in (
            (frontend, "frontend"),
            (backend, "backend"),
            (database, "database"),
            (api, "API layer"),
            (auth, "authentication/authorization"),
            (testing, "automated testing"),
            (deployment, "deployment"),
            (containerized, "containerization"),
            (ci_cd, "CI/CD"),
            (security, "security/validation"),
            (realtime, "real-time features"),
            (state_management, "state/data management"),
            (split_architecture, "separated frontend/backend architecture"),
        )
        if present
    ]

    substance = 10 if source_files >= 90 else 8 if source_files >= 60 else 6 if source_files >= 30 else 4 if source_files >= 15 else 2 if source_files >= 5 else 1 if source_files >= 3 else 0
    feature_breadth = min(len(feature_domains) * 2, 12)
    score = (
        (12 if frontend else 0)
        + (12 if backend else 0)
        + (10 if database else 0)
        + (18 if full_stack else 0)
        + (5 if auth else 0)
        + (4 if api else 0)
        + (4 if testing else 0)
        + (4 if deployment else 0)
        + (3 if containerized else 0)
        + (3 if ci_cd else 0)
        + (3 if split_architecture else 0)
        + (2 if security else 0)
        + (2 if realtime else 0)
        + (2 if state_management else 0)
        + (2 if "TypeScript" in technology_set else 0)
        + substance
        + feature_breadth
        + _recency_points(repo.get("pushed_at"))
        + (1 if readme.strip() else 0)
        + min(int(repo.get("stargazers_count", 0)), 2)
    )

    trivial = bool(EXCLUDE_KEYWORDS.search(f"{repo.get('name', '')} {repo.get('description') or ''}"))
    eligible = not repo.get("fork") and not repo.get("archived") and not trivial and source_files >= 3
    if trivial:
        score -= 40

    evidence_files = [
        path for path in paths
        if path.rsplit("/", 1)[-1] in MANIFEST_NAMES
        or path.startswith(".github/workflows/")
    ][:20]

    return {
        "score": score,
        "full_stack": full_stack,
        "eligible": eligible,
        "capabilities": capabilities,
        "feature_domains": feature_domains,
        "technologies": technologies,
        "source_file_count": source_files,
        "test_file_count": test_files,
        "evidence_files": evidence_files,
    }


def _decode_content(payload):
    content = payload.get("content") if isinstance(payload, dict) else None
    if not content:
        return ""
    return base64.b64decode(content).decode("utf-8", errors="ignore")


def _fetch_text(gh_get, repo_name, path):
    payload = gh_get(
        f"/repos/{{owner}}/{quote(repo_name, safe='')}/contents/{quote(path, safe='/')}"
    )
    return _decode_content(payload)


def analyze_github_repositories(gh_get, username, max_projects=3):
    """Fetch every public owned repo, analyze it, and return ranked summaries."""
    repos = []
    page = 1
    while True:
        batch = gh_get(
            f"/users/{username}/repos",
            params={"per_page": 100, "page": page, "sort": "pushed", "direction": "desc", "type": "owner"},
        )
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    owned_repos = [
        repo for repo in repos
        if not repo.get("fork") and repo.get("name", "").lower() != username.lower()
    ]
    known_repo_urls = {repo["html_url"].rstrip("/") for repo in owned_repos}
    summaries = []
    repo_artifacts = {}

    for repo in owned_repos:
        name = repo["name"]
        print(f"Analyzing repository code: {name}")
        readme = ""
        languages = {}
        tree_entries = []
        tree_complete = False

        try:
            readme = _decode_content(gh_get(f"/repos/{username}/{quote(name, safe='')}/readme"))
        except Exception:
            pass
        languages = gh_get(f"/repos/{username}/{quote(name, safe='')}/languages")
        if int(repo.get("size") or 0) == 0:
            tree_complete = True
        else:
            branch = quote(repo.get("default_branch") or "main", safe="")
            tree = gh_get(f"/repos/{username}/{quote(name, safe='')}/git/trees/{branch}", params={"recursive": "1"})
            tree_entries = tree.get("tree", [])
            tree_complete = not tree.get("truncated", False)
            if not tree_complete:
                raise RuntimeError(
                    f"GitHub truncated the recursive tree for {name}; refusing a partial ranking."
                )

        manifest_paths = [
            entry.get("path", "")
            for entry in tree_entries
            if entry.get("type") == "blob"
            and (
                entry.get("path", "").lower().rsplit("/", 1)[-1] in MANIFEST_NAMES
                or entry.get("path", "").lower().startswith(".github/workflows/")
            )
        ][:30]
        manifest_texts = {
            path: _fetch_text(
                lambda api_path, params=None: gh_get(api_path.replace("{owner}", username), params=params),
                name,
                path,
            )[:100_000]
            for path in manifest_paths
        }

        analysis = analyze_repository(repo, tree_entries, readme, manifest_texts, languages)
        summary = {
            "name": name,
            "description": repo.get("description") or "",
            "url": repo["html_url"],
            "homepage": repo.get("homepage") or "",
            "topics": repo.get("topics") or [],
            "languages": list(languages.keys()),
            "stars": repo.get("stargazers_count", 0),
            "pushed_at": repo.get("pushed_at"),
            "created_at": repo.get("created_at"),
            "tree_scan_complete": tree_complete,
            "readme_excerpt": readme[:2500],
            **analysis,
        }
        summaries.append(summary)
        repo_artifacts[repo["html_url"].rstrip("/")] = {
            "tree_entries": tree_entries,
            "manifest_texts": manifest_texts,
        }
        print(
            f"  score={analysis['score']} full_stack={analysis['full_stack']} "
            f"source_files={analysis['source_file_count']} capabilities={analysis['capabilities']}"
        )

    ranked = sorted(
        (summary for summary in summaries if summary["eligible"]),
        key=lambda item: (
            item["full_stack"],
            item["score"],
            item["source_file_count"],
            item.get("pushed_at") or "",
        ),
        reverse=True,
    )
    selected = ranked[:max_projects]
    selected_urls = {item["url"].rstrip("/") for item in selected}
    selected_rank = {item["url"].rstrip("/"): rank for rank, item in enumerate(selected, 1)}
    overall_rank = {
        item["url"].rstrip("/"): rank for rank, item in enumerate(ranked, 1)
    }

    for summary in summaries:
        normalized_url = summary["url"].rstrip("/")
        summary["resume_rank"] = selected_rank.get(normalized_url)
        summary["overall_rank"] = overall_rank.get(normalized_url)
        if summary["overall_rank"] is None or summary["overall_rank"] > 6:
            continue

        artifacts = repo_artifacts[normalized_url]
        evidence_paths = select_code_evidence_paths(artifacts["tree_entries"])
        code_evidence = []
        evidence_chars = 0
        for path in evidence_paths:
            content = _fetch_text(
                lambda api_path, params=None: gh_get(api_path.replace("{owner}", username), params=params),
                summary["name"],
                path,
            )
            if not content.strip():
                continue
            excerpt = _redact_sensitive_assignments(content[:3500])
            remaining = 24_000 - evidence_chars
            if remaining <= 0:
                break
            excerpt = excerpt[:remaining]
            code_evidence.append({"path": path, "excerpt": excerpt})
            evidence_chars += len(excerpt)

        manifest_evidence = {}
        manifest_chars = 0
        for path, content in artifacts["manifest_texts"].items():
            if not content.strip():
                continue
            remaining = 15_000 - manifest_chars
            if remaining <= 0:
                break
            excerpt = _redact_sensitive_assignments(content[: min(5000, remaining)])
            manifest_evidence[path] = excerpt
            manifest_chars += len(excerpt)
        summary["dependency_manifest_evidence"] = manifest_evidence
        summary["code_evidence"] = code_evidence

    summaries.sort(
        key=lambda item: (
            item["overall_rank"] is not None,
            -(item["overall_rank"] or 9999),
            item["full_stack"],
            item["score"],
            item.get("pushed_at") or "",
        ),
        reverse=True,
    )
    return summaries, known_repo_urls, selected_urls


def main():
    """Print a live ranking for diagnostics without contacting Gemini."""
    username = os.environ.get("GITHUB_USERNAME", "MuhammadHussain2004")
    token = os.environ.get("GH_READ_TOKEN")
    if not token:
        print("GH_READ_TOKEN is required for a live ranking audit.", file=sys.stderr)
        return 1

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    def api_get(path, params=None):
        response = requests.get(
            f"https://api.github.com{path}", headers=headers, params=params, timeout=30
        )
        response.raise_for_status()
        return response.json()

    summaries, _, selected_urls = analyze_github_repositories(api_get, username)
    selected = [item for item in summaries if item["url"].rstrip("/") in selected_urls]
    selected.sort(key=lambda item: item["resume_rank"])
    print("\nSelected resume projects:")
    print(
        json.dumps(
            [
                {
                    "rank": item["resume_rank"],
                    "name": item["name"],
                    "score": item["score"],
                    "full_stack": item["full_stack"],
                    "capabilities": item["capabilities"],
                    "technologies": item["technologies"],
                }
                for item in selected
            ],
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
