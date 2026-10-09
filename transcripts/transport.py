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
import threading
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


def bank_status_error(status):
    if status in (401,403): return "bank_http_unauthorized"
    if 300<=status<400:return "bank_http_redirect"
    if 400<=status<500:return "bank_http_client_error"
    if 500<=status<600:return "bank_http_server_error"
    return "bank_http_unexpected_status"


PROVIDER_FAILURES = {"provider_http_bad_request", "provider_http_unauthorized", "provider_http_payment_required",
                     "provider_http_not_found", "provider_http_rate_limited", "provider_http_server_error",
                     "provider_http_unexpected_status"}


def provider_status_error(status):
    """Fixed codes so a contributor can tell a bad key from a bad model or quota."""
    if status in (400, 422): return "provider_http_bad_request"
    if status in (401, 403): return "provider_http_unauthorized"
    if status == 402: return "provider_http_payment_required"
    if status == 404: return "provider_http_not_found"
    if status == 429: return "provider_http_rate_limited"
    if 500 <= status < 600: return "provider_http_server_error"
    return "provider_http_unexpected_status"


class HTTPTransport:
    def __init__(self, mode="vsock"):
        require(mode in {"direct", "vsock"}, "invalid_transport")
        self.mode = mode

    def request(self, method, url, *, headers=None, body=None, timeout=15, max_bytes=MAX_RESPONSE):
        return self._request(method,url,headers=headers,body=body,timeout=timeout,max_bytes=max_bytes)

    def request_bank(self,url,*,headers,timeout=15,max_bytes=MAX_RESPONSE,open_headers=False,body=None,content_type=None):
        # An open-campaign recipe may replay the read-only POST a bank site issues.
        require(body is None or open_headers and isinstance(body,str) and isinstance(content_type,str),"unsafe_method")
        if body is not None:headers={**headers,"Content-Type":content_type}
        return self._request("GET" if body is None else "POST",url,headers=headers,timeout=timeout,max_bytes=max_bytes,
                             body=None if body is None else body.encode("utf-8"),bank_status_codes=True,open_headers=open_headers)

    def request_provider(self,url,*,headers,body,timeout=15,max_bytes=65536):
        return self._request("POST",url,headers=headers,body=body,timeout=timeout,max_bytes=max_bytes,
                             provider_status_codes=True)

    def probe_anonymous(self,url,*,headers=None,timeout=15,body=None,content_type=None):
        """The same request without secret-bearing headers. Returns the status and,
        only when 2xx JSON is served, that anonymous body for the caller to inspect."""
        headers=dict(headers or {"Accept":"application/json"})
        if body is not None:headers["Content-Type"]=content_type
        return self._request("GET" if body is None else "POST",url,headers=headers,timeout=timeout,
                             body=None if body is None else body.encode("utf-8"),anonymous_probe=True,open_headers=True)

    def probe_authentication(self,url,*,timeout=15,invalid_credential=False):
        """Status-only anonymous GET: never read, retain or return an error body."""
        require(type(invalid_credential) is bool,"invalid_submission")
        headers={"Accept":"application/json"}
        # Public, deliberately invalid test value; never a contributor credential.
        invalid_probe_token="peerlink-deliberately-invalid-token-v1"
        if invalid_credential:headers["Authorization"]="Bearer "+invalid_probe_token
        return self._request("GET",url,headers=headers,timeout=timeout,authentication_probe=True)

    def _request(self, method, url, *, headers=None, body=None, timeout=15, max_bytes=MAX_RESPONSE, authentication_probe=False, bank_status_codes=False,
                 open_headers=False, anonymous_probe=False, provider_status_codes=False):
        require(method in {"GET", "POST"}, "unsafe_method")
        integer(max_bytes, 1, MAX_RESPONSE, "response_limits")
        require(type(timeout) in (int, float) and 0 < timeout <= 300, "request_timeout")
        require(isinstance(url, str) and len(url) <= 2048 and "\\" not in url and
                not any(ord(char) < 33 for char in url), "destination_forbidden")
        expired = threading.Event()
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
            if open_headers:
                # Contributor session headers for an open campaign. Names were
                # validated by credential_headers; AWS endpoints never use this path.
                require(not aws_host and all(
                    re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}", name) for name in headers), "unsafe_headers")
            else:
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
            # Socket timeouts bound each operation, not the whole exchange. Shut the
            # connection down at the absolute deadline so a peer trickling bytes
            # through the handshake or headers cannot hold a job slot.
            live = [raw]
            def expire():
                expired.set()
                for stream in live:
                    try:stream.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
            watchdog = threading.Timer(max(0.001, end - time.monotonic()), expire)
            watchdog.daemon = True
            watchdog.start()
            try:
                context = ssl.create_default_context()
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                secure = context.wrap_socket(raw, server_hostname=parsed.hostname)
                live.append(secure)
            except BaseException:
                watchdog.cancel()
                raw.close()
                raise
            connection = http.client.HTTPSConnection(parsed.hostname, timeout=timeout, context=context)
            connection.sock = secure  # TLS has already terminated inside this process/enclave.
            probing = False
            try:
                secure.settimeout(max(0.001, end - time.monotonic()))
                connection.request(method, parsed.path + ("?" + parsed.query if parsed.query else ""),
                                   body=body, headers=headers)
                response = connection.getresponse()
                response_headers = tuple((name.lower(), value) for name, value in response.getheaders())
                require(len(response_headers) <= 50 and sum(len(k) + len(v) for k, v in response_headers) <= 16384,
                        "response_headers_size")
                if authentication_probe:
                    require(response.status == 401, "unauthenticated_source")
                    # No body/content-type assumption or error headers cross this boundary.
                    return HTTPResponse(401,b"",())
                if anonymous_probe:
                    kinds = [v.split(";")[0].strip().lower() for k, v in response_headers if k == "content-type"]
                    served = len(kinds) == 1 and (kinds[0] == "application/json" or kinds[0].endswith("+json"))
                    plain = all(v.lower() == "identity" for k, v in response_headers if k == "content-encoding")
                    if not (200 <= response.status < 300 and served and plain):
                        # Not JSON to an anonymous caller: nothing is read or returned.
                        return HTTPResponse(response.status,b"",())
                    probing = True
                require(200 <= response.status < 300, bank_status_error(response.status) if bank_status_codes else
                        provider_status_error(response.status) if provider_status_codes else "http_request_failed")  # Redirects never followed.
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
                if probing:
                    return HTTPResponse(response.status, b"".join(chunks), (("content-type", "json"),))
                return HTTPResponse(response.status, b"".join(chunks), response_headers)
            finally:
                watchdog.cancel()
                connection.close()
        except Rejected:
            raise
        except (OSError, ValueError, http.client.HTTPException):
            raise Rejected("request_timeout" if expired.is_set() else "http_transport_failed") from None


def json_response(response, maximum=MAX_RESPONSE):
    require(type(response) is HTTPResponse and response.tls_verified is True and
            type(response.status) is int and 200 <= response.status < 300, "unauthenticated_source")
    require(isinstance(response.body, bytes) and len(response.body) <= maximum, "response_size")
    try:
        return strict_json(response.body, maximum=maximum)
    except (ValueError, TypeError):
        raise Rejected("response_invalid_json") from None


class BankClient:
    """Factory for reviewed descriptors and the internal Wise identity adapter.

    credential is {origin, kind: bearer|cookie, value}. profile_id selects a
    profile but is never evidence of ownership: /v1/profiles proves membership.
    """
    def __new__(cls,campaign,*args,**kwargs):
        if "sourceDescriptor" in campaign:
            from .acquisition import DescriptorBankClient
            return DescriptorBankClient(campaign,*args,**kwargs)
        if "openSource" in campaign:
            from .open_source import OpenBankClient
            return OpenBankClient(campaign,*args,**kwargs)
        return super().__new__(cls)

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
