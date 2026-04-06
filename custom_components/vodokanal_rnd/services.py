"""Services for Vodokanal Rostov-on-Don integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .api import VodokanalApiError, VodokanalAuthError
from .const import (
    DOMAIN,
    EVENT_SEND_READINGS_FAILED,
    EVENT_SEND_READINGS_SUCCESS,
    SERVICE_REFRESH,
    SERVICE_SEND_READINGS,
)
from .coordinator import VodokanalCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_REFRESH_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
    }
)

SERVICE_SEND_READINGS_SCHEMA = vol.Schema(
    vol.Any(
        {
            vol.Required("device_id"): cv.string,
            vol.Required("value"): vol.Coerce(int),
        },
        {
            vol.Required("account"): cv.string,
            vol.Required("value"): vol.Coerce(int),
        },
    )
)


def _get_coordinator_and_account(
    hass: HomeAssistant, device_id: str
) -> tuple[VodokanalCoordinator, str] | None:
    """Find coordinator and account number for a device."""
    device_registry = dr.async_get(hass)
    device_entry = device_registry.async_get(device_id)
    if device_entry is None:
        return None

    for identifier in device_entry.identifiers:
        if identifier[0] == DOMAIN:
            account_number = identifier[1]
            for entry_id in device_entry.config_entries:
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry and entry.domain == DOMAIN:
                    coordinator: VodokanalCoordinator = entry.runtime_data
                    return coordinator, account_number
    return None


def _get_counter_key_from_device(
    hass: HomeAssistant, device_id: str
) -> tuple[VodokanalCoordinator, str, str] | None:
    """Find coordinator, account number, and counter key for a counter device."""
    device_registry = dr.async_get(hass)
    device_entry = device_registry.async_get(device_id)
    if device_entry is None:
        return None

    for identifier in device_entry.identifiers:
        if identifier[0] == DOMAIN and "_" in identifier[1]:
            parts = identifier[1].split("_", 1)
            account_number = parts[0]
            counter_row_id = parts[1]

            for entry_id in device_entry.config_entries:
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry and entry.domain == DOMAIN:
                    coordinator: VodokanalCoordinator = entry.runtime_data
                    if coordinator.data:
                        account_data = coordinator.data.accounts.get(account_number)
                        if account_data:
                            for counter in account_data.counters:
                                if counter.row_id == counter_row_id:
                                    key = f"{counter.row_id}_{counter.tarif}"
                                    return coordinator, account_number, key
    return None


async def _async_handle_refresh(call: ServiceCall) -> None:
    """Handle the refresh service."""
    device_id = call.data["device_id"]
    result = _get_coordinator_and_account(call.hass, device_id)
    if result is None:
        _LOGGER.error("Device %s not found", device_id)
        return

    coordinator, _ = result
    await coordinator.async_request_refresh()


def _get_coordinator_by_account(
    hass: HomeAssistant, account_number: str
) -> tuple[VodokanalCoordinator, str] | None:
    """Find coordinator and first counter key for an account number."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        coordinator: VodokanalCoordinator = entry.runtime_data
        if coordinator.data and account_number in coordinator.data.accounts:
            account_data = coordinator.data.accounts[account_number]
            if account_data.counters:
                counter = account_data.counters[0]
                key = f"{counter.row_id}_{counter.tarif}"
                return coordinator, key
    return None


async def _async_handle_send_readings(call: ServiceCall) -> None:
    """Handle the send_readings service."""
    hass = call.hass
    value = call.data["value"]

    if "account" in call.data:
        account_number = call.data["account"]
        result = _get_coordinator_by_account(hass, account_number)
        if result is None:
            _LOGGER.error("Account %s not found", account_number)
            hass.bus.async_fire(
                EVENT_SEND_READINGS_FAILED,
                {"account": account_number, "error": "Account not found"},
            )
            return
        coordinator, counter_key = result
    else:
        device_id = call.data["device_id"]
        result = _get_counter_key_from_device(hass, device_id)
        if result is None:
            _LOGGER.error("Counter device %s not found", device_id)
            hass.bus.async_fire(
                EVENT_SEND_READINGS_FAILED,
                {"device_id": device_id, "error": "Device not found"},
            )
            return
        coordinator, account_number, counter_key = result

    try:
        api = coordinator._get_api()
        await api.send_readings(account_number, {counter_key: value})
        hass.bus.async_fire(
            EVENT_SEND_READINGS_SUCCESS,
            {
                "account": account_number,
                "counter_key": counter_key,
                "value": value,
            },
        )
        await coordinator.async_request_refresh()
    except VodokanalAuthError as err:
        _LOGGER.error("Auth error sending readings: %s", err)
        hass.bus.async_fire(
            EVENT_SEND_READINGS_FAILED,
            {"account": account_number, "error": str(err)},
        )
    except VodokanalApiError as err:
        _LOGGER.error("API error sending readings: %s", err)
        hass.bus.async_fire(
            EVENT_SEND_READINGS_FAILED,
            {"account": account_number, "error": str(err)},
        )


def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services."""
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        _async_handle_refresh,
        schema=SERVICE_REFRESH_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_READINGS,
        _async_handle_send_readings,
        schema=SERVICE_SEND_READINGS_SCHEMA,
    )


def async_unload_services(hass: HomeAssistant) -> None:
    """Unload services."""
    hass.services.async_remove(DOMAIN, SERVICE_REFRESH)
    hass.services.async_remove(DOMAIN, SERVICE_SEND_READINGS)
