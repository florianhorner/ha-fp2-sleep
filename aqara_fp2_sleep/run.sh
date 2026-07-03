#!/usr/bin/with-contenv bashio
set -e

STARTUP_FAILURE_COOLDOWN="${STARTUP_FAILURE_COOLDOWN:-30}"

startup_failure() {
    bashio::log.error "$1"
    bashio::log.error "Sleeping ${STARTUP_FAILURE_COOLDOWN}s before exit to avoid rapid restart loops."
    sleep "${STARTUP_FAILURE_COOLDOWN}"
    exit 1
}

bashio::log.info "Starting SleepRadar..."

if bashio::services.available "mqtt"; then
    export MQTT_HOST="$(bashio::services mqtt 'host')"
    export MQTT_PORT="$(bashio::services mqtt 'port')"
    export MQTT_USER="$(bashio::services mqtt 'username')"
    export MQTT_PASS="$(bashio::services mqtt 'password')"
    export MQTT_SSL="$(bashio::services mqtt 'ssl')"
    bashio::log.info "Using injected MQTT broker at ${MQTT_HOST}:${MQTT_PORT} (ssl=${MQTT_SSL})"
else
    startup_failure "No MQTT service available. Install and start an MQTT broker add-on."
fi

export AQARA_USER="$(bashio::config 'aqara_username')"
export AQARA_PASS="$(bashio::config 'aqara_password')"
export AQARA_AREA="$(bashio::config 'aqara_area')"
export SUBJECT_ID="$(bashio::config 'subject_id')"
export POLL_INTERVAL="$(bashio::config 'poll_interval')"
export LOG_LEVEL="$(bashio::config 'log_level')"
export DEVICE_NAME="$(bashio::config 'device_name')"
export MQTT_NODE_ID="$(bashio::config 'mqtt_node_id')"

if bashio::var.is_empty "${AQARA_USER}" || bashio::var.is_empty "${AQARA_PASS}"; then
    startup_failure "aqara_username and aqara_password are required."
fi

if bashio::var.is_empty "${SUBJECT_ID}"; then
    startup_failure "subject_id is required. Get it from the FP2 device information in the Aqara Home app."
fi

bashio::log.info "Polling configured FP2 in area ${AQARA_AREA} every ${POLL_INTERVAL}s"

exec python3 /aqara_fp2_sleep_poller.py
