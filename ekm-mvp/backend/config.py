from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # MongoDB
    mongo_uri: str = "mongodb://localhost:27017/ekm"
    mongo_db:  str = "ekm"

    # ── SharePoint ─────────────────────────────────────────────────────────────
    # Option A — Full cookie string (run utils/cookie_helper.py to generate)
    sharepoint_all_cookies: str = ""

    # Option B — Individual cookies
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

    # ── GitHub ───────────────────────────────────────────────────────────────────
    github_host:        str = ""   # GHE hostname e.g. github.yourcompany.com (leave blank for github.com)
    github_token:       str = ""   # PAT from your GitHub Enterprise instance
    github_repos:       str = ""   # comma-separated: org/repo1,org/repo2
    github_org:         str = ""   # crawl all repos in an org
    github_max_commits: int = 200  # commits per repo per sync

    # ── App ───────────────────────────────────────────────────────────────────
    sync_interval_minutes: int = 60
    max_results_per_page:  int = 20

    @property
    def github_repo_list(self) -> list[str]:
        return [r.strip() for r in self.github_repos.split(",") if r.strip()]

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
