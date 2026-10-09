"""CID-bound, memory-only forwarding of the parent's IMDSv2 role credentials.

Credentials are for enclave SigV4, not evidence secrecy. The parent already owns
them; private state is protected by Recipient KMS and enclave-terminated TLS.
Never log credentials, replies, request bodies or raw failures.
"""
import argparse
import datetime
import json
import re
import socket
import struct
import threading
import time
from urllib.request import Request, ProxyHandler, build_opener

from transcripts.common import canonical, strict_json
from transcripts.wire import exact

MAX_REQUEST = 512
MAX_RESPONSE = 8192
IMDS = "http://169.254.169.254/latest/"


class CredentialsUnavailable(Exception):
    pass


def require(ok):
    if not ok:
        raise CredentialsUnavailable("credentials_unavailable")


class CredentialSource:
    def __init__(self, *, role_arn, instance_id, opener=None, clock=time.time):
        require(isinstance(role_arn, str) and re.fullmatch("arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+", role_arn))
        require(isinstance(instance_id, str) and re.fullmatch("i-[a-f0-9]{17}", instance_id))
        self.role_arn, self.role_name, self.instance_id = role_arn, role_arn.rsplit("/", 1)[1], instance_id
        self.opener = opener or build_opener(ProxyHandler({}))
        self.clock = clock

    def _fetch(self, path, *, token=None, method="GET"):
        headers = {"X-aws-ec2-metadata-token": token} if token else {"X-aws-ec2-metadata-token-ttl-seconds": "60"}
        with self.opener.open(Request(IMDS + path, headers=headers, method=method), timeout=2) as response:
            require(response.status == 200)
            body = response.read(MAX_RESPONSE + 1)
            require(0 < len(body) <= MAX_RESPONSE)
            return body

    def credentials(self):
        try:
            token = self._fetch("api/token", method="PUT").decode("ascii")
            require(len(token) <= 4096 and not any(ord(c) < 33 for c in token))
            instance = self._fetch("meta-data/instance-id", token=token).decode("ascii")
            require(instance == self.instance_id)
            role = self._fetch("meta-data/iam/security-credentials/", token=token).decode("ascii").strip()
            require(role == self.role_name)
            raw = strict_json(self._fetch("meta-data/iam/security-credentials/" + self.role_name, token=token), MAX_RESPONSE)
            require(raw.get("Code") == "Success" and raw.get("Type") == "AWS-HMAC")
            expiration = int(datetime.datetime.fromisoformat(raw["Expiration"].replace("Z", "+00:00")).timestamp())
            require(self.clock() + 60 <= expiration <= self.clock() + 21600)
            access, secret, session = raw["AccessKeyId"], raw["SecretAccessKey"], raw["Token"]
            require(isinstance(access, str) and re.fullmatch("ASIA[A-Z0-9]{16}", access))
            require(isinstance(secret, str) and 16 <= len(secret) <= 128)
            require(isinstance(session, str) and 1 <= len(session) <= 6144)
            require(all(not any(ord(c) < 33 for c in v) for v in [access, secret, session]))
            result = {"version": 1, "accessKeyId": access, "secretAccessKey": secret, "sessionToken": session,
                      "expiration": expiration, "roleArn": self.role_arn, "instanceId": self.instance_id}
            require(len(canonical(result)) <= MAX_RESPONSE)
            return result
        except Exception:
            raise CredentialsUnavailable("credentials_unavailable") from None

    def __repr__(self):
        return "<CredentialSource memory-only>"


def connection(stream, peer_cid, allowed_cid, source):
    with stream:
        try:
            require(peer_cid == allowed_cid)
            stream.settimeout(5)
            size = struct.unpack("!I", exact(stream, 4))[0]
            require(0 < size <= MAX_REQUEST)
            request = strict_json(exact(stream, size), MAX_REQUEST)
            require(set(request) == {"version"} and type(request["version"]) is int and request["version"] == 1)
            response = source.credentials()
        except Exception:
            response = {"version": 1, "error": "credentials_unavailable"}
        try:
            payload = canonical(response)
            require(len(payload) <= MAX_RESPONSE)
            stream.sendall(struct.pack("!I", len(payload)) + payload)
        except Exception:
            pass


def serve(source, *, port=5104, cid=16, ready=None):
    slots = threading.BoundedSemaphore(4)
    def worker(stream, peer):
        try:
            connection(stream, peer[0], cid, source)
        finally:
            slots.release()
    with socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM) as listener:
        listener.bind((socket.VMADDR_CID_ANY, port)); listener.listen(8)
        if ready is not None:
            ready()
        while True:
            stream, peer = listener.accept()
            if peer[0] != cid or not slots.acquire(blocking=False):
                stream.close()
                continue
            threading.Thread(target=worker, args=(stream, peer), daemon=True).start()


def main():
    parser = argparse.ArgumentParser(description="Memory-only enclave AWS role forwarding")
    parser.add_argument("--role-arn", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--port", type=int, default=5104)
    args = parser.parse_args()
    require(args.port == 5104)
    from .listener_ready import notify_ready
    serve(CredentialSource(role_arn=args.role_arn, instance_id=args.instance_id), port=args.port,
          ready=notify_ready)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Credential service unavailable.") from None
