"""HDFC's owner-authorized, application-encrypted recent-history read.

This is an opt-in measured transport, not an arbitrary encryption hook. Only the
observed recent-transactions POST is admitted. The recipe contains the logical
JSON body, so validation and transcript redaction happen before encryption.
Session keys are private credential material and never become headers/artifacts.
"""
import base64
import binascii
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .common import Rejected, require, strict_json

TRANSPORT = "hdfc-aes-gcm-v1"
CREDENTIAL_KIND = "hdfc_session"
DOMAIN = "https://hdfc.bank.in"
ORIGIN = "https://api-now.hdfc.bank.in"
HISTORY_URL = ORIGIN + "/api/dis-transaction-service/client-api/v1/recent-transactions"
MAX_RESPONSE = 2_000_000


def validate_campaign_transport(campaign):
    descriptor = campaign["openSource"]
    require(descriptor["transport"] == TRANSPORT and descriptor["maxReads"] == 1
            and campaign["bankId"] == "in/hdfc" and campaign["country"] == "IN"
            and len(campaign["sources"]) == 1 and campaign["sources"][0]["origin"] == DOMAIN
            and campaign["sources"][0]["methods"] == ["GET", "POST"],
            "invalid_policy")


def session_parts(value):
    """Validate the secret object without echoing it or attaching it to a request."""
    require(isinstance(value, dict) and set(value) == {"headers", "aesKey"}, "bank_encryption_credential")
    require(isinstance(value["headers"], dict) and isinstance(value["aesKey"], str)
            and len(value["aesKey"]) in (24, 44), "bank_encryption_credential")
    try:
        key = base64.b64decode(value["aesKey"], validate=True)
    except (ValueError, binascii.Error):
        raise Rejected("bank_encryption_credential") from None
    require(len(key) in (16, 32) and base64.b64encode(key).decode("ascii") == value["aesKey"],
            "bank_encryption_credential")
    return value["headers"], key


def account_from_read(read):
    require(isinstance(read, dict) and read.get("url") == HISTORY_URL
            and read.get("method") == "POST" and read.get("contentType") == "application/json",
            "source_not_allowed")
    try:
        body = strict_json(read.get("body"), maximum=128)
    except Rejected:
        raise Rejected("recipe_invalid") from None
    require(isinstance(body, dict) and set(body) == {"accountNo"}
            and isinstance(body["accountNo"], str) and re.fullmatch(r"[0-9]{8,20}", body["accountNo"]),
            "recipe_invalid")
    return body["accountNo"]


def validate_recipe(recipe):
    require(len(recipe["reads"]) == 1, "recipe_limits")
    account_from_read(recipe["reads"][0])
    require(recipe["identity"] == {"read": 0, "path": [0, "arrangementId"]}, "identity_path_invalid")
    require(recipe["history"] == {"read": 0, "path": []}, "history_path_invalid")


class HDFCTransport:
    """Preserve TLS/source checks and authenticate the application encryption tag.

    The bank's framing is base64(16-byte IV || AES-GCM ciphertext || 16-byte tag),
    with no additional authenticated data. Every request uses a fresh random IV.
    No plaintext fallback is permitted for an authenticated bank response.
    """
    def __init__(self, transport, value):
        _, key = session_parts(value)
        self._cipher = AESGCM(key)
        self._transport = transport

    def _encode(self, url, body, content_type):
        require(self._cipher is not None, "bank_encryption_credential")
        account_from_read({"url": url, "method": "POST", "contentType": content_type, "body": body})
        iv = os.urandom(16)
        return base64.b64encode(iv + self._cipher.encrypt(iv, body.encode("utf-8"), None)).decode("ascii")

    def _decode(self, response, *, anonymous=False):
        from .transport import HTTPResponse
        require(type(response) is HTTPResponse and response.tls_verified is True, "unauthenticated_source")
        require(type(response.status) is int, "unauthenticated_source")
        if anonymous and not 200 <= response.status < 300:
            return response
        require(response.status == 200, "bank_http_unexpected_status")
        require(isinstance(response.body, bytes) and len(response.body) <= MAX_RESPONSE, "response_size")
        # Plain JSON from an anonymous caller must still reach the ordinary
        # identity/history gate. An undecipherable success cannot pass that gate.
        if anonymous:
            try:
                strict_json(response.body, maximum=MAX_RESPONSE)
                return response
            except Rejected:
                pass
        require(self._cipher is not None, "bank_encryption_credential")
        try:
            frame = base64.b64decode(response.body, validate=True)
            require(len(frame) >= 33 and base64.b64encode(frame) == response.body, "bank_encryption_invalid")
            plain = self._cipher.decrypt(frame[:16], frame[16:], None)
            strict_json(plain, maximum=MAX_RESPONSE)
        except (ValueError, InvalidTag, binascii.Error, Rejected):
            raise Rejected("bank_encryption_invalid") from None
        return HTTPResponse(response.status, plain, response.headers, response.tls_verified)

    def probe_anonymous(self, url, *, headers, timeout, body, content_type):
        encrypted = self._encode(url, body, content_type)
        response = self._transport.probe_anonymous(url, headers=headers, timeout=timeout,
                                                  body=encrypted, content_type=content_type)
        return self._decode(response, anonymous=True)

    def request_bank(self, url, *, headers, timeout, max_bytes, open_headers, body, content_type):
        encrypted = self._encode(url, body, content_type)
        response = self._transport.request_bank(url, headers=headers, timeout=timeout, max_bytes=max_bytes,
                                               open_headers=open_headers, body=encrypted, content_type=content_type)
        decoded = self._decode(response)
        rows = strict_json(decoded.body, maximum=MAX_RESPONSE)
        account = account_from_read({"url": url, "method": "POST", "contentType": content_type, "body": body})
        require(isinstance(rows, list) and all(isinstance(row, dict) and row.get("arrangementId") == account
                                             for row in rows), "bank_account_mismatch")
        return decoded

    def close(self):
        # Dropping references is not guaranteed Python memory zeroization.
        self._cipher = None
