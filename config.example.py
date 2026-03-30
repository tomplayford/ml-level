WIFI_SSID = "your-ssid"
WIFI_PASSWORD = "your-password"

# Well dimensions in mm
# Sensor mounted at top of well, measures distance down to water surface
# Water level = WELL_DEPTH_MM - sensor_reading
WELL_DEPTH_MM = 5000       # total well depth from sensor to bottom
WELL_DIAMETER_MM = 1000    # internal diameter (for volume calc)

# MQTT (Home Assistant) — can also be configured via web UI at /settings
MQTT_BROKER = ""
MQTT_PORT = 1883
MQTT_USER = ""
MQTT_PASSWORD = ""
MQTT_TOPIC_PREFIX = "homeassistant"
MQTT_DEVICE_ID = "well_level_sensor"
MQTT_PUBLISH_INTERVAL_S = 30
