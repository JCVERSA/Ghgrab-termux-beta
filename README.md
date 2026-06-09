# ghgrab-termux

An interactive, dependency-free GitHub repository browser and partial downloader tailored for **Termux** (Android). Navigate a remote repository's directory tree, cherry‑pick files or folders, and download them without cloning the entire Git history.

## Key Features

- **Terminal UI** built with Python's standard‑library `curses` – works in any Termux terminal.
- **Keyboard navigation**: Arrow keys or Vim‑style `j/k/h/l`, `Enter` to open folders, `Space` to toggle selection.
- **Fuzzy subsequence filtering**: Press `/` to type a filter that matches file/directory names in‑place.
- **Multi‑selection**: Pick multiple files and directories across different paths.
- **Recursive download**: Selecting a folder queues all its nested files.
- **Path‑traversal safety**: Strict validation prevents writing outside the target directory.
- **Atomic file writes**: Streams download to a `.tmp` file and renames on completion.
- **Zero external dependencies**: Only the Python standard library is used.
- **Rate‑limit aware**: Handles GitHub API limits gracefully (optional `GITHUB_TOKEN` raises the limit).

## Prerequisites & Installation

1. **Install Termux** (from F-Droid or the Termux website) and open it.
2. **Install Python and Git**:
   ```bash
   pkg update && pkg upgrade
   pkg install python git
   ```
3. **Clone this repository** (or copy the files):
   ```bash
   git clone https://github.com/yourusername/ghgrab-termux.git
   cd ghgrab-termux
   ```
   *(Replace the URL with the actual repository location.)*
4. **(Optional) Set a GitHub token** for higher rate limits:
   ```bash
   export GITHUB_TOKEN=your_personal_access_token
   ```
   Add the export to `~/.profile` or `~/.bashrc` to make it persistent.

## Usage Guide

### Launching the Application

Run the script with the target repository in `owner/repo` format:

```bash
python3 ghgrab.py torvalds/linux
```

You can also make the script executable and run it directly:

```bash
chmod +x ghgrab.py
./ghgrab.py torvalds/linux
```

### Keyboard Shortcuts

| Key               | Action                                   |
|-------------------|------------------------------------------|
| `↑` / `k`         | Move cursor up                           |
| `↓` / `j`         | Move cursor down                         |
| `←` / `h`         | Go to parent directory                   |
| `→` / `l` / `Enter`| Open a directory (if under cursor)      |
| `Space`           | Toggle selection (`[ ]` / `[x]`) of item |
| `/`               | Activate filter / search bar             |
| `Enter` (in filter)| Apply filter and return to normal mode  |
| `Esc`             | Cancel filter or go back (contextual)    |
| `q`               | Quit the application                     |
| `Enter` (at footer, after selection)| Start download of selected items |

### Environment Variables

- `GITHUB_TOKEN`: Optional personal access token. Increases the unauthenticated rate limit from 60/hour to 5000/hour.
- `GHGRAB_DEST`: Optional destination directory for downloads (default: `./ghgrab-downloads`).  
  Example: `export GHGRAB_DEST=/data/data/com.termux/files/home/downloads`

### Example Test Run

Try it with a small public repository:

```bash
python3 ghgrab.py octocat/Hello-World
```

Navigate, select a few files (e.g., `README.md`), press `Enter` at the footer to download, and check the `./ghgrab-downloads` folder.

## How It Works

1. **API Layer** (`src/api_client.py`):  
   Uses `urllib.request` to query the GitHub Contents API, handles authentication, rate limits, and returns normalized `RepoItem` dataclasses.

2. **TUI Layer** (`src/tui.py`):  
   A `curses`‑based interface that displays the repository tree, handles input, tracks selections, and shows a loading state while fetching data.

3. **Download Engine** (`src/downloader.py`):  
   - Recursively expands selected directories into a flat file list using the API client.  
   - Validates each target path with `pathlib.Path.is_relative_to` to block path‑traversal attacks.  
   - Streams each file in 8 KB chunks to a temporary file, then atomically renames it.  
   - Prints an in‑place progress bar (`[=====>   ] 42% 1.2 MB / 2.9 MB file.txt`) using only standard output.

4. **Orchestrator** (`ghgrab.py`):  
   Parses arguments, launches the TUI, and on download request invokes the engine.

## Safety & Dependencies

- **No external packages**: Everything relies on the Python standard library (`urllib`, `curses`, `pathlib`, `os`, `sys`, `time`).
- **Path safety**: Before writing any file, the resolved absolute path is checked to be inside the destination directory using `Path.is_relative_to`.
- **Atomic writes**: Prevents partially‑written files if the process is interrupted.
- **Rate‑limit respect**: The downloader pauses briefly between API calls to avoid bursting limits.

## License

This project is released under the MIT License – see the `LICENSE` file for details.

---
*Built with ❤️ for the Termux community.*