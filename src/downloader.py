"""Download engine for ghgrab-termux."""

import os
import sys
import time
from pathlib import Path
from typing import List, Set, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .api_client import GitHubAPIClient
from .models import RepoItem
from .exceptions import GitHubAPIError, GitHubNotFoundError, GitHubRateLimitError


def resolve_selected_items_to_files(
    api_client: GitHubAPIClient,
    owner: str,
    repo: str,
    selected_paths: Set[str],
) -> List[RepoItem]:
    """
    Resolve a set of selected paths (files or directories) to a flat list of file RepoItem objects.

    This function recursively expands directories using the GitHub Contents API.

    Args:
        api_client: Initialized GitHubAPIClient.
        owner: Repository owner.
        repo: Repository name.
        selected_paths: Set of paths relative to repository root (each path is a string).

    Returns:
        List of RepoItem objects representing files to download.
    """
    files: List[RepoItem] = []
    # We'll process each selected path
    for path in selected_paths:
        # Use a stack for depth-first traversal to avoid recursion depth issues
        stack = [path]
        while stack:
            current_path = stack.pop()
            try:
                # Get contents of this path (could be file or directory)
                items = api_client.get_contents(owner, repo, current_path)
                for item in items:
                    if item.type == "dir":
                        # Push directory onto stack for later processing
                        stack.append(item.path)
                    else:  # file
                        files.append(item)
                # Be nice to the rate limit: small delay between requests
                time.sleep(0.05)  # 50 ms
            except GitHubNotFoundError:
                # If a path is not found, skip it (should not happen if selected from TUI)
                continue
            except GitHubRateLimitError as e:
                # If we hit rate limit, wait until reset and retry once?
                # For simplicity, we'll just raise and let the caller handle.
                # In a production app we might want to wait and retry.
                raise GitHubAPIError(
                    f"Rate limit exceeded while resolving path '{current_path}'. "
                    f"Reset at {e.reset_timestamp}"
                ) from e
            except GitHubAPIError as e:
                # Other API errors
                raise GitHubAPIError(
                    f"Failed to fetch contents of '{current_path}': {e}"
                ) from e
    return files


def download_file(
    file_item: RepoItem,
    dest_dir: Path,
    chunk_size: int = 8192,
) -> None:
    """
    Download a single file to the destination directory with progress indication.

    Arguments:
        file_item: RepoItem representing the file to download.
        dest_dir: Base directory where the file should be saved.
        chunk_size: Number of bytes to read per chunk (default 8192).
    """
    # Construct the target path
    target_path = dest_dir / file_item.path
    # Security: ensure target_path is inside dest_dir (no path traversal)
    try:
        target_path.resolve().relative_to(dest_dir.resolve())
    except ValueError:
        raise ValueError(
            f"Potential path traversal detected: {file_item.path} resolves to {target_path}, "
            f"which is outside the destination directory {dest_dir}"
        )

    # Create parent directories if they don't exist
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Prepare the request (no auth needed for raw download_url, but we keep user-agent)
    request = Request(
        file_item.download_url,
        headers={
            "User-Agent": "ghgrab-termux/1.0",
            "Accept": "application/octet-stream",
        },
    )

    # Open the stream and download in chunks
    try:
        with urlopen(request) as response:
            # Get total size if available (from Content-Length header or file_item.size)
            total_size = None
            if file_item.size > 0:
                total_size = file_item.size
            else:
                # Try to get from headers
                content_length = response.headers.get("Content-Length")
                if content_length and content_length.isdigit():
                    total_size = int(content_length)

            # Open temporary file for atomic write
            temp_path = target_path.with_suffix(target_path.suffix + ".tmp")
            downloaded = 0
            with open(temp_path, "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    # Update progress in-place
                    _print_progress(downloaded, total_size, file_item.name)
            # Rename temp to target (atomic on same filesystem)
            os.replace(temp_path, target_path)
            # After completion, print a newline and final message
            print()  # newline after progress bar
    except HTTPError as e:
        raise GitHubAPIError(
            f"HTTP error {e.code} while downloading {file_item.name}: {e.reason}"
        ) from e
    except URLError as e:
        raise GitHubAPIError(f"URL error while downloading {file_item.name}: {e.reason}") from e


def _print_progress(downloaded: int, total_size: Optional[int], filename: str) -> None:
    """
    Print a text-based progress bar to stdout, updated in-place.

    Args:
        downloaded: Number of bytes downloaded so far.
        total_size: Total size in bytes (if known), else None.
        filename: Name of the file being downloaded (for display).
    """
    bar_width = 20
    if total_size is not None and total_size > 0:
        percent = min(100, int((downloaded * 100) / total_size))
        filled_length = int(bar_width * downloaded // total_size)
        bar = "=" * filled_length + ">" + "." * (bar_width - filled_length - 1)
        if filled_length == bar_width:
            bar = "=" * bar_width
        sys.stdout.write(
            f"\rDownloading: [{bar}] {percent:3d}% {downloaded:>8} / {total_size:<8} B  {filename}"
        )
    else:
        # Indeterminate: just show bytes downloaded
        sys.stdout.write(
            f"\rDownloading: {downloaded:>8} B  {filename}"
        )
    sys.stdout.flush()


def download_selected_items(
    api_client: GitHubAPIClient,
    owner: str,
    repo: str,
    selected_paths: Set[str],
    dest_dir: str | Path = "./ghgrab-downloads",
) -> None:
    """
    Download all selected items (files and directories) to the destination directory.

    This is the main entry point for the download engine.

    Arguments:
        api_client: Initialized GitHubAPIClient.
        owner: Repository owner.
        repo: Repository name.
        selected_paths: Set of selected paths (relative to repo root) from the TUI.
        dest_dir: Destination directory (default: ./ghgrab-downloads). Will be created if missing.
    """
    if not selected_paths:
        print("No items selected for download.")
        return

    dest_path = Path(dest_dir).resolve()
    print(f"Destination directory: {dest_path}")
    print(f"Resolving selected items to files...")

    try:
        files_to_download = resolve_selected_items_to_files(
            api_client, owner, repo, selected_paths
        )
    except GitHubAPIError as e:
        print(f"Error resolving items: {e}")
        return

    if not files_to_download:
        print("No files found in the selected items.")
        return

    print(f"Found {len(files_to_download)} file(s) to download.")
    print("-" * 60)

    # Ensure destination directory exists
    dest_path.mkdir(parents=True, exist_ok=True)

    # Download each file
    for idx, file_item in enumerate(files_to_download, start=1):
        print(f"[{idx}/{len(files_to_download)}] ", end="")
        try:
            download_file(file_item, dest_path)
        except Exception as e:
            print(f"\nFailed to download {file_item.name}: {e}")
            # Continue with other files
            continue

    print("\nDownload complete!")


if __name__ == "__main__":
    # Simple manual test (not intended for production use)
    print("This module is not meant to be run directly.")
    print("Use ghgrab.py instead.")