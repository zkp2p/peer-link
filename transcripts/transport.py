"""Transcript-specific bank acquisition over the shared enclave HTTPS transport."""
import copy
import re
import time
from urllib.parse import urlsplit, parse_qsl
from .common import fields, integer, opaque_id, require
from .policy import validate_campaign
from .recipe import LiveRead, permitted_endpoint, validate_recipe
from verification.https import HTTPResponse, HTTPTransport, json_response, MAX_RESPONSE, bank_status_error, PROVIDER_FAILURES

WISE_ORIGIN = "https://api.wise.com"


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
