#!/usr/bin/env bash
# Run through SSM on the dedicated transcript host only. Installs a separate unit
# that forwards the transcript units' journal lines to one CloudWatch log group. It
# never stops, restarts, reinstalls or edits the relay, enclave, credential or health
# services, holds no third-party credential, and lives outside
# /opt/peer-link-transcripts so a release rollover leaves it alone.
set -euo pipefail
umask 077
if [[ $# != 5 ]]; then
  echo 'usage: install_log_shipper.sh LOG_SHIPPER_PY EXPECTED_SHA256 LOG_GROUP REGION INSTANCE_ID' >&2
  exit 2
fi
# Validate everything before the first file or systemd change.
if [[ ! "$2" =~ ^[0-9a-f]{64}$ || ! "$3" =~ ^/[A-Za-z0-9/_-]{1,200}$ || ! "$4" =~ ^[a-z]{2}-[a-z]+-[0-9]$ || ! "$5" =~ ^i-[0-9a-f]{17}$ ]]; then
  echo 'Log shipper installation requires a SHA-256, log group, region and instance id.' >&2
  exit 1
fi
script=$(realpath "$1")
test -f "$script"
test "$(sha256sum "$script" | cut -d' ' -f1)" = "$2"
command -v aws >/dev/null
command -v journalctl >/dev/null
test -x /usr/bin/python3.11
base=/opt/peer-link-transcript-logs
unit=peer-link-transcript-logs
install -d -m 700 "$base"
install -m 600 "$script" "$base/log_shipper.py.new"
mv -f "$base/log_shipper.py.new" "$base/log_shipper.py"
# ProtectSystem=strict leaves every service directory read-only to this unit: it can
# read the journal and write its own cursor, nothing else.
cat > "/etc/systemd/system/$unit.service" <<UNIT
[Unit]
Description=Forward payload-free transcript service journal lines to CloudWatch Logs
After=network-online.target systemd-journald.service
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
ExecStart=/usr/bin/python3.11 $base/log_shipper.py --log-group $3 --instance-id $5 --region $4 --cursor-file /var/lib/peer-link-transcript-logs/cursor
StateDirectory=peer-link-transcript-logs
StateDirectoryMode=0700
Restart=on-failure
RestartSec=15
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
StandardOutput=null
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now "$unit.service"
sleep 3
systemctl is-active "$unit.service"
echo 'Log shipper installed; the relay, enclave, credential and health units were not touched.'
