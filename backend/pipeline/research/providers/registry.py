"""Provider registry.

Providers register themselves with the @register decorator. The pipeline
asks the registry for enabled providers; it never imports a provider by
name. Adding a provider = one class + one @register.
"""

from __future__ import annotations

from typing import Type

from pipeline.research.providers.base import ResearchProvider

_registry: dict[str, Type[ResearchProvider]] = {}


class ProviderRegistryError(RuntimeError):
    pass


def register(cls: Type[ResearchProvider]) -> Type[ResearchProvider]:
    if cls.name in _registry:
        raise ProviderRegistryError(f"provider {cls.name!r} already registered")
    _registry[cls.name] = cls
    return cls


def get_provider(name: str) -> ResearchProvider:
    try:
        cls = _registry[name]
    except KeyError as exc:
        raise ProviderRegistryError(f"unknown provider {name!r}") from exc
    return cls()


def all_providers() -> list[ResearchProvider]:
    return [cls() for cls in _registry.values()]


def enabled_providers() -> list[ResearchProvider]:
    return [p for p in all_providers() if p.enabled_by_default and p.is_configured()]


def provider_names() -> list[str]:
    return sorted(_registry)
