"""Mining log UI translation helper (uses portal i18n when available)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

TranslateFn = Callable[..., str]


def msg(translate: TranslateFn | None, key: str, **kwargs: Any) -> str:
    if translate is not None:
        try:
            return translate(key, **kwargs)
        except KeyError:
            pass
    from alphapilot.modules.portal.i18n import TRANSLATIONS

    text = TRANSLATIONS["zh"].get(key) or TRANSLATIONS["en"].get(key) or key
    return text.format(**kwargs) if kwargs else text
