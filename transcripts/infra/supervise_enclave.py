"""Host-only durable enclave liveness supervision; exact launched ID, no auto-resume."""
import argparse
import json
import re
import signal
import subprocess
import threading
import time
from pathlib import Path

from transcripts.infra.host_health import checked_health, policy_at, read_health
from transcripts.infra.listener_ready import notify_ready


def nitro(*args):
    result = subprocess.run(['/usr/bin/nitro-cli', *args], check=True,
                            capture_output=True, timeout=30)
    if len(result.stdout) > 32_768:
        raise ValueError('supervisor_failed')
    return json.loads(result.stdout)


def valid_record(record, instance):
    return (isinstance(record, dict) and isinstance(record.get('EnclaveID'), str)
            and re.fullmatch(re.escape(instance) + r'-enc[0-9a-f]+', record['EnclaveID'])
            and record.get('EnclaveCID') == 16)


def supervise(root, instance, record_path, stop, run=nitro, health=read_health,
              notify=notify_ready, startup_timeout=90):
    if not re.fullmatch(r'i-[0-9a-f]{17}', instance):
        raise ValueError('supervisor_failed')
    policy = policy_at(root)
    if run('describe-enclaves') != []:
        raise ValueError('supervisor_failed')  # Never adopt or stop another enclave.
    record = run('run-enclave', '--eif-path', str(Path(root)/'image.eif'),
                 '--cpu-count', '2', '--memory', '2048', '--enclave-cid', '16')
    if not valid_record(record, instance):
        raise ValueError('supervisor_failed')  # Unknown identity requires operator inspection.
    enclave_id = record['EnclaveID']
    try:
        path = Path(record_path)
        path.write_text(json.dumps(record))
        path.chmod(0o600)
        deadline = time.monotonic() + startup_timeout
        while not stop.is_set():
            try:
                checked_health(health(), policy, paused=True)
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise ValueError('supervisor_failed') from None
                stop.wait(min(0.5, max(0, deadline-time.monotonic())))
        if stop.is_set():
            return
        notify()
        # HTTP failures produce alarms, not destructive restarts. Only failed
        # actual enclave liveness makes this process fail for systemd backoff.
        while not stop.wait(5):
            rows = run('describe-enclaves')
            matching = [row for row in rows if row.get('EnclaveID') == enclave_id]
            if (len(matching) != 1 or not valid_record(matching[0], instance)
                    or matching[0].get('State') != 'RUNNING'
                    or matching[0].get('Flags') != 'NONE'
                    or matching[0].get('NumberOfCPUs') != 2
                    or matching[0].get('MemoryMiB') != 2048):
                raise ValueError('supervisor_failed')
    finally:
        # No terminate-all: cleanup only our validated ID, even on startup failure.
        run('terminate-enclave', '--enclave-id', enclave_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--instance-id', required=True)
    parser.add_argument('--record', required=True)
    args = parser.parse_args()
    stop = threading.Event()
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda *_: stop.set())
    try:
        supervise(args.root, args.instance_id, args.record, stop)
    except Exception:
        raise SystemExit('enclave_supervisor_failed') from None


if __name__ == '__main__':
    main()
