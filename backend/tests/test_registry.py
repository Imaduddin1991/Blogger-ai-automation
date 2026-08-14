"""Provider registry: registration, lookup, unknown-provider errors."""

import pytest

from pipeline.research.providers.base import ResearchProvider
from pipeline.research.providers.registry import (
    ProviderRegistryError,
    get_provider,
    provider_names,
    register,
)


def test_register_and_lookup():
    class FakeProvider(ResearchProvider):
        name = "fake"
        display_name = "Fake"

        async def search(self, topic: str, limit: int = 5) -> list:
            return []

    registered = register(FakeProvider)
    assert registered is FakeProvider
    instance = get_provider("fake")
    assert isinstance(instance, FakeProvider)
    assert "fake" in provider_names()


def test_duplicate_registration_raises():
    class Dupe(ResearchProvider):
        name = "dupe"

        async def search(self, topic: str, limit: int = 5) -> list:
            return []

    register(Dupe)
    with pytest.raises(ProviderRegistryError):
        register(Dupe)


def test_unknown_provider_raises():
    with pytest.raises(ProviderRegistryError):
        get_provider("does_not_exist")
