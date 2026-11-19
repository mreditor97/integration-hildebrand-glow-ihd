"""Tests for the repairs of the Hildebrand Glow IHD Integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.repairs import ConfirmRepairFlow
from homeassistant.helpers import issue_registry as ir

from custom_components.hildebrand_glow_ihd.const import DOMAIN
from custom_components.hildebrand_glow_ihd.repairs import async_create_fix_flow

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.typing import MqttMockHAClient


async def test_period_costs_issue_is_confirmed(hass: HomeAssistant) -> None:
    """The removed cost sensors issue is dismissed by confirming it."""
    flow = await async_create_fix_flow(hass, "period_costs_removed_abc", None)
    assert isinstance(flow, ConfirmRepairFlow)


async def test_removing_entry_removes_issue(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,  # noqa: ARG001
    config_entry: MockConfigEntry,
) -> None:
    """Removing the entry removes its removed cost sensors issue."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    issue_id = f"period_costs_removed_{config_entry.entry_id}"
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="period_costs_removed",
    )
    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
