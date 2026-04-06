"""Diagnostics support for Vodokanal Rostov-on-Don."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_LOGIN, CONF_PASSWORD
from .coordinator import VodokanalConfigEntry

TO_REDACT = {CONF_LOGIN, CONF_PASSWORD, "phone", "holder"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: VodokanalConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data: dict[str, Any] = {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
    }

    if coordinator.data:
        accounts = {}
        for account_id, account_data in coordinator.data.accounts.items():
            accounts[account_id] = {
                "address": account_data.info.address,
                "balance": account_data.info.balance,
                "counters_count": len(account_data.counters),
                "counters": [
                    {
                        "type": c.counter_type,
                        "serial": c.serial_number,
                        "last_value": c.last_value,
                    }
                    for c in account_data.counters
                ],
                "last_payment_amount": account_data.last_payment_amount,
                "last_payment_date": account_data.last_payment_date,
                "accruals_current": account_data.accruals_current,
            }
        data["accounts"] = async_redact_data(accounts, TO_REDACT)

    return data
