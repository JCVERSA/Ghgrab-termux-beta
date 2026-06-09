#!/usr/bin/env python3
"""
ghgrab-termux - Interactive GitHub repository browser for Termux.

This is the main entry point. It parses the repository argument
and launches the curses-based TUI. After the user makes selections
and triggers download, it proceeds to download the selected files.
"""

import sys
import os
import curses
from src.tui import main as tui_main
from src.downloader import download_selected_items
from src.api_client import GitHubAPIClient
from src.utils import get_github_token


def print_usage():
    """Print usage information."""
    print("Usage: ghgrab.py <owner>/<repo>")
    print("Example: ghgrab.py torvalds/linux")
    print("")
    print("Environment:")
    print("  GITHUB_TOKEN   Optional personal access token for higher rate limits")
    print("  GHGRAB_DEST    Optional destination directory (default: ./ghgrab-downloads)")


def parse_repo_arg(arg: str):
    """
    Parse owner/repo string.

    Args:
        arg: String in the form "owner/repo".

    Returns:
        Tuple (owner, repo).

    Raises:
        ValueError: If the format is invalid.
    """
    if "/" not in arg:
        raise ValueError("Repository must be in the format 'owner/repo'")
    parts = arg.split("/", 1)
    owner, repo = parts[0].strip(), parts[1].strip()
    if not owner or not repo:
        raise ValueError("Owner and repo names must be non-empty")
    return owner, repo


def main():
    """Main entry point."""
    if len(sys.argv) != 2:
        print_usage()
        sys.exit(1)

    arg = sys.argv[1]
    # Handle help flags
    if arg in ("-h", "--help"):
        print_usage()
        sys.exit(0)

    try:
        owner, repo = parse_repo_arg(arg)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        print_usage()
        sys.exit(1)

    # Initialize API client (token from environment)
    api_client = GitHubAPIClient()  # uses utils.get_github_token()

    # Launch the TUI using curses.wrapper to get selected paths
    try:
        selected_paths = curses.wrapper(tui_main, owner, repo)
    except KeyboardInterrupt:
        # Graceful exit on Ctrl+C
        print("\nInterrupted.")
        sys.exit(0)

    # If the user quit without downloading, selected_paths will be None
    if selected_paths is None:
        print("No download requested. Exiting.")
        sys.exit(0)

    # Determine destination directory from environment or default
    dest_dir = os.environ.get("GHGRAB_DEST", "./ghgrab-downloads")
    print(f"\nStarting download of {len(selected_paths)} selected item(s)...")
    try:
        download_selected_items(
            api_client=api_client,
            owner=owner,
            repo=repo,
            selected_paths=selected_paths,
            dest_dir=dest_dir,
        )
    except Exception as e:
        print(f"\nDownload failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()