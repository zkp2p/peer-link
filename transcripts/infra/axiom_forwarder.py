"""CloudWatch Logs subscription target: forward the transcript host's log lines to Axiom.

Runs as a Lambda outside the Nitro host, so the host never holds the Axiom token. The
lines are already payload-free (see transcripts/infra/log_shipper.py); this function
only reshapes them and adds the event time.
"""
import base64
import gzip
import json
import os
import urllib.request
from datetime import datetime, timezone


def rows(event):
    data = json.loads(gzip.decompress(base64.b64decode(event["awslogs"]["data"])))
    if data.get("messageType") != "DATA_MESSAGE":
        return []
    result = []
    for item in data.get("logEvents", []):
        try:
            row = json.loads(item["message"])
            if not isinstance(row, dict):
                raise ValueError
        except ValueError:
            row = {"message": str(item.get("message"))[:1000]}
        row["_time"] = datetime.fromtimestamp(item["timestamp"] / 1000, timezone.utc).isoformat()
        row["host"] = data.get("logStream")
        result.append(row)
    return result


def handler(event, context):
    batch = rows(event)
    if not batch:
        return {"forwarded": 0}
    bearer = "Bearer " + os.environ["AXIOM_TOKEN"]
    request = urllib.request.Request(
        os.environ["AXIOM_URL"].rstrip("/") + "/v1/datasets/" + os.environ["AXIOM_DATASET"] + "/ingest",
        data=json.dumps(batch).encode(), method="POST",
        headers={"Authorization": bearer, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        outcome = json.loads(response.read())
    if outcome.get("failed"):
        raise RuntimeError("axiom_ingest_failed")  # CloudWatch Logs retries the batch.
    return {"forwarded": len(batch)}
