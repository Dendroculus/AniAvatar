"""
Services layer for handling business logic, data persistence, and resource management.

This package isolates heavy logic from the Discord Cogs to ensure separation of concerns.

Modules:
    - user_repository: Handles direct database interactions for user progression, economy, and themes.
    - render_manager: Manages CPU-intensive image generation, caching, and process pools.
"""