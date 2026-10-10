"""Operational logs must stay payload-free from the relay to the forwarder. Synthetic data only."""
import base64
import gzip
import io
import json
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from transcripts.infra import axiom_forwarder, log_shipper, logs_template
from transcripts.server import egress_target, emit, request_event

JOB = "a" * 32
PAYOUT = "0x" + "1" * 40
TX = "0x" + "b" * 64
CIPHER = "Q0lQSEVSVEVYVA" * 8
POLICY = {"egressHosts": ["api.mercury.com", "mainnet.base.org"],
          "campaigns": [{"id": "examplebank-open-v1", "openSource": {}, "sources": [{"origin": "https://examplebank.com"}]},
                        {"id": "mercury-api-source-v1", "sources": [{"origin": "https://api.mercury.com"}]}]}


class RelayEventTests(unittest.TestCase):
    def event(self, command, body, result, code=200, method="POST"):
        return request_event(method, command, body, result, code, time.monotonic(), 120, 300)

    def test_reservation_logs_public_routing_and_never_the_recipient(self):
        body = {"campaignId": "examplebank-open-v1", "provider": "openai_compatible", "model": "any/model-1",
                "payoutAddress": PAYOUT, "inferenceBaseUrl": "https://llm.private.example/v1"}
        result = {"jobId": JOB, "campaignId": "examplebank-open-v1", "state": "reserved", "payoutAddress": PAYOUT,
                  "bindingDigest": "c" * 64, "reason": None, "transactionId": None}
        event = self.event({"command": "reserve", "body": body}, body, result)
        self.assertEqual({key: event[key] for key in ("command", "campaignId", "provider", "model", "jobId", "state")},
                         {"command": "reserve", "campaignId": "examplebank-open-v1", "provider": "openai_compatible",
                          "model": "any/model-1", "jobId": JOB, "state": "reserved"})
        text = json.dumps(event)
        for private in (PAYOUT, "llm.private.example", "c" * 64):
            self.assertNotIn(private, text)

    def test_submission_logs_no_ciphertext_and_status_logs_the_reason(self):
        envelope = {"jobId": JOB, "ciphertext": CIPHER, "wrappedKey": CIPHER}
        event = self.event({"command": "submit", "body": envelope}, envelope, {"jobId": JOB, "state": "submitted"}, 202)
        self.assertNotIn(CIPHER, json.dumps(event))
        self.assertEqual((event["status"], event["state"]), (202, "submitted"))
        status = {"jobId": JOB, "campaignId": "examplebank-open-v1", "state": "rejected",
                  "reason": "bank_http_unauthorized", "payoutAddress": PAYOUT, "transactionId": None}
        event = self.event({"command": "status", "body": {"jobId": JOB}}, {}, status, method="GET")
        self.assertEqual((event["jobId"], event["state"], event["reason"]), (JOB, "rejected", "bank_http_unauthorized"))
        paid = self.event({"command": "receipt", "body": {"jobId": JOB}}, {},
                          {"payload": {"job": {"jobId": JOB, "state": "paid", "transactionId": TX, "payoutAddress": PAYOUT}},
                           "signature": CIPHER}, method="GET")
        self.assertEqual((paid["state"], paid["transactionId"]), ("paid", TX))
        self.assertNotIn(CIPHER, json.dumps(paid))
        self.assertNotIn(PAYOUT, json.dumps(paid))

    def test_values_that_do_not_fit_their_public_pattern_are_dropped(self):
        result = {"jobId": "not-a-job", "state": "Paid With Spaces", "reason": "x" * 80, "error": "has space"}
        event = self.event({"command": "status", "body": {"jobId": JOB}}, {}, result, 400, "GET")
        self.assertEqual(event["jobId"], JOB)  # From the validated route only.
        for name in ("state", "reason", "error"):
            self.assertNotIn(name, event)
        unrouted = self.event(None, None, {"error": "service_unavailable"}, 503, "DELETE")
        self.assertEqual((unrouted["command"], unrouted["method"], unrouted["error"]), ("unrouted", "other", "service_unavailable"))

    def test_operator_action_is_logged_without_its_signature(self):
        body = {"payload": {"action": "pause", "nonce": "d" * 64, "wallet": PAYOUT}, "signature": CIPHER}
        event = self.event({"command": "operator", "body": body}, body, {"accepting": False})
        self.assertEqual(event["action"], "pause")
        self.assertNotIn("d" * 64, json.dumps(event))
        self.assertNotIn(CIPHER, json.dumps(event))

    def test_egress_is_labelled_by_public_name_only(self):
        self.assertEqual(egress_target("api.examplebank.com", POLICY), "examplebank.com")
        self.assertEqual(egress_target("examplebank.com", POLICY), "examplebank.com")
        self.assertEqual(egress_target("api.openai.com", POLICY), "openai")
        self.assertEqual(egress_target("mainnet.base.org", POLICY), "mainnet.base.org")
        # A contributor's own model endpoint or a look-alike host is never named.
        for host in ("llm.private.example", "evilexamplebank.com", "examplebank.com.evil.test", None, 5):
            self.assertIn(egress_target(host, POLICY), {"other", "invalid"})

    def test_emit_writes_one_json_line(self):
        output = io.StringIO()
        with redirect_stdout(output):
            emit({"event": "request", "status": 200})
        self.assertEqual(json.loads(output.getvalue()), {"event": "request", "status": 200})
        self.assertEqual(output.getvalue().count("\n"), 1)


class ShipperTests(unittest.TestCase):
    def entry(self, message, unit="peer-link-transcript-relay.service", **extra):
        return {"_SYSTEMD_UNIT": unit, "MESSAGE": message, "__REALTIME_TIMESTAMP": "1791600000123456", "PRIORITY": "6", **extra}

    def test_structured_event_keeps_scalars_and_drops_everything_else(self):
        line = json.dumps({"event": "request", "command": "status", "status": 200, "ms": 12, "jobId": JOB,
                           "transactionId": TX, "nested": {"secret": CIPHER}, "bad key": 1, "list": [1]})
        item = log_shipper.record(self.entry(line, _HOSTNAME="ip-10-0-0-1", _CMDLINE="python -m transcripts.server"))
        body = json.loads(item["message"])
        self.assertEqual(item["timestamp"], 1791600000123)
        self.assertEqual(body, {"unit": "relay", "priority": 6, "event": "request", "command": "status", "status": 200,
                                "ms": 12, "jobId": JOB, "transactionId": TX})

    def test_free_text_loses_addresses_and_opaque_runs(self):
        text = "Exception during request from ('203.0.113.9', 51234) or 2001:db8:0:1::2 with " + CIPHER
        body = json.loads(log_shipper.record(self.entry(text))["message"])
        self.assertNotIn("203.0.113.9", body["message"])
        self.assertNotIn(CIPHER, body["message"])
        self.assertIn("<address>", body["message"])
        self.assertLessEqual(len(json.loads(log_shipper.record(self.entry("x " * 5000))["message"])["message"]), 1000)

    def test_only_transcript_units_are_forwarded(self):
        lifecycle = {"UNIT": "peer-link-transcript-enclave.service", "_SYSTEMD_UNIT": "init.scope",
                     "MESSAGE": "Started enclave.", "__REALTIME_TIMESTAMP": "1791600000000000"}
        self.assertEqual(json.loads(log_shipper.record(lifecycle)["message"])["unit"], "enclave")
        for unit in ("sshd.service", "peer-link-transcript-unknown.service", None):
            self.assertIsNone(log_shipper.record(self.entry("x", unit=unit)))
        self.assertIsNone(log_shipper.record(self.entry(["binary"])))

    def test_put_sends_one_bounded_ordered_batch_with_the_instance_role(self):
        calls = []

        def run(arguments, region):
            calls.append((arguments, region))
            return type("Done", (), {"returncode": 0})()

        batch = [{"timestamp": 2, "message": "b"}, {"timestamp": 1, "message": "a"}]
        self.assertTrue(log_shipper.put(batch, "/peerlink/transcripts/host", "i-" + "0" * 17, "us-east-1", run))
        arguments = calls[0][0]
        self.assertEqual(json.loads(arguments[arguments.index("--log-events") + 1]),
                         [{"timestamp": 1, "message": "a"}, {"timestamp": 2, "message": "b"}])
        with patch.dict("os.environ", {"AWS_PROFILE": "operator", "AWS_ACCESS_KEY_ID": "x", "HTTPS_PROXY": "http://p"}):
            environment = log_shipper.role_environment()
        for name in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "HTTPS_PROXY"):
            self.assertNotIn(name, environment)
        self.assertLessEqual(log_shipper.MAX_BATCH * (log_shipper.MAX_MESSAGE + 200), 128 * 1024)


class ForwarderAndTemplateTests(unittest.TestCase):
    def test_forwarder_reshapes_lines_and_sends_them_with_the_token(self):
        lines = [{"id": "1", "timestamp": 1791600000123, "message": json.dumps({"unit": "relay", "event": "request"})},
                 {"id": "2", "timestamp": 1791600001000, "message": "plain text"}]
        payload = {"messageType": "DATA_MESSAGE", "logStream": "i-" + "0" * 17, "logEvents": lines}
        event = {"awslogs": {"data": base64.b64encode(gzip.compress(json.dumps(payload).encode())).decode()}}
        rows = axiom_forwarder.rows(event)
        self.assertEqual((rows[0]["event"], rows[0]["host"], rows[1]["message"]), ("request", "i-" + "0" * 17, "plain text"))
        self.assertTrue(rows[0]["_time"].startswith("2026-"))
        sent = {}

        class Reply:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"ingested": 2, "failed": 0}'

        def urlopen(request, timeout):
            sent.update(url=request.full_url, headers=dict(request.header_items()), body=json.loads(request.data))
            return Reply()

        token = "synthetic-axiom-token-value"
        with patch.dict("os.environ", {"AXIOM_URL": "https://api.axiom.example", "AXIOM_DATASET": "peerlink-test",
                                       "AXIOM_TOKEN": token}), patch("urllib.request.urlopen", urlopen):
            self.assertEqual(axiom_forwarder.handler(event, None), {"forwarded": 2})
        self.assertEqual(sent["url"], "https://api.axiom.example/v1/datasets/peerlink-test/ingest")
        self.assertTrue(sent["headers"]["Authorization"].endswith(token))
        self.assertEqual(len(sent["body"]), 2)
        control = {"awslogs": {"data": base64.b64encode(gzip.compress(b'{"messageType":"CONTROL_MESSAGE"}')).decode()}}
        self.assertEqual(axiom_forwarder.handler(control, None), {"forwarded": 0})

    def test_template_matches_the_generator_and_keeps_the_token_out(self):
        generated = logs_template.template()
        self.assertEqual(json.loads(Path("transcripts/infra/logs.cfn.json").read_text()), generated)
        self.assertTrue(generated["Parameters"]["AxiomToken"]["NoEcho"])
        self.assertNotIn("Default", generated["Parameters"]["AxiomToken"])
        self.assertLessEqual(len(generated["Resources"]["Forwarder"]["Properties"]["Code"]["ZipFile"]), 4096)
        group = "arn:aws:logs:us-east-1:111122223333:log-group:/peerlink/transcripts/host"
        allow, deny = logs_template.host_statements(group)
        self.assertEqual((allow["Effect"], allow["Action"], allow["Resource"]),
                         ("Allow", ["logs:CreateLogStream", "logs:PutLogEvents"], [group, group + ":*"]))
        self.assertEqual((deny["Effect"], deny["NotResource"]), ("Deny", [group, group + ":*"]))


if __name__ == "__main__":
    unittest.main()
