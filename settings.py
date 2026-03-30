import json

SETTINGS_FILE = "settings.json"

# Editable keys and their types
SCHEMA = {
    "MQTT_BROKER": str,
    "MQTT_PORT": int,
    "MQTT_USER": str,
    "MQTT_PASSWORD": str,
    "MQTT_TOPIC_PREFIX": str,
    "MQTT_DEVICE_ID": str,
    "MQTT_PUBLISH_INTERVAL_S": int,
    "WELL_DEPTH_MM": int,
    "WELL_DIAMETER_MM": int,
}

_overrides = {}

def load():
    global _overrides
    try:
        with open(SETTINGS_FILE, "r") as f:
            _overrides = json.load(f)
        print("Settings loaded:", list(_overrides.keys()))
    except (OSError, ValueError):
        _overrides = {}

def save():
    with open(SETTINGS_FILE, "w") as f:
        json.dump(_overrides, f)
    print("Settings saved")

def get(key, default):
    """Return override if set, else the compiled default."""
    return _overrides.get(key, default)

def get_all(defaults):
    """Return merged dict of defaults + overrides for all SCHEMA keys."""
    merged = {}
    for key in SCHEMA:
        merged[key] = _overrides.get(key, defaults.get(key))
    return merged

def update(new_vals, defaults):
    """Update overrides. Only store values that differ from defaults."""
    changed = False
    for key, cast in SCHEMA.items():
        if key in new_vals:
            try:
                val = cast(new_vals[key])
            except (ValueError, TypeError):
                continue
            if val != defaults.get(key):
                _overrides[key] = val
                changed = True
            elif key in _overrides:
                del _overrides[key]
                changed = True
    if changed:
        save()
    return changed
