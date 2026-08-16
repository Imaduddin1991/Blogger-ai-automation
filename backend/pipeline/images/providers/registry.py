"""Image provider registry.

Providers register themselves with the @register decorator. The pipeline asks
the registry for enabled providers; it never imports a provider by name.
Adding a provider = one class + one @register (e.g. Wikimedia Commons in
Phase 4B), with no changes to the core pipeline.
"""

from __future__ import annotations

from typing import Type

from pipeline.images.providers.base import ImageProvider

_registry: dict[str, Type[ImageProvider]] = {}


class ProviderRegistryError(RuntimeError):
    pass


def register(cls: Type[ImageProvider]) -> Type[ImageProvider]:
    if cls.name in _registry:
        raise ProviderRegistryError(f"provider {cls.name!r} already registered")
    _registry[cls.name] = cls
    return cls


def get_provider(name: str) -> ImageProvider:
    try:
        cls = _registry[name]
    except KeyError as exc:
        raise ProviderRegistryError(f"unknown provider {name!r}") from exc
    return cls()


def all_providers() -> list[ImageProvider]:
    return [cls() for cls in _registry.values()]


def enabled_providers() -> list[ImageProvider]:
    return [p for p in all_providers() if p.enabled_by_default and p.is_configured()]


def provider_names() -> list[str]:
    return sorted(_registry)
