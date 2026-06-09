"""Terminal User Interface for ghgrab-termux using curses."""

import curses
import sys
from typing import List, Set, Optional

from .api_client import GitHubAPIClient
from .models import RepoItem
from .exceptions import GitHubAPIError, GitHubNotFoundError, GitHubRateLimitError
from .utils import get_github_token


class TUIApp:
    """Main TUI application class."""

    def __init__(self, owner: str, repo: str):
        """
        Initialize the TUI.

        Args:
            owner: Repository owner.
            repo: Repository name.
        """
        self.owner = owner
        self.repo = repo
        self.api_client = GitHubAPIClient()  # token from env via utils
        self.items: List[RepoItem] = []  # current directory items
        self.selected_paths: Set[str] = set()  # selected item paths
        self.current_path = ""  # path within repo, empty for root
        self.history: List[str] = []  # stack of visited paths for back navigation
        self.filter_text = ""  # current filter string
        self.filter_mode = False  # whether filter bar is active
        self.cursor_idx = 0  # index of highlighted item in displayed list
        self.top_idx = 0  # index of first item displayed (for scrolling)
        self.status_message = ""  # temporary message (e.g., loading, errors)
        self.status_timeout = 0  # frames to show status message
        self.download_requested = False  # set to True when user triggers download

    # -----------------------------------------------------------------
    # Drawing methods
    # -----------------------------------------------------------------
    def draw(self, stdscr):
        """Draw the entire UI."""
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Header
        header = f"ghgrab-termux | {self.owner}/{self.repo} | Path: {self.current_path or '/'}"
        stdscr.addnstr(0, 0, header, width - 1, curses.A_BOLD)

        # Main list area
        list_top = 2
        list_bottom = height - 3  # reserve for filter bar and footer
        list_height = max(1, list_bottom - list_top)

        # Determine displayed items (filtered or full)
        displayed_items = self._get_displayed_items()
        # Adjust cursor and top index
        self._adjust_scroll(displayed_items, list_height)

        # Draw each visible item
        for i in range(list_height):
            idx = self.top_idx + i
            if idx >= len(displayed_items):
                break
            item = displayed_items[idx]
            y = list_top + i
            # Selection box
            checked = "[x]" if item.path in self.selected_paths else "[ ]"
            # Directory marker
            if item.type == "dir":
                name_str = f"[{item.name}]/"
            else:
                name_str = item.name
            line = f"{checked} {name_str}"
            # Highlight cursor line
            if idx == self.cursor_idx:
                attr = curses.A_REVERSE
            else:
                attr = curses.A_NORMAL
            # Truncate to width-1
            stdscr.addnstr(y, 0, line, width - 1, attr)

        # Filter bar (if active)
        if self.filter_mode:
            filter_y = height - 2
            filter_prompt = f"Filter: [{self.filter_text}]"
            stdscr.addnstr(filter_y, 0, filter_prompt, width - 1, curses.A_DIM)
        # Else filter bar hidden (blank line)

        # Footer
        footer_y = height - 1
        selected_count = len(self.selected_paths)
        footer_left = f"Selected: {selected_count} items"
        footer_center = "[Enter] Download"
        footer_right = "[q] Quit"
        # Combine with spacing
        footer = f"{footer_left} {' ' * (max(0, width - len(footer_left) - len(footer_center) - len(footer_right) - 2))}{footer_center} {' ' * (max(0, width - len(footer_left) - len(footer_center) - len(footer_right) - 2))}{footer_right}"
        # Ensure not negative
        if len(footer) > width:
            footer = footer[:width]
        stdscr.addnstr(footer_y, 0, footer, width - 1, curses.A_BOLD)

        # Status message (temporary overlay)
        if self.status_message and self.status_timeout > 0:
            msg_y = height // 2
            msg_x = max(0, (width - len(self.status_message)) // 2)
            stdscr.addnstr(msg_y, msg_x, self.status_message, width - 1, curses.A_BOLD)
            self.status_timeout -= 1

        stdscr.refresh()

    def _get_displayed_items(self) -> List[RepoItem]:
        """Return items after applying filter (if any)."""
        if not self.filter_mode or not self.filter_text:
            return self.items
        # Filter: case-insensitive subsequence match on name or path
        ft = self.filter_text.lower()
        def matches(item: RepoItem) -> bool:
            return ft in item.name.lower() or ft in item.path.lower()
        return [item for item in self.items if matches(item)]

    def _adjust_scroll(self, displayed_items: List[RepoItem], list_height: int):
        """Adjust cursor_idx and top_idx to keep cursor visible."""
        if not displayed_items:
            self.cursor_idx = 0
            self.top_idx = 0
            return
        # Ensure cursor within bounds
        if self.cursor_idx < 0:
            self.cursor_idx = 0
        if self.cursor_idx >= len(displayed_items):
            self.cursor_idx = len(displayed_items) - 1
        # Ensure top_idx <= cursor_idx < top_idx + list_height
        if self.cursor_idx < self.top_idx:
            self.top_idx = self.cursor_idx
        if self.cursor_idx >= self.top_idx + list_height:
            self.top_idx = self.cursor_idx - list_height + 1
        # Clamp top_idx
        if self.top_idx < 0:
            self.top_idx = 0
        if self.top_idx > len(displayed_items) - list_height:
            self.top_idx = max(0, len(displayed_items) - list_height)

    # -----------------------------------------------------------------
    # Input handling
    # -----------------------------------------------------------------
    def handle_key(self, key: int) -> bool:
        """
        Handle a key press. Return False to quit or trigger download, True to continue.

        Args:
            key: integer key code from curses.

        Returns:
            False if the loop should break (quit or download requested), True to continue.
        """
        # If in filter mode, handle filter keys unless special
        if self.filter_mode:
            if key == 27:  # ESC
                self.filter_mode = False
                self.filter_text = ""
                self.status_message = ""
                return True
            elif key == 10 or key == curses.KEY_ENTER:  # Enter
                self.filter_mode = False  # apply filter and return to normal
                self.status_message = ""
                return True
            elif key in (curses.KEY_BACKSPACE, 127, 8):  # Backspace
                self.filter_text = self.filter_text[:-1]
                return True
            elif key == curses.KEY_RESIZE:
                # Handled in main loop via redraw
                return True
            else:
                # Add printable character
                if 32 <= key <= 126:  # printable ASCII
                    self.filter_text += chr(key)
                return True

        # Normal mode keys
        if key == ord('q') or key == ord('Q'):
            return False  # quit
        elif key == curses.KEY_UP or key == ord('k'):
            self.cursor_idx -= 1
        elif key == curses.KEY_DOWN or key == ord('j'):
            self.cursor_idx += 1
        elif key == ord('/'):
            self.filter_mode = True
            self.filter_text = ""
            self.cursor_idx = 0
            self.top_idx = 0
        elif key == curses.KEY_LEFT or key == ord('h'):
            self.go_up()
        elif key == curses.KEY_RIGHT or key == ord('l'):
            self.open_selected()
        elif key == 10 or key == curses.KEY_ENTER:  # Enter -> trigger download
            self.download_requested = True
            return False  # break loop to initiate download
        elif key == ord(' ') or key == 32:  # Spacebar
            self.toggle_selection()
        elif key == curses.KEY_RESIZE:
            # Handled by redraw
            pass
        else:
            # Ignore other keys
            pass
        return True

    # -----------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------
    def go_up(self):
        """Navigate to parent directory."""
        if self.current_path == "":
            # Already at root, maybe go back in history?
            if self.history:
                self.current_path = self.history.pop()
                self.load_directory()
            return
        # Compute parent path
        if "/" in self.current_path:
            parent = self.current_path.rsplit("/", 1)[0]
        else:
            parent = ""
        # Push current to history? We'll treat go_up as back navigation; not push.
        # For simplicity, we just set path and load.
        self.current_path = parent
        self.load_directory()

    def open_selected(self):
        """Open directory (if item is a folder)."""
        displayed = self._get_displayed_items()
        if not displayed:
            return
        item = displayed[self.cursor_idx]
        if item.type == "dir":
            # Enter directory
            self.history.append(self.current_path)
            if self.current_path:
                self.current_path = f"{self.current_path}/{item.name}"
            else:
                self.current_path = item.name
            self.load_directory()
        # If it's a file, nothing happens on Enter (selection via spacebar)

    def toggle_selection(self):
        """Toggle selection of the item under cursor."""
        displayed = self._get_displayed_items()
        if not displayed:
            return
        item = displayed[self.cursor_idx]
        if item.path in self.selected_paths:
            self.selected_paths.remove(item.path)
        else:
            self.selected_paths.add(item.path)

    def load_directory(self):
        """Load the current directory from GitHub API, showing loading indicator."""
        # Reset cursor and scroll
        self.cursor_idx = 0
        self.top_idx = 0
        self.filter_mode = False
        self.filter_text = ""
        self.status_message = "[ Loading... ]"
        self.status_timeout = 10  # show for a few frames while loading
        # Perform the request
        try:
            raw_items = self.api_client.get_contents(self.owner, self.repo, self.current_path)
            self.items = raw_items
            self.status_message = f"Loaded {len(self.items)} items"
            self.status_timeout = 20  # show for a bit
        except GitHubNotFoundError:
            self.status_message = f"Error: Repository or path not found"
            self.status_timeout = 50
            self.items = []
        except GitHubRateLimitError as e:
            self.status_message = f"Rate limit exceeded. Resets at {e.reset_timestamp}"
            self.status_timeout = 50
            self.items = []
        except GitHubAPIError as e:
            self.status_message = f"Error: {e}"
            self.status_timeout = 50
            self.items = []
        finally:
            # After loading, reset filter
            self.filter_mode = False
            self.filter_text = ""

    def get_selected_paths(self) -> Set[str]:
        """Return the set of selected paths."""
        return self.selected_paths

    # -----------------------------------------------------------------
    # Main loop
    # -----------------------------------------------------------------
    def run(self, stdscr):
        """Main entry point for curses. Returns selected paths if download requested, else None."""
        # Initialize curses settings
        curses.curs_set(0)  # hide cursor
        stdscr.keypad(True)  # enable special keys
        # Initial load
        self.load_directory()
        # Main loop
        while True:
            self.draw(stdscr)
            key = stdscr.getch()
            if not self.handle_key(key):
                break   # break on quit or download requested
            # If we performed a load in handle_key (like open_selected), we already loaded.
            # But load_directory is called explicitly from actions.
            # Ensure we redraw after any state change.
        # End of run
        if self.download_requested:
            return self.selected_paths
        else:
            return None  # user quit without downloading


def main(stdscr, owner: str, repo: str):
    """Wrapper for curses.wrapper."""
    app = TUIApp(owner, repo)
    return app.run(stdscr)


if __name__ == "__main__":
        # For direct execution (though intended to be called via ghgrab.py)
        import sys
        if len(sys.argv) != 3:
            print("Usage: python -m src.tui <owner> <repo>")
            sys.exit(1)
        owner, repo = sys.argv[1], sys.argv[2]
        result = curses.wrapper(main, owner, repo)
        if result is not None:
            print("Selected paths:", result)
        else:
            print("Quitting without download.")