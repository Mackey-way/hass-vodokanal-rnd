"""Sensor platform for Vodokanal Rostov-on-Don integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VodokanalAccountData, VodokanalCoordinator, VodokanalConfigEntry
from .entity import VodokanalBaseEntity, VodokanalCounterEntity


@dataclass(frozen=True, kw_only=True)
class VodokanalAccountSensorDescription(SensorEntityDescription):
    """Sensor description for account-level sensors."""

    value_fn: Callable[[VodokanalAccountData], Any]
    attr_fn: Callable[[VodokanalAccountData], dict[str, Any]] | None = None


@dataclass(frozen=True, kw_only=True)
class VodokanalCounterSensorDescription(SensorEntityDescription):
    """Sensor description for counter-level sensors."""

    value_fn: Callable[[VodokanalAccountData, int], Any]


ACCOUNT_SENSORS: tuple[VodokanalAccountSensorDescription, ...] = (
    VodokanalAccountSensorDescription(
        key="balance",
        translation_key="balance",
        native_unit_of_measurement="RUB",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data: data.info.balance,
        attr_fn=lambda data: {
            "address": data.info.address,
            "holder": data.info.holder,
            "area": data.info.area,
            "residents": data.info.residents,
        },
    ),
    VodokanalAccountSensorDescription(
        key="debt",
        translation_key="debt",
        native_unit_of_measurement="RUB",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data: (
            data.accruals_current["debt_start"]
            if data.accruals_current
            else None
        ),
    ),
    VodokanalAccountSensorDescription(
        key="accrued",
        translation_key="accrued",
        native_unit_of_measurement="RUB",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data: (
            data.accruals_current["accrued"]
            if data.accruals_current
            else None
        ),
    ),
    VodokanalAccountSensorDescription(
        key="paid",
        translation_key="paid",
        native_unit_of_measurement="RUB",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data: (
            data.accruals_current["paid"]
            if data.accruals_current
            else None
        ),
    ),
    VodokanalAccountSensorDescription(
        key="last_payment_amount",
        translation_key="last_payment_amount",
        native_unit_of_measurement="RUB",
        device_class=SensorDeviceClass.MONETARY,
        value_fn=lambda data: data.last_payment_amount,
        attr_fn=lambda data: {
            "date": data.last_payment_date,
            "method": data.last_payment_method,
        },
    ),
    VodokanalAccountSensorDescription(
        key="last_payment_date",
        translation_key="last_payment_date",
        value_fn=lambda data: data.last_payment_date,
    ),
    VodokanalAccountSensorDescription(
        key="address",
        translation_key="address",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.info.address,
    ),
)

COUNTER_SENSORS: tuple[VodokanalCounterSensorDescription, ...] = (
    VodokanalCounterSensorDescription(
        key="reading",
        translation_key="counter_reading",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data, idx: _get_counter_reading(data, idx),
    ),
    VodokanalCounterSensorDescription(
        key="consumption",
        translation_key="counter_consumption",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        value_fn=lambda data, idx: _get_counter_consumption(data, idx),
    ),
    VodokanalCounterSensorDescription(
        key="reading_date",
        translation_key="counter_reading_date",
        value_fn=lambda data, idx: _get_counter_reading_date(data, idx),
    ),
)


def _get_counter_reading(data: VodokanalAccountData, idx: int) -> int | None:
    """Get latest counter reading value."""
    if idx >= len(data.counters):
        return None
    counter = data.counters[idx]
    reading = data.latest_readings.get(counter.serial_number)
    if reading:
        return reading.get("value")
    return counter.last_value


def _get_counter_consumption(data: VodokanalAccountData, idx: int) -> int | None:
    """Get latest counter consumption."""
    if idx >= len(data.counters):
        return None
    counter = data.counters[idx]
    reading = data.latest_readings.get(counter.serial_number)
    if reading:
        return reading.get("consumption")
    return None


def _get_counter_reading_date(data: VodokanalAccountData, idx: int) -> str | None:
    """Get latest counter reading date."""
    if idx >= len(data.counters):
        return None
    counter = data.counters[idx]
    reading = data.latest_readings.get(counter.serial_number)
    if reading:
        return reading.get("date")
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VodokanalConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    coordinator: VodokanalCoordinator = entry.runtime_data

    entities: list[SensorEntity] = []

    if coordinator.data:
        for account_id, account_data in coordinator.data.accounts.items():
            for description in ACCOUNT_SENSORS:
                entities.append(
                    VodokanalAccountSensor(
                        coordinator=coordinator,
                        account_number=account_id,
                        entity_description=description,
                    )
                )

            for idx, counter in enumerate(account_data.counters):
                for description in COUNTER_SENSORS:
                    entities.append(
                        VodokanalCounterSensor(
                            coordinator=coordinator,
                            account_number=account_id,
                            counter_index=idx,
                            entity_description=description,
                        )
                    )

    async_add_entities(entities, update_before_add=False)


class VodokanalAccountSensor(VodokanalBaseEntity, SensorEntity):
    """Account-level sensor."""

    entity_description: VodokanalAccountSensorDescription

    def __init__(
        self,
        coordinator: VodokanalCoordinator,
        account_number: str,
        entity_description: VodokanalAccountSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, account_number)
        self.entity_description = entity_description
        self._attr_unique_id = f"{account_number}_{entity_description.key}"

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        account_data = self.get_account_data()
        if account_data is None:
            return None
        return self.entity_description.value_fn(account_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attr_fn is None:
            return None
        account_data = self.get_account_data()
        if account_data is None:
            return None
        return self.entity_description.attr_fn(account_data)


class VodokanalCounterSensor(VodokanalCounterEntity, SensorEntity):
    """Counter-level sensor."""

    entity_description: VodokanalCounterSensorDescription

    def __init__(
        self,
        coordinator: VodokanalCoordinator,
        account_number: str,
        counter_index: int,
        entity_description: VodokanalCounterSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, account_number, counter_index)
        self.entity_description = entity_description
        account_data = coordinator.data.accounts.get(account_number) if coordinator.data else None
        counter_id = ""
        if account_data and counter_index < len(account_data.counters):
            counter_id = account_data.counters[counter_index].row_id
        self._attr_unique_id = (
            f"{account_number}_{counter_id}_{entity_description.key}"
        )

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        account_data = self.get_account_data()
        if account_data is None:
            return None
        return self.entity_description.value_fn(
            account_data, self._counter_index
        )
