"""Built-in research providers package.

Importing this package registers all built-in providers in the registry.
"""

from pipeline.research.providers import (  # noqa: F401  (register side effects)
    duckduckgo,
    wikidata,
    wikimedia,
)
