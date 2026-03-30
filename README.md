# mp-level

MicroPython well water level monitor for Raspberry Pi Pico 2W.

Uses a DYP-A22YYUW ultrasonic distance sensor mounted at the top of a well to measure the distance to the water surface, then calculates water level, volume (litres), and fill percentage.

## Features

- **Web dashboard** — real-time readings with 24h history chart served from the Pico
- **MQTT / Home Assistant** — auto-discovery sensor entities for water level, distance, volume, fill %, and connectivity status
- **Web-configurable** — well dimensions and MQTT settings adjustable via `/settings` without reflashing
- **Rolling average** — 10-sample smoothing for stable readings

## Hardware

| Component | Role |
|-----------|------|
| Raspberry Pi Pico 2W | Controller + WiFi |
| DYP-A22YYUW | Ultrasonic distance sensor (UART, 4-byte binary protocol) |

### Wiring

| Pico Pin | Sensor |
|----------|--------|
| GP0 (TX) | — |
| GP1 (RX) | TX |
| 3V3 | VCC |
| GND | GND |

## Setup

1. Copy `config.example.py` to `config.py` and fill in your WiFi credentials and well dimensions.

2. Upload all files to the Pico 2W:
   - `main.py`
   - `config.py`
   - `settings.py`
   - `index.html`
   - `settings.html`

3. The Pico connects to WiFi on boot and starts an HTTP server on port 80.

### Dependencies

Install the `umqtt.simple` package via `mip` (MicroPython package manager):

```python
import mip
mip.install("umqtt.simple")
```

## Web UI

| Endpoint | Description |
|----------|-------------|
| `/` | Dashboard with live readings and history chart |
| `/settings` | Configure well dimensions and MQTT |
| `/api` | JSON: current readings |
| `/api/history?range=N` | JSON: history for last N seconds (default 3600) |
| `/api/settings` | GET/POST JSON: runtime settings |

## MQTT

When a broker is configured, the device publishes to Home Assistant via MQTT discovery:

- `sensor.well_level_sensor_water_level_mm`
- `sensor.well_level_sensor_distance_mm`
- `sensor.well_level_sensor_litres`
- `sensor.well_level_sensor_pct`
- `binary_sensor.well_level_sensor_status`

Publish interval is configurable (default 30s).
