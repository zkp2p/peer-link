"""Versioned campaign and reservation bindings; model output cannot edit terms."""
from urllib.parse import urlsplit
import re
from .common import address, canonical, digest, fields, integer, opaque_id, require

REWARDS = (5_000_000, 10_000_000)
MAX_BUDGET = 50_000_000
CAMPAIGN_FIELDS = {"version", "id", "bankId", "bankName", "country", "issueUrl", "status",
                   "rewardMinor", "maxContributors", "sources", "inferenceRoutes", "rubricVersion",
                   "evidenceRequirements", "safeSchemaFields"}
REQUEST_FIELDS = {"version", "campaignId", "payoutAddress", "provider", "model", "privacyMode",
                  "consent", "policyDigest", "expiresAt", "limits"}
LIMIT_FIELDS = {"maxCalls", "maxInputTokens", "maxOutputTokens", "maxBankReads", "deadlineSeconds"}


def origin(value):
    require(isinstance(value, str), "invalid_source")
    parsed = urlsplit(value)
    require(parsed.scheme == "https" and parsed.hostname and parsed.username is None
            and parsed.password is None and parsed.port in (None, 443)
            and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
            and value == "https://" + parsed.hostname, "invalid_source")
    return value


def safe_name(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value), "invalid_policy")
    require(value.lower() not in {"cookie", "authorization", "password", "token", "secret", "apikey",
                                  "api_key", "session", "set_cookie"}, "unsafe_policy_name")
    return value


def validate_campaign(campaign):
    fields(campaign, CAMPAIGN_FIELDS)
    require(campaign["version"] == 1, "policy_version")
    for name in ("id", "rubricVersion"):
        opaque_id(campaign[name])
    require(isinstance(campaign["bankId"], str) and re.fullmatch(r"[a-z0-9][a-z0-9_/-]{0,119}", campaign["bankId"]), "invalid_identifier")
    for name in ("bankName", "country"):
        require(isinstance(campaign[name], str) and 1 <= len(campaign[name]) <= 100, "invalid_policy")
    require(isinstance(campaign["issueUrl"], str) and campaign["issueUrl"].startswith("https://github.com/")
            and len(campaign["issueUrl"]) <= 300, "invalid_policy")
    require(campaign["status"] in {"draft", "source_review", "active", "paused", "complete", "open", "review"}, "invalid_policy")
    require(type(campaign["rewardMinor"]) is int and campaign["rewardMinor"] in REWARDS, "invalid_reward")
    integer(campaign["maxContributors"], 1, 5, "invalid_capacity")
    require(isinstance(campaign["sources"], list) and 1 <= len(campaign["sources"]) <= 10, "invalid_source")
    for source in campaign["sources"]:
        fields(source, {"origin", "paths", "methods", "parameterNames", "headerNames"})
        origin(source["origin"])
        require(isinstance(source["paths"], list) and 1 <= len(source["paths"]) <= 30, "invalid_source")
        for path in source["paths"]:
            require(isinstance(path, str) and len(path) <= 300 and path.startswith("/")
                    and re.fullmatch(r"/[A-Za-z0-9_/{}/.-]*", path)
                    and ".." not in path and "//" not in path
                    and all("{" not in segment and "}" not in segment or segment == "{id}"
                            for segment in path.split("/")), "invalid_source")
        require(isinstance(source["methods"], list) and bool(source["methods"])
                and set(source["methods"]) <= {"GET", "HEAD"}, "unsafe_method")
        for name in ("parameterNames", "headerNames"):
            require(isinstance(source[name], list) and len(source[name]) <= 30, "invalid_policy")
            for item in source[name]:
                safe_name(item)
    require(isinstance(campaign["inferenceRoutes"], list) and 1 <= len(campaign["inferenceRoutes"]) <= 20,
            "invalid_provider")
    for route in campaign["inferenceRoutes"]:
        fields(route, {"provider", "models", "privacyModes"})
        opaque_id(route["provider"])
        require(isinstance(route["models"], list) and 1 <= len(route["models"]) <= 30
                and all(isinstance(model, str) and 1 <= len(model) <= 150 for model in route["models"]), "invalid_model")
        require(isinstance(route["privacyModes"], list) and bool(route["privacyModes"])
                and set(route["privacyModes"]) <= {"confidential", "provider_visible"}, "invalid_privacy_mode")
    require(isinstance(campaign["safeSchemaFields"], list) and len(campaign["safeSchemaFields"]) <= 200,
            "invalid_policy")
    for item in campaign["safeSchemaFields"]:
        safe_name(item)
    requirements = campaign["evidenceRequirements"]
    fields(requirements, {"historyPath", "minRecords", "requiredFields", "minScore"})
    require(isinstance(requirements["historyPath"], list) and len(requirements["historyPath"]) <= 8
            and all(field in campaign["safeSchemaFields"] for field in requirements["historyPath"]), "invalid_policy")
    integer(requirements["minRecords"], 1, 100, "invalid_policy")
    integer(requirements["minScore"], 0, 100, "invalid_policy")
    require(isinstance(requirements["requiredFields"], list) and bool(requirements["requiredFields"])
            and all(field in campaign["safeSchemaFields"] for field in requirements["requiredFields"]), "invalid_policy")
    require(len(canonical(campaign)) <= 32768, "policy_size")
    return campaign


def validate_reservation(campaign, request, now):
    validate_campaign(campaign)
    fields(request, REQUEST_FIELDS)
    require(request["version"] == 1, "submission_version")
    require(campaign["status"] in {"active", "open"}, "campaign_unavailable")
    require(request["campaignId"] == campaign["id"] and request["policyDigest"] == digest(campaign), "policy_mismatch")
    address(request["payoutAddress"])
    require(request["consent"] is True, "consent_required")
    require(any(request["provider"] == route["provider"] and request["model"] in route["models"]
                and request["privacyMode"] in route["privacyModes"] for route in campaign["inferenceRoutes"]), "provider_not_allowed")
    integer(request["expiresAt"], int(now) + 1, int(now) + 900, "job_expired")
    fields(request["limits"], LIMIT_FIELDS)
    for field, maximum in {"maxCalls": 10, "maxInputTokens": 100000, "maxOutputTokens": 20000,
                           "maxBankReads": 20, "deadlineSeconds": 300}.items():
        integer(request["limits"][field], 1, maximum, "invalid_limits")
    require(request["expiresAt"] >= int(now) + request["limits"]["deadlineSeconds"], "job_expired")
    return request
