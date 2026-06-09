"""GitHub API specific exceptions."""

class GitHubAPIError(Exception):
    """Base exception for GitHub API errors."""
    pass


class GitHubNotFoundError(GitHubAPIError):
    """Raised when a GitHub resource is not found (HTTP 404)."""
    pass


class GitHubRateLimitError(GitHubAPIError):
    """Raised when GitHub API rate limit is exceeded (HTTP 403 with rate limit)."""

    def __init__(self, reset_timestamp: int):
        """
        Initialize with the Unix timestamp when the rate limit resets.

        Args:
            reset_timestamp: Seconds since epoch when rate limit resets.
        """
        self.reset_timestamp = reset_timestamp
        super().__init__(f"GitHub API rate limit exceeded. Resets at {reset_timestamp}")