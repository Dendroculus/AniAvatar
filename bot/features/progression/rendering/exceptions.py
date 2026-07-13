"""Exceptions raised by progression image rendering."""


class AvatarError(Exception):
    """Base exception for avatar-related issues."""


class AvatarLoadError(AvatarError):
    """Raised when avatar bytes are present but cannot be decoded/loaded."""


class AvatarBytesMissing(AvatarError):
    """Raised when avatar bytes are missing."""
