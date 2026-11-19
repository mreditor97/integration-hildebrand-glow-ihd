"""Repairs for the Home Assistant Hildebrand Glow IHD Integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def async_create_fix_flow(
    hass: HomeAssistant,  # noqa: ARG001
    issue_id: str,  # noqa: ARG001
    data: dict[str, Any] | None,  # noqa: ARG001
) -> RepairsFlow:
    """Return the flow that dismisses an issue once it has been read.

    The only fixable issue lists the electricity cost sensors removed when
    the tariff was changed to variable, so there is nothing to do but
    confirm it has been read.
    """
    return ConfirmRepairFlow()
