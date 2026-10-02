#!/usr/bin/env python3
"""Poll Aqara FP2 sleep telemetry and publish Home Assistant MQTT discovery."""

from base64 import b64encode
import hashlib
import json
import os
import re
import signal
import time
import unicodedata
import urllib.error
import urllib.request
import uuid

import paho.mqtt.client as mqtt
from Crypto.Cipher import PKCS1_v1_5
from Crypto.Hash import MD5 as CMD5
from Crypto.PublicKey import RSA

# Aqara Home app built-in constants. These are public app constants, not user
# credentials. The USA and CN pairs were checked against their live hosts on
# 2026-10-01. scripts/validate_repository.py pins a fingerprint of every row
# (server, app id and key) and records how it was checked, so any change here
# fails the build until its fingerprint is updated, the prompt to check the
# row against its live host again.
AREAS = {
    "CN": {
        "server": "https://aiot-rpc.aqara.cn",
        "appid": "94549908487478b220992a70",
        "appkey": "euGhPe2rcmxwculATNj45eEtnd50zp0I",
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
        "appkey": "euGhPe2rcmxwculATNj45eEtnd50zp0I",
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
# hardware (URLError / Errno -3) that flagging the first one would notify the
# user about something the next poll fixes. A real outage still surfaces within
# TRANSIENT_FAILURE_GRACE * POLL_INTERVAL seconds. A permanent rejection never
# waits for this grace.
TRANSIENT_FAILURE_GRACE = max(1, int(os.environ.get("TRANSIENT_FAILURE_GRACE", "3")))

# Backoff between login attempts after Aqara has *rejected* the credentials, as
# opposed to failing to answer. Without it a wrong password or region retries
# every poll interval forever: at the default 60s that is ~2,880 rejected auth
# requests a day, which is how accounts get rate-limited or locked.
AUTH_RETRY_BACKOFF = max(INTERVAL, 60)
AUTH_RETRY_BACKOFF_MAX = 1800

# Aqara result codes that get their own message. Meanings follow Aqara's public
# error table and the msgDetails field of the response; everything else is
# classified structurally by is_transient_code().
# 106 "Invalid sign": Aqara rejected the request signature, which comes from
#     SleepRadar's built-in app key for the region. It says nothing about the
#     user's password or region.
AQARA_CODE_INVALID_SIGN = 106
# 108 "Token has expired": right after a fresh sign-in, another sign-in on the
#     same Aqara account has ended SleepRadar's session.
AQARA_CODE_TOKEN_EXPIRED = 108
# 755 no permission for the device: after a good sign-in, aqara_area is not the
#     region the FP2 is registered in, or subject_id points at another device.
AQARA_CODE_SUBJECT_PERMISSION_DENIED = 755

ISSUES_URL = "https://github.com/florianhorner/ha-fp2-sleep/issues"

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
# These topics carry the reason, so they are not gated by AVAIL_TOPIC: gating
# them would blank the reason at the moment it is needed.
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
                body = json.loads(err.read().decode())
            except Exception:
                return {"code": err.code, "message": f"HTTP {err.code}"}
            # A gateway error page carries no usable Aqara code. Keep the HTTP
            # status, so a 429 or 5xx still reads as "no answer", not as a
            # rejection.
            code = body.get("code") if isinstance(body, dict) else None
            if isinstance(body, dict) and (not isinstance(code, int) or isinstance(code, bool)):
                body["code"] = err.code
            return body
        except Exception as err:
            return {"code": -1, "message": f"{type(err).__name__}: {err}"}

    def login(self):
        # Every sign-in starts like the first one: an expired session's token
        # must not be signed into the request that replaces it.
        self.token = None
        self.userid = None
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
        log("error", f"Aqara login failed: code={code_text(res.get('code'))} {aqara_error_text(res)}")
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

    Three differences from the vitals sensors, all on purpose:

    - no `availability_topic`. The vitals hang off AVAIL_TOPIC and go
      unavailable on any failure. This entity exists to explain that failure,
      so gating it on the same topic would blank it when it is needed.
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


# Aqara's own text reaches the log, the entity's cause attribute and a Markdown
# notification, so it is shown as one line of plain text, capped. The detail
# gets its own share of the cap, so a long message cannot push it out.
ERROR_TEXT_LIMIT = 200
DETAILS_LIMIT = 80
# Markdown link, image and HTML syntax, and backslash escapes.
_MARKUP = re.compile(r"[\[\]()<>!`\\]")


def plain_text(value):
    """`value` as one line of plain text: control and invisible format
    characters (Unicode categories C, Zl and Zp) and Markdown link, image and
    HTML syntax become spaces, and whitespace collapses."""
    text = "".join(
        " " if unicodedata.category(char)[0] == "C" or unicodedata.category(char) in ("Zl", "Zp")
        else char
        for char in str(value)
    )
    return " ".join(_MARKUP.sub(" ", text).split())


def code_text(code):
    """The reply's code for display. It comes from the server as well, so
    anything but an int is shown as capped plain text."""
    if isinstance(code, int) and not isinstance(code, bool):
        return str(code)[:20]
    return plain_text(code)[:20] if code is not None else "none"


def aqara_error_text(res):
    """Aqara's own error text: `message`, plus `msgDetails` when it adds
    something. `msgDetails` is where Aqara names the real cause ("Invalid
    sign"), while `message` is often a generic "Request failed"."""
    details = plain_text(res.get("msgDetails") or "")[:DETAILS_LIMIT].rstrip()
    budget = ERROR_TEXT_LIMIT - (len(details) + 3 if details else 0)
    message = plain_text(res.get("message") or "")[:budget].rstrip() or "no message returned"
    if details and details != message:
        return f"{message} ({details})"
    return message


def user_message(plain, todo, technical):
    """A message in the order a user needs it: what happened, what to do, and
    only then the technical details (code and Aqara's own text)."""
    if not technical.endswith("."):
        technical += "."
    return f"{plain} What to do: {todo} Technical details: {technical}"


def describe_poll_failure(res):
    code = res.get("code")
    if code is not None and code != 0:
        return f"Aqara API error (code={code_text(code)}): {aqara_error_text(res)}"
    # The shape only: the reply itself can carry the sensor's id and readings,
    # and this line is what users paste into a report. main() logs the raw
    # reply at debug level.
    if "result" in res:
        return (
            "unexpected response shape from Aqara API (result was a "
            f"{type(res['result']).__name__}, not a list)"
        )
    return f"unrecognized response from Aqara API (no code, {len(res)} fields)"


def is_transient_code(code):
    """True when Aqara failed to answer, false when Aqara answered "no".

    The distinction decides whether a human has to do something. A DNS blip
    clears on the next poll; a rejected password never does.
    """
    return code == -1 or code in TRANSIENT_HTTP_CODES


# What users see, by Aqara code. Every message reads: what happened, what to
# do, then the technical details.
#
#   106 at sign-in or on the sensor query -> SleepRadar's request rejected;
#                                            update SleepRadar or report it
#   108 right after a fresh sign-in       -> session ended by another sign-in
#   755 after a sign-in                   -> wrong aqara_area or subject_id
#   other code after a sign-in            -> check subject_id
#   other code at sign-in (810, ...)      -> check username, password, region
#   -1, 429, 5xx                          -> no answer from Aqara; wait
#   0 with an unreadable payload          -> unreadable reply; wait
def describe_login_failure(res, area=None, request="sign-in"):
    """Classify a failed login into (kind, cause) where kind is
    "transient" or "permanent" and cause is text a user can act on.

    `request` names the request that failed in the technical details; the
    106 message is shared with describe_failure for the sensor query."""
    code = res.get("code")
    area = area or AREA

    # Aqara answered successfully and we could not read the payload. Nothing
    # about the credentials is wrong, so this must never reach the permanent
    # branch: that would suspend polling for up to AUTH_RETRY_BACKOFF_MAX and
    # tell the user their sign-in was rejected with "code 0".
    if code == 0:
        result = res.get("result")
        shape = "no result" if result is None else f"a {type(result).__name__} result, not a list"
        return (
            "transient",
            user_message(
                "Aqara answered, but SleepRadar couldn't read the reply. This "
                "is usually temporary.",
                f"nothing yet. If it keeps happening, report it at {ISSUES_URL}.",
                # The shape only: the reply itself can carry the sensor's id and
                # readings, and this text is what users paste into a report.
                f"code 0 with {shape}",
            ),
        )

    if is_transient_code(code):
        return (
            "transient",
            user_message(
                "SleepRadar can't get an answer from Aqara right now. This is "
                "usually a short network problem or a busy Aqara server and "
                "clears on its own.",
                "nothing yet. If it doesn't clear, check that Home Assistant is "
                "online and that nothing on your network blocks Aqara's servers.",
                f"code {code_text(code)}: {aqara_error_text(res)}",
            ),
        )

    if code == AQARA_CODE_INVALID_SIGN:
        return (
            "permanent",
            user_message(
                f"SleepRadar can't get your data from Aqara: Aqara's {area} "
                "server rejected SleepRadar's request. This error does not mean "
                "your password or region is wrong.",
                "update SleepRadar first. If you already have the latest "
                f"version, report it at {ISSUES_URL}.",
                f"Aqara code {code_text(code)} on {request}: {aqara_error_text(res)}",
            ),
        )

    return (
        "permanent",
        user_message(
            "Aqara didn't accept SleepRadar's sign-in.",
            "in Settings > Apps > SleepRadar > Configuration, check "
            "aqara_username and aqara_password (your Aqara Home app account, "
            f"not the Aqara webshop account) and that aqara_area ({area}) is "
            "the region your Aqara Home app uses, then restart the app.",
            aqara_code_text(res),
        ),
    )


def aqara_code_text(res):
    """The technical-details part for a rejection: the code and Aqara's text."""
    code = res.get("code")
    if code is None:
        return f"Aqara returned no error code: {aqara_error_text(res)}"
    return f"Aqara code {code_text(code)}: {aqara_error_text(res)}"


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
            # The cause already says what to do. The frame adds no instruction
            # of its own: a generic "correct the options" would contradict the
            # causes the options cannot fix (an outdated SleepRadar, Aqara not
            # answering).
            "message": (
                f"{cause}\n\n"
                "Sensors stay unavailable until this is resolved.\n\n"
                "[Troubleshooting](https://github.com/florianhorner/ha-fp2-sleep"
                "#login-fails)"
            ),
        },
    )
    if not delivered:
        # Warning rather than debug: an undelivered notification is itself an
        # outage the user cannot see. Bounded, because notify_problem only runs
        # when the cause changes.
        log(
            "warning",
            "Could not raise the Home Assistant notification; the diagnostic "
            "entity still reports the problem. After updating from a version "
            "without Home Assistant API access, approve it once in the app's "
            "Configuration tab.",
        )
    return delivered


def clear_problem_notification():
    """Dismiss the problem notification once the problem is fixed."""
    return call_core_service(
        "persistent_notification", "dismiss", {"notification_id": NOTIFICATION_ID}
    )


def last_error(aqara):
    """The client's last failing login response, or {}.

    getattr because test doubles for Aqara are not required to carry it.
    """
    return getattr(aqara, "last_error", None) or {}


def describe_failure(res, login_ok, area=None):
    """(kind, cause) for whatever most recently failed.

    A rejected sign-in and a rejected device query need different advice: the
    first points at the credentials, the second at subject_id, the region, or
    a device that has left the account. Two codes keep their own meaning after
    a good sign-in: 106 is still SleepRadar's signing problem, and 108 is a
    session another sign-in ended, not a sensor-ID problem.
    """
    area = area or AREA
    code = res.get("code")
    if login_ok and code == AQARA_CODE_INVALID_SIGN:
        return describe_login_failure(res, area, request="the sensor query")
    kind, cause = describe_login_failure(res, area)
    if not login_ok or kind != "permanent":
        return kind, cause
    if code == AQARA_CODE_TOKEN_EXPIRED:
        return kind, user_message(
            "Aqara ended SleepRadar's session right after it signed in. This "
            "happens when another app or a second SleepRadar signs in with the "
            "same Aqara account.",
            "make sure only one SleepRadar (or other Aqara cloud tool) uses "
            "this account, then restart the app.",
            aqara_code_text(res),
        )
    if code == AQARA_CODE_SUBJECT_PERMISSION_DENIED:
        return kind, user_message(
            "SleepRadar signed in to Aqara but can't read your FP2: Aqara's "
            f"{area} server won't give it access to this sensor. This happens "
            "when aqara_area isn't the region your FP2 is registered in, or "
            "when subject_id points at another device.",
            "in Settings > Apps > SleepRadar > Configuration, set aqara_area to "
            "the region your Aqara Home app uses and check subject_id, then "
            f"restart the app. If both are already right, report it at {ISSUES_URL}.",
            aqara_code_text(res),
        )
    return kind, user_message(
        "SleepRadar signed in to Aqara but can't read your FP2.",
        "in Settings > Apps > SleepRadar > Configuration, check that subject_id "
        "points at your sleep FP2 and that the FP2 is still in your Aqara Home "
        "account, then restart the app.",
        aqara_code_text(res),
    )


class Health:
    """Owns the diagnostic entity and the notification that mirrors it.

    Transient failures get a grace window before they count, because a single
    DNS blip is not worth a notification. Permanent ones are flagged on the
    first occurrence: retrying will not fix them.
    """

    def __init__(self, client):
        """Track health state without publishing anything yet.

        `problem` is tri-state on purpose: None means nothing has been
        published this run, so the first result always writes, whichever way it
        goes. False and True are the two published states, and both transitions
        between them are what gates publishing and notifying.
        """
        self.client = client
        self.problem = None
        self.cause = None
        self.transient_streak = 0
        self.last_success = None

    def recovered(self):
        """Record a successful poll, clearing a problem if one was flagged."""
        self.transient_streak = 0
        self.last_success = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if self.problem is False:
            # Steady-state healthy: publish nothing. last_success is tracked in
            # memory and shipped with the next failure, which is the only time
            # anyone asks for it. Republishing it every poll would write a
            # retained attribute update per interval, 1440 a day, on an entity
            # this repo tells people to put in Recorder.
            return
        if self.problem:
            log("info", "Aqara connection recovered; clearing the problem flag")
        publish_problem(self.client, False, last_success=self.last_success)
        clear_problem_notification()
        self.problem = False
        self.cause = None

    def failed(self, kind, cause, code):
        """Record a failed poll, flagging a problem once it counts.

        Transient failures only count after TRANSIENT_FAILURE_GRACE of them in
        a row; permanent ones count immediately.
        """
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
        # A blip that turns out to be a permanent rejection would otherwise
        # leave the notification reading "clears on its own" for the rest of
        # the outage. An unchanged cause stays silent, so an ongoing outage
        # does not re-notify every poll.
        changed = self.problem is not True or cause != self.cause
        if not changed:
            # Nothing in the payload differs, and it is retained, so the broker
            # is already serving the current state. Republishing it every poll
            # would write a Recorder row per interval for the whole outage.
            return
        publish_problem(
            self.client, True, cause=cause, code=code, last_success=self.last_success
        )
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
        # Not "fatal": this process keeps running and recovers on its own once
        # the cause is gone (an options change needs an app restart). Calling
        # it fatal told users to expect a crash that never came.
        # The cause goes last so its technical details end the line.
        log(
            "error",
            "Aqara login failed at startup; SleepRadar keeps retrying, and the "
            f"sensors stay unavailable until the sign-in succeeds. {cause}",
        )
        # Flag it now rather than after the first poll. A rejected sign-in at
        # boot is already certain, so waiting a full poll interval to say so
        # would leave the user without an answer for no reason. Transient
        # failures still go through the grace window inside Health.
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
                f"res/query code={code_text(res.get('code'))} ({aqara_error_text(res)}); re-login",
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
            log("debug", f"raw Aqara reply: {json.dumps(res)[:ERROR_TEXT_LIMIT]}")
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

    # A requested stop is not a problem, and a problem that was already flagged
    # does not stop being one. Either way the retained diagnostic state is left
    # as it is; the MQTT will fires only on an ungraceful death, which is the
    # case that needs flagging.
    log("info", "Shutting down; marking offline.")
    client.publish(AVAIL_TOPIC, "offline", qos=1, retain=True)
    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
