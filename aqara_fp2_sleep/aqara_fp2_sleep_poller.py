#!/usr/bin/env python3
"""Poll Aqara FP2 sleep telemetry and publish Home Assistant MQTT discovery."""

from base64 import b64encode
import hashlib
import json
import os
import re
import signal
import time
import urllib.error
import urllib.request
import uuid

import paho.mqtt.client as mqtt
from Crypto.Cipher import PKCS1_v1_5
from Crypto.Hash import MD5 as CMD5
from Crypto.PublicKey import RSA

# Aqara Home app built-in constants. These are public app constants, not user
# credentials.
AREAS = {
    "CN": {
        "server": "https://aiot-rpc.aqara.cn",
        "appid": "94549908487478b220992a70",
        "appkey": "Jddz01kIORDYrBzqGYgpUXKBnIHfW8E3",
    },
    "EU": {
        "server": "https://rpc-ger.aqara.com",
        "appid": "7be1984f0556276133336839",
        "appkey": "Jddz01kIORDYrBzqGYgpUXKBnIHfW8E3",
    },
    "RU": {
        "server": "https://rpc-ru.aqara.com",
        "appid": "94549908487478b220992a70",
        "appkey": "euGhPe2rcmxwculATNj45eEtnd50zp0I",
    },
    "KR": {
        "server": "https://rpc-kr.aqara.com",
        "appid": "94549908487478b220992a70",
        "appkey": "euGhPe2rcmxwculATNj45eEtnd50zp0I",
    },
    "USA": {
        "server": "https://aiot-rpc-usa.aqara.com",
        "appid": "94549908487478b220992a70",
        "appkey": "Jddz01kIORDYrBzqGYgpUXKBnIHfW8E3",
    },
}

PUBKEY = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCG46slB57013JJs4Vvj5cVyMpR\n"
    "9b+B2F+YJU6qhBEYbiEmIdWpFPpOuBikDs2FcPS19MiWq1IrmxJtkICGurqImRUt\n"
    "4lP688IWlEmqHfSxSRf2+aH0cH8VWZ2OaZn5DWSIHIPBF2kxM71q8stmoYiV0oZs\n"
    "rZzBHsMuBwA4LQdxBwIDAQAB\n"
    "-----END PUBLIC KEY-----"
)

SLEEP_OPTIONS = [
    "heartrate_value",
    "respiration_rate_value",
    "sleep_state",
    "body_movement_value",
    "lux",
    "set_device_mode4",
    "device_offline_status",
]

AREA = os.environ.get("AQARA_AREA", "EU").upper()
USER = os.environ.get("AQARA_USER", "")
PASSWORD = os.environ.get("AQARA_PASS", "")
SUBJECT = os.environ.get("SUBJECT_ID", "").strip()
INTERVAL = max(15, int(os.environ.get("POLL_INTERVAL", "60") or "60"))
DEVICE_NAME = os.environ.get("DEVICE_NAME", "Aqara FP2 Sleep Monitor").strip()

LEVELS = {
    "trace": 0,
    "debug": 1,
    "info": 2,
    "notice": 2,
    "warning": 3,
    "error": 4,
    "fatal": 4,
}
LOG_LEVEL = LEVELS.get(os.environ.get("LOG_LEVEL", "info"), 2)

MQTT_HOST = os.environ.get("MQTT_HOST", "core-mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883") or "1883")
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
MQTT_SSL = str(os.environ.get("MQTT_SSL", "false")).lower() in ("true", "1", "yes")
MQTT_CONNECT_RETRIES = 6
MQTT_CONNECT_BACKOFF = (
    5  # seconds; doubles each attempt, capped at MQTT_CONNECT_BACKOFF_MAX
)
MQTT_CONNECT_BACKOFF_MAX = 60


def sanitize_node_id(value):
    node = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower())
    node = re.sub(r"_+", "_", node).strip("_")
    return node or "aqara_fp2_sleep"


DISCOVERY_PREFIX = "homeassistant"
NODE = sanitize_node_id(os.environ.get("MQTT_NODE_ID", "aqara_fp2_sleep"))
STATE_TOPIC = f"aqara/{NODE}/state"
AVAIL_TOPIC = f"aqara/{NODE}/status"
DEVICE = {
    "identifiers": [f"aqara_fp2_sleep_{NODE}"],
    "name": DEVICE_NAME or "Aqara FP2 Sleep Monitor",
    "manufacturer": "Aqara",
    "model": "FP2 (Sleep Monitor)",
    "sw_version": "aqara_fp2_sleep 1.0.0",
}
ORIGIN = {"name": "SleepRadar", "sw": "1.0.0"}
EXPIRE_AFTER = max(180, INTERVAL * 3)

SENSORS = [
    (
        "heartrate_value",
        f"{NODE}_heart_rate",
        "heart_rate",
        "Heart rate",
        "bpm",
        "measurement",
        None,
        "mdi:heart-pulse",
    ),
    (
        "respiration_rate_value",
        f"{NODE}_respiration_rate",
        "respiration_rate",
        "Respiration rate",
        "br/min",
        "measurement",
        None,
        "mdi:lungs",
    ),
    (
        "sleep_state",
        f"{NODE}_sleep_state",
        "sleep_state",
        "Sleep state",
        None,
        None,
        None,
        "mdi:sleep",
    ),
    (
        "body_movement_value",
        f"{NODE}_body_movement",
        "body_movement",
        "Body movement",
        None,
        "measurement",
        None,
        "mdi:run",
    ),
    (
        "lux",
        f"{NODE}_illuminance",
        "illuminance",
        "Illuminance",
        "lx",
        "measurement",
        "illuminance",
        "mdi:brightness-5",
    ),
]


def log(level, msg):
    if LEVELS.get(level, 2) >= LOG_LEVEL:
        print(f"[{level}] {msg}", flush=True)


def md5(s):
    return hashlib.md5(s.encode()).hexdigest()


class Aqara:
    def __init__(self, area):
        if area not in AREAS:
            fatal_startup(f"Unknown AQARA_AREA={area!r}; use one of {', '.join(AREAS)}")
        self.area = area
        self.cfg = AREAS[area]
        self.token = None
        self.userid = None

    def _headers(self, body):
        nonce = md5(str(uuid.uuid4()))
        now_ms = str(round(time.time() * 1000))
        appid = self.cfg["appid"]
        appkey = self.cfg["appkey"]
        parts = [f"Appid={appid}", f"Nonce={nonce}", f"Time={now_ms}"]
        if self.token:
            parts.append(f"Token={self.token}")
        if body:
            parts.append(body)
        parts.append(appkey)
        headers = {
            "Area": self.area,
            "Appid": appid,
            "Nonce": nonce,
            "Time": now_ms,
            "Sign": md5("&".join(parts)),
            "User-Agent": "pyAqara/1.0.0",
            "App-Version": "3.0.0",
            "Sys-Type": "1",
            "Lang": "en",
            "PhoneId": str(uuid.uuid4()).upper(),
        }
        if self.token:
            headers["Token"] = self.token
        if self.userid:
            headers["Userid"] = self.userid
        return headers

    def _post(self, path, body_obj):
        body = json.dumps(body_obj)
        headers = self._headers(body)
        headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(
            self.cfg["server"] + path,
            data=body.encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as err:
            try:
                return json.loads(err.read().decode())
            except Exception:
                return {"code": err.code, "message": f"HTTP {err.code}"}
        except Exception as err:
            return {"code": -1, "message": f"{type(err).__name__}: {err}"}

    def login(self):
        rsa = PKCS1_v1_5.new(RSA.importKey(PUBKEY))
        encrypted_password = b64encode(
            rsa.encrypt(CMD5.new(PASSWORD.encode()).hexdigest().encode())
        ).decode()
        res = self._post(
            "/app/v1.0/lumi/user/login",
            {"account": USER, "encryptType": 2, "password": encrypted_password},
        )
        if res.get("code") == 0:
            self.token = res["result"]["token"]
            self.userid = res["result"]["userId"]
            log("info", "Aqara login OK")
            return True
        log("error", f"Aqara login failed: code={res.get('code')} {res.get('message')}")
        return False

    def res_query(self, did, options):
        return self._post(
            "/app/v1.0/lumi/res/query",
            {"data": [{"options": options, "subjectId": did}]},
        )


def discovery_payload(
    attr, object_id, uid_suffix, name, unit, state_class, device_class, icon
):
    payload = {
        "name": name,
        "unique_id": f"{NODE}_{uid_suffix}",
        "object_id": object_id,
        "default_entity_id": f"sensor.{object_id}",
        "state_topic": STATE_TOPIC,
        "value_template": "{{ value_json.%s | default('unknown') }}" % attr,
        "icon": icon,
        "availability_topic": AVAIL_TOPIC,
        "payload_available": "online",
        "payload_not_available": "offline",
        "expire_after": EXPIRE_AFTER,
        # Without this, HA skips the state write (and last_updated stays
        # frozen) whenever a poll republishes an unchanged value — e.g. a
        # long stable deep-sleep reading — which would make the SleepRadar
        # Card's last_updated-based "stale" badge false-positive during
        # entirely normal operation.
        "force_update": True,
        "origin": ORIGIN,
        "device": DEVICE,
    }
    if unit:
        payload["unit_of_measurement"] = unit
    if state_class:
        payload["state_class"] = state_class
    if device_class:
        payload["device_class"] = device_class
    return payload


def publish_discovery(client):
    for attr, object_id, uid_suffix, name, unit, sc, dc, icon in SENSORS:
        topic = f"{DISCOVERY_PREFIX}/sensor/{NODE}/{uid_suffix}/config"
        payload = discovery_payload(
            attr, object_id, uid_suffix, name, unit, sc, dc, icon
        )
        client.publish(topic, json.dumps(payload), qos=1, retain=True)
    log("info", f"Published discovery for {len(SENSORS)} sensors")


def make_mqtt():
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=NODE)
    except (AttributeError, TypeError):
        client = mqtt.Client(client_id=NODE)
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    if MQTT_SSL:
        client.tls_set()
    client.will_set(AVAIL_TOPIC, "offline", qos=1, retain=True)

    delay = MQTT_CONNECT_BACKOFF
    for attempt in range(1, MQTT_CONNECT_RETRIES + 1):
        if not _running:
            log("info", "Shutdown requested during MQTT connect retry; exiting")
            raise SystemExit(0)
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=max(60, INTERVAL * 2))
            break
        except OSError as err:
            if not _running:
                log("info", "Shutdown requested during MQTT connect retry; exiting")
                raise SystemExit(0) from None
            if attempt == MQTT_CONNECT_RETRIES:
                log(
                    "fatal",
                    f"MQTT connect to {MQTT_HOST}:{MQTT_PORT} failed after "
                    f"{MQTT_CONNECT_RETRIES} attempts: {err}",
                )
                raise
            log(
                "warning",
                f"MQTT connect to {MQTT_HOST}:{MQTT_PORT} failed "
                f"(attempt {attempt}/{MQTT_CONNECT_RETRIES}): {err}; "
                f"retrying in {delay}s",
            )
            if not interruptible_sleep(delay):
                log("info", "Shutdown requested during MQTT connect retry; exiting")
                raise SystemExit(0) from None
            delay = min(delay * 2, MQTT_CONNECT_BACKOFF_MAX)

    client.loop_start()
    return client


def describe_poll_failure(res):
    code = res.get("code")
    if code is not None and code != 0:
        return f"Aqara API error (code={code}): {res.get('message') or 'no message returned'}"
    if "result" in res:
        return f"unexpected response shape from Aqara API (result was not a list): {json.dumps(res)[:200]}"
    return f"unrecognized response from Aqara API: {json.dumps(res)[:200]}"


_running = True


def _stop(*_):
    global _running
    _running = False


def interruptible_sleep(seconds):
    for _ in range(seconds):
        if not _running:
            return False
        time.sleep(1)
    return _running


# Cooldown before exiting on a permanent startup misconfiguration. If the process
# is supervised by an external watchdog, this keeps blank/typo'd config or an
# unknown area from becoming a tight restart loop that burns CPU and floods logs.
STARTUP_FAILURE_COOLDOWN = int(os.getenv("STARTUP_FAILURE_COOLDOWN", "30"))


def fatal_startup(msg):
    log("fatal", msg)
    interruptible_sleep(STARTUP_FAILURE_COOLDOWN)
    raise SystemExit(1)


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    if not (USER and PASSWORD and SUBJECT):
        fatal_startup("Missing AQARA_USER / AQARA_PASS / SUBJECT_ID")

    client = make_mqtt()
    publish_discovery(client)

    aqara = Aqara(AREA)
    if not aqara.login():
        log(
            "fatal",
            "Aqara login failed at startup. Check aqara_username, aqara_password, "
            "aqara_area, and subject_id. The add-on keeps retrying; the sensors "
            "stay unavailable until login succeeds.",
        )

    while _running:
        ok = False
        res = aqara.res_query(SUBJECT, SLEEP_OPTIONS)
        if res.get("code") != 0:
            log(
                "warning",
                f"res/query code={res.get('code')} ({res.get('message')}); re-login",
            )
            if aqara.login():
                res = aqara.res_query(SUBJECT, SLEEP_OPTIONS)

        if res.get("code") == 0 and isinstance(res.get("result"), list):
            values = {
                item["attr"]: item["value"] for item in res["result"] if "attr" in item
            }
            state = {attr: values.get(attr) for attr, *_ in SENSORS}
            client.publish(STATE_TOPIC, json.dumps(state), qos=0, retain=False)
            client.publish(AVAIL_TOPIC, "online", qos=1, retain=True)
            ok = True
            log("debug", f"state={state}")
        if not ok:
            client.publish(AVAIL_TOPIC, "offline", qos=1, retain=True)
            log("error", f"poll failed: {describe_poll_failure(res)}")

        interruptible_sleep(INTERVAL)

    log("info", "Shutting down; marking offline.")
    client.publish(AVAIL_TOPIC, "offline", qos=1, retain=True)
    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
