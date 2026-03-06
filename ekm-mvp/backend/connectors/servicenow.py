"""
ServiceNow Connector — FUTURE SCOPE
────────────────────────────────────
This module is intentionally left as a stub.
It will pull incidents, knowledge base articles, and change requests
from ServiceNow when credentials are configured.

To implement:
  1. Add SERVICENOW_* vars to .env
  2. Install: pip install pysnow
  3. Implement fetch_documents() following the same pattern as
     the Confluence and Jira connectors.

Tables to target:
  - kb_knowledge          → Knowledge Base articles
  - incident              → Incidents
  - change_request        → Change requests
  - sc_req_item           → Service catalog items
"""

import logging
from models import Document

logger = logging.getLogger(__name__)


async def fetch_documents() -> list[Document]:
    """ServiceNow connector — not yet implemented."""
    logger.info("ServiceNow connector: future scope — skipping")
    return []
