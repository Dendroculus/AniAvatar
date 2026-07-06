from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


"""
rebase.py

Mechanical project rebase script for AniAvatar.

What it does:
1. Moves old top-level code folders into a generic bot/ package.
2. Updates Python imports automatically.
3. Updates dynamic extension strings like "cogs.general" -> "bot.cogs.general".
4. Creates missing __init__.py files.
5. Deletes empty folders after moving.

What it does NOT do:
- It does not rewrite architecture deeply.
- It does not split huge files like profile_cards.py.
- It does not touch assets, docs, data, README, requirements, LICENSE, or .env.

Run dry-run first:

    python rebase.py

Apply for real:

    python rebase.py --apply
"""


MOVE_RULES = [
    # old path, new path, old import package, new import package
    ("cogs", "bot/cogs", "cogs", "bot.cogs"),
    ("constants", "bot/config", "constants", "bot.config"),
    ("loggers", "bot/core/logging_config", "loggers", "bot.core.logging_config"),
    ("search_engine", "bot/features/animepfp/search_engine", "search_engine", "bot.features.animepfp.search_engine"),
    ("services", "bot/services", "services", "bot.services"),
    ("utils", "bot/utils", "utils", "bot.utils"),
]


IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "ENV",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
}


PYTHON_FILE_IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "ENV",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
}


def log(message: str) -> None:
    print(message)


def run_git_status(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return []

    if result.returncode != 0:
        return []

    return [line for line in result.stdout.splitlines() if line.strip()]


def ensure_git_clean(root: Path, allow_dirty: bool) -> None:
    dirty = run_git_status(root)

    # Ignore the rebase.py script itself if it is newly created.
    dirty_without_this_script = [
        line for line in dirty
        if not line.endswith(" rebase.py") and not line.endswith(" rebase.py\r")
    ]

    if dirty_without_this_script and not allow_dirty:
        log("[ERROR] Git working tree has existing changes.")
        log("")
        log("Commit/stash them first, or run with:")
        log("    python rebase.py --apply --allow-dirty")
        log("")
        log("Current changes:")
        for line in dirty_without_this_script:
            log(f"    {line}")
        sys.exit(1)


def is_inside_ignored_dir(path: Path, root: Path, ignored: set[str]) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True

    return any(part in ignored for part in relative.parts)


def ensure_init_file(path: Path, apply: bool) -> None:
    init_file = path / "__init__.py"

    if init_file.exists():
        return

    if apply:
        path.mkdir(parents=True, exist_ok=True)
        init_file.write_text('"""Package initializer."""\n', encoding="utf-8")

    log(f"[CREATE] {init_file}")


def ensure_package_inits(root: Path, apply: bool) -> None:
    package_dirs = {
        root / "bot",
        root / "bot" / "core",
        root / "bot" / "core" / "logging_config",
        root / "bot" / "features",
        root / "bot" / "features" / "animepfp",
        root / "bot" / "features" / "animepfp" / "search_engine",
        root / "bot" / "services",
        root / "bot" / "utils",
        root / "bot" / "config",
        root / "bot" / "cogs",
    }

    for package_dir in sorted(package_dirs):
        ensure_init_file(package_dir, apply)


def move_folder(root: Path, old_rel: str, new_rel: str, apply: bool) -> None:
    src = root / old_rel
    dst = root / new_rel

    if not src.exists():
        log(f"[SKIP] {old_rel} not found")
        return

    if dst.exists():
        log(f"[SKIP] {new_rel} already exists")
        return

    if apply:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))

    log(f"[MOVE] {old_rel} -> {new_rel}")


def update_imports_in_text(text: str) -> str:
    new_text = text

    for _old_path, _new_path, old_pkg, new_pkg in MOVE_RULES:
        # from constants.configs import X
        # from utils.progression.profile_cards import X
        new_text = re.sub(
            rf"(?m)^(\s*from\s+){re.escape(old_pkg)}(\.[A-Za-z_][\w\.]*)?(\s+import\s+)",
            lambda m: f"{m.group(1)}{new_pkg}{m.group(2) or ''}{m.group(3)}",
            new_text,
        )

        # import constants
        # import constants.configs
        # import utils.progression.profile_cards
        new_text = re.sub(
            rf"(?m)^(\s*import\s+){re.escape(old_pkg)}(\.[A-Za-z_][\w\.]*)?(\s*(?:#.*)?$)",
            lambda m: f"{m.group(1)}{new_pkg}{m.group(2) or ''}{m.group(3)}",
            new_text,
        )

        # Dynamic extension strings:
        # "cogs.general" -> "bot.cogs.general"
        # 'utils.dev_commands' -> 'bot.utils.dev_commands'
        new_text = new_text.replace(f'"{old_pkg}.', f'"{new_pkg}.')
        new_text = new_text.replace(f"'{old_pkg}.", f"'{new_pkg}.")

    return new_text


def iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []

    for path in root.rglob("*.py"):
        if is_inside_ignored_dir(path, root, PYTHON_FILE_IGNORE_DIRS):
            continue
        if path.name == "rebase.py":
            continue
        files.append(path)

    return sorted(files)


def update_python_imports(root: Path, apply: bool) -> None:
    for path in iter_python_files(root):
        old_text = path.read_text(encoding="utf-8", errors="replace")
        new_text = update_imports_in_text(old_text)

        if new_text == old_text:
            continue

        if apply:
            path.write_text(new_text, encoding="utf-8")

        log(f"[UPDATE IMPORTS] {path.relative_to(root)}")


def delete_empty_folders(root: Path, apply: bool) -> None:
    deleted_any = True

    while deleted_any:
        deleted_any = False

        for current_root, dirnames, filenames in os.walk(root, topdown=False):
            current = Path(current_root)

            if current == root:
                continue

            if is_inside_ignored_dir(current, root, IGNORE_DIRS):
                continue

            try:
                # Refresh actual folder contents.
                children = list(current.iterdir())
            except FileNotFoundError:
                continue

            if children:
                continue

            if apply:
                current.rmdir()

            log(f"[DELETE EMPTY DIR] {current.relative_to(root)}")
            deleted_any = True


def print_summary() -> None:
    log("")
    log("Next checks:")
    log("    python -m compileall .")
    log("    python main.py")
    log("")
    log("Search for missed old imports:")
    log('    Select-String -Path .\\**\\*.py -Pattern "from constants|from utils|from services|from loggers|from search_engine|from cogs|import constants|import utils|import services|import loggers|import search_engine|import cogs"')
    log("")
    log("Then inspect:")
    log("    git diff --stat")
    log("    git diff")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mechanically move AniAvatar code into a generic bot/ package.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually move files and rewrite imports. Without this flag, the script only previews changes.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow running even when Git has existing uncommitted changes.",
    )
    args = parser.parse_args()

    root = Path.cwd().resolve()

    if not (root / "main.py").exists():
        log("[ERROR] main.py not found. Run this script from the AniAvatar repo root.")
        sys.exit(1)

    if not args.apply:
        log("[DRY RUN] No files will be changed.")
        log("Use this to apply:")
        log("    python rebase.py --apply")
        log("")

    if args.apply:
        ensure_git_clean(root, allow_dirty=args.allow_dirty)

    log(f"[ROOT] {root}")
    log("")

    for old_path, new_path, _old_pkg, _new_pkg in MOVE_RULES:
        move_folder(root, old_path, new_path, args.apply)

    log("")
    ensure_package_inits(root, args.apply)

    log("")
    update_python_imports(root, args.apply)

    log("")
    delete_empty_folders(root, args.apply)

    print_summary()


if __name__ == "__main__":
    main()