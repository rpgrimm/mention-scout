# MS-0009 implementation

Moved `StartLimitIntervalSec` and `StartLimitBurst` from `[Service]` to `[Unit]`
in `deploy/systemd/mention-scout-watch.service`. Added regression test for section
placement. No product code changes.
