"""Synthetic IMDS/VSOCK checks; no actual metadata or credential access."""
import datetime
import json
import socket
import threading
import unittest
from unittest.mock import Mock

from transcripts.infra.credentials import CredentialSource, CredentialsUnavailable, connection, MAX_REQUEST, IMDS
from transcripts.wire import receive, send

ROLE = "arn:aws:iam::111122223333:role/synthetic-role"
INSTANCE = "i-0123456789abcdef0"
NOW = 2_000_000_000


class Response:
    status = 200
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *_args): pass
    def read(self, size): return self.body[:size]


class Imds:
    def __init__(self):
        self.calls = []
        self.role, self.instance = "synthetic-role", INSTANCE
        self.data = {"Code": "Success", "Type": "AWS-HMAC", "AccessKeyId": "ASIA" + "A" * 16,
                     "SecretAccessKey": "synthetic-not-a-live-key-value", "Token": "synthetic-not-a-live-session",
                     "Expiration": datetime.datetime.fromtimestamp(NOW + 3600, datetime.timezone.utc).isoformat()}
    def open(self, request, timeout):
        self.calls.append(request)
        assert timeout == 2
        if request.full_url == IMDS + "api/token":
            assert request.method == "PUT"
            assert dict((k.lower(), v) for k, v in request.header_items())["x-aws-ec2-metadata-token-ttl-seconds"] == "60"
            return Response(b"synthetic-token")
        assert dict((k.lower(), v) for k, v in request.header_items())["x-aws-ec2-metadata-token"] == "synthetic-token"
        if request.full_url.endswith("instance-id"): return Response(self.instance.encode())
        if request.full_url.endswith("security-credentials/"): return Response(self.role.encode())
        return Response(json.dumps(self.data).encode())


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.imds = Imds()
        self.source = CredentialSource(role_arn=ROLE, instance_id=INSTANCE, opener=self.imds, clock=lambda: NOW)

    def test_imdsv2_returns_only_bounded_role_credentials_in_memory(self):
        result = self.source.credentials()
        self.assertEqual(set(result), {"version", "accessKeyId", "secretAccessKey", "sessionToken", "expiration", "roleArn", "instanceId"})
        self.assertEqual(result["roleArn"], ROLE)
        self.assertEqual(result["instanceId"], INSTANCE)
        self.assertEqual(result["expiration"], NOW + 3600)
        self.assertNotIn(result["secretAccessKey"], repr(self.source))
        self.source.credentials()
        self.assertEqual(len(self.imds.calls), 8)  # Refresh from IMDS each time, no disk/cache.

    def test_role_instance_expiry_and_failure_are_fixed_errors(self):
        for mutate in [lambda: setattr(self.imds, "role", "other-role"),
                       lambda: setattr(self.imds, "instance", "i-00000000000000000"),
                       lambda: self.imds.data.update(Expiration="2000-01-01T00:00:00Z"),
                       lambda: self.imds.data.update(Token="x" * 6145),
                       lambda: self.imds.data.update(Code="synthetic private diagnostic")]:
            self.setUp(); mutate()
            with self.assertRaisesRegex(CredentialsUnavailable, "^credentials_unavailable$"):
                self.source.credentials()

    def exchange(self, value, cid=16):
        client, server = socket.socketpair()
        source = Mock(); source.credentials.return_value = {"version": 1, "synthetic": True}
        worker = threading.Thread(target=connection, args=(server, cid, 16, source)); worker.start()
        try:
            if cid == 16: send(client, value)
            reply = receive(client)
        finally:
            client.close(); worker.join(2)
        self.assertFalse(worker.is_alive())
        return reply, source

    def test_wrong_cid_and_malformed_requests_never_fetch_credentials(self):
        reply, source = self.exchange({}, cid=15)
        self.assertEqual(reply, {"version": 1, "error": "credentials_unavailable"})
        source.credentials.assert_not_called()
        for value in [{"version": True}, {"version": 2}, {"version": 1, "path": "/arbitrary"},
                      {"version": 1, "padding": "x" * MAX_REQUEST}]:
            reply, source = self.exchange(value)
            self.assertEqual(reply, {"version": 1, "error": "credentials_unavailable"})
            source.credentials.assert_not_called()

    def test_authorized_request_fetches_once(self):
        reply, source = self.exchange({"version": 1})
        self.assertEqual(reply, {"version": 1, "synthetic": True})
        source.credentials.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
