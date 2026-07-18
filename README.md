# ✨ CleanUp ✨

**CleanUp** is a sophisticated CLI tool designed to intelligently organize your directories. It goes beyond simple extension matching by using MIME type detection, context-aware "Smart Tags," and an interactive mode to ensure your files are always right where they should be.

## 🌟 Key Features

-   **Content-Aware Detection**: Reads each file's **magic bytes** (via `libmagic`) to classify it by its *actual* content — so a JPEG renamed `photo.txt` still lands in `IMAGES/`. Falls back to extension-based detection when `libmagic` isn't installed.
-   **🧠 Smart Sorting (Context-Aware)**: Groups related files into "Themes" based on keywords in their names or parent folders. No more scattering your project files by type!
-   **🤖 Local AI Tagging (optional)**: Re-tags files in the generic buckets (`TEXTS`, `OTHERS`) into meaningful categories — an invoice → `INVOICES`, a log → `LOGS`. Two modes:
    -   `--ai` (default): **deterministic zero-shot** — encodes the file and each candidate category with an embedding model, picks the nearest by cosine similarity. Always returns a name from a fixed list (no hallucinated typos), fast (~ms/file). Runs **in-process** via `fastembed` (`pip install cleanup-cli[embed]`, no server) **or** via Ollama — `--ai-backend local|ollama|auto`.
    -   `--ai-creative`: a **generative LLM** (Ollama) that may invent new category names. More flexible, slower (~seconds/file).
    -   `--ai-images`: **sub-sorts images by content** — screenshots, photos, memes, documents, diagrams, art — into `IMAGES/<type>/`, using local CLIP (`pip install cleanup-cli[image]`). No cloud.
    -   `--ai-adaptive`: **learns from your corrections** — when you re-file something, a similar file is filed the same way next time (a local, embedding-based memory). Teach from the CLI (`--ai-teach FILE CATEGORY`) or by editing a category in the web preview.
    -   Fully offline, no API key; if no backend is available the feature simply switches off.
-   **📊 Insights**: `--stats` (CLI) or the **Insights** tab (web) summarizes a folder — totals, a per-category size breakdown, the largest files, duplicate-reclaimable space, and a by-month histogram.
-   **👀 Watch Mode**: `--watch` keeps a folder tidy continuously — new files are sorted as they arrive, once they finish downloading (size-stability debounce). Every move is undoable and logged; stops cleanly on Ctrl+C or `kill`.
-   **🗂️ Layout Schemes**: Organize by `type` (default), by `date` (`IMAGES/2026/07/`), or by `size` bucket — `--by date|size`.
-   **♊ Duplicate Finder**: Detects identical files by **content hash** (BLAKE2, with a size pre-filter), reports reclaimable space, and can move or trash extra copies — `--dedupe report|move|trash`.
-   **🤝 Interactive Mode**: An "Assistant" mode that asks for your confirmation for themes, unrecognized files, and project folder protection.
-   **🛡️ Safety First**:
    -   `--dry-run`: Preview every move before it happens.
    -   **Multi-level `--undo` / `--redo`**: Step back through *several* past runs, and replay them.
    -   **Trash, not delete**: overwrites and dedupe removals go to the OS trash (recoverable) unless you pass `--no-trash`.
    -   **Run log**: every operation is appended to `.cleanup.log`.
    -   **Project Detection**: Automatically identifies folders like `.git` or `venv` to prevent breaking your projects.
-   **🎨 Modern Interface**: A beautiful terminal UI powered by `rich`, featuring progress bars, stylized panels, and a final summary dashboard.
-   **📋 Rules, Ignore & Profiles**: Force a category by name/size/date with `RULES`; exclude paths with a `.cleanupignore`; save reusable rule sets as profiles (`--profile downloads`). Plus shell completion (`--print-completion bash|zsh`).
-   **⚙️ External Configuration**: Fully customizable via a `cleanup_config.json` file.

## 🚀 Usage

```bash
# Basic sort of the current directory
python Clean_up.py .

# Smart sort with subdirectories and preview only
python Clean_up.py . --smart --recursive --dry-run

# Watch a folder and sort new files as they arrive (Ctrl+C to stop)
python Clean_up.py ~/Downloads --watch

# Full interactive intelligent sort
python Clean_up.py . --smart --recursive --interactive

# Organize by date (IMAGES/2026/07/, ...)
python Clean_up.py . --by date

# Find duplicate files by content
python Clean_up.py . --dedupe report --recursive

# Rollback the last operation (repeat to step further back), then replay it
python Clean_up.py . --undo
python Clean_up.py . --redo
```

## 🖥️ Web GUI

Prefer a visual interface? CleanUp ships a local web app (nothing leaves your machine — it binds to `127.0.0.1`).

```bash
pip install -e ".[content,web]"
cleanup-web            # opens http://127.0.0.1:8765 in your browser
```

- **Folder picker** or paste a path
- **Preview plan** — see every planned move (grouped by category) before committing
- **Apply** with a **live progress** stream (WebSocket)
- **Duplicates** tab — find identical files by content, move or trash extras
- **History** tab — multi-level undo / redo of past runs

The GUI is a thin layer over the same `cleanup.core` engine the CLI uses.
The **🤖 AI** toggle appears automatically when Ollama is running, with a model picker; AI-suggested categories are marked with an `AI` badge in the preview.

## 🤖 Local AI setup (optional)

There are two ways to run the default `--ai` (embedding) mode:

**A) In-process, no server (simplest):**

```bash
pip install "cleanup-cli[embed]"    # adds fastembed (ONNX, CPU)
cleanup ~/Downloads --ai            # downloads a ~130 MB model once, then offline
```

**B) Via Ollama** (also required for `--ai-creative`):

```bash
ollama serve                        # start the local server (http://localhost:11434)
ollama pull nomic-embed-text        # embedding model for --ai (~274 MB)
cleanup ~/Downloads --ai --ai-backend ollama

# Creative mode uses a generative LLM (can invent categories):
ollama pull llama3                  # or mistral, qwen2.5, …
cleanup ~/Downloads --ai-creative --ai-model mistral
```

`--ai-backend auto` (default) prefers the in-process backend if `fastembed` is
installed, otherwise Ollama.

**Adaptive mode** learns from your corrections (stored locally in
`~/.config/cleanup/decisions.json`, or `$CLEANUP_HOME`):

```bash
cleanup ~/Downloads --ai-teach report_q1.pdf REPORTS   # teach once
cleanup ~/Downloads --ai --ai-adaptive                 # similar files → REPORTS
```

In the web GUI, edit a suggested category in the preview to teach the same way.

The default embedding mode is deterministic (categories from a fixed list, no
typos) and much faster than generation. Nothing leaves your machine, and if
Ollama is down CleanUp runs normally without AI.

**Threshold tuning.** A file is only re-tagged when its best category scores
above a cosine threshold (default **0.56**, calibrated on a labeled corpus with
`nomic-embed-text`); below it, the file safely stays in `TEXTS`. Recalibrate on
your own files and override it:

```bash
python scripts/calibrate_threshold.py          # sweep on a built-in labeled corpus
python scripts/calibrate_threshold.py --corpus ~/my_labeled_files
CLEANUP_AI_THRESHOLD=0.60 cleanup ~/Downloads --ai
```

## 🛠️ Options

-   `directory`: The target directory to organize.
-   `--smart`, `-s`: Enable contextual theme-based grouping.
-   `--by`, `-b`: Folder layout: `type` (default), `date` (YYYY/MM), or `size`.
-   `--dedupe [ACTION]`: Find duplicate files by content. `ACTION`: `report` (default), `move` (to `DUPLICATES/`, undoable), `trash`.
-   `--interactive`, `-i`: Enable interactive assistant mode.
-   `--ai`: Categorize ambiguous files by embedding similarity (deterministic).
-   `--ai-backend auto|local|ollama`: Embedding backend for `--ai` (default: `auto`, prefers in-process `local`).
-   `--ai-creative`: Use a generative LLM (Ollama) that can invent new categories.
-   `--ai-adaptive`: Learn from corrections — reuse a remembered category for similar files.
-   `--ai-teach FILE CATEGORY`: Teach the adaptive AI that `FILE` belongs in `CATEGORY`.
-   `--ai-images`: Sub-sort images by content into `IMAGES/<type>/` (local CLIP).
-   `--ai-model MODEL`: Ollama model for `--ai-creative` / `ollama` backend (default: auto-detect).
-   `--stats`: Show a summary of the directory (categories, sizes, largest files, duplicates, by month).
-   `--watch`, `-w`: Watch the directory and sort new files continuously (Ctrl+C to stop).
-   `--interval SEC`: Polling interval for `--watch` (default: 2.0s).
-   `--recursive`, `-r`: Scan subdirectories (includes project detection).
-   `--dry-run`, `-n`: Preview mode (no files are moved).
-   `--clean-empty`: Remove empty subdirectories after sorting.
-   `--undo`, `-u`: Roll back the last operation (repeatable — multi-level).
-   `--redo`: Re-apply the last undone operation.
-   `--no-trash`: Hard-delete on overwrite/dedupe instead of using the OS trash.
-   `--profile NAME`: Load a named profile (`~/.config/cleanup/profiles/NAME.json`).
-   `--print-completion bash|zsh`: Print a shell completion script and exit.
-   `--extensions`, `-e`: Filter sorting to specific extensions (e.g., `py js`).
-   `--conflict`, `-c`: Strategy for duplicate names: `rename` (default), `skip`, `overwrite`.

## ⚙️ Custom Configuration

Create a `cleanup_config.json` in your target folder to customize rules:

```json
{
  "THEMES": {
    "Architecture": ["arch", "logiciel", "uml"],
    "System_Dev": ["linux", "kernel", "drivers"]
  },
  "MIME_CATEGORIES": {
    "LOGS": "startswith:text/x-log"
  },
  "EXT_FALLBACK": {
    "CONFIGS": ["yaml", "yml", "sql"]
  },
  "RULES": [
    {"name": "*.facture.pdf", "category": "INVOICES"},
    {"ext": "psd", "category": "DESIGN"},
    {"min_size": "1GB", "category": "BIG"},
    {"older_than": "365d", "category": "ARCHIVE"}
  ]
}
```

**Rules** (`RULES`) force a category by name/extension/size/age and are applied
*before* content detection and AI — the first matching rule wins.

### `.cleanupignore`

Drop a `.cleanupignore` in a folder to exclude paths (gitignore-style globs):

```
*.tmp
node_modules/
secret*
```

### Profiles

Save a named config at `~/.config/cleanup/profiles/<name>.json` (same shape) and
apply it anywhere with `--profile <name>` (the folder's own `cleanup_config.json`
still overrides it).

### Shell completion

```bash
cleanup --print-completion bash >> ~/.bashrc      # or: zsh
```

## 📦 Requirements & Install

-   **Python 3.10+**
-   Core: `rich`, `pydantic`
-   Optional (recommended) for content detection: `python-magic` + the `libmagic` system library
    -   macOS: `brew install libmagic`
    -   Debian/Ubuntu: `sudo apt install libmagic1`

```bash
# Install as a package (adds a `cleanup` command)
pip install -e ".[content]"

# ...then run it from anywhere
cleanup ~/Downloads --smart

# The legacy entry point still works too
python Clean_up.py ~/Downloads
```

## 🧪 Development

```bash
pip install -e ".[content,dev]"
pytest
```

## 🏗️ Architecture

The engine and the interface are separated so the same logic can drive the CLI
(and, soon, a web GUI):

```
cleanup/
├── core/        # UI-agnostic engine
│   ├── detect.py     # magic-byte + extension detection
│   ├── config.py     # schema-validated rules (pydantic)
│   ├── collect.py    # file discovery + project protection
│   ├── conflict.py   # duplicate-name strategies
│   ├── rules.py      # user rules (name/size/date → category)
│   ├── ignore.py     # .cleanupignore exclusions
│   ├── organize.py   # layout schemes: type / date / size
│   ├── dedupe.py     # content-hash duplicate detection
│   ├── engine.py     # orchestrator, emits progress events
│   ├── watch.py      # polling watch mode (sort new files continuously)
│   ├── stats.py      # directory insights (categories, sizes, duplicates, months)
│   ├── events.py     # event dataclasses
│   ├── history.py    # multi-level undo/redo sessions
│   ├── trash.py      # recoverable removal (send2trash)
│   ├── runlog.py     # append-only .cleanup.log
│   └── manifest.py   # the persisted move record
├── ai/          # optional local AI tagging (opt-in, offline)
│   ├── ollama.py       # dependency-free Ollama HTTP client (generate + embeddings)
│   ├── local_embed.py  # in-process embedding backend (fastembed, no server)
│   ├── backends.py     # embedding backend resolver (local / ollama / auto)
│   ├── classify.py     # Embedding (zero-shot) & Creative (LLM) classifiers + AiInteraction
│   ├── memory.py       # persistent store of user corrections (~/.config/cleanup)
│   ├── adaptive.py     # AdaptiveClassifier — learns from corrections
│   └── images.py       # CLIP image sub-sorting (screenshots/photos/… → IMAGES/<type>)
├── cli/         # Rich terminal interface built on core/
└── web/         # FastAPI backend + self-contained frontend
    ├── service.py    # JSON bridge to the core engine
    ├── server.py     # REST + WebSocket app, `cleanup-web` launcher
    └── static/       # single-page UI (no external assets)
```

The engine reports progress through an event callback and delegates interactive
choices to an `Interaction` object, so batch runs, the CLI, and a future web
backend all share one code path.
