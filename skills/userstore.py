"""
userstore — a tiny shared JSON store for skills that need to persist lists.

Notes, to-dos, and reminders all need to remember a small list of items across
sessions. Rather than each skill inventing its own file, they share this one
store (a *file*, not a skill folder, so the registry ignores it — same pattern
as ``skills/geolocation.py`` and ``skills/websearch.py``).

The data lives in ``~/.meryna_userdata.json`` as ``{namespace: [items...]}``.
Writes are atomic (temp file + replace). All functions are synchronous and
cheap; call them from a skill via ``asyncio.to_thread`` if you prefer, though
the files are tiny.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("meryna.skills.userstore")

_STORE_PATH = Path.home() / ".meryna_userdata.json"


def _load_all() -> Dict[str, Any]:
    try:
        if _STORE_PATH.exists():
            return json.loads(_STORE_PATH.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read user store: %s", exc)
    return {}


def _save_all(data: Dict[str, Any]) -> None:
    try:
        tmp = _STORE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_STORE_PATH)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not write user store: %s", exc)


def get_list(namespace: str) -> List[Any]:
    """Return the list stored under *namespace* (empty list if none)."""
    data = _load_all()
    items = data.get(namespace)
    return list(items) if isinstance(items, list) else []


def set_list(namespace: str, items: List[Any]) -> None:
    """Replace the whole list stored under *namespace*."""
    data = _load_all()
    data[namespace] = items
    _save_all(data)


def add_item(namespace: str, item: Any) -> List[Any]:
    """Append *item* to *namespace* and return the updated list."""
    items = get_list(namespace)
    items.append(item)
    set_list(namespace, items)
    return items


def remove_index(namespace: str, index: int) -> Any:
    """Remove the item at 1-based *index*; return it, or None if out of range."""
    items = get_list(namespace)
    if 1 <= index <= len(items):
        removed = items.pop(index - 1)
        set_list(namespace, items)
        return removed
    return None


def clear(namespace: str) -> None:
    """Remove every item under *namespace*."""
    set_list(namespace, [])
