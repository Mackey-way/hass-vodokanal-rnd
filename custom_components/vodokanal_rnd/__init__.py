"""The Vodokanal Rostov-on-Don integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import VodokanalConfigEntry, VodokanalCoordinator
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: VodokanalConfigEntry
) -> bool:
    """Set up Vodokanal from a config entry."""
    coordinator = VodokanalCoordinator(hass, entry)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async_setup_services(hass)

    entry.async_on_unload(
        entry.add_update_listener(_async_update_listener)
    )

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: VodokanalConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )

    if unload_ok:
        await entry.runtime_data.async_shutdown()

    remaining = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id
    ]
    if not remaining:
        async_unload_services(hass)

    return unload_ok


async def _async_update_listener(
    hass: HomeAssistant, entry: VodokanalConfigEntry
) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
