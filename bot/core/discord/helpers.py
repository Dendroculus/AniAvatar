"""
Utility helpers for Discord and app_commands interactions.

This module provides reusable helper functions to reduce duplication
when working with Discord API features such as choices, commands,
and interactions.
"""

from typing import TypeVar
from discord import app_commands
from discord.ext import commands

ChoiceT = TypeVar("ChoiceT", str, int, float)


def is_admin():
    """
    Custom check decorator to ensure the user has manage_guild permissions.
    """

    def predicate(ctx: commands.Context) -> bool:
        return ctx.author.guild_permissions.manage_guild

    return commands.check(predicate)


def create_choices(
    choices_dict: dict[str, ChoiceT],
) -> list[app_commands.Choice[ChoiceT]]:
    """
    Create a list of app_commands.Choice objects from a dictionary.

    Args:
        choices_dict (dict[str, ChoiceT]): A dictionary where keys are the names
                                        and values are the corresponding values
                                        for the choices.
    Returns:
        list[app_commands.Choice[ChoiceT]]: A list of Choice objects.
    """
    return [
        app_commands.Choice(name=name, value=value)
        for name, value in choices_dict.items()
    ]


def create_same_choices(
    choices_list: list[ChoiceT],
) -> list[app_commands.Choice[ChoiceT]]:
    """
    Create a list of app_commands.Choice objects where names and values are the same.

    Args:
        choices_list (list[ChoiceT]): A list of strings to be used as both names
                                   and values for the choices.
    Returns:
        list[app_commands.Choice[ChoiceT]]: A list of Choice objects.
    """
    return [app_commands.Choice(name=choice, value=choice) for choice in choices_list]
