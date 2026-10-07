# Project rules

This repository publishes public provider documentation facts as static files.
Keep account credentials, live balances, routing histories and private connectors
out of this repository and its container image. The private capacity service is
an independent deployment.

Run `python3 -m unittest discover -s tests` and `python3 scripts/update.py` before
publishing. Parsers must fail on unsupported document layouts and preserve the
previous catalog on failure. Publish only numerical plan facts and model names,
with source URL, observation time, expiry and content hash. Build images in CI;
the homelab host runs prebuilt images.
