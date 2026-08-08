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

# Home Assistant core API, reached through the Supervisor proxy. Used only to
# raise and clear a persistent notification, and only when the add-on was
# granted homeassistant_api. Every call fails soft.
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
CORE_API = os.environ.get("CORE_API", "http://supervisor/core/api")

# Consecutive transient failures tolerated before the diagnostic entity flips
# to a problem. DNS blips against the Aqara endpoints are common enough on this
# hardware (URLError / Errno -3) that flagging the first one would page people
# at 03:00 for something that heals itself on the next poll. A real outage
# still surfaces within TRANSIENT_FAILURE_GRACE * POLL_INTERVAL seconds.
# A permanent rejection never waits for this grace.
TRANSIENT_FAILURE_GRACE = max(1, int(os.environ.get("TRANSIENT_FAILURE_GRACE", "3")))

# Backoff between login attempts after Aqara has *rejected* the credentials, as
# opposed to failing to answer. Without it a wrong password or region retries
# every poll interval forever: at the default 60s that is ~2,880 rejected auth
# requests a day, which is how accounts get rate-limited or locked.
AUTH_RETRY_BACKOFF = max(INTERVAL, 60)
AUTH_RETRY_BACKOFF_MAX = 1800

# Aqara answers a rejected login with code 106 and the unhelpful text "Request
# failed. Please try again." — which is what a wrong region looks like, because
# an Aqara Home account only exists in the region it was created in. Codes
# below are the ones observed in the field; everything else is classified
# structurally by is_transient_code().
AQARA_CODE_ACCOUNT_REJECTED = 106

# Failures that mean "Aqara did not answer" rather than "Aqara said no".
# -1 is this client's own catch-all for socket/DNS/timeout exceptions, see
# Aqara._post(). The HTTP codes are server-side and heal without user action.
TRANSIENT_HTTP_CODES = frozenset({429, 500, 502, 503, 504})


def sanitize_node_id(value):
    node = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower())
    node = re.sub(r"_+", "_", node).strip("_")
    return node or "aqara_fp2_sleep"


DISCOVERY_PREFIX = "homeassistant"
NODE = sanitize_node_id(os.environ.get("MQTT_NODE_ID", "aqara_fp2_sleep"))
STATE_TOPIC = f"aqara/{NODE}/state"
AVAIL_TOPIC = f"aqara/{NODE}/status"

# Diagnostic surface. The vitals sensors go `unavailable` when anything breaks,
# which tells a user that something is wrong but never what or how to fix it.
# These topics carry the reason. They are deliberately NOT gated by
# AVAIL_TOPIC: an entity that goes unavailable at exactly the moment it has
# something to say is useless.
PROBLEM_STATE_TOPIC = f"aqara/{NODE}/problem"
PROBLEM_ATTR_TOPIC = f"aqara/{NODE}/problem/attributes"
PROBLEM_OBJECT_ID = f"{NODE}_connection_problem"
NOTIFICATION_ID = f"{NODE}_connection_problem"
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
        # Last failing login response, kept so callers can tell "Aqara said no"
        # apart from "Aqara did not answer" without re-running the request.
        self.last_error = None

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
            self.last_error = None
            log("info", "Aqara login OK")
            return True
        self.last_error = res
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


def problem_discovery_payload():
    """Discovery for the diagnostic entity.

    Three deliberate differences from the vitals sensors:

    - no `availability_topic`. The vitals hang off AVAIL_TOPIC and go
      unavailable on any failure. This entity exists to explain that failure,
      so gating it on the same topic would blank it exactly when it matters.
    - no `expire_after`. The vitals expire so a dead poller stops showing a
      stale heart rate. This one must stay readable, and process death is
      covered by the MQTT will instead (see make_mqtt).
    - no `force_update`. That flag exists so the card's last_updated stale
      badge survives unchanged readings; a problem flag has no such consumer.
    """
    return {
        "name": "Connection problem",
        "unique_id": f"{NODE}_connection_problem",
        "object_id": PROBLEM_OBJECT_ID,
        "default_entity_id": f"binary_sensor.{PROBLEM_OBJECT_ID}",
        "state_topic": PROBLEM_STATE_TOPIC,
        "json_attributes_topic": PROBLEM_ATTR_TOPIC,
        "payload_on": "ON",
        "payload_off": "OFF",
        "device_class": "problem",
        "entity_category": "diagnostic",
        "icon": "mdi:cloud-alert",
        "origin": ORIGIN,
        "device": DEVICE,
    }


def publish_discovery(client):
    for attr, object_id, uid_suffix, name, unit, sc, dc, icon in SENSORS:
        topic = f"{DISCOVERY_PREFIX}/sensor/{NODE}/{uid_suffix}/config"
        payload = discovery_payload(
            attr, object_id, uid_suffix, name, unit, sc, dc, icon
        )
        client.publish(topic, json.dumps(payload), qos=1, retain=True)
    client.publish(
        f"{DISCOVERY_PREFIX}/binary_sensor/{NODE}/connection_problem/config",
        json.dumps(problem_discovery_payload()),
        qos=1,
        retain=True,
    )
    log(
        "info",
        f"Published discovery for {len(SENSORS)} sensors and 1 diagnostic entity",
    )


def publish_problem(client, problem, cause=None, code=None, last_success=None):
    """Publish the diagnostic state and its attributes, both retained.

    Retained so the reason survives a Home Assistant restart: an outage that
    started before the restart still explains itself afterwards.
    """
    client.publish(
        PROBLEM_STATE_TOPIC, "ON" if problem else "OFF", qos=1, retain=True
    )
    client.publish(
        PROBLEM_ATTR_TOPIC,
        json.dumps(
            {
                "cause": cause,
                "error_code": code,
                "configured_area": AREA,
                "last_successful_poll": last_success,
            }
        ),
        qos=1,
        retain=True,
    )


def make_mqtt():
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=NODE)
    except (AttributeError, TypeError):
        client = mqtt.Client(client_id=NODE)
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    if MQTT_SSL:
        client.tls_set()
    # paho allows a single will, and the diagnostic entity is the one that
    # needs it: it has no expire_after, so nothing else would ever mark it
    # stale if this process dies ungracefully. The vitals keep their
    # expire_after (>= 3 poll intervals), which covers the same case for them.
    client.will_set(PROBLEM_STATE_TOPIC, "ON", qos=1, retain=True)

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


def is_transient_code(code):
    """True when Aqara failed to answer, false when Aqara answered "no".

    The distinction decides whether a human has to do something. A DNS blip
    heals itself; a rejected password never does, no matter how often it is
    retried.
    """
    return code == -1 or code in TRANSIENT_HTTP_CODES


def describe_login_failure(res, area=None):
    """Classify a failed login into (kind, cause) where kind is
    "transient" or "permanent" and cause is text a user can act on."""
    code = res.get("code")
    message = res.get("message") or "no message returned"
    area = area or AREA

    # Aqara answered successfully and we could not read the payload. Nothing
    # about the credentials is wrong, so this must never reach the permanent
    # branch: that would suspend polling for up to AUTH_RETRY_BACKOFF_MAX and
    # tell the user their sign-in was rejected with "code 0".
    if code == 0:
        return ("transient", describe_poll_failure(res))

    if is_transient_code(code):
        return (
            "transient",
            f"Cannot reach the Aqara cloud (code {code}): {message}. "
            "This is usually a network or DNS problem and often clears on its "
            "own.",
        )

    if code == AQARA_CODE_ACCOUNT_REJECTED:
        return (
            "permanent",
            f"Aqara rejected the sign-in (code {code}). The configured region "
            f"is {area}. An Aqara Home account only exists in the region it "
            "was created in, so the wrong region rejects an otherwise correct "
            "password. Check aqara_area first, then aqara_username and "
            "aqara_password.",
        )

    return (
        "permanent",
        f"Aqara rejected the sign-in (code {code}): {message}. Check "
        "aqara_username, aqara_password and aqara_area (currently "
        f"{area}). Use the Aqara Home app account, not the Aqara webshop "
        "account.",
    )


def call_core_service(domain, service, payload):
    """Best-effort Home Assistant service call through the Supervisor proxy.

    Returns True on success. Never raises: losing a notification must not take
    the poller down, and the add-on still runs fine when homeassistant_api was
    not granted.
    """
    if not SUPERVISOR_TOKEN:
        log("debug", f"no SUPERVISOR_TOKEN; skipping {domain}.{service}")
        return False
    req = urllib.request.Request(
        f"{CORE_API}/services/{domain}/{service}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            return True
    except Exception as err:  # noqa: BLE001 - notifications are best effort
        log("debug", f"{domain}.{service} call failed: {type(err).__name__}: {err}")
        return False


def notify_problem(cause):
    """Raise (or replace) the Home Assistant notification carrying the cause.

    A fixed notification_id means a repeat replaces the previous one instead of
    stacking a new card every poll interval.
    """
    delivered = call_core_service(
        "persistent_notification",
        "create",
        {
            "notification_id": NOTIFICATION_ID,
            "title": "SleepRadar is not receiving data",
            "message": (
                f"{cause}\n\n"
                "Open **Settings > Apps > SleepRadar > Configuration**, correct "
                "the options, then restart the app. Sensors stay unavailable "
                "until the sign-in succeeds.\n\n"
                "[Troubleshooting](https://github.com/florianhorner/ha-fp2-sleep"
                "#login-fails)"
            ),
        },
    )
    if not delivered:
        # Loud, because a silently undelivered notification is the exact
        # failure mode this feature exists to remove. Bounded: notify_problem
        # only runs when the cause changes.
        log(
            "warning",
            "Could not raise the Home Assistant notification; the diagnostic "
            "entity still reports the problem. After updating from a version "
            "without Home Assistant API access, approve it once in the app's "
            "Configuration tab.",
        )
    return delivered


def clear_problem_notification():
    return call_core_service(
        "persistent_notification", "dismiss", {"notification_id": NOTIFICATION_ID}
    )


def last_error(aqara):
    """The client's last failing login response, or {}.

    getattr because test doubles for Aqara are not required to carry it.
    """
    return getattr(aqara, "last_error", None) or {}


def describe_failure(res, login_ok):
    """(kind, cause) for whatever most recently failed.

    A rejected sign-in and a rejected device query need different advice: the
    first points at the credentials, the second at subject_id or a device that
    has left the account.
    """
    kind, cause = describe_login_failure(res)
    if login_ok and kind == "permanent" and res.get("code") != 0:
        cause = (
            f"Signed in to Aqara, but the FP2 query was rejected "
            f"(code {res.get('code')}): "
            f"{res.get('message') or 'no message returned'}. Check that "
            "subject_id points at the sleep FP2 and that the device is still "
            "in your Aqara Home account."
        )
    return kind, cause


class Health:
    """Owns the diagnostic entity and the notification that mirrors it.

    Transient failures get a grace window before they count, because a single
    DNS blip is not worth a notification. Permanent ones are flagged on the
    first occurrence: retrying will not fix them.
    """

    def __init__(self, client):
        self.client = client
        self.problem = None  # None = nothing published yet
        self.cause = None
        self.transient_streak = 0
        self.last_success = None

    def recovered(self):
        self.transient_streak = 0
        self.last_success = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if self.problem is not False:
            if self.problem:
                log("info", "Aqara connection recovered; clearing the problem flag")
            publish_problem(self.client, False, last_success=self.last_success)
            clear_problem_notification()
            self.problem = False
            self.cause = None
            return
        publish_problem(self.client, False, last_success=self.last_success)

    def failed(self, kind, cause, code):
        if kind == "transient":
            self.transient_streak += 1
            if self.transient_streak < TRANSIENT_FAILURE_GRACE:
                log(
                    "debug",
                    f"transient failure {self.transient_streak}/"
                    f"{TRANSIENT_FAILURE_GRACE} before flagging a problem",
                )
                return
        else:
            self.transient_streak = 0

        # Re-notify when the *reason* changes, not just on the first failure.
        # A blip that turns out to be a rejected region would otherwise leave
        # the notification reading "often clears on its own" forever, which is
        # the opposite of what this feature is for. Unchanged causes stay
        # quiet, so an ongoing outage still does not re-notify every poll.
        changed = self.problem is not True or cause != self.cause
        publish_problem(
            self.client, True, cause=cause, code=code, last_success=self.last_success
        )
        if changed:
            log("error", f"Flagging a connection problem: {cause}")
            notify_problem(cause)
        self.problem = True
        self.cause = cause


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
    health = Health(client)

    login_ok = aqara.login()
    if not login_ok:
        startup_error = last_error(aqara)
        kind, cause = describe_login_failure(startup_error)
        # Deliberately not "fatal": this process keeps running and recovers on
        # its own once the options are corrected. Calling it fatal told users
        # to expect a crash that never came.
        log(
            "error",
            f"Aqara login failed at startup. {cause} The add-on keeps retrying; "
            "the sensors stay unavailable until the sign-in succeeds.",
        )
        # Flag it now rather than after the first poll. A rejected sign-in at
        # boot is already certain, and waiting a full poll interval to say so
        # is a whole interval of the silence this entity exists to end.
        # Transient failures still go through the grace window inside Health.
        health.failed(kind, cause, startup_error.get("code"))

    auth_wait = 0
    auth_delay = AUTH_RETRY_BACKOFF

    while _running:
        # Aqara has rejected these credentials. Retrying at the poll interval
        # would hammer the auth endpoint for no possible gain, so hold off.
        if auth_wait > 0:
            log("debug", f"auth backoff: {auth_wait}s before retrying the sign-in")
            auth_wait = max(0, auth_wait - INTERVAL)
            interruptible_sleep(INTERVAL)
            continue

        ok = False
        res = aqara.res_query(SUBJECT, SLEEP_OPTIONS)
        if res.get("code") != 0:
            log(
                "warning",
                f"res/query code={res.get('code')} ({res.get('message')}); re-login",
            )
            login_ok = aqara.login()
            if login_ok:
                res = aqara.res_query(SUBJECT, SLEEP_OPTIONS)
            else:
                res = last_error(aqara) or res

        if res.get("code") == 0 and isinstance(res.get("result"), list):
            values = {
                item["attr"]: item["value"] for item in res["result"] if "attr" in item
            }
            state = {attr: values.get(attr) for attr, *_ in SENSORS}
            client.publish(STATE_TOPIC, json.dumps(state), qos=0, retain=False)
            client.publish(AVAIL_TOPIC, "online", qos=1, retain=True)
            ok = True
            log("debug", f"state={state}")

        if ok:
            auth_delay = AUTH_RETRY_BACKOFF
            health.recovered()
        else:
            client.publish(AVAIL_TOPIC, "offline", qos=1, retain=True)
            log("error", f"poll failed: {describe_poll_failure(res)}")
            kind, cause = describe_failure(res, login_ok)
            health.failed(kind, cause, res.get("code"))
            if kind == "permanent":
                # The end-of-loop sleep below already burns one interval, so
                # subtract it here. Without this the real gap between sign-in
                # attempts is auth_delay + INTERVAL and the logged countdown
                # understates the actual wait.
                auth_wait = max(0, auth_delay - INTERVAL)
                auth_delay = min(auth_delay * 2, AUTH_RETRY_BACKOFF_MAX)

        interruptible_sleep(INTERVAL)

    # A deliberate stop is not a problem, and a problem that was already
    # flagged does not stop being one. Either way the retained diagnostic
    # state is left exactly as it was; the MQTT will only fires on an
    # ungraceful death, which is the case that genuinely needs flagging.
    log("info", "Shutting down; marking offline.")
    client.publish(AVAIL_TOPIC, "offline", qos=1, retain=True)
    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
