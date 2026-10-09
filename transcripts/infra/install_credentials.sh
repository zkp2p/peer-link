#!/usr/bin/env bash
# Reviewed new durable deployment only. Public role/instance identifiers in argv;
# the service fetches credentials into RAM from IMDSv2 and never writes them.
set -euo pipefail
umask 077
if [[ $# != 2 ]]; then
  echo 'usage: install_credentials.sh HOST_ROLE_ARN INSTANCE_ID' >&2
  exit 2
fi
role_arn=$1
instance_id=$2
base=/opt/peer-link-transcripts
test -f "$base/current/transcripts/infra/credentials.py"
"$base/venv/bin/python" - "$role_arn" "$instance_id" <<'PY'
import sys
sys.path.insert(0, '/opt/peer-link-transcripts/current')
from transcripts.infra.credentials import CredentialSource
CredentialSource(role_arn=sys.argv[1], instance_id=sys.argv[2])
PY
cat > /etc/systemd/system/peer-link-transcript-credentials.service <<UNIT
[Unit]
Description=Memory-only IMDSv2 forwarding to the transcript enclave
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
NotifyAccess=main
TimeoutStartSec=35
WorkingDirectory=$base/current
ExecStart=$base/venv/bin/python -m transcripts.infra.credentials --role-arn $role_arn --instance-id $instance_id
Restart=no
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
RestrictAddressFamilies=AF_INET AF_VSOCK AF_UNIX
StandardOutput=null
StandardError=null
UNIT
systemctl daemon-reload
systemctl start peer-link-transcript-credentials.service
systemctl is-active --quiet peer-link-transcript-credentials.service
echo 'Credential forwarder started; enclave AWS identity and Recipient checks remain required.'
