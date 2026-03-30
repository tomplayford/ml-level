import time
import network
import socket
import json
from machine import UART, Pin
import config
import settings
from umqtt.simple import MQTTClient

# Load saved settings overrides
settings.load()

# Helper to get a config value (override or default)
def cfg(key):
    return settings.get(key, getattr(config, key))

# --- Hardware setup ---
led = Pin("LED", Pin.OUT)
uart = UART(0, baudrate=115200, tx=Pin(0), rx=Pin(1))

# --- State ---
level_mm = None       # smoothed distance reading in mm
status = None         # sensor status field
last_update = 0       # ticks_ms of last valid reading

# --- Smoothing (rolling average) ---
SMOOTH_SIZE = 10
_readings = []

# --- History ring buffer ---
# Sample every 30s, keep 2880 entries = 24h
HISTORY_INTERVAL_MS = 30_000
HISTORY_MAX = 2880
_history = []         # list of (uptime_s, level_mm)
_last_sample = 0      # ticks_ms of last history sample
_boot_ticks = time.ticks_ms()

def record_history():
    global _last_sample
    now = time.ticks_ms()
    if time.ticks_diff(now, _last_sample) >= HISTORY_INTERVAL_MS:
        _last_sample = now
        uptime_s = time.ticks_diff(now, _boot_ticks) // 1000
        if level_mm is not None:
            _history.append((uptime_s, round(level_mm, 1)))
            if len(_history) > HISTORY_MAX:
                _history.pop(0)

# --- UART parsing (DYP-A22YYUW binary protocol) ---
uart_buf = bytearray()

def poll_uart():
    global level_mm, status, last_update, uart_buf
    if uart.any():
        chunk = uart.read()
        if chunk:
            uart_buf.extend(chunk)

    while len(uart_buf) >= 4:
        if uart_buf[0] != 0xFF:
            uart_buf = uart_buf[1:]
            continue

        header = uart_buf[0]
        dist_h = uart_buf[1]
        dist_l = uart_buf[2]
        checksum = uart_buf[3]

        expected = (header + dist_h + dist_l) & 0xFF
        if checksum != expected:
            uart_buf = uart_buf[1:]
            status = "CHECKSUM_ERR"
            continue

        dist = (dist_h << 8) | dist_l
        uart_buf = uart_buf[4:]

        if dist == 0 or dist == 0xFFFF:
            level_mm = None
            _readings.clear()
            status = "NO_ECHO"
        else:
            _readings.append(dist)
            if len(_readings) > SMOOTH_SIZE:
                _readings.pop(0)
            level_mm = sum(_readings) / len(_readings)
            status = "OK"
            last_update = time.ticks_ms()

    if len(uart_buf) > 64:
        uart_buf = uart_buf[-4:]

# --- WiFi ---
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to WiFi:", config.WIFI_SSID)
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        for _ in range(40):
            if wlan.isconnected():
                break
            led.toggle()
            time.sleep_ms(500)
    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        print("Connected:", ip)
        led.on()
        return ip
    else:
        print("WiFi connection failed")
        led.off()
        return None

# --- MQTT (Home Assistant) ---
mqtt = None
_last_mqtt_publish = 0

def mqtt_enabled():
    return bool(cfg("MQTT_BROKER"))

def mqtt_connect():
    global mqtt
    broker = cfg("MQTT_BROKER")
    if not broker:
        return False
    try:
        user = cfg("MQTT_USER") or None
        pw = cfg("MQTT_PASSWORD") or None
        mqtt = MQTTClient(cfg("MQTT_DEVICE_ID"), broker,
                          port=cfg("MQTT_PORT"),
                          user=user, password=pw,
                          keepalive=60)
        mqtt.connect()
        print("MQTT connected to", broker)
        mqtt_publish_discovery()
        return True
    except Exception as e:
        print("MQTT connect failed:", e)
        mqtt = None
        return False

def mqtt_publish_discovery():
    device_id = cfg("MQTT_DEVICE_ID")
    prefix = cfg("MQTT_TOPIC_PREFIX")
    dev = json.dumps({
        "ids": [device_id],
        "name": "Well Level Sensor",
        "mfr": "DIY",
        "mdl": "Pico2W + DYP-A22YYUW (Well)",
    })
    state_topic = device_id + "/state"
    sensors = [
        ("water_level_mm", "Water Level", "mm", "distance", "measurement"),
        ("distance_mm", "Sensor Distance", "mm", "distance", "measurement"),
        ("litres", "Volume", "L", None, "measurement"),
        ("pct", "Fill", "%", None, "measurement"),
    ]
    for key, name, unit, dev_class, state_class in sensors:
        topic = prefix + "/sensor/" + device_id + "/" + key + "/config"
        c = {
            "name": name,
            "stat_t": state_topic,
            "val_tpl": "{{ value_json." + key + " }}",
            "unit_of_meas": unit,
            "uniq_id": device_id + "_" + key,
            "dev": json.loads(dev),
        }
        if dev_class:
            c["dev_cla"] = dev_class
        if state_class:
            c["stat_cla"] = state_class
        mqtt.publish(topic, json.dumps(c), retain=True)
    topic = prefix + "/binary_sensor/" + device_id + "/status/config"
    c = {
        "name": "Sensor Status",
        "stat_t": state_topic,
        "val_tpl": "{{ 'ON' if value_json.status == 'OK' else 'OFF' }}",
        "dev_cla": "connectivity",
        "uniq_id": device_id + "_status",
        "dev": json.loads(dev),
    }
    mqtt.publish(topic, json.dumps(c), retain=True)
    print("MQTT discovery published")

def mqtt_publish():
    global mqtt, _last_mqtt_publish
    if mqtt is None:
        return
    now = time.ticks_ms()
    interval = cfg("MQTT_PUBLISH_INTERVAL_S") * 1000
    if time.ticks_diff(now, _last_mqtt_publish) < interval:
        return
    _last_mqtt_publish = now
    wl = water_level_mm()
    l = litres()
    depth = cfg("WELL_DEPTH_MM")
    pct = None
    if wl is not None and depth > 0:
        pct = round((wl / depth) * 100, 1)
    payload = json.dumps({
        "water_level_mm": round(wl, 1) if wl is not None else None,
        "distance_mm": round(level_mm, 1) if level_mm is not None else None,
        "litres": round(l, 1) if l is not None else None,
        "pct": pct,
        "status": status,
    })
    try:
        mqtt.publish(cfg("MQTT_DEVICE_ID") + "/state", payload)
    except Exception as e:
        print("MQTT publish error:", e)
        mqtt = None

def mqtt_reconnect():
    """Force disconnect and reconnect MQTT."""
    global mqtt
    if mqtt:
        try:
            mqtt.disconnect()
        except Exception:
            pass
        mqtt = None
    mqtt_connect()

# --- Well calculations ---
# Sensor at top of well measures distance to water surface.
# water_level_mm = well_depth - sensor_reading
def water_level_mm():
    if level_mm is None:
        return None
    return cfg("WELL_DEPTH_MM") - level_mm

def litres():
    wl = water_level_mm()
    if wl is None or wl <= 0:
        return 0.0
    r = cfg("WELL_DIAMETER_MM") / 2
    volume_mm3 = math.pi * r * r * wl
    return volume_mm3 / 1_000_000

# --- Web server ---

def api_response():
    wl = water_level_mm()
    pct = None
    l = litres()
    depth = cfg("WELL_DEPTH_MM")
    if wl is not None and depth > 0:
        pct = (wl / depth) * 100
    return json.dumps({
        "water_level_mm": round(wl, 1) if wl is not None else None,
        "distance_mm": round(level_mm, 1) if level_mm is not None else None,
        "litres": round(l, 1) if l is not None else None,
        "pct": round(pct, 1) if pct is not None else None,
        "status": status,
    })

def history_response(seconds):
    if not _history:
        return "[]"
    now_s = time.ticks_diff(time.ticks_ms(), _boot_ticks) // 1000
    cutoff = now_s - seconds
    pts = [(t, v) for t, v in _history if t >= cutoff]
    return json.dumps(pts)

def settings_get_response():
    defaults = {}
    for key in settings.SCHEMA:
        defaults[key] = getattr(config, key, None)
    return json.dumps(settings.get_all(defaults))

def settings_post(body):
    try:
        new_vals = json.loads(body)
    except ValueError:
        return '{"ok":false}'
    defaults = {}
    for key in settings.SCHEMA:
        defaults[key] = getattr(config, key, None)
    settings.update(new_vals, defaults)
    mqtt_reconnect()
    return '{"ok":true}'

def serve(ip):
    addr = socket.getaddrinfo(ip, 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(5)
    s.setblocking(False)
    print("HTTP server on http://{}".format(ip))
    return s

def send_file(cl, path):
    with open(path, "rb") as f:
        while True:
            chunk = f.read(256)
            if not chunk:
                break
            cl.sendall(chunk)

def handle_client(cl):
    try:
        cl.setblocking(True)
        cl.settimeout(2)
        req = cl.recv(1024).decode("ascii", "ignore")
        if "GET /api/history" in req:
            secs = 3600
            if "range=" in req:
                try:
                    idx = req.index("range=") + 6
                    end = idx
                    while end < len(req) and req[end].isdigit():
                        end += 1
                    secs = int(req[idx:end])
                except (ValueError, IndexError):
                    pass
            body = history_response(secs)
            cl.send("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n")
            cl.send(body)
        elif "GET /api/settings" in req:
            body = settings_get_response()
            cl.send("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n")
            cl.send(body)
        elif "POST /api/settings" in req:
            # extract JSON body after blank line
            body_str = ""
            if "\r\n\r\n" in req:
                body_str = req.split("\r\n\r\n", 1)[1]
            resp = settings_post(body_str)
            cl.send("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n")
            cl.send(resp)
        elif "GET /api" in req:
            body = api_response()
            cl.send("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n")
            cl.send(body)
        elif "GET /settings" in req:
            cl.send(b"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n")
            send_file(cl, "settings.html")
        elif "GET" in req:
            cl.send(b"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n")
            send_file(cl, "index.html")
        else:
            cl.send("HTTP/1.0 404 Not Found\r\n\r\n")
    except Exception as e:
        print("client error:", e)
    finally:
        cl.close()

# --- Main ---
for _ in range(3):
    led.on()
    time.sleep_ms(150)
    led.off()
    time.sleep_ms(150)

ip = connect_wifi()
if not ip:
    while True:
        led.toggle()
        time.sleep_ms(100)

srv = serve(ip)
if mqtt_enabled():
    mqtt_connect()

while True:
    poll_uart()
    record_history()

    # MQTT publish (reconnects if dropped, with cooldown)
    if mqtt_enabled():
        if mqtt is None:
            if time.ticks_diff(time.ticks_ms(), _last_mqtt_publish) > 30_000:
                mqtt_connect()
        mqtt_publish()

    for _ in range(5):
        try:
            cl, _ = srv.accept()
            handle_client(cl)
        except OSError:
            break

    time.sleep_ms(50)
