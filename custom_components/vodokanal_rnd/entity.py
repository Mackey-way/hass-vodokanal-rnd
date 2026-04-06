"""Base entity for Vodokanal Rostov-on-Don integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BASE_URL, DOMAIN, MANUFACTURER
from .coordinator import VodokanalAccountData, VodokanalCoordinator, VodokanalData


class VodokanalBaseEntity(CoordinatorEntity[VodokanalCoordinator]):
    """Base entity for Vodokanal."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: VodokanalCoordinator,
        account_number: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._account_number = account_number

    def _get_address(self) -> str:
        """Get account address."""
        account_data = self.get_account_data()
        if account_data and account_data.info.address:
            return account_data.info.address
        return ""

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        address = self._get_address()
        if address:
            name = f"ЛС {self._account_number} ({address})"
        else:
            name = f"ЛС {self._account_number}"
        return DeviceInfo(
            identifiers={(DOMAIN, self._account_number)},
            name=name,
            manufacturer=MANUFACTURER,
            model="Лицевой счёт",
            configuration_url=f"{BASE_URL}/account/{self._account_number}",
        )

    def get_account_data(self) -> VodokanalAccountData | None:
        """Get account data from coordinator."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.accounts.get(self._account_number)


class VodokanalCounterEntity(VodokanalBaseEntity):
    """Entity for a water counter."""

    def __init__(
        self,
        coordinator: VodokanalCoordinator,
        account_number: str,
        counter_index: int,
    ) -> None:
        """Initialize the counter entity."""
        super().__init__(coordinator, account_number)
        self._counter_index = counter_index

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the counter."""
        account_data = self.get_account_data()
        address = self._get_address()
        if account_data and self._counter_index < len(account_data.counters):
            counter = account_data.counters[self._counter_index]
            water_type = "ХВС" if counter.counter_type == "cold" else "ГВС"
            if address:
                name = f"Счётчик {water_type} ({address})"
            else:
                name = f"Счётчик {water_type} №{counter.serial_number}"
            return DeviceInfo(
                identifiers={
                    (DOMAIN, f"{self._account_number}_{counter.row_id}")
                },
                name=name,
                manufacturer=MANUFACTURER,
                model=f"{counter.description} №{counter.serial_number}",
                via_device=(DOMAIN, self._account_number),
            )
        return DeviceInfo(
            identifiers={
                (DOMAIN, f"{self._account_number}_counter_{self._counter_index}")
            },
            name=f"Счётчик {self._counter_index + 1}",
            manufacturer=MANUFACTURER,
            via_device=(DOMAIN, self._account_number),
        )
