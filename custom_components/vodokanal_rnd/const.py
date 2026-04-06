"""Constants for the Vodokanal Rostov-on-Don integration."""

from datetime import timedelta

DOMAIN = "vodokanal_rnd"
MANUFACTURER = "Водоканал Ростов-на-Дону"
BASE_URL = "https://lkfl.vodokanalrnd.ru"

CONF_LOGIN = "login"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = timedelta(hours=1)
MIN_SCAN_INTERVAL = 1
MAX_SCAN_INTERVAL = 168

API_TIMEOUT = 30

PLATFORMS = ["sensor"]

DATE_FORMAT = "%d.%m.%Y"
DATE_FORMAT_SHORT = "%d.%m.%y"

SERVICE_REFRESH = "refresh"
SERVICE_SEND_READINGS = "send_readings"

ATTR_ACCOUNT_NUMBER = "account_number"
ATTR_ADDRESS = "address"
ATTR_HOLDER = "holder"
ATTR_AREA = "area"
ATTR_RESIDENTS = "residents"

EVENT_SEND_READINGS_SUCCESS = f"{DOMAIN}_send_readings_success"
EVENT_SEND_READINGS_FAILED = f"{DOMAIN}_send_readings_failed"
