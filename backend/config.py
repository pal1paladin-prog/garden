import os

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "garden")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///garden.db"
)

SOIL_DRY_DEFAULT = 750
SOIL_WET_DEFAULT = 350
PUMP_DEFAULT_TIMEOUT = 10000
