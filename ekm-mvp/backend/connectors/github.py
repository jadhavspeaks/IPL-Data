"""
GitHub Connector
─────────────────
Crawls GitHub repositories via Personal Access Token (PAT).

Per repository, fetches:
  - Recent commits (message, author, date, files changed, diff summary)
  - Code files (README, key source files with content)
  - Pull requests (title, description, linked issues)

Cross-linking:
  - Extracts Jira ticket refs from commit messages → links to Jira issues
  - Extracts commit SHAs from Jira content → links back to GitHub

Config (.env):
  GITHUB_TOKEN=ghp_xxxxxxxxxxxx
  GITHUB_REPOS=org/repo1,org/repo2      # specific repos
  GITHUB_ORG=your-org                   # OR crawl all repos in an org
  GITHUB_MAX_COMMITS=200                # commits per repo (default 200)
"""

import os
import logging
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from datetime import datetime, timezone
from config import get_settings
from models import Document, SourceType
from utils.extractor import extract_from_document

logger   = logging.getLogger(__name__)
settings = get_settings()

# Set dynamically from settings — supports both github.com and GitHub Enterprise
GITHUB_API = None  # resolved in _api_base()
REQUEST_TIMEOUT = 30
MAX_DIFF_CHARS  = 3000   # truncate large diffs
MAX_FILE_CHARS  = 8000   # truncate large source files


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _api_base() -> str:
    """
    Returns the correct API base URL.
    GitHub Enterprise: https://your-host/api/v3
    GitHub.com:        https://api.github.com
    """
    host = settings.github_host.strip().rstrip("/")
    if host and host != "github.com":
        return f"https://{host}/api/v3"
    return "https://api.github.com"


def _headers() -> dict:
    token = settings.github_token
    h = {"Accept": "application/vnd.github+json"}
    # X-GitHub-Api-Version header only for github.com, not GHE
    if not settings.github_host or settings.github_host == "github.com":
        h["X-GitHub-Api-Version"] = "2022-11-28"
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _proxies() -> dict | None:
    """Build proxy dict for requests — reads from env vars."""
    proxy = (
        os.environ.get("HTTPS_PROXY") or
        os.environ.get("https_proxy") or
        os.environ.get("HTTP_PROXY") or
        os.environ.get("http_proxy")
    )
    if proxy:
        logger.debug(f"GitHub: using proxy {proxy}")
        return {"http": proxy, "https": proxy}
    return None


def _get(url: str, params: dict = None) -> dict | list | None:
    try:
        resp = requests.get(
            url, headers=_headers(), params=params,
            timeout=REQUEST_TIMEOUT, verify=False,
            proxies=_proxies(),
        )
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 403:
            logger.warning("GitHub rate limit hit — add GITHUB_TOKEN to .env for higher limits")
        else:
            logger.warning(f"GitHub {resp.status_code}: {url}")
        return None
    except Exception as e:
        logger.warning(f"GitHub request error: {e}")
        return None


def _get_paginated(url: str, params: dict = None, max_items: int = 500) -> list:
    """Fetch all pages of a paginated GitHub endpoint."""
    items  = []
    params = params or {}
    params["per_page"] = 100
    page   = 1

    while len(items) < max_items:
        params["page"] = page
        data = _get(url, params)
        if not data or not isinstance(data, list) or not data:
            break
        items.extend(data)
        if len(data) < 100:
            break
        page += 1

    return items[:max_items]


# ── Repo list ─────────────────────────────────────────────────────────────────

def _get_repos() -> list[str]:
    """
    Return list of 'owner/repo' strings to crawl.
    Uses GITHUB_REPOS if set, otherwise discovers from GITHUB_ORG.
    """
    repos = settings.github_repo_list
    if repos:
        return repos

    org = settings.github_org
    if org:
        data = _get_paginated(f"{_api_base()}/orgs/{org}/repos", {"type": "all"})
        return [r["full_name"] for r in data if not r.get("archived")]

    logger.warning("No GitHub repos configured. Set GITHUB_REPOS or GITHUB_ORG in .env")
    return []


# ── Commits ───────────────────────────────────────────────────────────────────

def _fetch_commit_detail(full_name: str, sha: str) -> dict | None:
    """Fetch full commit detail including file diffs."""
    return _get(f"{_api_base()}/repos/{full_name}/commits/{sha}")


def _build_diff_summary(files: list[dict]) -> str:
    """Build a readable summary of changed files and their diffs."""
    parts = []
    total_chars = 0

    for f in files:
        filename = f.get("filename", "")
        status   = f.get("status", "")      # added/modified/removed/renamed
        additions = f.get("additions", 0)
        deletions = f.get("deletions", 0)
        patch     = f.get("patch", "")

        header = f"[{status.upper()}] {filename} (+{additions} -{deletions})"
        parts.append(header)

        if patch and total_chars < MAX_DIFF_CHARS:
            remaining = MAX_DIFF_CHARS - total_chars
            parts.append(patch[:remaining])
            total_chars += min(len(patch), remaining)

    return "\n".join(parts)


def _process_commits(
    full_name: str,
    updated_since: datetime | None,
    max_commits: int,
) -> list[Document]:
    """Fetch and process commits for a repo."""
    repo_short = full_name.split("/")[-1]
    documents  = []

    params = {"per_page": 100}
    if updated_since:
        params["since"] = updated_since.strftime("%Y-%m-%dT%H:%M:%SZ")

    commits = _get_paginated(
        f"{_api_base()}/repos/{full_name}/commits",
        params,
        max_items=max_commits,
    )

    logger.info(f"GitHub '{repo_short}': {len(commits)} commits to process")

    for i, commit_ref in enumerate(commits):
        sha     = commit_ref.get("sha", "")
        c       = commit_ref.get("commit", {})
        message = c.get("message", "")
        author  = c.get("author", {})
        name    = author.get("name", "")
        date    = author.get("date", "")

        # Get full diff for this commit
        detail     = _fetch_commit_detail(full_name, sha)
        files      = detail.get("files", []) if detail else []
        diff_text  = _build_diff_summary(files)
        file_names = [f.get("filename", "") for f in files]

        # Build rich content for search indexing
        content_parts = [
            f"Commit: {sha[:12]}",
            f"Author: {name}",
            f"Date: {date}",
            f"Message: {message}",
            f"Files changed: {', '.join(file_names[:20])}",
        ]
        if diff_text:
            content_parts.append(f"\nDiff:\n{diff_text}")

        content = "\n".join(content_parts)

        # Parse date
        updated_at = None
        if date:
            try:
                updated_at = datetime.fromisoformat(date.replace("Z", "+00:00"))
            except Exception:
                pass

        # Stats
        stats    = detail.get("stats", {}) if detail else {}
        html_url = commit_ref.get("html_url", f"https://{settings.github_host or 'github.com'}/{full_name}/commit/{sha}")

        doc = Document(
            external_id = f"{full_name}/commit/{sha}",
            source_type = SourceType.GITHUB,
            source      = f"GitHub / {full_name}",
            title       = f"{message[:120]} ({sha[:8]})",
            content     = content,
            url         = html_url,
            author      = name or None,
            tags        = ["github", "commit", repo_short],
            metadata    = {
                "content_type":  "commit",
                "repo":          full_name,
                "sha":           sha,
                "short_sha":     sha[:8],
                "message":       message,
                "files_changed": file_names[:30],
                "additions":     stats.get("additions", 0),
                "deletions":     stats.get("deletions", 0),
                "total_changes": stats.get("total", 0),
                "author_name":   name,
                "author_date":   date,
            },
            updated_at = updated_at,
        )
        documents.append(doc)

        if (i + 1) % 50 == 0:
            logger.info(f"GitHub '{repo_short}': {i + 1}/{len(commits)} commits processed")

    return documents


# ── Code files ────────────────────────────────────────────────────────────────

CRAWL_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rb",
    ".cs", ".cpp", ".c", ".h", ".scala", ".kt", ".swift",
    ".md", ".txt", ".yaml", ".yml", ".json", ".xml", ".sql",
    ".sh", ".bat", ".dockerfile",
}

SKIP_PATHS = {
    "node_modules", ".git", "vendor", "dist", "build",
    "__pycache__", ".idea", ".vscode", "coverage",
}

MAX_FILES_PER_REPO = 300


def _fetch_file_content(full_name: str, path: str) -> str:
    """Fetch decoded content of a file."""
    data = _get(f"{_api_base()}/repos/{full_name}/contents/{path}")
    if not data or isinstance(data, list):
        return ""
    try:
        import base64
        encoded = data.get("content", "").replace("\n", "")
        return base64.b64decode(encoded).decode("utf-8", errors="ignore")[:MAX_FILE_CHARS]
    except Exception:
        return ""


def _process_files(full_name: str) -> list[Document]:
    """Fetch key source files from repo default branch."""
    repo_short = full_name.split("/")[-1]
    documents  = []

    # Get repo tree (full recursive listing)
    repo_data = _get(f"{_api_base()}/repos/{full_name}")
    if not repo_data:
        return []
    branch = repo_data.get("default_branch", "main")

    tree_data = _get(
        f"{_api_base()}/repos/{full_name}/git/trees/{branch}",
        {"recursive": "1"}
    )
    if not tree_data:
        return []

    tree = tree_data.get("tree", [])

    # Filter to supported files, skip system paths
    candidate_files = []
    for item in tree:
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")

        # Skip if any path component is in skip list
        parts = path.replace("\\", "/").split("/")
        if any(p in SKIP_PATHS for p in parts):
            continue

        # Check extension
        ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext not in CRAWL_EXTENSIONS:
            continue

        candidate_files.append(path)

    # Prioritise: README first, then source files, cap total
    readme_files = [f for f in candidate_files if "readme" in f.lower()]
    other_files  = [f for f in candidate_files if "readme" not in f.lower()]
    ordered      = readme_files + other_files
    ordered      = ordered[:MAX_FILES_PER_REPO]

    logger.info(f"GitHub '{repo_short}': {len(ordered)} files to index")

    for path in ordered:
        content = _fetch_file_content(full_name, path)
        if not content:
            continue

        filename = path.split("/")[-1]
        ext      = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        doc = Document(
            external_id = f"{full_name}/blob/{path}",
            source_type = SourceType.GITHUB,
            source      = f"GitHub / {full_name}",
            title       = f"{path}",
            content     = content,
            url         = f"https://{settings.github_host or 'github.com'}/{full_name}/blob/{branch}/{path}",
            author      = None,
            tags        = ["github", "code", repo_short, ext.lstrip(".")],
            metadata    = {
                "content_type": "file",
                "repo":         full_name,
                "path":         path,
                "filename":     filename,
                "extension":    ext,
                "branch":       branch,
            },
            updated_at  = None,
        )
        documents.append(doc)

    return documents


# ── Pull Requests ─────────────────────────────────────────────────────────────

def _process_pull_requests(
    full_name: str,
    updated_since: datetime | None,
) -> list[Document]:
    """Fetch merged pull requests."""
    repo_short = full_name.split("/")[-1]
    documents  = []

    prs = _get_paginated(
        f"{_api_base()}/repos/{full_name}/pulls",
        {"state": "closed", "sort": "updated", "direction": "desc"},
        max_items=100,
    )

    for pr in prs:
        if not pr.get("merged_at"):
            continue   # skip unmerged PRs

        merged_at = None
        if pr.get("merged_at"):
            try:
                merged_at = datetime.fromisoformat(
                    pr["merged_at"].replace("Z", "+00:00")
                )
                if updated_since and merged_at <= updated_since:
                    continue
            except Exception:
                pass

        title    = pr.get("title", "")
        body     = pr.get("body") or ""
        number   = pr.get("number", "")
        author   = (pr.get("user") or {}).get("login", "")

        content = "\n".join(filter(None, [
            f"PR #{number}: {title}",
            f"Author: {author}",
            f"Merged: {pr.get('merged_at','')}",
            body[:3000],
        ]))

        doc = Document(
            external_id = f"{full_name}/pull/{number}",
            source_type = SourceType.GITHUB,
            source      = f"GitHub / {full_name}",
            title       = f"PR #{number}: {title}",
            content     = content,
            url         = pr.get("html_url", ""),
            author      = author or None,
            tags        = ["github", "pull_request", repo_short],
            metadata    = {
                "content_type": "pull_request",
                "repo":         full_name,
                "number":       number,
                "state":        "merged",
                "merged_at":    pr.get("merged_at"),
            },
            updated_at  = merged_at,
        )
        documents.append(doc)

    logger.info(f"GitHub '{repo_short}': {len(documents)} merged PRs")
    return documents


# ── Main ──────────────────────────────────────────────────────────────────────

async def fetch_documents(updated_since: datetime | None = None) -> list[Document]:
    """
    Fetch commits, code files, and PRs from all configured GitHub repos.
    """
    repos = _get_repos()
    if not repos:
        return []

    max_commits = settings.github_max_commits
    mode        = "incremental" if updated_since else "full"
    logger.info(f"GitHub: {mode} sync — {len(repos)} repo(s)")

    all_documents: list[Document] = []

    for full_name in repos:
        logger.info(f"GitHub: processing '{full_name}'...")

        # Verify repo is accessible
        repo_data = _get(f"{_api_base()}/repos/{full_name}")
        if not repo_data:
            logger.warning(f"GitHub: cannot access '{full_name}' — check token/permissions")
            continue

        repo_count = 0

        # 1. Commits
        try:
            commits = _process_commits(full_name, updated_since, max_commits)
            all_documents.extend(commits)
            repo_count += len(commits)
        except Exception as e:
            logger.error(f"GitHub commits error '{full_name}': {e}")

        # 2. Source files (full sync only — files don't have easy incremental)
        if not updated_since:
            try:
                files = _process_files(full_name)
                all_documents.extend(files)
                repo_count += len(files)
            except Exception as e:
                logger.error(f"GitHub files error '{full_name}': {e}")

        # 3. Pull requests
        try:
            prs = _process_pull_requests(full_name, updated_since)
            all_documents.extend(prs)
            repo_count += len(prs)
        except Exception as e:
            logger.error(f"GitHub PRs error '{full_name}': {e}")

        logger.info(f"GitHub '{full_name}': done — {repo_count} total documents")

    logger.info(f"GitHub: TOTAL {len(all_documents)} documents")
    return all_documents
