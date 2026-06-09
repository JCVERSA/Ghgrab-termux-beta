# ghgrab-termux Architecture

## Step 1 — The API Engine (Request Management)

### 1. Stack Selection & Justification

**Proposed Core Technology:** **Python 3.11+** (specifically the `cpython` distribution available via Termux packages)

**Justification:**

- **Termux Compatibility & Architecture Support:**  
  Python is readily available in Termux's official repositories for both `aarch64` (64-bit) and `arm` (32-bit) Android architectures. Installation via `pkg install python` provides a pre‑compiled binary, eliminating any need for cross‑compilation or Rust toolchains on the device. This satisfies the “zero unnecessary dependencies” and “multi‑architecture Android compatibility” constraints directly.

- **Lightweight & Dependency Control:**  
  The standard library (`urllib`, `json`, `os`, `sys`) provides sufficient functionality for HTTP requests, JSON parsing, and basic CLI handling. If external packages are unavoidable, we will prioritize:
  - **`requests`** (only if URI handling, timeout, and retry logic prove cumbersome with `urllib`; otherwise avoided)
  - **`rich`** or **`textual`** for TUI (deferred to Phase 2; for the API engine, no TUI dependencies are needed)
  
  By relying primarily on the standard library, we keep the dependency footprint near‑zero, simplify installation, and reduce attack surface.

- **Ease of Maintenance & Debugging:**  
  Python’s readability accelerates troubleshooting and contributions. Error handling is explicit, and the interactive Python REPL available in Termux allows quick API prototyping without a compile step.

- **Performance Considerations:**  
  For an I/O‑bound application (network requests to GitHub), Python’s speed is adequate. The anticipated workload (sequential directory traversal, occasional file downloads) does not demand the low‑level performance of Rust. Simplicity and correctness take precedence over raw speed per our Decision Priority Order.

- **Alignment with Operating Principles:**  
  - *Simplicity:* Python’s standard library reduces moving parts.  
  - *Dependency Control:* Avoids native build tools (Cargo, rustc) and large runtime dependencies.  
  - *Correctness:* Explicit error handling and type safety (via runtime checks) are straightforward.  
  - *Maintainability:* Clear, idiomatic Python is easier to audit and extend than equivalent Rust for this use case.

**Rejected Alternatives:**
- **Node.js:** While available in Termux, it brings a larger runtime (V8) and encourages a callback/promise paradigm that may increase cognitive overhead for simple sequential API work. The standard library (`http`, `https`) is lower‑level than Python’s `urllib`, requiring more boilerplate.
- **Rust (original):** Would require cross‑compiling for Android or installing Rustc/Cargo in Termux, violating the “zero unnecessary dependencies” and “elimination of complex compilation steps” goals. The binary size and build complexity are unjustified for the anticipated workload.
- **Bash/`curl`/`jq`:** Pure shell scripting would be lightweight but struggles with complex JSON manipulation, error handling, and maintainability. Relying on external tools (`curl`, `jq`) introduces dependency variability and security surface (shell injection risks).

### 2. API Engine Architecture

**Goal:** Provide a reliable, rate‑limit‑aware abstraction over the GitHub Contents API (`/repos/{owner}/{repo}/contents/{path}`) that returns normalized data for the TUI layer.

#### 2.1 HTTP Request Module Structure

We propose a single, stateless class `GitHubAPIClient` (or a module of pure functions) responsible for:

- Constructing authenticated/unauthenticated requests to `https://api.github.com/repos/{owner}/{repo}/contents/{path}`.
- Handling pagination (though the Contents API does not paginate for a single directory; note: tree API would paginate, but we are using Contents for simplicity).
- Implementing retry logic with exponential backoff for transient errors (5xx, network timeouts).
- Respecting `Retry-After` headers and monitoring `X-RateLimit-Remaining` and `X-RateLimit-Reset` to avoid 403 errors.
- Raising specific, typed exceptions (e.g., `GitHubRateLimitError`, `GitHubNotFoundError`, `GitHubAPIError`) for the caller to handle.

**Key Design Points:**
- **No Persistent Connections:** Each request is independent; we avoid connection pooling complexity (standard library’s `urllib.request` opens/closes per call). This is acceptable given the low frequency of requests in an interactive TUI (user‑driven navigation).
- **Timeouts:** Conservative default (10 seconds) for connect and read, configurable via environment or constructor.
- **User-Agent:** Set to `ghgrab-termux/1.0 (+https://github.com/yourname/ghgrab-termux)` as required by GitHub API guidelines.
- **Authentication:** Optional. If `GITHUB_TOKEN` environment variable is present, it is sent as `Authorization: token <token>`. This raises the unauthenticated limit from 60/hour to 5000/hour.

#### 2.2 Normalized Data Structure

The engine will transform the raw GitHub Contents API response into a consistent internal dictionary (or `@dataclass` if we opt for minimal typing) with the following fields:

| Field        | Type     | Description                                                                 |
|--------------|----------|-----------------------------------------------------------------------------|
| `name`       | `str`    | File or directory name (base name only).                                    |
| `path`       | `str`    | Full path from repository root (URL‑decoded, matching the API’s `path`).    |
| `type`       | `str`    | Either `"file"` or `"dir"` (directly from API `type`).                      |
| `sha`        | `str`    | Git object SHA (useful for future download or blob inspection).             |
| `download_url`| `str` \| `None` | For files: the raw download URL; for directories: `None`.             |
| `size`       | `int`    | File size in bytes (0 for directories).                                     |
| `html_url`   | `str`    | URL to the file/directory on github.com (for potential sharing/debugging). |

**Example Internal Object (Python dict):**
```python
{
    "name": "README.md",
    "path": "docs/README.md",
    "type": "file",
    "sha": "a1b2c3d4e5f6...",
    "download_url": "https://raw.githubusercontent.com/owner/repo/main/docs/README.md",
    "size": 4257,
    "html_url": "https://github.com/owner/repo/blob/main/docs/README.md"
}
```

For a directory:
```python
{
    "name": "src",
    "path": "src",
    "type": "dir",
    "sha": "f6e5d4c3b2a1...",
    "download_url": None,
    "size": 0,
    "html_url": "https://github.com/owner/repo/tree/main/src"
}
```

**Why This Structure?**
- It isolates the TUI from API‑specific nuances (e.g., GitHub’s `_links` field, which we do not need for navigation).
- All fields are either directly from the API or trivial derivations, minimizing processing overhead.
- The `download_url` enables the download phase (Phase 2) to fetch file content without additional API calls.
- Including `html_url` aids debugging and potential future features (e.g., “open on GitHub”).

#### 2.3 Rate Limit Handling Strategy

- **Pre‑flight Check:** Before each request, optionally check `GET /rate_limit` if token is available and we are near a threshold (e.g., <50 remaining). This adds overhead but prevents hard 403s; we may skip this for simplicity and rely on response headers.
- **Response‑Driven Throttling:** After every response, inspect:
  - `X-RateLimit-Remaining`: If `0`, compute sleep time until `X-RateLimit-Reset` (epoch seconds).
  - `Retry-After`: Honor if present ( sekunds ).
- **Backoff on 403:** If a 403 occurs and the response indicates rate limit exceeded (check `X-RateLimit-Remaining` == 0), sleep until reset and retry once.
- **User Feedback:** The API engine will raise a `GitHubRateLimitError` containing the reset timestamp, allowing the TUI to display a polite “Waiting for rate limit reset…” message and pause navigation.

This approach ensures we never exceed limits while keeping the engine simple: no background token bucket thread, just blocking sleeps when necessary.

### 3. Project Structure

We aim for a flat, modular layout that separates concerns and facilitates testing. The root directory will contain:

```
ghgrab-termux/
├── src/                     # Main source code (all Python modules)
│   ├── __init__.py
│   ├── api_client.py        # GitHubAPIClient class and rate‑limit logic
│   ├── models.py            # Internal data structures (e.g., RepoItem dataclass)
│   ├── exceptions.py        # Custom exception types (GitHubAPIError, etc.)
│   └── utils.py             # Helper functions (URL building, retry logic, env var loading)
├── tests/                   # Unit tests (using unittest or pytest, if added later)
│   ├── __init__.py
│   └── test_api_client.py
├── docs/                    # Documentation (architecture, usage)
│   └── api_design.md
├── README.md                # User‑facing overview (to be written post‑approval)
├── LICENSE                  # MIT or similar permissive license
└── .gitignore               # Standard Python/git ignores
```

**Rationale:**
- **`src/` Layout:** Keeps implementation isolated; avoids polluting the root with modules. Each file has a single responsibility:
  - `api_client.py`: Core HTTP logic.
  - `models.py`: Pure data objects (no behavior).
  - `exceptions.py`: Clear error hierarchy.
  - `utils.py`: Cross‑cutting concerns (e.g., building URLs from owner/repo/path, parsing ISO8601 timestamps).
- **Tests:** Placed alongside source for ease of access; we will adopt test‑driven development in Phase 2.
- **No `bin/` or Scripts Yet:** The entry point (CLI/TUI) will be added in Phase 2; for now, we focus solely on the API engine.
- **Dependency Manifest:** If external packages are ultimately needed (e.g., `requests`), they will be listed in `requirements.txt` at the project root. For now, we target zero external deps.

**Modularity & Future Proofing:**
- The `GitHubAPIClient` depends only on `urllib`, `json`, `time`, and `os` (for token). This makes it trivial to mock in tests (by patching `urllib.request.urlopen`).
- Should we later switch to `httpx` or `aiohttp` for async TUI integration, the interface (methods like `get_contents(owner, repo, path="") -> List[RepoItem]`) can remain stable.

---

## Step 2 — Terminal User Interface (TUI) Design & Layout

### 1. TUI Technology Choice & Justification

**Chosen Technology:** **Python’s standard library `curses` module** (specifically, the `curses` wrapper provided by Termux).

**Justification:**

- **Stability & Feature Set:**  
  The `curses` module provides a mature, terminal‑independent API for handling screen rendering, keyboard input, and window management. It abstracts away low‑level ANSI escape codes and handles complexities such as screen resizing, color attributes, and special keys (arrow keys, function keys) in a portable way. This is crucial for Android Termux, where terminal emulators may vary in behavior and support for escape sequences.

- **Zero External Dependencies:**  
  `curses` is part of Python’s standard library, satisfying our strict zero‑dependency constraint. No additional packages need to be installed in Termux beyond the core Python interpreter.

- **Handling Android Constraints:**  
  - **Screen Resizing:** `curses` provides mechanisms (e.g., `curses.resizeterm()`) to adapt to terminal size changes, which can occur when rotating the device or switching between split‑screen modes on Android.
  - **Font Rendering:** While font rendering is ultimately handled by the terminal emulator, `curses` works with the character grid provided by the emulator, ensuring predictable layout.
  - **32/64‑bit Compatibility:** The `curses` module is compiled as part of the Python interpreter for both architectures, so no compatibility issues arise.

- **Alternative: ANSI Escape Codes + Raw Input:**  
  Building a custom engine on ANSI codes and reading raw `sys.stdin` would give us fine‑grained control but would require reimplementing many features that `curses` already provides (e.g., keypad mode for arrow keys, window buffering, color pairs). This increases development time and the likelihood of bugs, especially regarding cross‑terminal compatibility. Given our priority on correctness and maintainability, `curses` is the superior choice.

**Rejected Alternative:**
- **`curtsies` or `blessed`:** These third‑party libraries offer more modern APIs but would introduce external dependencies, violating our zero‑dependency rule.
- **Pure ANSI with Manual Input:** Too error‑prone and labor‑intensive for the scope of this project.

### 2. Core TUI Features & Logic Flow

#### 2.1 Navigation

- **Keyboard Input Handling:**  
  We will use `curses`’s `keypad(True)` mode to enable special keys (arrow keys, function keys). Input will be read via `stdscr.getch()` in a non‑blocking or half‑delay mode to allow for real‑time filtering (see below).
  
- **Key Bindings:**
  - `KEY_UP` or `k`: Move cursor up one item.
  - `KEY_DOWN` or `j`: Move cursor down one item.
  - `KEY_RIGHT` or `l` / `Enter`: Open a directory (if item is a folder) or prepare a file for selection (if item is a file).
  - `KEY_LEFT` or `h`: Go up to the parent directory.
  - `Spacebar`: Toggle selection (check/uncheck) of the item under the cursor.
  - `/`: Activate the search/filter bar (see below).
  - `Esc`: Cancel search or return to parent directory (context‑dependent).
  - `q`: Quit the application.

- **State Management:**  
  The TUI will maintain:
  - A stack of visited directories (for navigation history).
  - The current list of `RepoItem` objects for the directory being viewed.
  - The index of the currently highlighted item.
  - A set of selected items (identified by their `path` or `sha` for uniqueness across directories).

#### 2.2 Fuzzy Search / Filtering

- **Architecture:**  
  The search/filter will operate on the currently loaded directory’s items (already fetched from the API). No additional network calls are triggered by keystrokes; filtering is performed purely in‑memory on the displayed list.

- **Algorithm:**  
  We will implement a simple fuzzy filter that matches the user’s input as a subsequence (case‑insensitive) of the item’s `name` or `path`. For example, typing "rdme" will match "README.md". This approach provides a good balance between usability and simplicity.

- **Implementation:**  
  - When the user presses `/`, we clear the input buffer and switch to “filter mode”.
  - Each subsequent character (until `Enter` or `Esc`) is appended to a filter string.
  - On each keystroke, we filter the current directory’s `RepoItem` list to only those items where the filter string appears as a subsequence (case‑insensitive) in either `name` or `path`.
  - The filtered list replaces the displayed list, and the cursor is reset to the top.
  - Pressing `Enter` applies the filter and returns to normal navigation mode (the filter remains active until cleared).
  - Pressing `Esc` cancels the filter and restores the full list.

- **Performance:**  
  Since directory listings are expected to be small (GitHub API returns up to 1000 items per directory, but typical repositories have far fewer), in‑memory filtering is instantaneous and causes no perceptible lag.

#### 2.3 Multi‑Selection Mechanism

- **Selection State:**  
  Selected items are stored in a set (`selected_items`) containing unique identifiers. We will use the item’s `path` (relative to the repository root) as the identifier, as it is unique within a repository and stable across directory views.

- **Toggling Selection:**  
  When the user presses `Spacebar`:
  1. Identify the `RepoItem` under the cursor.
  2. If its `path` is in `selected_items`, remove it (uncheck).
  3. Otherwise, add its `path` to `selected_items` (check).
  4. The visual representation of the item updates immediately to reflect the checked/unchecked state.

- **Persistence Across Directories:**  
  Because selections are keyed by the full `path`, navigating into a subdirectory will still show items as checked if their full path is in the selection set. Conversely, checking a file in a subdirectory will not affect items in parent directories with the same base name.

- **Visual Feedback:**  
  Checked items will be indicated by a prefix (e.g., `[x]`) while unchecked items show `[ ]`. This will be rendered in the item’s line in the list view.

### 3. Visual Layout Blueprint

The terminal screen is divided into logical regions:

```
+---------------------------------------------------------------------------------+
| ghgrab-termux | Owner/Repo: [user/repo] | Path: /current/path                  |  ← Header
+---------------------------------------------------------------------------------+
| [ ] [folder_1]                                                    |          |
| [x] README.md                                                     |          |
| [ ] src/                                                          |  ← Main  |
| [ ] [docs]                                                        |   List   |
| [ ] main.py                                                       |          |
| [ ] .gitignore                                                    |          |
| [ ] ... (more items)                                              |          |
+---------------------------------------------------------------------------------+
| Filter: [_search_term_]                                           |  ← Filter Bar
+---------------------------------------------------------------------------------+
| Selected: 3 items | [Enter] Download | [q] Quit                    |  ← Footer
+---------------------------------------------------------------------------------+
```

**Region Descriptions:**

- **Header (1 line):**  
  - Left: Application name (`ghgrab-termux`).
  - Center: Repository owner/name (e.g., `user/repo`).
  - Right: Current path within the repository (empty for root, otherwise like `/src/utils`).

- **Main List Area (dynamic height):**  
  - Each line represents one `RepoItem`.
  - Items are prefixed with a selection box: `[ ]` for unchecked, `[x]` for checked.
  - Directories are appended with a trailing `/` and their name is bracketed (e.g., `[folder_1]`) to visually distinguish them from files.
  - Files show their name directly (e.g., `README.md`).
  - The currently highlighted item is rendered with reverse video (or bold/underline, depending on `curses` capabilities) to stand out.
  - If the list exceeds the terminal height, the view scrolls to keep the cursor visible.

- **Filter Bar (1 line):**  
  - Shown only when filter mode is active (triggered by `/`).
  - Displays the prompt `Filter: [` followed by the current filter text and a closing `]`.
  - When inactive, this line is hidden to maximize list space.

- **Footer (1 line):**  
  - Left: Count of currently selected items (e.g., `Selected: 3 items`).
  - Center: Primary action (`[Enter] Download`) to initiate downloading of selected items.
  - Right: Quit hint (`[q] Quit`).

**Visual Distinctions:**
- **Directories vs. Files:**  
  Directory names are surrounded by square brackets (`[dirname]`) and have a trailing `/`. File names appear without brackets.
- **Selection State:**  
  Checked items show `[x]`, unchecked show `[ ]`.
- **Cursor Highlight:**  
  The item under the cursor uses `curses.A_REVERSE` (black text on white background) or another highlight attribute if reverse video is problematic in some Termux themes.

**Responsiveness:**  
The layout will adapt to terminal resizes:
- On `KEY_RESIZE` (or manually via `curses.resizeterm()`), we redraw all regions to fit the new dimensions.
- The main list area expands/contracts vertically, while header, filter bar, and footer remain fixed at 1 line each (if visible).

This blueprint provides a clear, intuitive interface that prioritizes keyboard‑driven navigation, real‑time filtering, and persistent multi‑selection—all within the constraints of the Termux environment and our dependency‑free goal.

---

## Step 3 — Download Engine & Recursive Traversal Design

### 1. Folder Traversal Strategy (API Efficiency)

**Chosen Approach:** **Recursive Contents API calls** (navigating folder by folder via `/contents/{path}`).

**Tradeoff Analysis:**

| Approach | Pros | Cons |
|----------|------|------|
| **Recursive Contents API** | - Simple, leverages existing `api_client.get_contents` method.<br>- Each call returns only the immediate children of a directory, keeping payloads small.<br>- Easy to integrate with current TUI state (we already parse `RepoItem` objects).<br>- Allows early termination if user cancels mid‑traversal (we can check after each directory). | - Potential for many API calls in deep repositories (one per directory).<br>- Each request consumes one unit of rate limit (though still well within limits for typical use). |
| **GitHub Trees API (`/git/trees/{sha}?recursive=1`)** | - Single request returns the entire repository tree (if not too large).<br>- Reduces number of HTTP round‑trips. | - Returns a *flat* list of all entries; we would need to rebuild the directory hierarchy ourselves.<br>- Payload can be very large for big repos (hundreds of KB or MB), increasing memory usage and parsing time on the device.<br>- Requires the commit SHA of the default branch (an extra API call to get the reference).<br>- Less flexible for partial traversal (you either get everything or nothing).<br>- The Trees API is rate‑limited like any other endpoint; a large request still consumes significant quota. |

**Decision:**  
Given our emphasis on **dependency control**, **simplicity**, and **rate‑limit friendliness**, the recursive Contents API is preferable. It keeps each request small, reuses our well‑tested `RepoItem` model, and allows us to show progress per‑directory (or even per‑file) in the download phase. The total number of API calls remains modest for typical Termux usage (users are unlikely to download massive monorepos on a phone). Moreover, we can implement a simple concurrency limit (e.g., process directories sequentially) to avoid bursting the rate limit.

We will implement a depth‑first traversal that:
1. Takes a selected `path` (file or directory) from the TUI’s `selected_items` set.
2. If it’s a file, enqueue it for download.
3. If it’s a directory, recursively list its contents via `api_client.get_contents(owner, repo, path)` and process each entry.
4. To avoid exceeding the rate limit, we will insert a short delay (e.g., 0.1 s) between requests if `X-RateLimit-Remaining` drops below a threshold (say 10). This is optional but adds safety.

### 2. Local File Writing & Security (Path Sanitization)

**Goal:** Recreate the selected repository structure under a user‑chosen destination directory (default: `./ghgrab-downloads/<owner>_<repo>` or a path supplied via CLI/environment).

**Implementation Steps:**
- Use Python’s `pathlib.Path` (standard library) for safe, OS‑independent path manipulation.
- Define a base destination directory (`dest_base`). Ensure it is an absolute path (via `Path.resolve()`).
- For each item to download:
  - Compute the relative path from the repository root (the `RepoItem.path` field, already URL‑decoded and normalized by the API engine).
  - Join it with `dest_base` using `Path / item.path`.
  - **Critical Security Check:** Before writing, verify that the resolved absolute path of the target file starts with the resolved absolute path of `dest_base`. This prevents directory‑traversal attacks.
    ```python
    target = (dest_base / rel_path).resolve()
    if not target.is_relative_to(dest_base.resolve()):
        raise ValueError(f"Potential path traversal detected: {rel_path}")
    ```
  - Create parent directories with `target.parent.mkdir(parents=True, exist_ok=True)`.
- **Additional Sanitization:**
  - Reject any path components that are empty or equal to `.` or `..` after splitting (though the `is_relative_to` check already catches escapes).
  - Limit filename length to avoid filesystem issues (optional).
- **Writing Files:**
  - Stream the download via `urllib.request.urlopen` on the `download_url` (provided by the API engine) to avoid loading entire files into memory.
  - Write to a temporary file (`target.with_suffix(target.suffix + '.tmp')`) and rename on success to avoid partially‑written files on interruption.

**Why This Is Secure:**  
The `is_relative_to` check guarantees that no file can be written outside `dest_base`, even if the repository contains malicious paths like `../../etc/passwd`. Using `pathlib` avoids manual string‑based pitfalls.

### 3. Zero‑Dependency Progress Indicator

**Design:** A lightweight, textual progress display printed to stdout after the TUI exits (curses mode ends). We will use a simple “percentage + bar” format updated in‑place via carriage return (`\r`).

**Progress Metrics:**
- For each file being downloaded, we show:
  ```
  [=====>   ] 42% 1.23 MB / 2.93 MB  file.txt
  ```
- The bar width is fixed (e.g., 20 characters). Percentage is computed from bytes transferred so far vs. `Content‑Length` header (if available) or from the `size` field in `RepoItem` (which the API engine already provides).
- If total size is unknown, we fall back to indeterminate spinner or just show bytes downloaded.

**Implementation Details:**
- Re‑use `urllib.request.urlopen` to stream the response in chunks (e.g., 8192 bytes).
- Update the progress line after each chunk.
- After completing a file, print a newline and move to the next file.
- Optionally, show overall progress: “Downloaded 57/132 files”.
- All formatting uses only standard library (`sys.stdout.write`, `flush`).

**Example Output:**
```
Downloading:  [=========>    ] 55%  1.4 MB / 2.5 MB  src/utils.py
Downloaded 3/10 files.
```

This approach provides clear feedback without requiring any external dependencies, works in any Termux terminal, and incurs negligible CPU overhead.

---

End of Step 3 design.
Awaiting Architect's explicit approval before proceeding to download engine implementation.