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
# A contributor-chosen endpoint speaking the OpenAI chat-completions format.
CUSTOM_PROVIDER = "openai_compatible"
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,149}")
INFERENCE_HOST = re.compile(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


def inference_base_url(value):
    """https://dns-name[/short/path]: no credentials, port, query, fragment, address
    literal, or the service's own cloud and settlement endpoints."""
    require(isinstance(value, str) and len(value) <= 200, "invalid_provider")
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    require(parsed.scheme == "https" and parsed.netloc == host and INFERENCE_HOST.fullmatch(host)
            and not host.endswith((".amazonaws.com", ".internal", ".local")) and host != "mainnet.base.org"
            and not parsed.query and not parsed.fragment
            and re.fullmatch(r"(?:/[A-Za-z0-9_.~-]{1,40}){0,5}", parsed.path) and ".." not in parsed.path
            and re.search(r"\d{6,}", parsed.path) is None
            and value == "https://" + host + parsed.path, "invalid_provider")
    return value


def route_allows(campaign, provider, model, privacy):
    """A route listing "*" accepts any well-formed model name for that provider."""
    # A model id may carry a date stamp; a longer digit run is an identifier.
    return isinstance(model, str) and model != "*" and re.search(r"\d{9,}", model) is None and any(
        provider == route["provider"] and privacy in route["privacyModes"]
        and (model in route["models"] or "*" in route["models"] and MODEL_NAME.fullmatch(model) is not None)
        for route in campaign["inferenceRoutes"])


def validate_payout_authority(value):
    from .kms_signer import KEY_ARN
    fields(value, {"kind", "keyId", "wallet"})
    require(value["kind"] == "aws_kms" and isinstance(value["keyId"], str)
            and len(value["keyId"]) <= 256 and KEY_ARN.fullmatch(value["keyId"]), "invalid_payout_authority")
    require(value["wallet"] == address(value["wallet"]), "invalid_payout_authority")
    return value


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
    extra = {name for name in ("sourceDescriptor", "openSource") if isinstance(campaign, dict) and name in campaign}
    require(len(extra) <= 1, "invalid_policy")
    fields(campaign, CAMPAIGN_FIELDS | extra)
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
        # Only an open campaign may replay a contributor-chosen read-only POST.
        require(isinstance(source["methods"], list) and bool(source["methods"])
                and set(source["methods"]) <= {"GET", "HEAD"} | ({"POST"} if "openSource" in campaign else set()),
                "unsafe_method")
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
    if "openSource" in campaign:
        from .open_source import validate_open_campaign
        validate_open_campaign(campaign)
        require(len(canonical(campaign)) <= 32768, "policy_size")
        return campaign
    require(isinstance(requirements["requiredFields"], list) and bool(requirements["requiredFields"])
            and all(field in campaign["safeSchemaFields"] for field in requirements["requiredFields"]), "invalid_policy")
    if "sourceDescriptor" in campaign:
        from .acquisition import validate_descriptor
        validate_descriptor(campaign)
    require(len(canonical(campaign)) <= 32768, "policy_size")
    return campaign


def validate_reservation(campaign, request, now):
    validate_campaign(campaign)
    custom = isinstance(request, dict) and request.get("provider") == CUSTOM_PROVIDER
    fields(request, REQUEST_FIELDS | ({"inferenceBaseUrl"} if custom else set()))
    require(request["version"] == 1, "submission_version")
    require(campaign["status"] in {"active", "open"}, "campaign_unavailable")
    require(request["campaignId"] == campaign["id"] and request["policyDigest"] == digest(campaign), "policy_mismatch")
    address(request["payoutAddress"])
    require(request["consent"] is True, "consent_required")
    require(route_allows(campaign, request["provider"], request["model"], request["privacyMode"]),
            "provider_not_allowed")
    if custom:
        inference_base_url(request["inferenceBaseUrl"])
    integer(request["expiresAt"], int(now) + 1, int(now) + 900, "job_expired")
    fields(request["limits"], LIMIT_FIELDS)
    for field, maximum in {"maxCalls": 10, "maxInputTokens": 100000, "maxOutputTokens": 20000,
                           "maxBankReads": 20, "deadlineSeconds": 300}.items():
        integer(request["limits"][field], 1, maximum, "invalid_limits")
    require(request["expiresAt"] >= int(now) + request["limits"]["deadlineSeconds"], "job_expired")
    return request
