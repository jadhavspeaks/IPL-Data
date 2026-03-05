from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # MongoDB
    mongo_uri: str = "mongodb://localhost:27017/ekm"
    mongo_db:  str = "ekm"

    # SharePoint — supports both Office365 (shareplum) and on-premise (NTLM)
    sharepoint_site_urls:  str = ""   # comma-separated site URLs
    sharepoint_username:   str = ""   # firstname.lastname@citi.com
    sharepoint_password:   str = ""   # Windows password
    sharepoint_auth_type:  str = "office365"  # "office365" or "ntlm"

    # Azure AD (optional — only if using app registration)
    sharepoint_tenant_id:     str = ""
    sharepoint_client_id:     str = ""
    sharepoint_client_secret: str = ""

    # Confluence (on-premise, PAT auth)
    confluence_url:       str = ""
    confluence_username:  str = ""
    confluence_api_token: str = ""
    confluence_spaces:    str = ""

    # Jira (on-premise, PAT auth)
    jira_url:        str = ""
    jira_username:   str = ""
    jira_api_token:  str = ""
    jira_projects:   str = ""

    # App
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
