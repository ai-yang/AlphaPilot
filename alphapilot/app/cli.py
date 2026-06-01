"""CLI entrance for AlphaPilot (modules-only command routing)."""

try:
    from dotenv import load_dotenv

    load_dotenv(".env")
    # 1) Make sure it is at the beginning of the script so that it will load dotenv before initializing BaseSettings.
    # 2) The ".env" argument is necessary to make sure it loads `.env` from the current directory.
except Exception:  # noqa: BLE001 - CLI still works without python-dotenv
    pass

import fire


def _module_commands():
    """Collect CLI subcommands contributed by loaded kernel modules.

    The engine loads the four built-in systems + the alpha_mining module
    and discovers any third-party systems/modules via entry points. Built-in
    explicit commands (defined below) take precedence; module-contributed
    commands extend the CLI surface for plug-and-play features.
    """
    try:
        from alphapilot.kernel import build_engine

        engine = build_engine()
        return engine.collect_commands()
    except Exception as exc:  # noqa: BLE001 - never let plugins break the CLI
        from alphapilot.log import logger

        logger.warning(f"Skipping kernel module command discovery: {exc}")
        return {}


def app():
    commands = _module_commands()
    if not commands:
        raise RuntimeError(
            "No commands are available from modules. "
            "Check module registration / plugin loading."
        )
    fire.Fire(commands)
