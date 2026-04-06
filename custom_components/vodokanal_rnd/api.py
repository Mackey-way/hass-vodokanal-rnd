"""Async API client for Vodokanal Rostov-on-Don personal cabinet."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import aiohttp

from .const import API_TIMEOUT, BASE_URL, DATE_FORMAT, DATE_FORMAT_SHORT

_LOGGER = logging.getLogger(__name__)


class VodokanalAuthError(Exception):
    """Authentication error."""


class VodokanalApiError(Exception):
    """API request error."""


@dataclass
class CounterInfo:
    """Water meter counter information."""

    row_id: str
    tarif: str
    serial_number: str
    counter_type: str  # "cold" or "hot"
    last_value: int
    limit: int
    description: str


@dataclass
class AccountInfo:
    """Account information."""

    number: str
    address: str = ""
    holder: str = ""
    phone: str = ""
    area: str = ""
    residents: str = ""
    balance: float = 0.0
    debt: float = 0.0
    accrued: float = 0.0
    counters: list[CounterInfo] = field(default_factory=list)
    last_payment_amount: float | None = None
    last_payment_date: str | None = None
    last_payment_method: str | None = None
    counter_readings: list[dict] = field(default_factory=list)
    accruals: list[dict] = field(default_factory=list)


class VodokanalAPI:
    """Async client for Vodokanal Rostov-on-Don personal cabinet."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        login: str,
        password: str,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._login = login
        self._password = password
        self._authenticated = False
        self._csrf_token: str | None = None
        self._accounts: list[str] = []
        self._first_account: str | None = None

    async def authenticate(self) -> bool:
        """Authenticate with the personal cabinet."""
        try:
            csrf_token = await self._get_csrf_token()
            async with self._session.post(
                f"{BASE_URL}/login",
                data={
                    "_token": csrf_token,
                    "login": self._login,
                    "password": self._password,
                },
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as resp:
                if resp.status == 302:
                    location = resp.headers.get("Location", "")
                    if "/account/" in location:
                        self._authenticated = True
                        self._csrf_token = None
                        match = re.search(r"/account/(\d+)", location)
                        if match:
                            self._first_account = match.group(1)
                        _LOGGER.debug("Authentication successful")
                        return True
                _LOGGER.error("Authentication failed: status %s", resp.status)
                raise VodokanalAuthError("Invalid credentials")
        except aiohttp.ClientError as err:
            raise VodokanalApiError(f"Connection error: {err}") from err

    async def _get_csrf_token(self) -> str:
        """Get CSRF token from login page."""
        async with self._session.get(
            f"{BASE_URL}/login",
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            text = await resp.text()
            match = re.search(r'<meta name="csrf-token" content="([^"]+)"', text)
            if match:
                return match.group(1)
            match = re.search(r'name="_token"[^>]*value="([^"]+)"', text)
            if match:
                return match.group(1)
            raise VodokanalApiError("Could not find CSRF token")

    async def _ensure_csrf_token(self, account_id: str) -> str:
        """Get CSRF token from an authenticated page."""
        if self._csrf_token:
            return self._csrf_token
        async with self._session.get(
            f"{BASE_URL}/account/{account_id}",
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            text = await resp.text()
            if resp.status != 200 or "/login" in str(resp.url):
                self._authenticated = False
                raise VodokanalAuthError("Session expired")
            match = re.search(r'<meta name="csrf-token" content="([^"]+)"', text)
            if match:
                self._csrf_token = match.group(1)
                return self._csrf_token
            raise VodokanalApiError("Could not find CSRF token")

    async def _ensure_authenticated(self) -> None:
        """Ensure we have an active session."""
        if not self._authenticated:
            await self.authenticate()

    async def get_accounts(self) -> list[str]:
        """Get list of account numbers."""
        await self._ensure_authenticated()
        first_account = self._get_first_account_from_redirect()
        url = f"{BASE_URL}/account/{first_account}" if first_account else f"{BASE_URL}/account/300000000"
        async with self._session.get(
            url,
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            text = await resp.text()
            if "/login" in str(resp.url):
                self._authenticated = False
                raise VodokanalAuthError("Session expired")
            accounts = re.findall(
                r'/account/(\d{6,})', text
            )
            filtered = [a for a in dict.fromkeys(accounts) if a != "add"]
            self._accounts = list(filtered)
            if not self._accounts:
                match = re.search(r"/account/(\d+)", str(resp.url))
                if match:
                    self._accounts = [match.group(1)]
            _LOGGER.debug("Found accounts: %s", self._accounts)
            return self._accounts

    def _get_first_account_from_redirect(self) -> str | None:
        """Get first account number from login redirect."""
        return self._first_account

    async def get_account_info(self, account_id: str) -> AccountInfo:
        """Get account information from account page."""
        await self._ensure_authenticated()
        async with self._session.get(
            f"{BASE_URL}/account/{account_id}",
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            text = await resp.text()
            if "/login" in str(resp.url):
                self._authenticated = False
                raise VodokanalAuthError("Session expired")

            info = AccountInfo(number=account_id)
            self._csrf_token = None
            csrf_match = re.search(
                r'<meta name="csrf-token" content="([^"]+)"', text
            )
            if csrf_match:
                self._csrf_token = csrf_match.group(1)

            info.address = self._extract_inline_field(text, "mdi-map-marker")
            info.holder = self._extract_inline_field(text, "mdi-account")
            info.phone = self._extract_inline_field(text, "mdi-phone")

            right_values = re.findall(
                r'text-col-right[^>]*>([^<]+)', text
            )
            if len(right_values) >= 3:
                info.area = right_values[1].strip()
                info.residents = right_values[2].strip()

            balance_match = re.search(r'pay-second[^>]*>([^<]+)', text)
            if balance_match:
                info.balance = self._parse_float(balance_match.group(1))

            return info

    async def get_counters(self, account_id: str) -> list[CounterInfo]:
        """Get counter information from counters page."""
        await self._ensure_authenticated()
        async with self._session.get(
            f"{BASE_URL}/account/{account_id}/counters",
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            text = await resp.text()
            if "/login" in str(resp.url):
                self._authenticated = False
                raise VodokanalAuthError("Session expired")

            csrf_match = re.search(
                r'<meta name="csrf-token" content="([^"]+)"', text
            )
            if csrf_match:
                self._csrf_token = csrf_match.group(1)

            counters = []
            pattern = re.compile(
                r'counters\[(\d+)_(\d+)\]\[rowId\].*?value="(\d+)".*?'
                r'counters\[\d+_\d+\]\[tarif\].*?value="(\d+)".*?'
                r'counters\[\d+_\d+\]\[limit\].*?'
                r'data-ls-num="([^"]*)".*?'
                r'data-old-value="(\d+)".*?'
                r'data-limit="(\d+)"',
                re.DOTALL,
            )
            for match in pattern.finditer(text):
                row_id = match.group(1)
                tarif = match.group(2)
                serial = match.group(5)
                old_value = int(match.group(6))
                limit = int(match.group(7))

                cold_hot_match = re.search(
                    rf'counters\[{row_id}_{tarif}\].*?'
                    r'(cold-water|hot-water|Холодное|Горячее)',
                    text[:match.start() + 500],
                    re.DOTALL,
                )
                counter_type = "cold"
                description = "Холодное водоснабжение"
                if cold_hot_match:
                    val = cold_hot_match.group(1)
                    if "hot" in val.lower() or "Горяч" in val:
                        counter_type = "hot"
                        description = "Горячее водоснабжение"

                counters.append(
                    CounterInfo(
                        row_id=row_id,
                        tarif=tarif,
                        serial_number=serial,
                        counter_type=counter_type,
                        last_value=old_value,
                        limit=limit,
                        description=description,
                    )
                )

            if not counters:
                counters = self._parse_counters_simple(text)

            _LOGGER.debug(
                "Account %s: found %d counters", account_id, len(counters)
            )
            return counters

    def _parse_counters_simple(self, text: str) -> list[CounterInfo]:
        """Fallback counter parser using simpler patterns."""
        counters = []
        row_ids = re.findall(r'name="counters\[(\d+)_(\d+)\]\[rowId\]"', text)
        for row_id, tarif in row_ids:
            serial_match = re.search(
                rf'counters\[{row_id}_{tarif}\]\[limit\].*?data-ls-num="([^"]*)"',
                text,
                re.DOTALL,
            )
            old_val_match = re.search(
                rf'counters\[{row_id}_{tarif}\]\[limit\].*?data-old-value="(\d+)"',
                text,
                re.DOTALL,
            )
            limit_match = re.search(
                rf'counters\[{row_id}_{tarif}\]\[limit\].*?data-limit="(\d+)"',
                text,
                re.DOTALL,
            )

            block = text[: text.find(f"counters[{row_id}_{tarif}][rowId]") + 500]
            counter_type = "cold"
            description = "Холодное водоснабжение"
            if "hot-water" in block or "Горячее" in block:
                counter_type = "hot"
                description = "Горячее водоснабжение"

            counters.append(
                CounterInfo(
                    row_id=row_id,
                    tarif=tarif,
                    serial_number=serial_match.group(1) if serial_match else "",
                    counter_type=counter_type,
                    last_value=int(old_val_match.group(1)) if old_val_match else 0,
                    limit=int(limit_match.group(1)) if limit_match else 100,
                    description=description,
                )
            )
        return counters

    async def get_counters_history(
        self,
        account_id: str,
        date_from: str,
        date_to: str,
    ) -> list[dict]:
        """Get counter readings history."""
        await self._ensure_authenticated()
        async with self._session.get(
            f"{BASE_URL}/ajax/{account_id}/countersHistory",
            params={"from": date_from, "to": date_to},
            headers={"X-Requested-With": "XMLHttpRequest"},
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                raise VodokanalApiError(
                    f"countersHistory failed: {resp.status}"
                )
            data = await resp.json(content_type=None)
            results = []
            for row in data:
                counter_type = "cold"
                if "hot-water" in str(row[0]) or "Горячее" in str(row[1]):
                    counter_type = "hot"
                serial_match = re.search(r'№\s*(.+)', str(row[1]))
                serial = serial_match.group(1).strip() if serial_match else ""
                date_match = re.search(r'data-sort="([^"]+)"', str(row[2]))
                date_str = date_match.group(1) if date_match else ""

                results.append(
                    {
                        "type": counter_type,
                        "description": re.sub(r'<[^>]+>', '', str(row[1])).strip(),
                        "serial": serial,
                        "date": date_str,
                        "value": int(row[3]) if row[3] else 0,
                        "consumption": int(row[4]) if row[4] else 0,
                        "source": str(row[5]) if len(row) > 5 else "",
                    }
                )
            return results

    async def get_accruals_history(
        self,
        account_id: str,
        date_from: str,
        date_to: str,
    ) -> list[dict]:
        """Get accruals history."""
        await self._ensure_authenticated()
        async with self._session.get(
            f"{BASE_URL}/ajax/{account_id}/accrualsHistory",
            params={"from": date_from, "to": date_to},
            headers={"X-Requested-With": "XMLHttpRequest"},
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                raise VodokanalApiError(
                    f"accrualsHistory failed: {resp.status}"
                )
            data = await resp.json(content_type=None)
            results = []
            for row in data:
                month_match = re.search(
                    r'data-date="([^"]+)"', str(row[0])
                )
                month_str = month_match.group(1) if month_match else ""
                month_name = re.sub(r'<[^>]+>', '', str(row[0])).strip()

                results.append(
                    {
                        "month": month_str,
                        "month_name": month_name,
                        "debt_start": self._parse_float(row[1]),
                        "accrued": self._parse_float(row[2]),
                        "total": self._parse_float(row[3]),
                        "paid": self._parse_float(row[4]),
                    }
                )
            return results

    async def get_payments_history(
        self,
        account_id: str,
        date_from: str,
        date_to: str,
    ) -> list[dict]:
        """Get payments history."""
        await self._ensure_authenticated()
        async with self._session.get(
            f"{BASE_URL}/ajax/{account_id}/paymentsHistory",
            params={"from": date_from, "to": date_to},
            headers={"X-Requested-With": "XMLHttpRequest"},
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                raise VodokanalApiError(
                    f"paymentsHistory failed: {resp.status}"
                )
            data = await resp.json(content_type=None)
            results = []
            for row in data:
                date_match = re.search(r'data-sort="([^"]+)"', str(row[0]))
                date_str = date_match.group(1) if date_match else ""
                results.append(
                    {
                        "date": date_str,
                        "amount": self._parse_float(row[1]),
                        "method": str(row[2]).strip() if len(row) > 2 else "",
                    }
                )
            return results

    async def send_readings(
        self,
        account_id: str,
        readings: dict[str, int],
    ) -> bool:
        """Submit counter readings.

        Args:
            account_id: Account number.
            readings: Dict mapping "rowId_tarif" to new value.

        """
        await self._ensure_authenticated()
        csrf_token = await self._ensure_csrf_token(account_id)

        form_data: dict[str, str] = {"_token": csrf_token}
        counters = await self.get_counters(account_id)
        counter_map = {f"{c.row_id}_{c.tarif}": c for c in counters}

        for key, value in readings.items():
            if key not in counter_map:
                raise VodokanalApiError(f"Unknown counter: {key}")
            counter = counter_map[key]
            form_data[f"counters[{key}][value]"] = str(value)
            form_data[f"counters[{key}][rowId]"] = counter.row_id
            form_data[f"counters[{key}][tarif]"] = counter.tarif
            form_data[f"counters[{key}][limit]"] = str(counter.limit)

        async with self._session.post(
            f"{BASE_URL}/account/{account_id}/counters",
            data=form_data,
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as resp:
            if resp.status in (200, 302):
                _LOGGER.info(
                    "Readings submitted for account %s: %s",
                    account_id,
                    readings,
                )
                self._csrf_token = None
                return True
            raise VodokanalApiError(
                f"Failed to submit readings: {resp.status}"
            )

    @staticmethod
    def _extract_inline_field(html: str, icon_class: str) -> str:
        """Extract text that follows an icon class within the same element."""
        pattern = rf'{icon_class}">\s*</i>\s*([^<]+)'
        match = re.search(pattern, html, re.DOTALL)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _parse_float(value: str | int | float | None) -> float:
        """Parse string to float safely."""
        if value is None:
            return 0.0
        try:
            return float(str(value).replace(",", ".").replace(" ", "").strip())
        except (ValueError, TypeError):
            return 0.0
