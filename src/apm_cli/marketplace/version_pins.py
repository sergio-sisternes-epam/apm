"""Ref pin cache for marketplace plugin immutability checks.

Records plugin-to-ref mappings per marketplace.  When a previously-seen
plugin resolves to a *different* ref, a warning is emitted -- this may
indicate a ref-swap attack where an attacker changed the git ref for
an existing marketplace entry.

The pin file lives at ``~/.apm/cache/marketplace/version-pins.json``
and has the structure::

    {
      "marketplace/plugin": "abc123..."
    }

All functions are **fail-open**: filesystem or JSON errors are logged
and never block resolution.
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_PINS_FILENAME = "version-pins.json"


# ------------------------------------------------------------------
# Path helpers
# ------------------------------------------------------------------


def _pins_path(pins_dir: Optional[str] = None) -> str:
    """Return the full path to the version-pins JSON file.

    Args:
        pins_dir: Override directory for the pins file.  When ``None``,
            the default ``~/.apm/cache/marketplace/`` is used.
    """
    if pins_dir is not None:
        return os.path.join(pins_dir, _PINS_FILENAME)

    from ..config import CONFIG_DIR

    return os.path.join(CONFIG_DIR, "cache", "marketplace", _PINS_FILENAME)


def _pin_key(marketplace_name: str, plugin_name: str) -> str:
    """Build the canonical dict key for a marketplace/plugin pair."""
    return f"{marketplace_name}/{plugin_name}".lower()


# ------------------------------------------------------------------
# Load / save
# ------------------------------------------------------------------


def load_ref_pins(pins_dir: Optional[str] = None) -> dict:
    """Load the ref-pins file from disk.

    Returns an empty dict when the file is missing or contains invalid
    JSON.  Never raises.
    """
    path = _pins_path(pins_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            logger.debug("version-pins file is not a JSON object; ignoring")
            return {}
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Failed to load version-pins: %s", exc)
        return {}


def save_ref_pins(pins: dict, pins_dir: Optional[str] = None) -> None:
    """Persist *pins* to disk atomically.

    Writes to a temporary file first, then uses ``os.replace`` to move
    it into place so readers never see a partial write.  Errors are
    logged and swallowed (advisory system).
    """
    path = _pins_path(pins_dir)
    tmp_path = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp_path, "w") as fh:
            json.dump(pins, fh, indent=2)
        os.replace(tmp_path, path)
    except OSError as exc:
        logger.debug("Failed to save version-pins: %s", exc)


# ------------------------------------------------------------------
# Check / record
# ------------------------------------------------------------------


def check_ref_pin(
    marketplace_name: str,
    plugin_name: str,
    ref: str,
    pins_dir: Optional[str] = None,
) -> Optional[str]:
    """Check whether *ref* matches the previously-recorded pin.

    Returns:
        The **previously pinned ref** if it differs from *ref* (possible
        ref swap).  ``None`` if this is the first time seeing the
        plugin or the ref matches.
    """
    pins = load_ref_pins(pins_dir)
    key = _pin_key(marketplace_name, plugin_name)
    previous_ref = pins.get(key)
    if previous_ref is None:
        return None
    if not isinstance(previous_ref, str):
        return None
    if previous_ref == ref:
        return None
    return previous_ref


def record_ref_pin(
    marketplace_name: str,
    plugin_name: str,
    ref: str,
    pins_dir: Optional[str] = None,
) -> None:
    """Store a plugin-to-ref mapping in the pin cache.

    Overwrites any existing pin for the same plugin (advisory system
    -- we always record the current ref even if it changed).
    """
    pins = load_ref_pins(pins_dir)
    key = _pin_key(marketplace_name, plugin_name)
    pins[key] = ref
    save_ref_pins(pins, pins_dir)
