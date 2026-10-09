"""Bounded read-only recipes and transport-only live evidence objects."""
from dataclasses import dataclass
from urllib.parse import urlsplit, parse_qsl
import re
from .common import canonical, fields, integer, require
from .policy import validate_campaign


@dataclass(frozen=True, repr=False)
class LiveRead:
    """Created exclusively by the enclave's authenticated bank transport.

    Never deserialize this object from an uploaded transcript. account_id must be
    extracted from authenticated account evidence by the configured bank adapter.
    acquired_at and job_id bind this evidence to fresh execution of this job.
    """
    job_id: str
    url: str
    method: str
    status: int
    body: object
    account_id: str
    acquired_at: int
    authenticated: bool
    tls_verified: bool
    response_headers: tuple = ()
    authentication_gate: bool = False

    def __repr__(self):
        # URLs, bodies and authenticated identifiers remain private even when an
        # exception/debugger formats this object or a container holding it.
        return 'LiveRead(<private evidence omitted>)'


def permitted_endpoint(campaign, url, method):
    require(isinstance(url, str) and len(url) <= 2048 and "\\" not in url,
            "source_not_allowed")
    try:
        parsed = urlsplit(url)
        require(parsed.scheme == "https" and parsed.hostname and parsed.username is None
                and parsed.password is None and parsed.port in (None, 443) and not parsed.fragment,
                "source_not_allowed")
        source_origin = "https://" + parsed.hostname
        require(url.startswith(source_origin + "/") and ".." not in parsed.path and "//" not in parsed.path and "%" not in parsed.path,
                "source_not_allowed")
        parameters = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing="openSource" not in campaign)
    except (ValueError, UnicodeError):
        require(False, "source_not_allowed")
    for source in campaign["sources"]:
        if "openSource" in campaign:
            # The campaign pins the bank's registrable domain; the contributor's
            # recipe chooses the host under it and the path.
            from .open_source import origin_in_domain
            if not origin_in_domain(source_origin, source["origin"]) or method not in source["methods"]:
                continue
            require(re.fullmatch(r"/[A-Za-z0-9_.~:@,=+;()'/-]*", parsed.path) and len(parameters) <= 30
                    and len({name for name, _ in parameters}) == len(parameters)
                    and all(re.fullmatch(r"[A-Za-z0-9_.$\[\]-]{1,64}", name) and len(value) <= 512
                            for name, value in parameters), "source_not_allowed")
            return source, "/", sorted(name for name, _ in parameters)
        if source["origin"] != source_origin or method not in source["methods"]:
            continue
        require(len(parameters) <= 30 and len({name for name, _ in parameters}) == len(parameters)
                and all(name in source["parameterNames"] and len(value) <= 512 for name, value in parameters), "source_not_allowed")
        for template in source["paths"]:
            pattern = re.escape(template).replace(r"\{id\}", r"[A-Za-z0-9_-]{1,160}")
            if re.fullmatch(pattern, parsed.path):
                return source, template, sorted(name for name, _ in parameters)
    require(False, "source_not_allowed")


def validate_recipe(campaign, recipe, max_reads=20):
    validate_campaign(campaign)
    if "sourceDescriptor" in campaign:
        from .acquisition import validate_hints
        return validate_hints(campaign, recipe, max_reads)
    if "openSource" in campaign:
        from .open_source import validate_open_recipe
        return validate_open_recipe(campaign, recipe, max_reads)
    fields(recipe, {"version", "reads"})
    require(recipe["version"] == 1, "recipe_version")
    require(isinstance(recipe["reads"], list) and 1 <= len(recipe["reads"]) <= max_reads, "recipe_limits")
    for read in recipe["reads"]:
        fields(read, {"method", "url"})
        require(read["method"] in {"GET", "HEAD"}, "unsafe_method")
        permitted_endpoint(campaign, read["url"], read["method"])
    require(len(canonical(recipe)) <= 32768, "recipe_limits")
    return recipe


def validate_live_reads(campaign, reads, job_id, submitted_at, now, max_reads=20):
    require(isinstance(reads, list) and 1 <= len(reads) <= max_reads, "insufficient_evidence")
    account_ids = set()
    for read in reads:
        require(type(read) is LiveRead, "untrusted_evidence")
        require(read.job_id == job_id and read.authenticated is True and read.tls_verified is True,
                "unauthenticated_source")
        integer(read.acquired_at, int(submitted_at), int(now), "stale_evidence")
        require(type(read.status) is int and 200 <= read.status <= 299, "bank_read_failed")
        require(isinstance(read.account_id, str) and 1 <= len(read.account_id) <= 300, "account_evidence_missing")
        permitted_endpoint(campaign, read.url, read.method)
        require(len(canonical(read.body)) <= 2_000_000, "evidence_size")
        account_ids.add(read.account_id)
    require(len(account_ids) == 1, "ambiguous_account")
    if "sourceDescriptor" in campaign:
        from .acquisition import validate_evidence
        return validate_evidence(campaign, reads)
    if "openSource" in campaign:
        # The identity and history reads carry the anonymous-probe gate; the
        # transcript builder requires it on exactly those two.
        require(all(read.method in {"GET", "POST"} and read.status == 200 for read in reads)
                and any(read.authentication_gate is True for read in reads), "unauthenticated_source")
    return next(iter(account_ids))


def assess_history(campaign, reads):
    requirements = campaign["evidenceRequirements"]
    record_count = 0
    for read in reads:
        history = read.body
        for part in requirements["historyPath"]:
            history = history.get(part) if isinstance(history, dict) else None
        if not isinstance(history, list):
            continue
        for row in history:
            if isinstance(row, dict) and all(field in row and type(row[field]) in (str, int, float)
                                            and (not isinstance(row[field], str) or bool(row[field].strip()))
                                            for field in requirements["requiredFields"]):
                record_count += 1
    require(record_count >= requirements["minRecords"], "insufficient_history")
    return record_count
