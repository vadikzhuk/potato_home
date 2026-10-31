"""Where listings come from: one module per website.

Each has NAME and fetch(search, http, pause), which yields listings as dicts
with the fields of core.LISTING_FIELDS. `search` is the "search" part of
criteria.yaml; `pause()` waits between pages. To add a site, write such a
module and add it to SOURCES.
"""

from . import pvp, trovacasa

SOURCES = {source.NAME: source for source in (trovacasa, pvp)}
REGIONS = list(trovacasa.PROVINCES)  # the regions every source knows
