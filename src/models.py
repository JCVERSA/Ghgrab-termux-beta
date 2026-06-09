"""Data models for GitHub API responses."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class RepoItem:
    """Represents a single file or directory in a GitHub repository."""

    name: str
    path: str
    type: str  # "file" or "dir"
    sha: str
    download_url: Optional[str]
    size: int
    html_url: str