"""Public pySMF API."""

from __future__ import annotations

from typing import TYPE_CHECKING

import smf_parser as _smf_parser
from smf_parser import __all__ as __all__

if TYPE_CHECKING:
    from smf_parser import HeaderCatalog as HeaderCatalog, read_file as read_file

globals().update({name: getattr(_smf_parser, name) for name in __all__})
