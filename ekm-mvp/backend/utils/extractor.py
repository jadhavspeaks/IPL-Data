"""
Entity Extractor
─────────────────
Extracts structured entities from document content using regex.
No AI — pure pattern matching.

Extracts:
  - Jira ticket references  (PROJ-123)
  - Change/CR numbers       (CHG-12345, CR-999)
  - Version numbers         (v1.2.3, 2.4.0)
  - Dates                   (2024-01-15, 15 Jan 2024, Jan 15 2024)
  - Environments            (production, staging, UAT, dev)
  - Build/release numbers   (build-1234, release-5.6)
"""

import re
from datetime import datetime

# ── Patterns ──────────────────────────────────────────────────────────────────

# Jira-style ticket: 2-10 uppercase letters, dash, digits  e.g. PROJ-123, C147873D-456
TICKET_RE = re.compile(r'\b([A-Z][A-Z0-9]{1,9}-\d+)\b')

# Change / CR numbers
CHANGE_RE = re.compile(
    r'\b(CHG[-_]?\d{3,8}|CR[-_]?\d{3,8}|CHANGE[-_]?\d{3,8}|RFC[-_]?\d{3,8})\b',
    re.IGNORECASE
)

# Semantic version  e.g. v1.2.3, 1.2.3, v2.0
VERSION_RE = re.compile(r'\bv?(\d{1,3}\.\d{1,3}(?:\.\d{1,4})?(?:-[a-zA-Z0-9]+)?)\b')

# ISO date  2024-01-15
ISO_DATE_RE = re.compile(r'\b(\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))\b')

# Human date  15 Jan 2024 / Jan 15, 2024 / January 15 2024
MONTHS = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
HUMAN_DATE_RE = re.compile(
    rf'\b(?:\d{{1,2}}\s+{MONTHS}[\s,]+\d{{4}}|{MONTHS}[\s]+\d{{1,2}}[\s,]+\d{{4}})\b',
    re.IGNORECASE
)

# Environments
ENV_RE = re.compile(
    r'\b(prod(?:uction)?|staging|pre[-_]?prod|uat|qa|dev(?:elopment)?|sandbox)\b',
    re.IGNORECASE
)

# Build / release label
BUILD_RE = re.compile(
    r'\b(?:build|release|deploy(?:ment)?|rollout|roll[-_]?out)[\s#:_-]*([A-Z0-9][\w.\-]{1,20})\b',
    re.IGNORECASE
)


def extract_entities(text: str) -> dict:
    """
    Extract all structured entities from a text string.
    Returns a dict ready to be stored in MongoDB.
    """
    if not text:
        return {}

    # Deduplicate while preserving order
    def unique(lst):
        seen = set()
        return [x for x in lst if not (x.lower() in seen or seen.add(x.lower()))]

    tickets     = unique(TICKET_RE.findall(text))
    change_nums = unique([m.upper() for m in CHANGE_RE.findall(text)])
    versions    = unique(VERSION_RE.findall(text))
    envs        = unique([e.lower() for e in ENV_RE.findall(text)])

    # Dates — combine ISO + human, normalise to strings
    iso_dates   = ISO_DATE_RE.findall(text)
    human_dates = HUMAN_DATE_RE.findall(text)
    all_dates   = unique(iso_dates + human_dates)

    # Build/release labels
    build_labels = unique(BUILD_RE.findall(text))

    # Normalise environment names
    env_map = {
        'prod': 'production', 'production': 'production',
        'staging': 'staging', 'pre-prod': 'pre-prod', 'preprod': 'pre-prod',
        'uat': 'uat', 'qa': 'qa',
        'dev': 'development', 'development': 'development',
        'sandbox': 'sandbox',
    }
    envs = unique([env_map.get(e, e) for e in envs])

    entities = {}
    if tickets:      entities['jira_tickets']   = tickets[:20]
    if change_nums:  entities['change_numbers']  = change_nums[:10]
    if versions:     entities['versions']         = versions[:10]
    if all_dates:    entities['dates']             = all_dates[:10]
    if envs:         entities['environments']      = envs
    if build_labels: entities['build_labels']      = build_labels[:5]

    return entities


def extract_from_document(title: str, content: str) -> dict:
    """Extract entities from both title and content combined."""
    combined = f"{title} {content}"
    return extract_entities(combined)
