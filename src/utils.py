"""Utility functions for the GitHub API client."""

from urllib.parse import quote
from typing import Optional


def build_api_url(owner: str, repo: str, path: str = "") -> str:
    """
    Build the GitHub Contents API URL for a given repository and path.

    The owner, repo, and path components are URL-encoded to handle
    special characters, spaces, or symbols safely.

    Args:
        owner: Repository owner (username or organization).
        repo: Repository name.
        path: Path inside the repository (empty for root).

    Returns:
        The fully qualified API URL.
    """
    # Encode each component individually to preserve '/' separators
    encoded_owner = quote(owner, safe='')
    encoded_repo = quote(repo, safe='')
    # If path is provided, encode it but allow '/' to remain as separator
    # We quote each segment of the path to handle spaces, etc.
    if path:
        # Split by '/' and encode each non-empty segment
        encoded_parts = [quote(part, safe='') for part in path.split('/') if part]
        encoded_path = '/'.join(encoded_parts)
    else:
        encoded_path = ''
    # Construct the URL
    base_url = "https://api.github.com/repos"
    if encoded_path:
        return f"{base_url}/{encoded_owner}/{encoded_repo}/contents/{encoded_path}"
    else:
        return f"{base_url}/{encoded_owner}/{encoded_repo}/contents"


def get_github_token() -> Optional[str]:
    """
    Retrieve the GitHub token from the environment variable GITHUB_TOKEN.

    Returns:
        The token string if set, otherwise None.
    """
    import os
    return os.environ.get("GITHUB_TOKEN")