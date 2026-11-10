"""Offline compatibility checks against real, installed runtime dependencies.

Run in a fresh process: the repository validator's poller checks install stubs.
Only HTTP and the TCP connection boundary are replaced here; crypto, MQTT
packet encoding, acknowledgements, and the MQTT network loop remain real.
"""

from base64 import b64decode
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
import unittest
from unittest import mock

import paho.mqtt.client as mqtt
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_module("runtime_validator", "scripts/validate_repository.py")


class RuntimeDependenciesTest(unittest.TestCase):
    def setUp(self):
        # No ambient account credentials, broker settings, or node overrides.
        with mock.patch.dict(os.environ, {}, clear=True):
            self.poller = load_module(
                "runtime_poller", "aqara_fp2_sleep/aqara_fp2_sleep_poller.py"
            )
        self.addCleanup(mock.patch.stopall)
        # Fail closed if any test accidentally tries HTTP or an external socket.
        mock.patch("urllib.request.urlopen", side_effect=AssertionError("HTTP forbidden")).start()
        mock.patch("socket.create_connection", side_effect=AssertionError("TCP forbidden")).start()
        mock.patch.object(self.poller, "log").start()

    def test_installed_versions_match_independent_validator_pins(self):
        validator.validate_requirements()
        for requirement in validator.EXPECTED_RUNTIME_REQUIREMENTS:
            name, expected = requirement.split("==")
            with self.subTest(package=name):
                self.assertEqual(importlib.metadata.version(name), expected)
        self.assertIs(self.poller.mqtt.Client, mqtt.Client)
        self.assertIs(self.poller.PKCS1_v1_5.new, PKCS1_v1_5.new)

    def test_requirement_guard_rejects_partial_updates_and_drift(self):
        accepted = "paho-mqtt==2.2.0\npycryptodome==4.3.0\n"
        rejected = (
            "paho-mqtt==2.1.0\npycryptodome==3.23.0\n",
            "paho-mqtt==2.2.0\npycryptodome==3.23.0\n",
            "paho-mqtt==2.1.0\npycryptodome==4.3.0\n",
            accepted.replace("==2.2.0", ">=2.2.0"),
            accepted.replace("==4.3.0", ">=4.3.0"),
            "pycryptodome==4.3.0\n",
            "paho-mqtt==2.2.0\n",
            accepted + "paho-mqtt==2.2.0\n",
            accepted + "unexpected-package==1.0.0\n",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "aqara_fp2_sleep/requirements.txt"
            runtime.parent.mkdir()
            (root / "requirements-ci.txt").write_text(
                (ROOT / "requirements-ci.txt").read_text(encoding="utf-8"), encoding="utf-8"
            )
            with mock.patch.object(validator, "ROOT", root):
                runtime.write_text(accepted, encoding="utf-8")
                validator.validate_requirements()
                for content in rejected:
                    with self.subTest(requirements=content):
                        runtime.write_text(content, encoding="utf-8")
                        with self.assertRaisesRegex(validator.ValidationError, "must contain exactly"):
                            validator.validate_requirements()

    def login_payload(self, aqara):
        aqara.token, aqara.userid = "expired-token", "expired-user"
        with mock.patch.object(aqara, "_post", return_value={
            "code": 0, "result": {"token": "test-token", "userId": "test-user"}
        }) as post:
            self.assertTrue(aqara.login())
        path, payload = post.call_args.args
        self.assertEqual(path, "/app/v1.0/lumi/user/login")
        self.assertEqual(payload["account"], self.poller.USER)
        self.assertEqual(payload["encryptType"], 2)
        self.assertEqual((aqara.token, aqara.userid), ("test-token", "test-user"))
        return b64decode(payload["password"], validate=True)

    def test_aqara_builtin_public_key_and_randomized_encryption(self):
        key = RSA.importKey(self.poller.PUBKEY)
        self.assertFalse(key.has_private())
        self.assertEqual(key.size_in_bits(), 1024)
        aqara = self.poller.Aqara("EU")
        self.poller.PASSWORD = "synthetic-password"
        first, second = self.login_payload(aqara), self.login_payload(aqara)
        self.assertEqual(len(first), key.size_in_bytes())
        self.assertEqual(len(second), key.size_in_bytes())
        self.assertNotEqual(first, second)

    def test_aqara_login_encrypts_utf8_password_md5_as_pkcs1_v1_5(self):
        # Generated in memory; never store a private key or use a real account.
        key = RSA.generate(1024)
        self.poller.PUBKEY = key.public_key().export_key().decode("ascii")
        self.poller.USER = "synthetic-account"
        for password in ("", "synthetic-password", "Grüße-月"):
            with self.subTest(password=password):
                self.poller.PASSWORD = password
                ciphertext = self.login_payload(self.poller.Aqara("EU"))
                plaintext = PKCS1_v1_5.new(key).decrypt(ciphertext, b"invalid-padding")
                self.assertEqual(plaintext, hashlib.md5(password.encode("utf-8")).hexdigest().encode("ascii"))

    def test_mqtt_tls_configuration(self):
        self.poller.MQTT_SSL = True
        with mock.patch.object(mqtt.Client, "connect", autospec=True) as connect, \
                mock.patch.object(mqtt.Client, "loop_start", autospec=True) as loop_start:
            client = self.poller.make_mqtt()
        self.assertEqual(client.callback_api_version, mqtt.CallbackAPIVersion.VERSION2)
        self.assertEqual(client._ssl_context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(client._ssl_context.check_hostname)
        connect.assert_called_once_with(client, self.poller.MQTT_HOST, self.poller.MQTT_PORT, keepalive=120)
        loop_start.assert_called_once_with(client)

    def test_mqtt_connect_publish_acknowledge_and_disconnect(self):
        # Use an OS socket pair as a scripted broker: no network or device.
        transport, broker = socket.socketpair()
        self.addCleanup(transport.close)
        self.addCleanup(broker.close)
        broker.settimeout(5)
        self.poller.MQTT_USER, self.poller.MQTT_PASS = "test-user", "test-password"
        with mock.patch("socket.create_connection", return_value=transport) as connect:
            client = self.poller.make_mqtt()
        self.addCleanup(client.loop_stop)
        self.addCleanup(client.disconnect)
        self.assertEqual(client.callback_api_version, mqtt.CallbackAPIVersion.VERSION2)
        connect.assert_called_once()
        self.assertEqual(connect.call_args.args[0], (self.poller.MQTT_HOST, self.poller.MQTT_PORT))

        header, packet = read_packet(broker)
        self.assertEqual(header, 0x10)  # MQTT 3.1.1 CONNECT, clean session, QoS1 will.
        self.assertEqual(packet[:10], b"\x00\x04MQTT\x04\xee\x00\x78")
        fields = []
        offset = 10
        while offset < len(packet):
            length = int.from_bytes(packet[offset:offset + 2], "big")
            fields.append(packet[offset + 2:offset + 2 + length].decode())
            offset += 2 + length
        self.assertEqual(fields, [self.poller.NODE, self.poller.PROBLEM_STATE_TOPIC,
                                  "ON", "test-user", "test-password"])
        broker.sendall(b"\x20\x02\x00\x00")  # CONNACK success.

        self.poller.publish_discovery(client)
        self.poller.publish_problem(client, True, cause="synthetic-outage", code=-1)
        state = json.dumps({"heartrate_value": 65})
        state_info = client.publish(self.poller.STATE_TOPIC, state, qos=0, retain=False)
        online_info = client.publish(self.poller.AVAIL_TOPIC, "online", qos=1, retain=True)
        messages = {}
        for _ in range(len(self.poller.SENSORS) + 5):
            header, packet = read_packet(broker)
            self.assertEqual(header >> 4, 3)  # PUBLISH.
            topic_length = int.from_bytes(packet[:2], "big")
            topic = packet[2:2 + topic_length].decode()
            offset = 2 + topic_length
            qos = (header >> 1) & 3
            if qos == 1:
                broker.sendall(b"\x40\x02" + packet[offset:offset + 2])
                offset += 2
            messages[topic] = (qos, bool(header & 1), packet[offset:].decode())
        self.assertEqual(messages[self.poller.STATE_TOPIC], (0, False, state))
        self.assertEqual(messages[self.poller.AVAIL_TOPIC], (1, True, "online"))
        self.assertEqual(messages[self.poller.PROBLEM_STATE_TOPIC], (1, True, "ON"))
        attrs = messages[self.poller.PROBLEM_ATTR_TOPIC]
        self.assertEqual(attrs[:2], (1, True))
        self.assertEqual(json.loads(attrs[2])["cause"], "synthetic-outage")
        discovery = {topic: value for topic, value in messages.items() if topic.endswith("/config")}
        self.assertEqual(len(discovery), 6)
        for qos, retain, payload in discovery.values():
            self.assertEqual((qos, retain), (1, True))
            self.assertIn("state_topic", json.loads(payload))
        for info in (state_info, online_info):
            info.wait_for_publish(timeout=5)
            self.assertTrue(info.is_published())
        self.assertEqual(client.disconnect(), mqtt.MQTT_ERR_SUCCESS)
        self.assertEqual(read_packet(broker), (0xe0, b""))


def read_packet(stream):
    def exact(size):
        result = b""
        while len(result) < size:
            chunk = stream.recv(size - len(result))
            if not chunk:
                raise AssertionError("MQTT transport closed before packet completed")
            result += chunk
        return result

    header = exact(1)[0]
    remaining, multiplier = 0, 1
    for _ in range(4):
        value = exact(1)[0]
        remaining += (value & 127) * multiplier
        if value < 128:
            return header, exact(remaining)
        multiplier *= 128
    raise AssertionError("Invalid MQTT remaining length")


if __name__ == "__main__":
    unittest.main()
