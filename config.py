from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # MongoDB
    mongo_uri: str = "mongodb://localhost:27017/ekm"
    mongo_db:  str = "ekm"

    # ── SharePoint ─────────────────────────────────────────────────────────────
    # Option A — Cookie auth (recommended for citi.sharepoint.com)
    # Copy FedAuth and rtFa cookie values from browser dev tools
    sharepoint_fed_auth:   str = ""
    sharepoint_rt_fa:      str = ""

    # Option B — Username/password (NTLM for on-premise, basic for others)
    sharepoint_username:   str = ""
    sharepoint_password:   str = ""
    sharepoint_auth_type:  str = "office365"   # "ntlm" or "basic"

    # Sites to crawl — comma-separated
    sharepoint_site_urls:  str = ""

    # ── Confluence (on-premise PAT) ────────────────────────────────────────────
    confluence_url:        str = ""
    confluence_username:   str = ""
    confluence_api_token:  str = ""
    confluence_spaces:     str = ""

    # ── Jira (on-premise PAT) ─────────────────────────────────────────────────
    jira_url:              str = ""
    jira_username:         str = ""
    jira_api_token:        str = ""
    jira_projects:         str = ""

    # ── App ───────────────────────────────────────────────────────────────────
    sync_interval_minutes: int = 60
    max_results_per_page:  int = 20

    @property
    def sharepoint_site_url_list(self) -> list[str]:
        return [u.strip() for u in self.sharepoint_site_urls.split(",") if u.strip()]

    @property
    def confluence_space_list(self) -> list[str]:
        return [s.strip() for s in self.confluence_spaces.split(",") if s.strip()]

    @property
    def jira_project_list(self) -> list[str]:
        return [p.strip() for p in self.jira_projects.split(",") if p.strip()]

    class Config:
        env_file = ".env"
        extra    = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
