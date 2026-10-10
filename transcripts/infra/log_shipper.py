"""Host-only: forward the transcript units' journal lines to one CloudWatch log group.

The relay prints payload-free JSON events (see transcripts/server.py); the other
units print fixed status lines. This shipper forwards a fixed set of journal fields,
masks network addresses in free text, and holds no third-party credential: it writes
with the instance role, and a forwarder outside the host sends the group to Axiom.
"""
import argparse
import json
import os
import queue
import re
import subprocess
import threading
import time

UNITS = ("relay", "enclave", "credentials", "health", "archive-sync", "logs")
PREFIX = "peer-link-transcript-"
# One command-line argument may not exceed 128 KiB on Linux; 50 bounded lines stay well under it.
MAX_BATCH, MAX_QUEUE, MAX_MESSAGE = 50, 5000, 1000
KEY = re.compile(r"[A-Za-z][A-Za-z0-9]{0,31}")
ADDRESS = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])|(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{1,4}:){3,7}[0-9A-Fa-f]{1,4}")
OPAQUE = re.compile(r"[A-Za-z0-9+/=_-]{40,}")


def role_environment():
    # Instance-role credentials and the official endpoint only; this file is installed
    # on its own, so the same rule as the health publisher is repeated here.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("AWS_", "BOTO_")) and key.upper() not in {
               "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"}}
    env.update(AWS_CONFIG_FILE="/dev/null", AWS_SHARED_CREDENTIALS_FILE="/dev/null", AWS_PAGER="",
               AWS_EC2_METADATA_DISABLED="false", AWS_MAX_ATTEMPTS="1",
               AWS_IGNORE_CONFIGURED_ENDPOINT_URLS="true", NO_PROXY="169.254.169.254")
    return env


def scrub(text, opaque=True):
    """Text from a unit: no network addresses, bounded length, and for free text no
    long opaque runs. A structured field keeps a public transaction or job id."""
    text = ADDRESS.sub("<address>", text)
    return (OPAQUE.sub("<opaque>", text) if opaque else text)[:MAX_MESSAGE if opaque else 200]


def record(entry):
    """One journal entry as a CloudWatch log event, or None when it is not ours."""
    unit = entry.get("UNIT") or entry.get("_SYSTEMD_UNIT")
    message, stamp = entry.get("MESSAGE"), entry.get("__REALTIME_TIMESTAMP")
    if not (isinstance(unit, str) and unit.startswith(PREFIX) and isinstance(message, str)
            and isinstance(stamp, str) and stamp.isdigit()):
        return None
    name = unit[len(PREFIX):].split(".")[0]
    if name not in UNITS:
        return None
    priority = entry.get("PRIORITY")
    body = {"unit": name, "priority": int(priority) if isinstance(priority, str) and priority.isdigit() else 6}
    event = None
    if message.startswith("{"):
        try:
            event = json.loads(message)
        except ValueError:
            event = None
    if isinstance(event, dict) and isinstance(event.get("event"), str) and KEY.fullmatch(event["event"]):
        # A structured line: keep scalar fields with plain names, scrub any text.
        for key, value in list(event.items())[:40]:
            if not (isinstance(key, str) and KEY.fullmatch(key)) or key in body:
                continue
            if type(value) in (int, float, bool) or value is None:
                body[key] = value
            elif isinstance(value, str):
                body[key] = scrub(value, opaque=False)
    else:
        body["message"] = scrub(message)
    return {"timestamp": int(stamp) // 1000, "message": json.dumps(body, sort_keys=True, separators=(",", ":"))}


def follow(cursor_file, sink):
    """Stream the units' journal as JSON, resuming from the saved cursor."""
    command = ["journalctl", "--follow", "--output=json", "--cursor-file=" + cursor_file, "--lines=0"]
    for name in UNITS:
        command += ["--unit", PREFIX + name + ".service"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    for line in process.stdout:
        try:
            item = record(json.loads(line))
        except (ValueError, TypeError):
            item = None
        if item is not None:
            sink(item)
    raise SystemExit("log_shipper_journal_closed")


def aws(arguments, region):
    return subprocess.run(["aws", "logs", *arguments, "--region", region,
                           "--endpoint-url", "https://logs." + region + ".amazonaws.com",
                           "--cli-connect-timeout", "5", "--cli-read-timeout", "10"],
                          env=role_environment(), capture_output=True, timeout=20)


def put(batch, group, stream, region, run=aws):
    events = sorted(batch, key=lambda item: item["timestamp"])
    result = run(["put-log-events", "--log-group-name", group, "--log-stream-name", stream,
                  "--log-events", json.dumps(events, separators=(",", ":"))], region)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-group", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--cursor-file", required=True)
    args = parser.parse_args()
    if not (re.fullmatch(r"/[A-Za-z0-9/_-]{1,200}", args.log_group) and re.fullmatch(r"i-[0-9a-f]{17}", args.instance_id)
            and re.fullmatch(r"[a-z]{2}-[a-z]+-[0-9]", args.region)):
        raise SystemExit("log_shipper_failed")
    # Already existing is the normal case after the first start.
    aws(["create-log-stream", "--log-group-name", args.log_group, "--log-stream-name", args.instance_id], args.region)
    pending = queue.Queue()
    threading.Thread(target=follow, args=(args.cursor_file, pending.put), daemon=True).start()
    held, dropped, delay = [], 0, 5
    while True:
        deadline = time.monotonic() + delay
        while len(held) < MAX_QUEUE and time.monotonic() < deadline:
            try:
                held.append(pending.get(timeout=max(0.1, deadline - time.monotonic())))
            except queue.Empty:
                break
        while pending.qsize() and len(held) >= MAX_QUEUE:
            pending.get_nowait()
            dropped += 1
        if not held:
            continue
        batch = held[:MAX_BATCH]
        try:
            sent = put(batch, args.log_group, args.instance_id, args.region)
        except (OSError, subprocess.SubprocessError):
            sent = False
        if sent:
            held, delay = held[len(batch):], 5
            if dropped:
                held.append({"timestamp": int(time.time() * 1000), "message": json.dumps(
                    {"unit": "logs", "priority": 4, "event": "dropped", "count": dropped})})
                dropped = 0
        else:
            delay = min(60, delay * 2)  # Keep the lines and try again later.


if __name__ == "__main__":
    main()
