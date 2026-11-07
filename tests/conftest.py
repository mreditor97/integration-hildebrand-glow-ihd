"""Fixtures for the Home Assistant Hildebrand Glow IHD Integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hildebrand_glow_ihd.const import DOMAIN

from .const import ENTRY_DATA

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,  # noqa: ARG001
) -> Generator[None]:
    """Let Home Assistant load the integration from custom_components."""
    yield  # noqa: PT022


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Allow the MQTT client's housekeeping timer to outlive a test."""
    return True


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry that detects every Glow device."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Hildebrand Glow IHD",
        unique_id=f"{DOMAIN}_+",
        data=ENTRY_DATA,
        minor_version=2,
    )
