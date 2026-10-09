#!/usr/bin/env bash
# Operator runs ONLY after approved hardware restore proof and CF finite-guard
# opt-out. This workflow token is not cryptographic release authorization.
set -euo pipefail
umask 077
if [[ $# != 3 ]]; then
  echo 'usage: install_continuous.sh HOST_INSTANCE_ID REGION POLICY_DIGEST' >&2
  exit 2
fi
# This rollout intentionally supports only the existing NEW durable host.
test "$1" = i-03244cd4a1bd6567a
test "$2" = us-east-1
test "${PEERLINK_CONTINUOUS_APPROVED:-}" = "$3"
base=/opt/peer-link-transcripts
"$base/venv/bin/python" - "$base/current" "$3" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from transcripts.common import digest
from transcripts.infra.host_health import checked_health, policy_at, read_health
policy = policy_at(sys.argv[1])
assert digest(policy) == sys.argv[2]
checked_health(read_health(), policy, paused=True)
PY
for unit in enclave relay credentials; do
  systemctl is-active --quiet "peer-link-transcript-$unit.service"
  install -d -m 700 "/etc/systemd/system/peer-link-transcript-$unit.service.d"
  cat > "/etc/systemd/system/peer-link-transcript-$unit.service.d/continuous.conf" <<'UNIT'
[Unit]
StartLimitIntervalSec=300
StartLimitBurst=3
[Service]
Restart=on-failure
RestartSec=10
UNIT
done
cat > /etc/systemd/system/peer-link-transcript-health.service <<UNIT
[Unit]
Description=Payload-free functional health for durable transcript service
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=3
[Service]
Type=simple
WorkingDirectory=$base/current
ExecStart=$base/venv/bin/python -m transcripts.infra.health_publisher --root $base/current --instance-id $1 --region $2
Restart=on-failure
RestartSec=10
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
RestrictAddressFamilies=AF_INET AF_INET6
StandardOutput=null
StandardError=null
[Install]
WantedBy=multi-user.target
UNIT
# Existing units lack [Install]; explicit wants symlinks preserve reviewed units.
install -d /etc/systemd/system/multi-user.target.wants
for unit in enclave relay credentials; do
  ln -sf "/etc/systemd/system/peer-link-transcript-$unit.service" "/etc/systemd/system/multi-user.target.wants/peer-link-transcript-$unit.service"
done
systemctl daemon-reload
systemctl enable --now peer-link-transcript-health.service
echo 'Continuous host recovery enabled; restored admissions remain paused until signed operator resume.'
