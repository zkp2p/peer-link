"""Deterministic structural extraction. No bank values or model prose are retained."""
import hashlib
import hmac
import math
from urllib.parse import urlsplit
from .common import canonical, fields, integer, require
from .recipe import LiveRead, permitted_endpoint, assess_history
from .policy import validate_campaign

ARTIFACT_FIELDS = {"version", "campaignId", "bankId", "sourceOrigins", "endpoints", "relationships", "toolFlow", "coverage", "limitations"}
TYPES = {"null", "boolean", "integer", "number", "string", "object", "array"}
LIMITATIONS = {"account_duplicates_only", "schema_only", "no_payment_authenticity_claim"}
def artifact_limitations(campaign):
    if "sourceDescriptor" in campaign:
        return {"organization_duplicates_only", "no_human_identity_claim", "schema_only", "no_payment_authenticity_claim", "one_page_history_only", "first_contributor_source_validation"}
    return LIMITATIONS


def descriptor_binding(campaign):
    d=campaign["sourceDescriptor"]
    return {"origin":d["origin"], "listPath":d["accountsPath"], "detailPath":d["historyPath"],
            "relation":"authenticated_path_parameter",
            "sourceField":"$"+"".join("."+part for part in d["accountsListPath"])+"[]."+d["accountIdField"],
            "parameter":"accountId", "placeholder":1}


WISE_ORIGIN = "https://api.wise.com"
WISE_PROFILES = "/v1/profiles"
WISE_BALANCES = "/v4/profiles/{id}/balances"
WISE_STATEMENT = "/v1/profiles/{id}/balance-statements/{id}/statement.json"
# placeholder is the one-based occurrence of {id} in the target template. Only
# reviewed public names/paths are emitted; concrete identifiers never leave RAM.
WISE_PATH_BINDINGS = (
    {"origin": WISE_ORIGIN, "listPath": WISE_PROFILES, "detailPath": WISE_BALANCES,
     "relation": "authenticated_path_parameter", "sourceField": "$[].id", "parameter": "profileId", "placeholder": 1},
    {"origin": WISE_ORIGIN, "listPath": WISE_PROFILES, "detailPath": WISE_STATEMENT,
     "relation": "authenticated_path_parameter", "sourceField": "$[].id", "parameter": "profileId", "placeholder": 1},
    {"origin": WISE_ORIGIN, "listPath": WISE_BALANCES, "detailPath": WISE_STATEMENT,
     "relation": "authenticated_path_parameter", "sourceField": "$[].id", "parameter": "balanceId", "placeholder": 2},
)


def _wise_relationships(campaign, reads):
    """Match actual authenticated IDs before retaining only their structural roles."""
    if "id" not in campaign["safeSchemaFields"]:
        return []
    observed = []
    for read in reads:
        source, template, _ = permitted_endpoint(campaign, read.url, read.method)
        if (source["origin"] == WISE_ORIGIN and read.method == "GET" and read.authenticated is True
                and read.tls_verified is True and type(read.status) is int and 200 <= read.status <= 299):
            observed.append((read, template, urlsplit(read.url).path.split("/")))
    found = set()
    for index, (first, first_path, first_segments) in enumerate(observed):
        if first_path not in {WISE_PROFILES, WISE_BALANCES} or not isinstance(first.body, list):
            continue
        ids = {str(row["id"]) for row in first.body
               if isinstance(row, dict) and type(row.get("id")) is int and row["id"] > 0}
        for second, second_path, second_segments in observed[index + 1:]:
            if second_path not in {WISE_BALANCES, WISE_STATEMENT}:
                continue
            profile = second_segments[3]
            if (not profile.isdigit() or first.job_id != second.job_id
                    or first.account_id != second.account_id or second.account_id != "wise-profile:" + profile):
                continue
            if first_path == WISE_PROFILES and profile in ids:
                found.add(0 if second_path == WISE_BALANCES else 1)
            elif (first_path == WISE_BALANCES and second_path == WISE_STATEMENT
                  and first_segments[3] == profile and second_segments[5] in ids):
                found.add(2)
    return [dict(WISE_PATH_BINDINGS[index]) for index in sorted(found)]


def account_fingerprint(key, campaign_id, live_account_id):
    require(isinstance(key, bytes) and len(key) >= 32, "dedup_key_unavailable")
    require(isinstance(live_account_id, str) and 1 <= len(live_account_id) <= 300, "account_evidence_missing")
    return hmac.new(key, b"peer-link-account-dedup-v1\0" + canonical([campaign_id, live_account_id]),
                    hashlib.sha256).hexdigest()


def account_fingerprints(key,campaign,reads,account_id):
    """Private overlap witnesses, never a proof of one human or exported count.

    Wise's authenticated profile discovery proves the set reachable by this
    credential. Selecting another profile cannot earn a second overlapping slot.
    Other source adapters retain their independently authenticated account ID.
    """
    identities={account_id}
    if any(source['origin']=='https://api.wise.com' for source in campaign['sources']):
        discovery=[read for read in reads if read.url=='https://api.wise.com/v1/profiles' and read.method=='GET']
        require(len(discovery)==1,'account_evidence_missing')
        body=discovery[0].body
        require(isinstance(body,list) and 1<=len(body)<=100,'account_evidence_missing')
        identities=set()
        for profile in body:
            require(isinstance(profile,dict) and type(profile.get('id')) is int and 0<profile['id']<10**20,
                    'account_evidence_missing')
            identities.add('wise-profile:'+str(profile['id']))
        require(len(identities)==len(body) and account_id in identities,'account_evidence_missing')
    return sorted(account_fingerprint(key,campaign['id'],identity) for identity in identities)


def _type(value):
    if value is None: return "null"
    if type(value) is bool: return "boolean"
    if type(value) is int: return "integer"
    if type(value) is float:
        require(math.isfinite(value), "unsafe_artifact")
        return "number"
    if isinstance(value, str): return "string"
    if isinstance(value, dict): return "object"
    if isinstance(value, list): return "array"
    require(False, "unsafe_artifact")


def _schema(value, safe_fields, output, path="$", depth=0, counter=None):
    counter = [0] if counter is None else counter
    counter[0] += 1
    require(depth <= 16 and counter[0] <= 30000, "schema_limits")
    output.setdefault(path, set()).add(_type(value))
    if isinstance(value, dict):
        require(len(value) <= 1000 and all(isinstance(key, str) for key in value), "schema_limits")
        for key, item in value.items():
            # Unknown keys may themselves be account numbers/names/token material.
            # A constant wildcard preserves dynamic-object shape without retaining them.
            name = key if key in safe_fields else "{key}"
            _schema(item, safe_fields, output, path + "." + name, depth + 1, counter)
    elif isinstance(value, list):
        require(len(value) <= 10000, "schema_limits")
        for item in value:
            _schema(item, safe_fields, output, path + "[]", depth + 1, counter)


def extract_artifact(campaign, reads, context=None):
    validate_campaign(campaign)
    require(isinstance(reads, list) and bool(reads) and all(type(read) is LiveRead for read in reads), "untrusted_evidence")
    if "openSource" in campaign:
        from .open_source import extract_transcript
        return extract_transcript(campaign, reads, context)
    require(context is None, "invalid_submission")
    if "sourceDescriptor" in campaign:
        from .acquisition import validate_evidence
        validate_evidence(campaign, reads)
    endpoints = {}
    origins = set()
    for read in reads:
        source, template, parameters = permitted_endpoint(campaign, read.url, read.method)
        origins.add(source["origin"])
        key = (source["origin"], template, read.method)
        entry = endpoints.setdefault(key, {"origin": source["origin"], "path": template, "method": read.method,
                                          "parameterNames": set(), "headerNames": set(), "fields": {}})
        entry["parameterNames"].update(parameters)
        approved_headers = {name.lower(): name for name in source["headerNames"]}
        entry["headerNames"].update(approved_headers[name.lower()] for name in read.response_headers
                                    if isinstance(name, str) and name.lower() in approved_headers)
        _schema(read.body, set(campaign["safeSchemaFields"]), entry["fields"])
    normalized = []
    for key in sorted(endpoints):
        entry = endpoints[key]
        normalized.append({**entry, "parameterNames": sorted(entry["parameterNames"]),
                           "headerNames": sorted(entry["headerNames"]),
                           "fields": [{"path": path, "types": sorted(types)} for path, types in sorted(entry["fields"].items())]})
    relationships = []
    for first in normalized:
        for second in normalized:
            if first["origin"] == second["origin"] and second["path"] == first["path"].rstrip("/") + "/{id}":
                relationships.append({"origin": first["origin"], "listPath": first["path"],
                                      "detailPath": second["path"], "relation": "list_detail"})
    relationships.extend(_wise_relationships(campaign, reads))
    if "sourceDescriptor" in campaign:
        relationships.append(descriptor_binding(campaign))
    tool_flow = []
    for index, read in enumerate(reads):
        source, template, _ = permitted_endpoint(campaign, read.url, read.method)
        tool_flow.append({"step": index + 1, "origin": source["origin"], "path": template,
                          "method": read.method, "status": read.status})
    # Eligibility is checked against private live history, but its cardinality is
    # not part of the structural artifact sent to inference or retained publicly.
    assess_history(campaign, reads)
    artifact = {"version": 1, "campaignId": campaign["id"], "bankId": campaign["bankId"],
                "sourceOrigins": sorted(origins), "endpoints": normalized,
                "relationships": relationships, "toolFlow": tool_flow,
                "coverage": {"readCount": len(reads), "historyMinimumSatisfied": True},
                "limitations": sorted(artifact_limitations(campaign))}
    validate_artifact(campaign, artifact)
    return artifact


def validate_artifact(campaign, artifact):
    validate_campaign(campaign)
    if "openSource" in campaign:
        from .open_source import validate_transcript
        return validate_transcript(campaign, artifact)
    fields(artifact, ARTIFACT_FIELDS)
    require(artifact["version"] == 1 and artifact["campaignId"] == campaign["id"]
            and artifact["bankId"] == campaign["bankId"], "unsafe_artifact")
    require(isinstance(artifact["sourceOrigins"], list) and bool(artifact["sourceOrigins"])
            and set(artifact["sourceOrigins"]) <= {source["origin"] for source in campaign["sources"]}, "unsafe_artifact")
    require(isinstance(artifact["endpoints"], list) and 1 <= len(artifact["endpoints"]) <= 20, "unsafe_artifact")
    for endpoint in artifact["endpoints"]:
        fields(endpoint, {"origin", "path", "method", "parameterNames", "headerNames", "fields"})
        source = next((source for source in campaign["sources"] if source["origin"] == endpoint["origin"]), None)
        require(source is not None and endpoint["path"] in source["paths"] and endpoint["method"] in source["methods"], "unsafe_artifact")
        for name in ("parameterNames", "headerNames"):
            require(isinstance(endpoint[name], list) and set(endpoint[name]) <= set(source[name]), "unsafe_artifact")
        require(isinstance(endpoint["fields"], list) and len(endpoint["fields"]) <= 30000, "unsafe_artifact")
        allowed_parts = set(campaign["safeSchemaFields"]) | {"{key}"}
        for field in endpoint["fields"]:
            fields(field, {"path", "types"})
            path = field["path"]
            require(isinstance(path, str) and path.startswith("$") and len(path) <= 1500, "unsafe_artifact")
            parts = path[1:].replace("[]", "").split(".")
            require(parts[0] == "" and all(part in allowed_parts for part in parts[1:]), "unsafe_artifact")
            require(isinstance(field["types"], list) and bool(field["types"]) and set(field["types"]) <= TYPES,
                    "unsafe_artifact")
    require(isinstance(artifact["relationships"], list) and len(artifact["relationships"]) <= 400, "unsafe_artifact")
    for relationship in artifact["relationships"]:
        require(isinstance(relationship, dict), "unsafe_artifact")
        if relationship.get("relation") == "authenticated_path_parameter":
            fields(relationship, {"origin", "listPath", "detailPath", "relation", "sourceField", "parameter", "placeholder"})
            allowed_bindings = (descriptor_binding(campaign),) if "sourceDescriptor" in campaign else WISE_PATH_BINDINGS
            require(type(relationship["placeholder"]) is int and relationship in allowed_bindings, "unsafe_artifact")
            identity_type = "string" if "sourceDescriptor" in campaign else "integer"
            require(any(endpoint["origin"] == relationship["origin"] and endpoint["path"] == relationship["listPath"]
                        and endpoint["method"] == "GET" and any(field["path"] == relationship["sourceField"]
                            and identity_type in field["types"] for field in endpoint["fields"])
                        for endpoint in artifact["endpoints"]), "unsafe_artifact")
        else:
            fields(relationship, {"origin", "listPath", "detailPath", "relation"})
            require(relationship["relation"] == "list_detail"
                    and relationship["detailPath"] == relationship["listPath"].rstrip("/") + "/{id}", "unsafe_artifact")
        require(all(any(endpoint["origin"] == relationship["origin"] and endpoint["path"] == relationship[path]
                        and (relationship["relation"] != "authenticated_path_parameter" or endpoint["method"] == "GET")
                        for endpoint in artifact["endpoints"]) for path in ("listPath", "detailPath")), "unsafe_artifact")
    require(isinstance(artifact["toolFlow"], list) and 1 <= len(artifact["toolFlow"]) <= 20, "unsafe_artifact")
    for index, flow in enumerate(artifact["toolFlow"]):
        fields(flow, {"step", "origin", "path", "method", "status"})
        require(type(flow["step"]) is int and flow["step"] == index + 1 and
                any(endpoint["origin"] == flow["origin"] and endpoint["path"] == flow["path"]
                    and endpoint["method"] == flow["method"] for endpoint in artifact["endpoints"]), "unsafe_artifact")
        integer(flow["status"], 200, 299, "unsafe_artifact")
    fields(artifact["coverage"], {"readCount", "historyMinimumSatisfied"})
    integer(artifact["coverage"]["readCount"], 1, 20, "unsafe_artifact")
    require(artifact["coverage"]["readCount"] == len(artifact["toolFlow"]), "unsafe_artifact")
    require(artifact["coverage"]["historyMinimumSatisfied"] is True, "unsafe_artifact")
    require(isinstance(artifact["limitations"], list) and set(artifact["limitations"]) == artifact_limitations(campaign), "unsafe_artifact")
    require(len(canonical(artifact)) <= 1_000_000, "unsafe_artifact")
    return artifact


def validate_epoch_descriptor(epoch, policy, *, code="epoch_mismatch"):
    """Bind operator-recoverable KMS custody to the independently measured policy.

    The descriptor does not claim exclusive enclave signing authority or durable
    ledger state. Exact fields reject legacy custody and optimistic recovery flags.
    """
    import re
    from .common import address
    from .epoch import CHAIN_ID, USDC_ADDRESS, MAX_GAS_FUNDING_WEI
    from .policy import MAX_BUDGET
    durable = "stateAuthority" in policy
    expected_extra = {"stateNamespace","stateAuthorityArn","stateWrappingKeyId"} if durable else set()
    fields(epoch, expected_extra | {"version", "epochId", "payoutWallet", "chainId", "usdcContract", "budgetMinor",
                   "maxGasFundingWei", "payoutKeyCustody", "payoutKeyId", "operatorRecovery",
                   "ledgerPersistence", "restartRequiresOperatorReview"})
    require(isinstance(policy, dict), code)
    budget = policy.get("pilotBudgetMinor")
    require(type(budget) is int and 5_000_000 <= budget <= MAX_BUDGET, code)
    authority = policy.get("payoutAuthority")
    fields(authority, {"kind", "keyId", "wallet"})
    require(authority["kind"] == "aws_kms" and isinstance(authority["keyId"], str)
            and re.fullmatch(r"arn:aws(?:-cn|-us-gov)?:kms:[a-z0-9-]+:[0-9]{12}:key/"
                             r"(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|mrk-[0-9a-f]{32})",
                             authority["keyId"]), code)
    require(type(epoch["version"]) is int and epoch["version"] == (3 if durable else 2)
            and isinstance(epoch["epochId"], str) and re.fullmatch(r"[0-9a-f]{32}", epoch["epochId"]), code)
    require(epoch["payoutWallet"] == address(authority["wallet"])
            and address(epoch["payoutWallet"]) == epoch["payoutWallet"]
            and epoch["payoutKeyCustody"] == "aws_kms" and epoch["payoutKeyId"] == authority["keyId"], code)
    require(type(epoch["chainId"]) is int and epoch["chainId"] == CHAIN_ID
            and epoch["usdcContract"] == USDC_ADDRESS and type(epoch["budgetMinor"]) is int
            and epoch["budgetMinor"] == budget and type(epoch["maxGasFundingWei"]) is int
            and epoch["maxGasFundingWei"] == MAX_GAS_FUNDING_WEI
            and epoch["operatorRecovery"] is True and epoch["ledgerPersistence"] == ("aws_dynamodb_encrypted_snapshot" if durable else "enclave_ram_only")
            and epoch["restartRequiresOperatorReview"] is True, code)
    if durable:
        from .aws_state import authority_config
        state=authority_config(policy["stateAuthority"])
        require(epoch["stateNamespace"]==state["namespace"] and epoch["stateAuthorityArn"]==state["functionArn"]
                and epoch["stateWrappingKeyId"]==state["wrappingKeyId"],code)
    return epoch


def validate_archive_record(campaign, record, *, policy):
    """Validate the complete unsigned public record before enclave egress/signing.

    Exact field sets prevent raw bank/model/credential blobs from being accidentally
    added to an otherwise redacted artifact. Receipt signatures are wrapped only
    after this boundary. Campaign must be the immutable ledger-bound job policy.
    """
    import re
    from .common import address, digest, hex_digest
    fields(record, {"version", "epoch", "job", "artifact", "modelResult", "inference", "policyDigest"})
    require(type(record["version"]) is int and record["version"] == 1, "unsafe_archive")
    validate_artifact(campaign, record["artifact"])
    require(isinstance(policy, dict) and campaign in policy.get("campaigns", [])
            and record["policyDigest"] == digest(policy), "unsafe_archive")
    validate_epoch_descriptor(record["epoch"], policy, code="unsafe_archive")
    job = record["job"]
    fields(job, {"jobId", "campaignId", "state", "bindingDigest", "expiresAt", "rewardMinor",
                 "payoutAddress", "reason", "artifactDigest", "transactionId"})
    require(isinstance(job["jobId"],str) and re.fullmatch(r"[0-9a-f]{32}",job["jobId"])
            and job["campaignId"] == campaign["id"] and job["state"] in {"accepted","payout_pending","paid"},
            "unsafe_archive")
    hex_digest(job["bindingDigest"])
    integer(job["expiresAt"],0,2**63-1,"unsafe_archive")
    require(type(job["rewardMinor"]) is int and job["rewardMinor"] == campaign["rewardMinor"]
            and job["reason"] is None and job["artifactDigest"] == digest(record["artifact"]), "unsafe_archive")
    address(job["payoutAddress"])
    require((job["state"] == "accepted" and job["transactionId"] is None) or
            (job["state"] != "accepted" and isinstance(job["transactionId"],str)
             and re.fullmatch(r"0x[0-9a-f]{64}",job["transactionId"])), "unsafe_archive")
    from .policy import CUSTOM_PROVIDER, inference_base_url, route_allows
    grade = record["modelResult"]
    inference = record["inference"]
    require(isinstance(inference, dict), "unsafe_archive")
    custom = inference.get("provider") == CUSTOM_PROVIDER
    fields(inference,{"requestDigest","responseDigest","provider","model","privacyMode","inputTokens","outputTokens"}
           | ({"baseUrl"} if custom else set()))
    hex_digest(inference["requestDigest"])
    if "openSource" in campaign:
        # The model only proposed roles; the stored result is the code-derived
        # assessment, so its digest is not the model response digest.
        from .open_source import validate_model_result
        validate_model_result(campaign, record["artifact"], grade)
        require(grade["useful"] is True, "unsafe_archive")
        hex_digest(inference["responseDigest"])
        if custom:
            inference_base_url(inference["baseUrl"])
    else:
        fields(grade, {"rubricVersion", "score", "useful"})
        require(grade["rubricVersion"] == campaign["rubricVersion"] and grade["useful"] is True, "unsafe_archive")
        require(not custom and inference["responseDigest"] == digest(grade),"unsafe_archive")
    integer(grade["score"],campaign["evidenceRequirements"]["minScore"],100,"unsafe_archive")
    require(route_allows(campaign, inference["provider"], inference["model"], inference["privacyMode"]),
            "unsafe_archive")
    integer(inference["inputTokens"],0,100000,"unsafe_archive")
    integer(inference["outputTokens"],0,20000,"unsafe_archive")
    require(len(canonical(record)) <= 1_100_000,"unsafe_archive")
    return record
