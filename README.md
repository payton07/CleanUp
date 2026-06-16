# ✨ CleanUp ✨

**CleanUp** is a sophisticated CLI tool designed to intelligently organize your directories. It goes beyond simple extension matching by using MIME type detection, context-aware "Smart Tags," and an interactive mode to ensure your files are always right where they should be.

## 🌟 Key Features

-   **MIME-Type Intelligence**: Detects file categories (IMAGES, VIDEOS, DOCS, etc.) using real file content types, with an extension fallback.
-   **🧠 Smart Sorting (Context-Aware)**: Groups related files into "Themes" based on keywords in their names or parent folders. No more scattering your project files by type!
-   **🤝 Interactive Mode**: An "Assistant" mode that asks for your confirmation for themes, unrecognized files, and project folder protection.
-   **🛡️ Safety First**:
    -   `--dry-run`: Preview every move before it happens.
    -   `--undo`: Instantly rollback the last sorting operation.
    -   **Project Detection**: Automatically identifies folders like `.git` or `venv` to prevent breaking your projects.
-   **🎨 Modern Interface**: A beautiful terminal UI powered by `rich`, featuring progress bars, stylized panels, and a final summary dashboard.
-   **⚙️ External Configuration**: Fully customizable via a `cleanup_config.json` file.

## 🚀 Usage

```bash
# Basic sort of the current directory
python Clean_up.py .

# Smart sort with subdirectories and preview only
python Clean_up.py . --smart --recursive --dry-run

# Full interactive intelligent sort
python Clean_up.py . --smart --recursive --interactive

# Rollback the last operation
python Clean_up.py . --undo
```

## 🛠️ Options

-   `directory`: The target directory to organize.
-   `--smart`, `-s`: Enable contextual theme-based grouping.
-   `--interactive`, `-i`: Enable interactive assistant mode.
-   `--recursive`, `-r`: Scan subdirectories (includes project detection).
-   `--dry-run`, `-n`: Preview mode (no files are moved).
-   `--undo`, `-u`: Rollback the previous operation.
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
  }
}
```

## 📦 Requirements

-   Python 3.7+
-   `rich` library (`pip install rich`)
