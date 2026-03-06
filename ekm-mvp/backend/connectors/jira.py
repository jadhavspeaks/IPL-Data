"""
Jira Connector — with timeout + progress logging
"""

import logging
import urllib3
from datetime import datetime, timezone
from atlassian import Jira
from config import get_settings
from models import Document, SourceType

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_ISSUES_PER_PROJECT = 2000
REQUEST_TIMEOUT = 30


def _get_client() -> Jira | None:
    if not all([settings.jira_url, settings.jira_api_token]):
        logger.warning("Jira credentials not configured — skipping")
        return None
    return Jira(
        url=settings.jira_url,
        token=settings.jira_api_token,
        cloud=False,
        verify_ssl=False,
        timeout=REQUEST_TIMEOUT,
    )


def _safe_get(d, *keys, default=""):
    val = d
    for key in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(key)
        if val is None:
            return default
    return val or default


def _adf_to_text(adf) -> str:
    if isinstance(adf, str):
        return adf
    texts = []
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                texts.append(node.get("text", ""))
            for child in node.get("content", []):
                walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(adf)
    return " ".join(texts)


def _extract_comments(issue: dict) -> str:
    comments = _safe_get(issue, "fields", "comment", "comments") or []
    if not isinstance(comments, list):
        return ""
    parts = []
    for c in comments:
        if not isinstance(c, dict):
            continue
        body = c.get("body", "")
        author = _safe_get(c, "author", "displayName") or "Unknown"
        if isinstance(body, dict):
            body = _adf_to_text(body)
        if body:
            parts.append(f"[{author}]: {body}")
    return "\n".join(parts)


async def fetch_documents(updated_since: datetime | None = None) -> list[Document]:
    client = _get_client()
    if not client:
        return []

    projects = settings.jira_project_list
    if not projects:
        try:
            all_projects = client.projects()
            projects = [p["key"] for p in (all_projects or [])[:20]]
        except Exception as e:
            logger.error(f"Could not list Jira projects: {e}")
            return []

    mode = "incremental" if updated_since else "full"
    since_str = updated_since.strftime("%Y-%m-%d") if updated_since else None
    logger.info(f"Jira: {mode} sync across {len(projects)} projects")

    documents = []

    for proj_idx, project_key in enumerate(projects):
        try:
            start = 0
            limit = 100
            project_count = 0

            while project_count < MAX_ISSUES_PER_PROJECT:
                jql = (
                    f'project = {project_key} AND updated >= "{since_str}" ORDER BY updated DESC'
                    if updated_since else
                    f'project = {project_key} ORDER BY updated DESC'
                )

                try:
                    result = client.jql(
                        jql, start=start, limit=limit,
                        fields=[
                            "summary", "description", "issuetype", "status",
                            "priority", "assignee", "reporter", "labels",
                            "comment", "created", "updated", "components",
                            "fixVersions", "resolution", "resolutiondate",
                        ],
                    )
                except Exception as e:
                    logger.warning(f"Jira: batch fetch failed for {project_key} at start={start}: {e}")
                    break

                issues = (result or {}).get("issues", [])
                if not issues:
                    break

                for issue in issues:
                    if not isinstance(issue, dict):
                        continue
                    try:
                        fields = issue.get("fields") or {}
                        desc = fields.get("description") or ""
                        if isinstance(desc, dict):
                            desc = _adf_to_text(desc)

                        comments = _extract_comments(issue)
                        full_content = "\n\n".join(filter(None, [desc, comments]))

                        issue_type = (fields.get("issuetype")  or {}).get("name", "")
                        status     = (fields.get("status")     or {}).get("name", "")
                        priority   = (fields.get("priority")   or {}).get("name", "")
                        assignee   = (fields.get("assignee")   or {}).get("displayName", "")
                        reporter   = (fields.get("reporter")   or {}).get("displayName", "")
                        resolution = (fields.get("resolution") or {}).get("name", "")

                        labels = ["jira", project_key.lower()]
                        labels += [l for l in (fields.get("labels") or []) if isinstance(l, str)]
                        if issue_type:
                            labels.append(issue_type.lower())

                        updated_str = fields.get("updated")
                        updated_at = None
                        if updated_str:
                            try:
                                updated_at = datetime.fromisoformat(str(updated_str).replace("Z", "+00:00"))
                            except Exception:
                                pass

                        created_str = fields.get("created")
                        created_at = None
                        if created_str:
                            try:
                                created_at = datetime.fromisoformat(str(created_str).replace("Z", "+00:00"))
                            except Exception:
                                pass

                        doc = Document(
                            external_id=str(issue.get("id", "")),
                            source_type=SourceType.JIRA,
                            source=f"Jira / {project_key}",
                            title=f"[{issue.get('key','')}] {fields.get('summary','No Summary')}",
                            content=full_content,
                            url=f"{settings.jira_url.rstrip('/')}/browse/{issue.get('key','')}",
                            author=reporter,
                            tags=labels,
                            metadata={
                                "issue_key":     issue.get("key"),
                                "project":       project_key,
                                "issue_type":    issue_type,
                                "status":        status,
                                "priority":      priority,
                                "assignee":      assignee,
                                "reporter":      reporter,
                                "resolution":    resolution,
                                "created_at":    str(created_at) if created_at else None,
                                "components":    [c.get("name","") for c in (fields.get("components") or []) if isinstance(c, dict)],
                                "fix_versions":  [v.get("name","") for v in (fields.get("fixVersions") or []) if isinstance(v, dict)],
                                "comment_count": (fields.get("comment") or {}).get("total", 0),
                            },
                            updated_at=updated_at,
                        )
                        documents.append(doc)
                        project_count += 1
                    except Exception as e:
                        logger.warning(f"Jira: skipping issue {issue.get('key','?')}: {e}")
                        continue

                logger.info(f"Jira [{proj_idx+1}/{len(projects)}] {project_key}: {project_count} issues so far...")

                if len(issues) < limit:
                    break
                start += limit

            logger.info(f"Jira {project_key}: done — {project_count} issues")

        except Exception as e:
            logger.error(f"Jira error for project {project_key}: {e}")
            continue

    logger.info(f"Jira: TOTAL {len(documents)} documents")
    return documents
