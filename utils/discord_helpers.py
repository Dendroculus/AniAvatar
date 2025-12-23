"""
Utility helpers for Discord and app_commands interactions.

This module provides reusable helper functions to reduce duplication
when working with Discord API features such as choices, commands,
and interactions.
"""
from typing import TypeVar
from discord import app_commands

T = TypeVar("T")

def create_choices(choices_dict: dict[str, T]) -> list[app_commands.Choice[T]]:
    """
    Create a list of app_commands.Choice objects from a dictionary.

    Args:
        choices_dict (dict[str, T]): A dictionary where keys are the names
                                        and values are the corresponding values
                                        for the choices.
    Returns:
        list[app_commands.Choice[str]]: A list of Choice objects.
    """
    return [
        app_commands.Choice(name=name, value=value) 
        for name, value in choices_dict.items()
        ]


def create_same_choices(choices_list: list[T]) -> list[app_commands.Choice[T]]:
    """
    Create a list of app_commands.Choice objects where names and values are the same.

    Args:
        choices_list (list[T]): A list of strings to be used as both names
                                   and values for the choices.
    Returns:
        list[app_commands.Choice[T]]: A list of Choice objects.
    """
    return [
        app_commands.Choice(name=choice, value=choice) 
        for choice in choices_list
        ]

