"""Per-method runners for the AlphaForge baseline search module.

Each runner wraps one of AlphaForge's ``train_{GP,RL}`` entry points as a
class and is imported lazily by :class:`AlphaForgeSearchModule` so that the
heavy / optional dependencies (stable-baselines3 for RL) are only required
when that method is actually invoked.
"""
