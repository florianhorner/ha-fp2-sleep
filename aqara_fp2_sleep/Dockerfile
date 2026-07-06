FROM ghcr.io/home-assistant/base-python:3.13-alpine3.21

ARG BUILD_VERSION=1.2.1

COPY requirements.txt /requirements.txt

RUN apk add --no-cache --virtual .build-deps gcc musl-dev python3-dev \
    && pip3 install --no-cache-dir -r /requirements.txt \
    && apk del .build-deps

COPY run.sh /run.sh
COPY aqara_fp2_sleep_poller.py /aqara_fp2_sleep_poller.py
RUN chmod a+x /run.sh

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="aarch64|amd64" \
    org.opencontainers.image.title="SleepRadar" \
    org.opencontainers.image.description="Polls Aqara FP2 sleep telemetry and publishes it to MQTT"

CMD [ "/run.sh" ]
