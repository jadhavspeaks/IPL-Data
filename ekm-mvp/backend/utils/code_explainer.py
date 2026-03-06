"""
Code Intelligence Engine
─────────────────────────
Explains commits and code files using 4 signals — no AI, no external calls.

Signal 1 — Jira Cross-link   : commit message has PROJ-123 → fetch Jira doc → business reason
Signal 2 — PR Body           : find PR that contains this commit SHA → technical rationale
Signal 3 — Static Analysis   : parse diff for added/removed functions, endpoints, imports
Signal 4 — README/Confluence : match module/file name against docs → architectural context
"""

import re
import logging
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

# ── Signal 3: Static diff analysis ───────────────────────────────────────────

def _categorise_commit(message: str, files: list[str]) -> tuple[str, str]:
    """Returns (emoji_label, category_name)."""
    msg = message.lower()
    if any(w in msg for w in ["fix", "bug", "patch", "hotfix", "resolve", "revert"]):
        return "🐛", "Bug Fix"
    if any(w in msg for w in ["feat", "feature", "add", "new", "implement", "support"]):
        return "✨", "New Feature"
    if any(w in msg for w in ["refactor", "clean", "restructure", "simplify", "rename"]):
        return "♻️", "Refactor"
    if any(w in msg for w in ["test", "spec", "coverage"]):
        return "🧪", "Tests"
    if any(w in msg for w in ["doc", "readme", "comment", "changelog"]):
        return "📝", "Documentation"
    if any(w in msg for w in ["config", "env", "deploy", "ci", "cd", "pipeline", "docker"]):
        return "⚙️", "Config / DevOps"
    if any(w in msg for w in ["perf", "optim", "speed", "cache", "faster", "latency"]):
        return "⚡", "Performance"
    if any(w in msg for w in ["security", "auth", "vuln", "cve", "sanitize", "encrypt"]):
        return "🔒", "Security"
    if any(w in msg for w in ["merge", "rebase"]):
        return "🔀", "Merge"
    return "🔧", "General Change"


def _analyse_diff(diff_text: str, files: list[str]) -> dict:
    """
    Parse a unified diff and extract structural changes.
    Detects: new/modified/removed functions, classes, API endpoints,
    DB operations, config keys, imports added.
    """
    added_lines   = [l[1:] for l in diff_text.splitlines() if l.startswith("+") and not l.startswith("+++")]
    removed_lines = [l[1:] for l in diff_text.splitlines() if l.startswith("-") and not l.startswith("---")]

    def find_names(lines, pattern):
        names = set()
        for line in lines:
            for m in re.finditer(pattern, line):
                name = next((g for g in m.groups() if g), None)
                if name and len(name) > 1:
                    names.add(name)
        return names

    # Functions / methods
    func_pat = re.compile(
        r'\bdef\s+(\w+)\s*\(|'
        r'\bfunction\s+(\w+)\s*\(|'
        r'\b(\w+)\s*[:=]\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>)|'
        r'\bpublic\s+(?:static\s+)?(?:\w+\s+)?(\w+)\s*\(|'
        r'\bfunc\s+(\w+)\s*\('
    )
    added_funcs   = find_names(added_lines, func_pat)
    removed_funcs = find_names(removed_lines, func_pat)
    modified_funcs = added_funcs & removed_funcs
    new_funcs      = added_funcs - removed_funcs
    deleted_funcs  = removed_funcs - added_funcs

    # Classes
    class_pat    = re.compile(r'\bclass\s+(\w+)')
    new_classes  = find_names(added_lines, class_pat) - find_names(removed_lines, class_pat)

    # API endpoints (Flask/FastAPI/Express style)
    endpoint_pat  = re.compile(
        r'@\w+\.(get|post|put|patch|delete|router)\s*\(\s*[\'"]([^\'"]+)[\'"]|'
        r'router\.(get|post|put|delete)\s*\(\s*[\'"]([^\'"]+)[\'"]'
    )
    new_endpoints = set()
    for line in added_lines:
        for m in endpoint_pat.finditer(line):
            path = m.group(2) or m.group(4)
            method = (m.group(1) or m.group(3) or "").upper()
            if path:
                new_endpoints.add(f"{method} {path}" if method else path)

    # DB operations
    db_pat = re.compile(
        r'CREATE\s+TABLE\s+(\w+)|'
        r'ALTER\s+TABLE\s+(\w+)|'
        r'\.find\(|\.insert\(|\.update\(|\.delete\(|'
        r'db\.\w+\.(?:find|insert|update|delete|aggregate)',
        re.IGNORECASE
    )
    db_changes = []
    for line in added_lines:
        if db_pat.search(line):
            db_changes.append(line.strip()[:80])

    # New imports / dependencies
    import_pat   = re.compile(
        r'^import\s+([\w.]+)|'
        r'^from\s+([\w.]+)\s+import|'
        r'require\s*\(\s*[\'"]([^\'"]+)[\'"]'
    )
    new_imports = set()
    for line in added_lines:
        m = import_pat.match(line.strip())
        if m:
            dep = next((g for g in m.groups() if g), None)
            if dep:
                new_imports.add(dep.split(".")[0])

    # Config keys added
    config_pat  = re.compile(r'^([A-Z_]{3,})\s*[:=]|^[\'"]([a-z_]{3,})[\'"]\s*:')
    new_configs = set()
    for line in added_lines:
        m = config_pat.match(line.strip())
        if m:
            key = m.group(1) or m.group(2)
            if key:
                new_configs.add(key)

    # File type summary
    ext_counts: dict = {}
    for f in files:
        ext = f.rsplit(".", 1)[-1].lower() if "." in f else "other"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

    return {
        "new_functions":    sorted(new_funcs)[:15],
        "modified_functions": sorted(modified_funcs)[:15],
        "deleted_functions": sorted(deleted_funcs)[:10],
        "new_classes":      sorted(new_classes)[:10],
        "new_endpoints":    sorted(new_endpoints)[:10],
        "db_changes":       db_changes[:5],
        "new_imports":      sorted(new_imports)[:10],
        "new_configs":      sorted(new_configs)[:10],
        "file_type_summary": ext_counts,
        "lines_added":      len(added_lines),
        "lines_removed":    len(removed_lines),
    }


# ── Signal 4: README/Confluence match ────────────────────────────────────────

async def _find_architecture_docs(db: AsyncIOMotorDatabase, files: list[str], repo: str) -> list[dict]:
    """
    Search Confluence/SharePoint docs that mention the same module/component
    names as the changed files. Gives architectural context.
    """
    if not files:
        return []

    # Extract module names from file paths (strip extension, take last 2 parts)
    module_names = set()
    for f in files[:10]:
        parts = f.replace("\\", "/").split("/")
        for part in parts[-2:]:
            name = part.rsplit(".", 1)[0]
            if len(name) > 3 and name not in ("index", "main", "init", "utils", "test"):
                module_names.add(name)

    if not module_names:
        return []

    # Search for these names in Confluence/SharePoint
    query_terms = " ".join(list(module_names)[:5])
    cursor = db.documents.find(
        {
            "$text": {"$search": query_terms},
            "source_type": {"$in": ["confluence", "sharepoint"]},
        },
        {"title": 1, "url": 1, "source": 1, "source_type": 1, "content": 1}
    ).limit(4)

    docs = await cursor.to_list(length=4)
    results = []
    for doc in docs:
        content_preview = doc.get("content", "")[:200]
        results.append({
            "title":       doc.get("title", ""),
            "url":         doc.get("url", ""),
            "source":      doc.get("source", ""),
            "source_type": doc.get("source_type", ""),
            "preview":     content_preview,
        })
    return results


# ── Signal 1: Jira cross-link ─────────────────────────────────────────────────

async def _find_jira_context(db: AsyncIOMotorDatabase, text: str) -> list[dict]:
    """Find Jira tickets mentioned in the commit message/content."""
    tickets = list(set(re.findall(r'\b[A-Z][A-Z0-9]{1,9}-\d+\b', text)))
    if not tickets:
        return []

    cursor = db.documents.find(
        {
            "source_type": "jira",
            "$or": [
                {"external_id": {"$in": tickets}},
                {"entities.jira_tickets": {"$in": tickets}},
                {"title": {"$regex": "|".join(re.escape(t) for t in tickets[:5])}},
            ]
        },
        {"title": 1, "url": 1, "content": 1, "metadata": 1, "entities": 1}
    ).limit(5)

    jira_docs = await cursor.to_list(length=5)
    results   = []
    for doc in jira_docs:
        meta = doc.get("metadata", {})
        results.append({
            "ticket":      doc.get("external_id", ""),
            "title":       doc.get("title", ""),
            "url":         doc.get("url", ""),
            "status":      meta.get("status", ""),
            "priority":    meta.get("priority", ""),
            "assignee":    meta.get("assignee", ""),
            "description": doc.get("content", "")[:300],
        })
    return results


# ── Signal 2: PR context ──────────────────────────────────────────────────────

async def _find_pr_context(db: AsyncIOMotorDatabase, sha: str, repo: str) -> dict | None:
    """Find the PR that contains this commit SHA."""
    if not sha:
        return None

    doc = await db.documents.find_one(
        {
            "source_type": "github",
            "metadata.content_type": "pull_request",
            "metadata.repo": repo,
            "$or": [
                {"content": {"$regex": sha[:8]}},
                {"metadata.merge_commit_sha": sha},
            ]
        },
        {"title": 1, "url": 1, "content": 1, "metadata": 1}
    )

    if not doc:
        return None

    return {
        "title":   doc.get("title", ""),
        "url":     doc.get("url", ""),
        "number":  doc.get("metadata", {}).get("number", ""),
        "body":    doc.get("content", "")[:500],
    }


# ── File explanation ──────────────────────────────────────────────────────────

def _analyse_file(content: str, path: str, ext: str) -> dict:
    """Extract structural information from a source file."""
    lang_map = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".jsx": "React JSX", ".tsx": "React TSX", ".java": "Java",
        ".go": "Go", ".rb": "Ruby", ".cs": "C#", ".sql": "SQL",
        ".sh": "Shell Script", ".yaml": "YAML Config", ".yml": "YAML Config",
        ".json": "JSON Config", ".md": "Markdown",
    }
    language = lang_map.get(ext, ext.lstrip(".").upper() or "Unknown")

    classes = re.findall(r'(?:^|\n)\s*class\s+(\w+)', content)

    funcs = re.findall(
        r'(?:^|\n)\s*(?:async\s+)?(?:def|function)\s+(\w+)\s*[\(\[]|'
        r'(?:^|\n)\s*(?:public|private|protected)\s+(?:static\s+)?(?:\w+\s+)?(\w+)\s*\(',
        content
    )
    func_names = [f for pair in funcs for f in pair if f and f not in
                  ("__init__", "constructor", "if", "for", "while", "return")]

    imports = set()
    for m in re.finditer(
        r'import\s+([\w.]+)|from\s+([\w.]+)\s+import|require\s*\(\s*[\'"]([^\'"]+)[\'"]',
        content
    ):
        dep = next((g for g in m.groups() if g), None)
        if dep:
            imports.add(dep.split(".")[0])

    # File purpose heuristic
    p = path.lower()
    if any(x in p for x in ["test", "spec", "_test", ".test."]):
        purpose = "Test / specification file"
    elif any(x in p for x in ["model", "schema", "entity"]):
        purpose = "Data model / schema"
    elif any(x in p for x in ["route", "controller", "handler", "view"]):
        purpose = "API route / request handler"
    elif any(x in p for x in ["util", "helper", "common", "shared"]):
        purpose = "Utility / shared helpers"
    elif any(x in p for x in ["config", "setting", "constant"]):
        purpose = "Configuration / constants"
    elif any(x in p for x in ["connector", "client", "adapter", "service"]):
        purpose = "External service integration"
    elif any(x in p for x in ["readme", "changelog", "contributing"]):
        purpose = "Project documentation"
    elif any(x in p for x in ["main", "index", "app", "server", "entry"]):
        purpose = "Application entry point"
    elif any(x in p for x in ["component", "widget", "page", "layout"]):
        purpose = "UI component"
    elif any(x in p for x in ["migration", "seed"]):
        purpose = "Database migration / seed"
    elif any(x in p for x in ["middleware", "interceptor", "filter"]):
        purpose = "Middleware / request pipeline"
    else:
        purpose = f"{language} module"

    return {
        "language":    language,
        "purpose":     purpose,
        "line_count":  content.count("\n") + 1,
        "classes":     classes[:15],
        "functions":   func_names[:20],
        "imports":     sorted(imports)[:15],
    }


# ── Main explain function ─────────────────────────────────────────────────────

async def explain(db: AsyncIOMotorDatabase, doc: dict, context: str | None) -> dict:
    """
    Build a full explanation for a GitHub document using all 4 signals.
    Returns a structured dict ready to send to the frontend.
    """
    meta         = doc.get("metadata", {})
    content_type = meta.get("content_type", "")
    content      = doc.get("content", "")
    repo         = meta.get("repo", "")

    if content_type == "commit":
        message  = meta.get("message", "")
        sha      = meta.get("sha", "")
        files    = meta.get("files_changed", [])
        author   = meta.get("author_name", doc.get("author", ""))
        date     = (meta.get("author_date", "") or "")[:10]
        adds     = meta.get("additions", 0)
        dels     = meta.get("deletions", 0)

        emoji, cat = _categorise_commit(message, files)
        diff_text  = content.split("Diff:", 1)[1] if "Diff:" in content else ""
        analysis   = _analyse_diff(diff_text, files)

        # All 4 signals in parallel
        jira_docs  = await _find_jira_context(db, message + " " + content)
        pr_context = await _find_pr_context(db, sha, repo)
        arch_docs  = await _find_architecture_docs(db, files, repo)

        # Impact size
        total = adds + dels
        size  = "tiny" if total < 10 else "small" if total < 50 else \
                "medium" if total < 200 else "large" if total < 500 else "very large"

        return {
            "type":        "commit",
            "repo":        repo,
            "sha":         sha,
            "url":         doc.get("url", ""),
            "category":    f"{emoji} {cat}",
            "author":      author,
            "date":        date,
            "message":     message,
            "change_size": size,
            "stats":       {"added": adds, "removed": dels},

            # Signal 3 — static analysis
            "code_changes": {
                "new_functions":      analysis["new_functions"],
                "modified_functions": analysis["modified_functions"],
                "deleted_functions":  analysis["deleted_functions"],
                "new_classes":        analysis["new_classes"],
                "new_endpoints":      analysis["new_endpoints"],
                "db_changes":         analysis["db_changes"],
                "new_imports":        analysis["new_imports"],
                "new_configs":        analysis["new_configs"],
                "file_types":         analysis["file_type_summary"],
            },

            # Signal 1 — Jira (the WHY)
            "jira_context": jira_docs,

            # Signal 2 — PR (the HOW)
            "pr_context": pr_context,

            # Signal 4 — Architecture docs (WHERE IT FITS)
            "architecture_docs": arch_docs,

            # Extra context passed in
            "user_context": context,
        }

    else:  # file
        path   = meta.get("path", doc.get("title", ""))
        ext    = meta.get("extension", "")
        result = _analyse_file(content, path, ext)

        arch_docs = await _find_architecture_docs(db, [path], repo)
        jira_docs = await _find_jira_context(db, content[:500])

        return {
            "type":       "file",
            "repo":       repo,
            "path":       path,
            "url":        doc.get("url", ""),
            "language":   result["language"],
            "purpose":    result["purpose"],
            "line_count": result["line_count"],
            "structure": {
                "classes":   result["classes"],
                "functions": result["functions"],
                "imports":   result["imports"],
            },
            "jira_context":      jira_docs,
            "architecture_docs": arch_docs,
            "user_context":      context,
        }
