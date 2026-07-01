"""Built-in capability systems: data / factor / strategy / backtest / timing.

Each subpackage exposes a ``base.py`` (the system interface) and a
``service.py`` (the default implementation). Systems are attached to the
kernel's :class:`~alphapilot.kernel.engine.MainEngine` and reached by
modules through the :class:`~alphapilot.kernel.context.Context`.
"""
