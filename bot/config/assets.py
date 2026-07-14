"""Asset discovery, validation, and safe path resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .paths import (
    BACKGROUND_PATH,
    ESSENTIAL_ICON_PATH,
    FONT_PATH,
    RANK_ICON_PATH,
    SHOP_ASSET_PATH,
)


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_NATURAL_PART_RE = re.compile(r"(\d+)")


def _natural_key(value: str) -> tuple[object, ...]:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in _NATURAL_PART_RE.split(value)
    )


@dataclass(frozen=True, slots=True)
class ThemeAsset:
    id: str
    label: str
    directory: Path


@dataclass(frozen=True, slots=True)
class BackgroundAsset:
    id: str
    label: str
    filename: str
    path: Path
    order: int


class AssetCatalog:
    """Discover application assets without scattering path literals."""

    def __init__(self, background_root: Path = BACKGROUND_PATH) -> None:
        self.background_root = background_root

    @lru_cache(maxsize=1)
    def list_themes(self) -> tuple[ThemeAsset, ...]:
        if not self.background_root.is_dir():
            return ()

        themes: list[ThemeAsset] = []
        seen: set[str] = set()
        directories = sorted(
            (item for item in self.background_root.iterdir() if item.is_dir()),
            key=lambda item: _natural_key(item.name),
        )
        for directory in directories:
            lookup = directory.name.casefold()
            if lookup in seen:
                continue
            seen.add(lookup)
            themes.append(
                ThemeAsset(
                    id=directory.name,
                    label=directory.name.replace("_", " ").title(),
                    directory=directory,
                )
            )
        return tuple(themes)

    def resolve_theme(self, theme_name: str | None) -> ThemeAsset | None:
        if not theme_name:
            return None
        lookup = theme_name.casefold()
        return next(
            (theme for theme in self.list_themes() if theme.id.casefold() == lookup),
            None,
        )

    @lru_cache(maxsize=64)
    def list_backgrounds(self, theme_name: str) -> tuple[BackgroundAsset, ...]:
        theme = self.resolve_theme(theme_name)
        if theme is None:
            return ()
        files = sorted(
            (
                item
                for item in theme.directory.iterdir()
                if item.is_file() and item.suffix.casefold() in IMAGE_SUFFIXES
            ),
            key=lambda item: _natural_key(item.name),
        )
        return tuple(
            BackgroundAsset(
                id=f"{theme.id.casefold()}-{index:02d}",
                label=f"Theme {index}",
                filename=file.name,
                path=file,
                order=index,
            )
            for index, file in enumerate(files, start=1)
        )

    def resolve_background(
        self,
        theme_name: str | None,
        background_file: str | None,
    ) -> Path | None:
        if (
            not theme_name
            or theme_name.casefold() == "default"
            or not background_file
            or background_file.casefold() == "null"
        ):
            return None
        requested_name = Path(background_file).name
        if requested_name != background_file:
            return None
        for asset in self.list_backgrounds(theme_name):
            if asset.filename.casefold() == requested_name.casefold():
                return asset.path
        return None

    def background_label(
        self,
        theme_name: str | None,
        background_file: str | None,
    ) -> str:
        if not background_file:
            return "Default"
        requested = Path(background_file).name.casefold()
        for asset in self.list_backgrounds(theme_name or ""):
            if asset.filename.casefold() == requested:
                return asset.label
        return Path(background_file).stem.replace("_", " ").title()

    def validate_required(self) -> tuple[str, ...]:
        missing: list[str] = []
        for label, path in AssetPaths.required_files().items():
            if not path.is_file():
                missing.append(f"{label}: {path}")
        return tuple(missing)


_RANK_TITLES = (
    "Novice",
    "Warrior",
    "Elite",
    "Champion",
    "Hero",
    "Legend",
    "Mythic",
    "Ascendant",
    "Immortal",
    "Celestial",
    "Transcendent",
    "Aetherborn",
    "Cosmic",
    "Divine",
    "Eternal",
    "Enlightened",
)


class AssetPaths:
    """Compatibility registry backed by canonical Path objects."""

    FONTS = {
        "bold": str(FONT_PATH / "gg sans Bold.ttf"),
        "medium": str(FONT_PATH / "gg sans Medium.ttf"),
        "regular": str(FONT_PATH / "gg sans Regular.ttf"),
        "semibold": str(FONT_PATH / "gg sans Semibold.ttf"),
        "cjk": str(FONT_PATH / "NotoSerifCJK.ttf"),
    }
    TITLE_EMOJI_FILES = {
        title: str(RANK_ICON_PATH / f"{title.upper()}.png") for title in _RANK_TITLES
    }
    ESSENTIAL_ICONS = {
        name: str(ESSENTIAL_ICON_PATH / filename)
        for name, filename in {
            "CHART": "CHART.png",
            "EXP": "EXP.png",
            "GRAY_LARGE_SQUARE": "Gray_Large_Square.png",
            "LEVEL_UP": "LEVELUP.png",
            "RIGHTWARD_ARROW": "RIGHTWARDARROW.png",
            "SECRET_BOX": "SecretBox.png",
            "VERIFIED": "VERIFIED.png",
        }.items()
    }
    SHOP_FILES = {
        name: str(SHOP_ASSET_PATH / filename)
        for name, filename in {
            "COINS": "Coins.png",
            "SHOP_ICON": "SHOP ICON.png",
            "SMALL_EXP_POTION": "SmallExpBoostPotion.png",
            "MEDIUM_EXP_POTION": "MediumExpBoostPotion.png",
            "LARGE_EXP_POTION": "LargeExpBoostPotion.png",
            "LEVEL_SKIP_TOKEN": "LevelSkipToken.png",
        }.items()
    }

    @classmethod
    def required_files(cls) -> dict[str, Path]:
        required = {f"font.{name}": Path(path) for name, path in cls.FONTS.items()}
        required.update(
            {f"rank.{name}": Path(path) for name, path in cls.TITLE_EMOJI_FILES.items()}
        )
        required["essential.EXP"] = Path(cls.ESSENTIAL_ICONS["EXP"])
        return required


asset_catalog = AssetCatalog()


def resolve_background_path(
    theme_name: str | None,
    background_file: str | None,
) -> str:
    """Return an exact case-safe background path or an empty string."""
    path = asset_catalog.resolve_background(theme_name, background_file)
    return str(path) if path is not None else ""
