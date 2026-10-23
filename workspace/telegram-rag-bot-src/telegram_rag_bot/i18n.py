"""Explicit YAML locale loading and strict dotted-key UI translation.

No locale is read on import. load_locale activates a validated catalog and
returns an independent copy. Missing keys/placeholders raise KeyError; invalid
catalogs/templates raise ValueError. Only simple named {placeholders} are
supported (plus escaped braces); no attribute/index access or format specs.
"""

from copy import deepcopy
from pathlib import Path
from string import Formatter

import yaml

_catalog: dict | None = None
_formatter = Formatter()


def _validate_catalog(node: object, ancestors: frozenset[int] = frozenset()) -> None:
    if not isinstance(node, dict) or not node:
        raise ValueError("locale must contain nonempty mappings with string leaves")
    if id(node) in ancestors:
        raise ValueError("locale must not contain recursive aliases")
    ancestors = ancestors | {id(node)}
    for key, value in node.items():
        if not isinstance(key, str) or not key or "." in key:
            raise ValueError("locale keys must be nonempty strings without dots")
        if isinstance(value, dict):
            _validate_catalog(value, ancestors)
            continue
        if not isinstance(value, str):
            raise ValueError("locale leaves must be strings")
        for _, field, spec, conversion in _formatter.parse(value):
            if field is not None and (
                not field.isidentifier() or spec or conversion is not None
            ):
                raise ValueError("locale templates support only named placeholders")


def load_locale(path: str | Path) -> dict:
    """Load UTF-8 YAML, validate completely, then atomically activate it.

    I/O and YAML parsing errors propagate. A failed load keeps the prior locale.
    The caller owns the returned copy; modifying it cannot alter translations.
    """
    global _catalog
    with Path(path).open(encoding="utf-8") as stream:
        candidate = yaml.safe_load(stream)
    _validate_catalog(candidate)
    result = deepcopy(candidate)
    _catalog = candidate
    return result


def t(key: str, **kwargs: object) -> str:
    """Translate a dotted string key using the explicitly loaded locale.

    Before load_locale, raise RuntimeError. Unknown/non-leaf keys and missing
    interpolation arguments raise KeyError; malformed keys raise ValueError.
    Extra arguments are ignored, as with str.format. Output is not HTML-escaped.
    """
    if _catalog is None:
        raise RuntimeError("locale has not been loaded")
    if not isinstance(key, str) or not key or any(not part for part in key.split(".")):
        raise ValueError("translation key must be a nonempty dotted string")
    value = _catalog
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(key)
        value = value[part]
    if not isinstance(value, str):
        raise KeyError(key)
    return value.format(**kwargs)
