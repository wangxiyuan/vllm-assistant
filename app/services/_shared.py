"""
Shared utilities for API clients and common patterns.
"""
from typing import Optional
from app.services.github_client import GitHubClient


def get_github_client() -> GitHubClient:
    """Get or create the global GitHubClient singleton.

    Used by all API modules that need GitHub API access.
    Avoids creating multiple client instances with separate sessions.
    """
    if not hasattr(get_github_client, "_instance"):
        get_github_client._instance = GitHubClient()
    return get_github_client._instance