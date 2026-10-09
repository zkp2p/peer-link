"""Credential-free HTTPS plumbing and authenticated, read-only bank acquisition.

The parent relay sees destination metadata and TLS ciphertext, never HTTP data.
Direct networking is an explicit local-test/operator choice; enclave default is VSOCK.
"""
from dataclasses import dataclass
import copy
import http.client
import ipaddress
import re
import socket
import ssl
import time
from urllib.parse import urlsplit, parse_qsl

from .common import Rejected, canonical, fields, integer, opaque_id, require, strict_json
from .policy import origin, validate_campaign
from .recipe import LiveRead, permitted_endpoint, validate_recipe

MAX_RESPONSE = 2_000_000
WISE_ORIGIN = "https://api.wise.com"


@dataclass(frozen=True, repr=False)
class HTTPResponse:
    status: int
    body: bytes
    headers: tuple = ()
    tls_verified: bool = True


def public_socket(host, port=443, timeout=15):
    """Resolve once, reject any non-global answer, connect to the checked address.

    Used by the host relay or explicit direct mode. TLS verification stays in
    HTTPTransport, and checks the original hostname independently of DNS.
    """
    origin("https://" + host)
    require(port == 443, "destination_forbidden")
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    require(bool(addresses), "destination_forbidden")
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        require(ip.is_global and not (getattr(ip, "ipv4_mapped", None) and
                                    not ip.ipv4_mapped.is_global), "destination_forbidden")
    family, kind, protocol, _, address = addresses[0]
    stream = socket.socket(family, kind, protocol)
    stream.settimeout(timeout)
    try:
        stream.connect(address)
        return stream
    except BaseException:
        stream.close()
        raise


def tunnel_socket(host, port=443, timeout=15):
    origin("https://" + host)
    require(port == 443, "destination_forbidden")
    require(hasattr(socket, "AF_VSOCK"), "vsock_unavailable")
    stream = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    stream.settimeout(timeout)
    try:
        stream.connect((3, 5101))
        stream.sendall(canonical({"host": host, "port": 443}) + b"\n")
        reply = bytearray()
        while len(reply) < 3:
            part = stream.recv(1)
            require(bool(part), "relay_refused")
            reply.extend(part)
        require(bytes(reply) == b"OK\n", "relay_refused")
        return stream
    except BaseException:
        stream.close()
        raise


class HTTPTransport:
    def __init__(self, mode="vsock"):
        require(mode in {"direct", "vsock"}, "invalid_transport")
        self.mode = mode

    def request(self, method, url, *, headers=None, body=None, timeout=15, max_bytes=MAX_RESPONSE):
        require(method in {"GET", "POST"}, "unsafe_method")
        integer(max_bytes, 1, MAX_RESPONSE, "response_limits")
        require(type(timeout) in (int, float) and 0 < timeout <= 300, "request_timeout")
        require(isinstance(url, str) and len(url) <= 2048 and "\\" not in url and
                not any(ord(char) < 33 for char in url), "destination_forbidden")
        try:
            parsed = urlsplit(url)
            source = "https://" + (parsed.hostname or "")
            origin(source)
            require(parsed.scheme == "https" and parsed.netloc == parsed.hostname and
                    parsed.port is None and not parsed.fragment and parsed.path.startswith("/"),
                    "destination_forbidden")
            headers = dict(headers or {})
            aws_host=parsed.hostname in {"kms.us-east-1.amazonaws.com","lambda.us-east-1.amazonaws.com"}
            permitted={"Accept","Content-Type","Authorization","Cookie","x-no-aliasing"}
            if aws_host:
                require(method=="POST" and not parsed.query,"unsafe_headers")
                permitted |= {"X-Amz-Date","X-Amz-Security-Token","X-Amz-Target"}
                if "X-Amz-Target" in headers:
                    require(parsed.hostname=="kms.us-east-1.amazonaws.com" and parsed.path=="/"
                            and headers["X-Amz-Target"] in {"TrentService.GenerateDataKey","TrentService.Decrypt"},"unsafe_headers")
            require(set(headers) <= permitted, "unsafe_headers")
            if "x-no-aliasing" in headers:
                require(method == "POST" and parsed.hostname == "cloud-api.near.ai"
                        and parsed.path == "/v1/chat/completions" and not parsed.query
                        and headers["x-no-aliasing"] == "true", "unsafe_headers")
            require(all(isinstance(value, str) and 0 < len(value) <= 16384 and
                        all(32 <= ord(char) < 127 for char in value) for value in headers.values()), "unsafe_headers")
            require(body is None or isinstance(body, bytes) and len(body) <= 1_000_000, "request_size")
            headers.update({"Accept-Encoding": "identity", "Connection": "close"})
            end = time.monotonic() + timeout
            factory = public_socket if self.mode == "direct" else tunnel_socket
            raw = factory(parsed.hostname, 443, timeout=timeout)
            try:
                context = ssl.create_default_context()
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                secure = context.wrap_socket(raw, server_hostname=parsed.hostname)
            except BaseException:
                raw.close()
                raise
            connection = http.client.HTTPSConnection(parsed.hostname, timeout=timeout, context=context)
            connection.sock = secure  # TLS has already terminated inside this process/enclave.
            try:
                secure.settimeout(max(0.001, end - time.monotonic()))
                connection.request(method, parsed.path + ("?" + parsed.query if parsed.query else ""),
                                   body=body, headers=headers)
                response = connection.getresponse()
                require(200 <= response.status < 300, "http_request_failed")  # Redirects never followed.
                response_headers = tuple((name.lower(), value) for name, value in response.getheaders())
                require(len(response_headers) <= 50 and sum(len(k) + len(v) for k, v in response_headers) <= 16384,
                        "response_headers_size")
                content_types = [v for k, v in response_headers if k == "content-type"]
                require(len(content_types) == 1 and (content_types[0].split(";")[0].strip().lower() == "application/json"
                        or content_types[0].split(";")[0].strip().lower().endswith("+json")
                        or aws_host and content_types[0].split(";")[0].strip().lower()=="application/x-amz-json-1.1"), "response_not_json")
                require(all(v.lower() == "identity" for k, v in response_headers if k == "content-encoding"),
                        "response_encoding")
                chunks, count = [], 0
                # A completed fixed-length read closes HTTPResponse's file and
                # may release the Connection: close socket. Do not touch that
                # socket again merely to discover the already-known end of body.
                while not response.isclosed():
                    remaining = end - time.monotonic()
                    require(remaining > 0, "request_timeout")
                    secure.settimeout(remaining)
                    chunk = response.read1(min(65536, max_bytes + 1 - count))
                    if not chunk:
                        break
                    count += len(chunk)
                    require(count <= max_bytes, "response_size")
                    chunks.append(chunk)
                require(response.length in (None, 0), "response_incomplete")
                return HTTPResponse(response.status, b"".join(chunks), response_headers)
            finally:
                connection.close()
        except Rejected:
            raise
        except (OSError, ValueError, http.client.HTTPException):
            raise Rejected("http_transport_failed") from None


def json_response(response, maximum=MAX_RESPONSE):
    require(type(response) is HTTPResponse and response.tls_verified is True and
            type(response.status) is int and 200 <= response.status < 300, "unauthenticated_source")
    require(isinstance(response.body, bytes) and len(response.body) <= maximum, "response_size")
    try:
        return strict_json(response.body, maximum=maximum)
    except (ValueError, TypeError):
        raise Rejected("response_invalid_json") from None


class BankClient:
    """Only Wise has an authenticated account-identity adapter in this pilot.

    credential is {origin, kind: bearer|cookie, value}. profile_id selects a
    profile but is never evidence of ownership: /v1/profiles proves membership.
    """
    def __init__(self, campaign, credential, transport=None, *, profile_id=None, max_reads=20, timeout=15):
        validate_campaign(campaign)
        fields(credential, {"origin", "kind", "value"})
        require(credential["origin"] == WISE_ORIGIN and credential["kind"] == "bearer", "source_review_required")
        require(isinstance(credential["value"], str) and 1 <= len(credential["value"]) <= 16384 and
                all(33 <= ord(char) < 127 for char in credential["value"]), "invalid_credential")
        require(campaign["sources"] and all(source["origin"] == WISE_ORIGIN for source in campaign["sources"]),
                "source_review_required")
        require(profile_id is None or type(profile_id) in (str, int) and re.fullmatch(r"[1-9][0-9]{0,19}", str(profile_id)),
                "invalid_profile")
        self.campaign, self.credential = copy.deepcopy(campaign), credential.copy()
        self.transport = transport or HTTPTransport()
        self.profile_id = None if profile_id is None else str(profile_id)
        self.max_reads = integer(max_reads, 1, 20, "recipe_limits")
        self.timeout = timeout

    def acquire(self, job_id, recipe, now):
        opaque_id(job_id)
        integer(now, 0, 2**63 - 1)
        require(bool(self.credential), "invalid_credential")
        validate_recipe(self.campaign, recipe, self.max_reads)
        require(recipe["reads"][0] == {"method": "GET", "url": WISE_ORIGIN + "/v1/profiles"}, "account_evidence_missing")
        selected = self.profile_id
        requested = set()
        for read in recipe["reads"][1:]:
            require(read["method"] == "GET", "unsafe_method")
            parsed = urlsplit(read["url"])
            match = re.fullmatch(r"/(v4/profiles/([1-9][0-9]{0,19})/balances|v1/profiles/([1-9][0-9]{0,19})/balance-statements/([1-9][0-9]{0,19})/statement.json)", parsed.path)
            require(match is not None, "source_not_allowed")
            requested.add(match[2] or match[3])
        require(len(requested) <= 1, "ambiguous_account")
        if requested:
            inferred = next(iter(requested))
            require(selected is None or selected == inferred, "ambiguous_account")
            selected = inferred
        outputs, known_balances = [], set()
        end = time.monotonic() + self.timeout
        for index, read in enumerate(recipe["reads"]):
            permitted_endpoint(self.campaign, read["url"], "GET")
            parsed = urlsplit(read["url"])
            params = dict(parse_qsl(parsed.query, strict_parsing=True))
            if index:
                if parsed.path.endswith("/balances"):
                    require(params == {"types": "STANDARD"}, "source_not_allowed")
                else:
                    require(set(params) == {"currency", "intervalStart", "intervalEnd", "type"}
                            and params["type"] == "COMPACT" and re.fullmatch(r"[A-Z]{3}", params["currency"]), "source_not_allowed")
                    balance_id = parsed.path.split("/")[5]
                    require(balance_id in known_balances, "account_evidence_missing")
            remaining = end - time.monotonic()
            require(remaining > 0, "request_timeout")
            bearer = "Bearer " + self.credential["value"]
            response = self.transport.request("GET", read["url"], headers={"Accept": "application/json",
                        "Authorization": bearer}, timeout=remaining, max_bytes=MAX_RESPONSE)
            body = json_response(response)
            if index == 0:
                require(isinstance(body, list) and 1 <= len(body) <= 100, "account_evidence_missing")
                ids = []
                for profile in body:
                    require(isinstance(profile, dict) and type(profile.get("id")) is int and profile["id"] > 0,
                            "account_evidence_missing")
                    ids.append(str(profile["id"]))
                require(len(set(ids)) == len(ids), "ambiguous_account")
                require(len(ids) == 1 or self.profile_id is not None, "ambiguous_account")
                if selected is None:
                    require(len(ids) == 1, "ambiguous_account")
                    selected = ids[0]
                require(selected in ids, "account_evidence_missing")
            elif parsed.path.endswith("/balances"):
                require(isinstance(body, list) and len(body) <= 1000, "account_evidence_missing")
                for balance in body:
                    require(isinstance(balance, dict) and type(balance.get("id")) is int and balance["id"] > 0
                            and balance.get("type") == "STANDARD", "account_evidence_missing")
                    if "profileId" in balance:
                        require(type(balance["profileId"]) is int and str(balance["profileId"]) == selected, "ambiguous_account")
                    known_balances.add(str(balance["id"]))
            elif isinstance(body, dict) and "profileId" in body:
                require(type(body["profileId"]) is int and str(body["profileId"]) == selected, "ambiguous_account")
            outputs.append(LiveRead(job_id, read["url"], "GET", response.status, body,
                                    "wise-profile:" + selected, now, True, True,
                                    tuple(name for name, _ in response.headers)))
        return outputs

    def close(self):
        self.credential.clear()
