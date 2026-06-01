"""Platform module for operational/utility commands.

This module hosts common commands that are not domain-specific mining
logic (data preparation, health checks, web launchers). It lets the CLI
stay modules-only while keeping backward-compatible capabilities.
"""

from alphapilot.modules.platform.module import PlatformModule

__all__ = ["PlatformModule"]
