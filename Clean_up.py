#!/usr/bin/env python3
"""
CleanUp — Tri de fichiers par type avec détection MIME
Usage : python cleanup.py <répertoire> [options]
"""

import os
import sys
import json
import shutil
import mimetypes
import argparse
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
from rich.prompt import Prompt, Confirm
from rich.theme import Theme

# Configuration du thème personnalisé
custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "theme": "magenta",
    "category": "blue",
    "dry": "italic dim white"
})

console = Console(theme=custom_theme)

# ─── UTILITAIRES ───────────────────────────────────────────────────────────────

def user_confirm(prompt: str, default: bool = True) -> bool:
    """Demande une confirmation à l'utilisateur via Rich."""
    return Confirm.ask(f"[info]{prompt}[/info]", default=default, console=console)

def user_choice(prompt: str, options: dict[str, str]) -> str:
    """Demande un choix parmi plusieurs options via Rich."""
    choices = list(options.keys())
    desc = ", ".join(f"[bold]{k}[/bold]: {v}" for k, v in options.items())
    console.print(f"  {desc}")
    return Prompt.ask(f"[info]{prompt}[/info]", choices=choices, console=console)

def is_project_folder(path: Path) -> bool:
    """Détecte si un dossier ressemble à un projet cohérent."""
    indicators = {".git", ".svn", "package.json", "pom.xml", "requirements.txt", "venv", ".vscode", "Makefile"}
    if not path.is_dir():
        return False
    try:
        content = {p.name for p in path.iterdir()}
        return not indicators.isdisjoint(content)
    except PermissionError:
        return False

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

MANIFEST_FILE = ".cleanup_manifest.json"
CONFIG_FILE = "cleanup_config.json"

# Mots-clés pour le tri par thème (Smart Tags)
THEMES: dict[str, list[str]] = {}

# Catégories détectées via prédicats MIME (détection primaire)
MIME_CATEGORIES: dict[str, callable] = {
    "IMAGES":   lambda m: m.startswith("image/"),
    "VIDEOS":   lambda m: m.startswith("video/"),
    "AUDIOS":   lambda m: m.startswith("audio/"),
    "TEXTS":    lambda m: m.startswith("text/") and m not in {
        "text/x-python", "text/x-c", "text/x-java-source",
        "text/javascript", "text/html", "text/css",
    },
    "SCRIPTS":  lambda m: m in {
        "text/x-python", "application/javascript", "text/javascript",
        "text/x-c", "text/x-java-source", "text/html", "text/css",
        "application/x-sh",
    },
    "DOCS":     lambda m: m in {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    },
    "ARCHIVES": lambda m: m in {
        "application/zip", "application/x-tar", "application/gzip",
        "application/x-bzip2", "application/x-7z-compressed",
        "application/x-rar-compressed",
    },
}

# Fallback par extension (si mimetypes ne reconnaît pas le type)
EXT_FALLBACK: dict[str, set] = {
    "IMAGES":   {"jpeg", "jpg", "png", "gif", "bmp", "svg", "webp", "ico", "tiff", "heic"},
    "VIDEOS":   {"mp4", "mkv", "avi", "mov", "wmv", "flv", "webm"},
    "AUDIOS":   {"mp3", "wav", "flac", "aac", "ogg", "m4a"},
    "DOCS":     {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods"},
    "ARCHIVES": {"zip", "tar", "gz", "bz2", "7z", "rar"},
    "SCRIPTS":  {"py", "js", "ts", "c", "cpp", "java", "html", "css", "sh", "rb", "go", "rs"},
    "TEXTS":    {"txt", "md", "csv", "json", "xml", "yaml", "yml", "ini", "cfg", "log", "env"},
}

def load_external_config(directory: Path):
    """Charge les catégories depuis cleanup_config.json s'il existe."""
    config_path = directory / CONFIG_FILE
    if not config_path.exists():
        return

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            
        if "EXT_FALLBACK" in config:
            for cat, exts in config["EXT_FALLBACK"].items():
                EXT_FALLBACK[cat] = set(exts)
                
        if "MIME_CATEGORIES" in config:
            updated_mime = {}
            for cat, rule in config["MIME_CATEGORIES"].items():
                if rule.startswith("startswith:"):
                    prefix = rule.split("startswith:")[1]
                    updated_mime[cat] = lambda m, p=prefix: m.startswith(p)
                elif rule.startswith("in:"):
                    allowed = set(rule.split("in:")[1].strip("[]").split(","))
                    updated_mime[cat] = lambda m, a=allowed: m in a
            
            # Conserver les anciens qui n'ont pas été écrasés (en fin de liste)
            for cat, pred in MIME_CATEGORIES.items():
                if cat not in updated_mime:
                    updated_mime[cat] = pred
            
            MIME_CATEGORIES.clear()
            MIME_CATEGORIES.update(updated_mime)
        
        # Mettre à jour les dossiers gérés
        global MANAGED_DIRS
        MANAGED_DIRS = set(MIME_CATEGORIES.keys()) | {"OTHERS"}

        if "THEMES" in config:
            for theme, keywords in config["THEMES"].items():
                THEMES[theme] = [k.lower() for k in keywords]

        console.print(f"  [success]✔[/success] Configuration chargée depuis [bold cyan]{CONFIG_FILE}[/bold cyan]")
    except Exception as e:
        console.print(f"  [warning]⚠[/warning] Erreur lors du chargement de la config : {e}")

# Dossiers gérés par le script (exclus du tri récursif)
MANAGED_DIRS = set(MIME_CATEGORIES.keys()) | {"OTHERS"}


# ─── DÉTECTION ────────────────────────────────────────────────────────────────

def detect_theme(path: Path) -> str | None:
    """Détecte un thème basé sur les mots-clés dans le nom ou le dossier parent."""
    # On regarde le nom du fichier et les noms des dossiers parents
    search_space = (path.name + " " + " ".join(path.parts)).lower()
    
    for theme, keywords in THEMES.items():
        if any(k in search_space for k in keywords):
            return theme
    return None

def detect_category(path: Path) -> str:
    """Détecte la catégorie d'un fichier via MIME type, avec fallback sur l'extension."""
    mime, _ = mimetypes.guess_type(str(path))

    if mime:
        for category, predicate in MIME_CATEGORIES.items():
            if predicate(mime):
                return category

    # Fallback extension
    ext = path.suffix.lstrip(".").lower()
    for category, extensions in EXT_FALLBACK.items():
        if ext in extensions:
            return category

    return "OTHERS"


# ─── GESTION DES CONFLITS ─────────────────────────────────────────────────────

def resolve_conflict(dest: Path, strategy: str) -> Path | None:
    """
    Résout un conflit de nom selon la stratégie choisie.
    Retourne None si le fichier doit être ignoré (strategy='skip').
    """
    if not dest.exists():
        return dest

    if strategy == "skip":
        return None

    if strategy == "overwrite":
        return dest

    # strategy == "rename" : suffixe numéroté
    stem, suffix = dest.stem, dest.suffix
    counter = 1
    while True:
        candidate = dest.parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


# ─── COLLECTE ─────────────────────────────────────────────────────────────────

def collect_files(
    directory: Path,
    recursive: bool,
    filter_exts: set[str] | None = None,
    interactive: bool = False,
) -> list[Path]:
    """
    Liste tous les fichiers à trier dans le répertoire.
    En mode récursif, exclut les fichiers déjà dans un dossier géré.
    """
    files = []
    
    def scan(current_dir: Path):
        try:
            for p in current_dir.iterdir():
                if p.name == MANIFEST_FILE or p.name == CONFIG_FILE:
                    continue
                
                if p.is_file():
                    if filter_exts is None or p.suffix.lstrip(".").lower() in filter_exts:
                        files.append(p)
                
                elif p.is_dir() and recursive and p.name not in MANAGED_DIRS:
                    if interactive and is_project_folder(p):
                        if not user_confirm(f"Dossier '{p.name}' détecté comme projet. L'ignorer ?", default=True):
                            scan(p)
                    else:
                        scan(p)
        except PermissionError:
            console.print(f"  [warning]⚠[/warning] Permission refusée pour [bold]{current_dir}[/bold]")

    if recursive:
        scan(directory)
    else:
        files = [
            f for f in directory.iterdir()
            if f.is_file() and f.name != MANIFEST_FILE and f.name != CONFIG_FILE
            and (filter_exts is None or f.suffix.lstrip(".").lower() in filter_exts)
        ]

    return files


# ─── TRI ──────────────────────────────────────────────────────────────────────

def sort_files(
    directory: Path,
    files: list[Path],
    conflict_strategy: str,
    dry_run: bool,
    smart: bool = False,
    interactive: bool = False,
) -> list[dict]:
    """
    Déplace les fichiers vers leurs dossiers de catégorie.
    Retourne le manifest des opérations effectuées (vide en dry-run).
    """
    manifest = []
    skipped = 0
    total = len(files)
    
    theme_decisions: dict[str, bool] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Traitement...", total=total)

        for file in files:
            category = detect_category(file)
            theme = detect_theme(file) if smart else None
            
            # Mode Interactif : Validation du thème
            if interactive and theme:
                if theme not in theme_decisions:
                    theme_decisions[theme] = user_confirm(f"Grouper le fichier '{file.name}' dans le thème '{theme}' ?", default=True)
                if not theme_decisions[theme]:
                    theme = None
            
            # Mode Interactif : Gestion des inconnus
            if interactive and category == "OTHERS":
                choice = user_choice(f"Le fichier '{file.name}' n'est pas reconnu. Que faire ?", 
                                     {"o": "others", "s": "skip", "n": "new category"})
                if choice == "s":
                    skipped += 1
                    progress.advance(task)
                    continue
                elif choice == "n":
                    new_cat = Prompt.ask("  [info]Nom de la nouvelle catégorie[/info]", console=console).strip().upper()
                    if new_cat:
                        category = new_cat
                        MANAGED_DIRS.add(new_cat)

            # Structure de destination
            dest_path = Path(theme) / category if theme else Path(category)
            dest_dir = directory / dest_path
            
            # Résolution de conflit
            target = dest_dir / file.name
            strategy = conflict_strategy
            if interactive and target.exists():
                console.print(f"  [warning]⚠ CONFLIT[/warning] Le fichier [bold]{target.name}[/bold] existe déjà dans [bold cyan]{dest_path}[/bold cyan]")
                strategy_choice = user_choice("Action ?", {"r": "rename", "s": "skip", "o": "overwrite"})
                strategy = {"r": "rename", "s": "skip", "o": "overwrite"}[strategy_choice]
                
            resolved = resolve_conflict(target, strategy)

            if resolved is None:
                if dry_run:
                    console.print(f"  [error]SKIPPED[/error]  {file.relative_to(directory)}")
                skipped += 1
                progress.advance(task)
                continue

            rel_src = file.relative_to(directory)
            rel_dest = str(dest_path / resolved.name)

            if dry_run:
                console.print(f"  [dry]DRY-RUN[/dry]  {rel_src} [bold]→[/bold] [category]{rel_dest}[/category]")
            else:
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(file), str(resolved))
                manifest.append({
                    "src": str(file),
                    "dest": str(resolved),
                    "category": category,
                    "theme": theme,
                    "timestamp": datetime.now().isoformat(),
                })
            
            progress.advance(task)

    if skipped:
        console.print(f"\n  [warning]⚠ {skipped} fichier(s) ignoré(s)[/warning]")

    return manifest


# ─── MANIFEST ─────────────────────────────────────────────────────────────────

def save_manifest(directory: Path, manifest: list[dict]) -> None:
    """Ajoute les entrées au manifest JSON persistant (pour undo)."""
    manifest_path = directory / MANIFEST_FILE
    existing: list[dict] = []

    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            existing = json.load(f)

    existing.extend(manifest)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    console.print(f"\n  [info]Manifest sauvegardé[/info]  [bold]→[/bold] [bold cyan]{manifest_path.name}[/bold cyan]")


# ─── UNDO ─────────────────────────────────────────────────────────────────────

def undo_last(directory: Path) -> None:
    """Annule le dernier tri en inversant toutes les opérations du manifest."""
    manifest_path = directory / MANIFEST_FILE

    if not manifest_path.exists():
        console.print("[error]❌ Aucun manifest trouvé. Pas d'opération à annuler.[/error]")
        sys.exit(1)

    with open(manifest_path, encoding="utf-8") as f:
        entries: list[dict] = json.load(f)

    if not entries:
        console.print("[info]ℹ Le manifest est vide. Rien à annuler.[/info]")
        return

    errors: list[Path] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Annulation...", total=len(entries))
        
        for entry in reversed(entries):
            src, dest = Path(entry["src"]), Path(entry["dest"])
            if dest.exists():
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dest), str(src))
            else:
                errors.append(dest)
            progress.advance(task)

    # Nettoyer les dossiers de catégorie et de thème devenus vides
    all_potential_dirs = set(MANAGED_DIRS) | set(THEMES.keys())
    for folder in all_potential_dirs:
        folder_path = directory / folder
        if folder_path.exists() and folder_path.is_dir():
            # Nettoyage récursif des sous-dossiers vides
            for sub in folder_path.iterdir():
                if sub.is_dir() and not any(sub.iterdir()):
                    sub.rmdir()
            
            # Nettoyage du dossier principal s'il est vide
            if not any(folder_path.iterdir()):
                folder_path.rmdir()

    manifest_path.unlink()
    console.print(f"\n  [success]✔ Undo terminé avec succès.[/success]")

    if errors:
        console.print(f"\n  [warning]⚠ {len(errors)} fichier(s) introuvable(s) lors du rollback.[/warning]")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cleanup",
        description="Trie les fichiers d'un répertoire par type (détection MIME + fallback extension).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
exemples :
  python cleanup.py ~/Downloads
  python cleanup.py ~/Downloads --dry-run
  python cleanup.py ~/Downloads --extensions py js ts --conflict skip
  python cleanup.py ~/Downloads --recursive --conflict rename
  python cleanup.py ~/Downloads --undo
        """,
    )

    parser.add_argument(
        "directory",
        type=Path,
        help="Répertoire à trier",
    )
    parser.add_argument(
        "--extensions", "-e",
        nargs="+", metavar="EXT",
        help="Filtrer sur des extensions précises (ex: py js png)",
    )
    parser.add_argument(
        "--recursive", "-r",
        action="store_true",
        help="Descendre dans les sous-dossiers",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Prévisualiser les déplacements sans les exécuter",
    )
    parser.add_argument(
        "--conflict", "-c",
        choices=["rename", "skip", "overwrite"],
        default="rename",
        help="Comportement en cas de doublon de nom (défaut : rename)",
    )
    parser.add_argument(
        "--undo", "-u",
        action="store_true",
        help="Annuler le dernier tri (rollback via manifest)",
    )
    parser.add_argument(
        "--smart", "-s",
        action="store_true",
        help="Activer le tri contextuel par thèmes (Smart Tags)",
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Activer le mode interactif (demande confirmation pour les actions)",
    )

    return parser


def print_summary(manifest: list[dict], dry_run: bool):
    """Affiche un tableau récapitulatif des opérations."""
    if not manifest and not dry_run:
        return

    table = Table(title="Résumé des opérations", box=None)
    table.add_column("Fichier", style="cyan")
    table.add_column("Thème", style="magenta")
    table.add_column("Catégorie", style="blue")
    table.add_column("Statut", style="green")

    for entry in manifest[:15]: # Limiter l'affichage si trop de fichiers
        table.add_row(
            Path(entry["src"]).name,
            entry["theme"] or "-",
            entry["category"],
            "Déplacé"
        )
    
    if len(manifest) > 15:
        table.add_row(f"... et {len(manifest) - 15} autres fichiers", "", "", "")

    console.print("\n")
    console.print(table)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    directory = args.directory.resolve()

    if not directory.is_dir():
        console.print(f"[error]❌ ERREUR : '{directory}' n'est pas un répertoire valide.[/error]")
        sys.exit(1)

    # Banner
    console.print(Panel.fit(
        "[bold cyan]✨ CleanUp ✨[/bold cyan]\n[italic]Tri de fichiers intelligent & contextuel[/italic]",
        border_style="blue"
    ))

    # Charger la config externe si elle existe
    load_external_config(directory)

    # ── Undo ──
    if args.undo:
        undo_last(directory)
        return

    # ── Tri ──
    filter_exts = set(args.extensions) if args.extensions else None
    files = collect_files(directory, args.recursive, filter_exts, args.interactive)

    if not files:
        console.print("\n  [info]ℹ Aucun fichier à trier.[/info]")
        return

    console.print(f"\n  [bold]{len(files)}[/bold] fichier(s) détecté(s)")
    if args.recursive: console.print("  [dim]• Mode récursif activé[/dim]")
    if args.dry_run:   console.print("  [warning]• ⚠ DRY-RUN — simulation uniquement[/warning]")
    if args.smart:     console.print("  [magenta]• 🧠 Tri contextuel activé (Smart Tags)[/magenta]")
    if args.interactive: console.print("  [cyan]• 🤝 Mode interactif activé[/cyan]")
    console.print()

    manifest = sort_files(directory, files, args.conflict, args.dry_run, args.smart, args.interactive)

    if not args.dry_run and manifest:
        save_manifest(directory, manifest)
        print_summary(manifest, args.dry_run)

    status = "[italic]simulés[/italic]" if args.dry_run else "[bold success]déplacés[/bold success]"
    console.print(f"\n  [bold success]✨ Terminé[/bold success] — {len(manifest)} fichier(s) {status}.")


if __name__ == "__main__":
    main()
