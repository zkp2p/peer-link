#!/usr/bin/env bash
# Run through SSM on the dedicated transcript host only. Installs a separate
# write-only mirror of signed redacted archive records. It never stops, restarts,
# reinstalls or edits the relay, enclave, credential or health services, and it
# lives outside /opt/peer-link-transcripts so a release rollover leaves it alone.
set -euo pipefail
umask 077
if [[ $# != 4 ]]; then
  echo 'usage: install_archive_sync.sh ARCHIVE_SYNC_PY EXPECTED_SHA256 BUCKET REGION' >&2
  exit 2
fi
# Validate everything before the first file or systemd change.
if [[ ! "$2" =~ ^[0-9a-f]{64}$ || ! "$3" =~ ^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$ || ! "$4" =~ ^[a-z]{2}-[a-z]+-[0-9]$ ]]; then
  echo 'Archive mirror installation requires a SHA-256, bucket name and region.' >&2
  exit 1
fi
script=$(realpath "$1")
test -f "$script"
test "$(sha256sum "$script" | cut -d' ' -f1)" = "$2"
command -v aws >/dev/null
test -x /usr/bin/python3.11
base=/opt/peer-link-transcript-archive
unit=peer-link-transcript-archive-sync
install -d -m 700 "$base"
install -m 600 "$script" "$base/archive_sync.py.new"
mv -f "$base/archive_sync.py.new" "$base/archive_sync.py"
# ProtectSystem=strict leaves the enclave archive read-only to this unit: it can
# copy records off-host but cannot alter or remove them.
cat > "/etc/systemd/system/$unit.service" <<UNIT
[Unit]
Description=Write-only S3 mirror of signed redacted transcript archive records
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
# The archive writes <digest>.tmp, fsyncs and renames; let that settle first.
ExecStartPre=/usr/bin/sleep 1
ExecStart=/usr/bin/python3.11 $base/archive_sync.py --source /var/lib/peer-link-transcripts/artifacts --state /var/lib/peer-link-transcript-archive --bucket $3 --region $4
StateDirectory=peer-link-transcript-archive
StateDirectoryMode=0700
TimeoutStartSec=300
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
RestrictAddressFamilies=AF_INET AF_INET6
# Journal keeps only the numeric summary of a run that uploaded or failed, not
# the start/stop lines of every idle one-minute retry.
StandardOutput=journal
StandardError=null
SyslogLevel=notice
LogLevelMax=notice
UNIT
# A missing directory is watched through its parent until the relay recreates it.
cat > "/etc/systemd/system/$unit.path" <<UNIT
[Unit]
Description=Mirror a signed transcript record as soon as the host archive stores it

[Path]
PathChanged=/var/lib/peer-link-transcripts/artifacts
Unit=$unit.service

[Install]
WantedBy=multi-user.target
UNIT
# Path events raised while a run is active can be missed; the timer retries those
# and any failed upload within a minute.
cat > "/etc/systemd/system/$unit.timer" <<UNIT
[Unit]
Description=One-minute retry for the transcript archive mirror

[Timer]
OnActiveSec=30
OnBootSec=60
OnUnitInactiveSec=60
AccuracySec=5
Unit=$unit.service

[Install]
WantedBy=timers.target
UNIT
chmod 644 "/etc/systemd/system/$unit.service" "/etc/systemd/system/$unit.path" "/etc/systemd/system/$unit.timer"
systemctl daemon-reload
systemctl enable --now "$unit.path" "$unit.timer"
if ! systemctl start "$unit.service"; then
  echo 'Initial archive mirror run failed; units stay installed and retry every minute.' >&2
  exit 1
fi
echo 'Archive mirror installed; verify the uploaded objects from an operator session.'
