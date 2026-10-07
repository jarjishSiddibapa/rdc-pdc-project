"""
RDC PDC Manager — HashID helper
Encodes/decodes integer database IDs to short opaque strings for URLs.

  hid_encode(5)          → 'Mj3xK9wL'
  hid_decode('Mj3xK9wL') → 5

The Hashids instance is initialised once via init_hashids() called from
create_app().  The werkzeug URL converter (HashIDConverter) is also
defined here so it can be registered with app.url_map.converters.
"""
from __future__ import annotations
from hashids import Hashids
from werkzeug.routing import BaseConverter
from werkzeug.exceptions import NotFound

_hashids: Hashids | None = None


# ── Initialisation ────────────────────────────────────────────────────────────

def init_hashids(salt: str, min_length: int = 8) -> None:
    """Call this once inside create_app() after config is loaded."""
    global _hashids
    _hashids = Hashids(salt=salt, min_length=min_length)


# ── Public encode / decode ────────────────────────────────────────────────────

def hid_encode(value: int | None) -> str:
    """Encode an integer DB id to a URL-safe opaque string."""
    if value is None or _hashids is None:
        return ''
    return _hashids.encode(int(value))


def hid_decode(value: str) -> int | None:
    """Decode a hashid string back to an integer, or None if invalid."""
    if not value or _hashids is None:
        return None
    decoded = _hashids.decode(str(value))
    return decoded[0] if decoded else None


# ── Flask URL converter ───────────────────────────────────────────────────────

class HashIDConverter(BaseConverter):
    """
    Use in route decorators as  /<hashid:cheque_id>
    Flask's url_for() will call to_url() automatically, so templates need
    NO changes — pass the plain integer and the converter encodes it.
    """
    # Accept the same alphabet hashids uses (alphanumeric, no punctuation)
    regex = r'[a-zA-Z0-9]+'

    def to_python(self, value: str) -> int:
        result = hid_decode(value)
        if result is None:
            raise NotFound(f'Resource not found')
        return result

    def to_url(self, value) -> str:
        return hid_encode(int(value))
