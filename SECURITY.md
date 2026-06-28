# Security Policy

## What Is Safe To Share

The Aqara app constants in this repository are public constants shipped with the
Aqara Home app:

- `appid`
- `appkey`
- the RSA public key

They are used to speak the same API as the mobile app. They are not your user
credentials.

## What Must Stay Private

Do not share:

- your Aqara Home app email address
- your Aqara Home app password
- your `subject_id` without redaction
- Home Assistant long-lived access tokens
- Supervisor options dumps
- MQTT credentials
- private Home Assistant URLs or screenshots with private dashboard state

When reporting an issue, redact device IDs like this:

```text
lumi1.xxxxxxxxxxxx
```

## Reporting A Vulnerability

Open a GitHub security advisory if the issue exposes credentials, tokens, or a
way to access another user's data.

For normal bugs, open an issue with:

- Home Assistant installation type
- add-on version
- Aqara region
- redacted logs
- whether the FP2 is in Sleep Monitor mode

Never paste your full add-on configuration into an issue.

## Private API Caveat

This add-on uses the Aqara Home app cloud API. Aqara can change or block this
API. Token refresh is handled by logging in again, but API compatibility is not
guaranteed.
