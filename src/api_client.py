"""GitHub API client for retrieving repository contents."""

import json
import os
from typing import List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import RepoItem
from .exceptions import (
    GitHubAPIError,
    GitHubNotFoundError,
    GitHubRateLimitError,
)
from .utils import build_api_url, get_github_token


class GitHubAPIClient:
    """
    Stateless client for interacting with the GitHub Contents API.

    Handles authentication, rate limiting, and error handling.
    Returns normalized RepoItem objects.
    """

    def __init__(self, token: Optional[str] = None):
        """
        Initialize the API client.

        Args:
            token: Optional GitHub personal access token.
                   If not provided, attempts to read from GITHUB_TOKEN environment variable.
        """
        self.token = token if token is not None else get_github_token()
        self.user_agent = "ghgrab-termux/1.0"

    def _prepare_request(self, url: str) -> Request:
        """
        Prepare an HTTP request with required headers.

        Args:
            url: The URL to request.

        Returns:
            A urllib.request.Request object with headers set.
        """
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/vnd.github.v3+json",
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return Request(url, headers=headers)

    def get_contents(self, owner: str, repo: str, path: str = "") -> List[RepoItem]:
        """
        Fetch the contents of a repository directory.

        Args:
            owner: Repository owner (username or organization).
            repo: Repository name.
            path: Path inside the repository (empty for root).

        Returns:
            A list of RepoItem objects representing files and directories.

        Raises:
            GitHubNotFoundError: If the repository or path is not found (404).
            GitHubRateLimitError: If the GitHub API rate limit is exceeded (403).
            GitHubAPIError: For other HTTP or network errors.
        """
        url = build_api_url(owner, repo, path)
        request = self._prepare_request(url)

        try:
            with urlopen(request) as response:
                # Read and parse the JSON response
                data = json.load(response)
                # GitHub API returns a list of items for a directory request
                if not isinstance(data, list):
                    # This should not happen for a contents endpoint, but guard anyway
                    raise GitHubAPIError(
                        f"Unexpected response format from GitHub API: {type(data)}"
                    )

                items: List[RepoItem] = []
                for item_data in data:
                    # Extract fields, providing defaults where necessary
                    name = item_data.get("name", "")
                    item_path = item_data.get("path", "")
                    item_type = item_data.get("type", "")
                    sha = item_data.get("sha", "")
                    download_url = item_data.get("download_url")  # None for directories
                    size = item_data.get("size", 0)
                    html_url = item_data.get("html_url", "")

                    # Basic validation
                    if not name or not item_path or not item_type or not sha:
                        # Skip malformed items but continue processing others
                        continue

                    repo_item = RepoItem(
                        name=name,
                        path=item_path,
                        type=item_type,
                        sha=sha,
                        download_url=download_url,
                        size=size,
                        html_url=html_url,
                    )
                    items.append(repo_item)

                return items

        except HTTPError as e:
            # Handle specific HTTP status codes
            if e.code == 404:
                raise GitHubNotFoundError(
                    f"Repository '{owner}/{repo}' or path '{path}' not found."
                ) from e
            elif e.code == 403:
                # Check if it's a rate limit error
                remaining = e.headers.get("X-RateLimit-Remaining")
                reset = e.headers.get("X-RateLimit-Reset")
                if remaining == "0" and reset:
                    try:
                        reset_timestamp = int(reset)
                        raise GitHubRateLimitError(reset_timestamp) from e
                    except ValueError:
                        pass  # Fall through to generic GitHubAPIError
                # If not rate limit, or headers missing, raise a generic error
                raise GitHubAPIError(
                    f"GitHub API access forbidden (403). "
                    f"Check your token and permissions. Details: {e.reason}"
                ) from e
            else:
                # Other HTTP errors (e.g., 500, 502)
                raise GitHubAPIError(
                    f"GitHub API returned HTTP {e.code}: {e.reason}"
                ) from e
        except URLError as e:
            # Network-related errors (e.g., no internet, DNS failure)
            raise GitHubAPIError(f"Failed to reach GitHub API: {e.reason}") from e
        except json.JSONDecodeError as e:
            raise GitHubAPIError(f"Failed to parse GitHub API response: {e}") from e