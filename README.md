# ironman-training-sms

Personal automation tool for my own IRONMAN 70.3 triathlon training. Each morning, a script pulls my own Whoop fitness data (recovery, sleep, training load) and generates a short text message with training guidance for that day, sent via Twilio SMS.

## Who receives these messages

Only me (Owen Felaris). This is a single-user personal project, not a commercial product or service. No other recipients, no marketing, no third-party data sharing.

## Consent & opt-in

I am the sole subscriber to this SMS tool. I configured my own phone number directly in the script's environment variables (not committed to this repo) and explicitly opted myself in to receive these automated daily training texts from my own Twilio toll-free number.

Consent language I agreed to before enabling the script:

"I consent to receive daily automated SMS training guidance messages from this personal Whoop-to-SMS tool, sent to my own phone number. Message frequency: up to 1x/day. Message and data rates may apply. I can stop these messages at any time by disabling the script or replying STOP."

Since I am both the operator and the only recipient, there is no public-facing signup form — opt-in was self-administered by entering my own number into the configuration and agreeing to the consent language above.

## What the messages look like

Example: "Morning! Recovery's at 72%. Good day for a moderate 45-min run. 12 days out from IRONMAN 70.3, prioritize sleep tonight."
