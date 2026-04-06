"""Data coordinator for Vodokanal Rostov-on-Don integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AccountInfo,
    CounterInfo,
    VodokanalAPI,
    VodokanalApiError,
    VodokanalAuthError,
)
from .const import (
    CONF_LOGIN,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    DATE_FORMAT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class VodokanalAccountData:
    """Processed account data."""

    info: AccountInfo
    counters: list[CounterInfo] = field(default_factory=list)
    last_payment_amount: float | None = None
    last_payment_date: str | None = None
    last_payment_method: str | None = None
    latest_readings: dict[str, dict] = field(default_factory=dict)
    accruals_current: dict | None = None


@dataclass
class VodokanalData:
    """All data from Vodokanal."""

    accounts: dict[str, VodokanalAccountData] = field(default_factory=dict)


type VodokanalConfigEntry = ConfigEntry[VodokanalCoordinator]


class VodokanalCoordinator(DataUpdateCoordinator[VodokanalData]):
    """Coordinator for fetching Vodokanal data."""

    config_entry: VodokanalConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: VodokanalConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        scan_interval_hours = config_entry.options.get(
            CONF_SCAN_INTERVAL,
            int(DEFAULT_SCAN_INTERVAL.total_seconds() / 3600),
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=scan_interval_hours),
            config_entry=config_entry,
        )

        self._session: aiohttp.ClientSession | None = None
        self._api: VodokanalAPI | None = None

    def _get_api(self) -> VodokanalAPI:
        """Get or create the API client."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar()
            )
        if self._api is None:
            self._api = VodokanalAPI(
                self._session,
                self.config_entry.data[CONF_LOGIN],
                self.config_entry.data[CONF_PASSWORD],
            )
        return self._api

    async def _async_update_data(self) -> VodokanalData:
        """Fetch data from Vodokanal."""
        api = self._get_api()
        result = VodokanalData()

        try:
            account_numbers = await api.get_accounts()
        except VodokanalAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except VodokanalApiError as err:
            raise UpdateFailed(f"Error fetching accounts: {err}") from err

        now = datetime.now()
        date_from = (now - timedelta(days=90)).strftime(DATE_FORMAT)
        date_to = now.strftime(DATE_FORMAT)

        for account_id in account_numbers:
            try:
                account_data = await self._fetch_account_data(
                    api, account_id, date_from, date_to
                )
                result.accounts[account_id] = account_data
            except VodokanalAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except VodokanalApiError as err:
                _LOGGER.warning(
                    "Error fetching data for account %s: %s",
                    account_id,
                    err,
                )
            except Exception:
                _LOGGER.exception(
                    "Unexpected error for account %s", account_id
                )

        if not result.accounts:
            raise UpdateFailed("No account data available")

        return result

    async def _fetch_account_data(
        self,
        api: VodokanalAPI,
        account_id: str,
        date_from: str,
        date_to: str,
    ) -> VodokanalAccountData:
        """Fetch all data for a single account."""
        info = await api.get_account_info(account_id)

        counters: list[CounterInfo] = []
        try:
            counters = await api.get_counters(account_id)
        except Exception:
            _LOGGER.warning(
                "Could not fetch counters for %s", account_id
            )

        latest_readings: dict[str, dict] = {}
        try:
            readings = await api.get_counters_history(
                account_id, date_from, date_to
            )
            for reading in readings:
                serial = reading.get("serial", "")
                if serial and (
                    serial not in latest_readings
                    or reading["date"] > latest_readings[serial].get("date", "")
                ):
                    latest_readings[serial] = reading
        except Exception:
            _LOGGER.warning(
                "Could not fetch counter readings for %s", account_id
            )

        last_payment_amount = None
        last_payment_date = None
        last_payment_method = None
        try:
            payments = await api.get_payments_history(
                account_id, date_from, date_to
            )
            if payments:
                latest = payments[0]
                last_payment_amount = latest["amount"]
                last_payment_date = latest["date"]
                last_payment_method = latest["method"]
        except Exception:
            _LOGGER.warning(
                "Could not fetch payments for %s", account_id
            )

        accruals_current = None
        try:
            accruals = await api.get_accruals_history(
                account_id, date_from, date_to
            )
            if accruals:
                accruals_current = accruals[0]
        except Exception:
            _LOGGER.warning(
                "Could not fetch accruals for %s", account_id
            )

        return VodokanalAccountData(
            info=info,
            counters=counters,
            last_payment_amount=last_payment_amount,
            last_payment_date=last_payment_date,
            last_payment_method=last_payment_method,
            latest_readings=latest_readings,
            accruals_current=accruals_current,
        )

    async def async_shutdown(self) -> None:
        """Close the API session."""
        await super().async_shutdown()
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            self._api = None
