"""Built-in image providers package.

Importing this package registers all built-in providers in the registry
(mirrors the research providers package).
"""

from pipeline.images.providers import (  # noqa: F401  (register side effects)
    commons,
)
