"""Contributor-authored read-only recipes for banks without a reviewed adapter.

The contributor's local agent chooses the GET requests. The enclave executes them
against the campaign's bank origin with the contributor's session headers and
retains a value-free transcript: request templates, credential header names,
response field paths with type/format classes, and tokens under status-like keys.
A model proposes which history fields carry payment details; code checks that
proposal against the live records and derives the score itself, so an arbitrary
contributor-chosen inference endpoint cannot grant a reward.
"""
import copy
import re
import time
from urllib.parse import parse_qsl, urlsplit

from .common import Rejected, canonical, fields, integer, opaque_id, require

KIND = "open-json-read-v1"
RUBRIC = "transcript-mapping-v1"
ROLE_WEIGHTS = {"paymentId": 25, "amount": 25, "timestamp": 20, "counterparty": 15, "status": 10, "currency": 5}
ROLES = tuple(ROLE_WEIGHTS)
OPEN_FAILURES = {"recipe_invalid", "credential_headers_invalid", "anonymous_access_allowed", "write_request_refused",
                 "identity_path_invalid", "history_path_invalid", "unsafe_notes", "transcript_too_large",
                 "model_output_not_json", "model_output_truncated"} | {"mapping_missing_" + role for role in ROLES}
LIMITATIONS = {"contributor_declared_identity", "no_human_identity_claim", "value_free_shapes_only",
               "no_payment_authenticity_claim", "heuristic_redaction", "model_mapping_code_verified"}
MAX_ARTIFACT_BYTES = 30000
MAX_FIELDS = 400
MAX_NOTES = 4000
MAX_ENUM_VALUES = 12

FORBIDDEN_HEADERS = frozenset({"host", "content-length", "transfer-encoding", "connection", "accept-encoding",
                               "upgrade", "te", "trailer", "expect", "keep-alive", "proxy-authorization",
                               "proxy-connection"})
HEADER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")
KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}")
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,39}")
FORMAT = re.compile(r"[a-z0-9_]+(?::[a-z0-9_]+){0,2}")
FIELD_PATH = re.compile(r"\$(?:\[\]|\.(?:\{key\}|[A-Za-z_][A-Za-z0-9_-]{0,63}))*")
ROLE_SUFFIX = re.compile(r"(?:\.[A-Za-z_][A-Za-z0-9_-]{0,63})+")
SEGMENT = re.compile(r"[A-Za-z][A-Za-z_.-]{0,39}[0-9]{0,2}[A-Za-z_.-]{0,39}")
PARAM = re.compile(r"[A-Za-z_][A-Za-z0-9_.\[\]-]{0,63}")
TYPES = {"null", "boolean", "integer", "number", "string", "object", "array"}
BODY_TYPES = {"application/json", "application/x-www-form-urlencoded"}
# A read-only POST is common on bank web apps. The recipe author is responsible for
# replaying only a history view; these words refuse the obvious state changes.
WRITE_SEGMENTS = frozenset({"transfer", "send", "pay", "create", "update", "delete", "cancel", "submit", "confirm",
                            "execute", "approve", "initiate", "schedule", "remove", "add", "edit", "modify",
                            "withdraw", "deposit", "logout", "enroll", "register"})
WRITE_OPERATION = re.compile(r"(?i)^(create|update|delete|remove|send|cancel|submit|execute|initiate|make|set|add)|mutation")
PAGINATION = {"limit", "size", "page", "pagesize", "perpage", "count", "offset", "skip", "top"}
QUERY_ENUMS = {"type", "types", "status", "state", "order", "sort", "direction", "kind", "format", "view",
               "currency", "sortby", "sortorder"}
PERSONAL_ANCESTORS = ("address", "location", "geo", "contact", "owner", "holder", "person", "customer", "user",
                      "recipient", "sender", "payer", "payee", "beneficiary", "counterparty", "merchant", "name")
ENUM_SUFFIXES = ("status", "state", "type", "kind", "currency", "scheme", "direction", "method", "rail", "network")
ISO_CURRENCIES = frozenset(
    "AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD CAD "
    "CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ "
    "GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR "
    "LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN "
    "PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SYP SZL THB TJS "
    "TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VES VND VUV WST XAF XCD XOF XPF YER ZAR ZMW ZWL".split())
ISO_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(Z|[+-]\d{2}:?\d{2})?")
UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
NOTE_FORBIDDEN = tuple(re.compile(pattern) for pattern in (
    r"\d{6,}", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", r"[A-Za-z0-9_-]{28,}",
    r"(?i)bearer\s+[A-Za-z0-9]", r"eyJ[A-Za-z0-9_-]{8,}"))


def validate_open_campaign(campaign):
    """Policy shape for a campaign whose reads come from the contributor's recipe."""
    descriptor = campaign["openSource"]
    fields(descriptor, {"version", "kind", "maxReads"})
    require(type(descriptor["version"]) is int and descriptor["version"] == 1 and descriptor["kind"] == KIND,
            "invalid_policy")
    integer(descriptor["maxReads"], 1, 8, "invalid_policy")
    require("sourceDescriptor" not in campaign and campaign["rubricVersion"] == RUBRIC
            and campaign["safeSchemaFields"] == [], "invalid_policy")
    for source in campaign["sources"]:
        require(source["paths"] == ["/"] and source["methods"] in (["GET"], ["GET", "POST"])
                and source["parameterNames"] == [] and source["headerNames"] == [], "invalid_source")
    requirements = campaign["evidenceRequirements"]
    require(requirements["historyPath"] == [] and isinstance(requirements["requiredFields"], list)
            and bool(requirements["requiredFields"])
            and len(set(requirements["requiredFields"])) == len(requirements["requiredFields"])
            and set(requirements["requiredFields"]) <= set(ROLES), "invalid_policy")
    require(sum(ROLE_WEIGHTS[role] for role in requirements["requiredFields"]) <= 100, "invalid_policy")
    return descriptor


def origin_in_domain(origin, domain_origin):
    """True when an https origin is the campaign domain or one of its subdomains."""
    host, domain = urlsplit(origin).hostname or "", urlsplit(domain_origin).hostname or ""
    return origin == "https://" + host and bool(domain) and (host == domain or host.endswith("." + domain))


def campaign_origin(campaign, origin):
    require(isinstance(origin, str) and any(origin_in_domain(origin, source["origin"])
                                             for source in campaign["sources"]), "source_not_allowed")
    return origin


def _segments(path, code):
    require(isinstance(path, list) and len(path) <= 12, code)
    for part in path:
        require(type(part) is int and 0 <= part <= 9999 or isinstance(part, str) and 1 <= len(part) <= 64, code)
    return path


def read_method(read):
    return read.get("method", "GET")


def _write_guard(read):
    """Refuse requests that name a state change. Not a proof of read-only behaviour."""
    from .common import strict_json
    require(not any(part.lower() in WRITE_SEGMENTS for part in urlsplit(read["url"]).path.split("/")),
            "write_request_refused")
    if read["contentType"] != "application/json":
        return
    try:
        body = strict_json(read["body"], maximum=16384)
    except Rejected:
        raise Rejected("recipe_invalid") from None
    for item in body if isinstance(body, list) else [body]:
        if not isinstance(item, dict):
            continue
        document, operation = item.get("query"), item.get("operationName")
        require(not (isinstance(document, str) and re.search(r"(?:^|[\s}])mutation[\s({]", document)),
                "write_request_refused")
        require(not (isinstance(operation, str) and WRITE_OPERATION.search(operation)), "write_request_refused")


def validate_open_recipe(campaign, recipe, max_reads=20):
    from .recipe import permitted_endpoint
    descriptor = validate_open_campaign(campaign)
    fields(recipe, {"version", "reads", "identity", "history"})
    require(type(recipe["version"]) is int and recipe["version"] == 3, "recipe_version")
    limit = min(max_reads, descriptor["maxReads"])
    require(isinstance(recipe["reads"], list) and 1 <= len(recipe["reads"]) <= limit, "recipe_limits")
    origins = set()
    for read in recipe["reads"]:
        require(isinstance(read, dict), "recipe_invalid")
        if "method" in read:
            # A POST the bank's own site issues to display history, replayed verbatim.
            fields(read, {"url", "method", "body", "contentType"})
            require(read["method"] == "POST" and read["contentType"] in BODY_TYPES and isinstance(read["body"], str)
                    and len(read["body"]) <= 16384 and all(32 <= ord(char) < 127 for char in read["body"]),
                    "recipe_invalid")
            _write_guard(read)
        else:
            fields(read, {"url"})
        permitted_endpoint(campaign, read["url"], read_method(read))
        origins.add("https://" + urlsplit(read["url"]).hostname)
    require(len(origins) == 1, "recipe_invalid")
    for name, code in (("identity", "identity_path_invalid"), ("history", "history_path_invalid")):
        fields(recipe[name], {"read", "path"})
        integer(recipe[name]["read"], 0, len(recipe["reads"]) - 1, code)
        _segments(recipe[name]["path"], code)
    require(len(canonical(recipe)) <= 16384, "recipe_limits")
    return recipe


def credential_headers(credential, origin):
    """Session headers sent only to the contributor-declared campaign origin."""
    fields(credential, {"origin", "kind", "value"})
    require(credential["origin"] == origin, "invalid_credential")
    if credential["kind"] == "bearer":
        value = credential["value"]
        require(isinstance(value, str) and 1 <= len(value) <= 16384 and all(33 <= ord(char) < 127 for char in value),
                "invalid_credential")
        bearer = "Bearer " + value
        return {"Authorization": bearer}
    require(credential["kind"] == "headers" and isinstance(credential["value"], dict)
            and 1 <= len(credential["value"]) <= 24, "credential_headers_invalid")
    headers, seen, total = {}, set(), 0
    for name, value in credential["value"].items():
        require(isinstance(name, str) and HEADER_NAME.fullmatch(name) and name.lower() not in FORBIDDEN_HEADERS
                and name.lower() not in seen, "credential_headers_invalid")
        require(isinstance(value, str) and 1 <= len(value) <= 8192 and all(32 <= ord(char) < 127 for char in value),
                "credential_headers_invalid")
        seen.add(name.lower())
        total += len(name) + len(value)
        headers[name] = value
    require(total <= 16384, "credential_headers_invalid")
    return headers


def validate_notes(notes):
    require(isinstance(notes, str) and len(notes) <= MAX_NOTES
            and all(char in "\n\t" or ord(char) >= 32 and ord(char) != 127 for char in notes), "unsafe_notes")
    require(not any(pattern.search(notes) for pattern in NOTE_FORBIDDEN), "unsafe_notes")
    return notes


def submission_context(campaign, payload):
    """Private per-job inputs that shape the transcript; never part of durable state."""
    descriptor = validate_open_campaign(campaign)
    recipe = validate_open_recipe(campaign, payload["recipe"], descriptor["maxReads"])
    require(payload["profileId"] is None and payload["transcript"] == [], "invalid_submission")
    origin = "https://" + urlsplit(recipe["reads"][0]["url"]).hostname
    names = sorted(name.lower() for name in credential_headers(payload["credential"], origin))
    return {"recipe": copy.deepcopy(recipe), "notes": validate_notes(payload["notes"]), "headerNames": names}


def select(body, path):
    for part in path:
        if type(part) is int:
            body = body[part] if isinstance(body, list) and part < len(body) else None
        else:
            body = body.get(part) if isinstance(body, dict) else None
    return body


class OpenBankClient:
    def __init__(self, campaign, credential, transport=None, *, profile_id=None, max_reads=20, timeout=45):
        from .policy import validate_campaign
        from .transport import HTTPTransport
        validate_campaign(campaign)
        self.descriptor = validate_open_campaign(campaign)
        require(profile_id is None, "invalid_profile")
        require(isinstance(credential, dict) and isinstance(credential.get("origin"), str) and any(
            origin_in_domain(credential["origin"], source["origin"]) for source in campaign["sources"]),
            "invalid_credential")
        self.headers = credential_headers(credential, credential["origin"])
        self.origin = credential["origin"]
        self.campaign = copy.deepcopy(campaign)
        self.transport = transport or HTTPTransport()
        self.max_reads = integer(max_reads, 1, 20, "recipe_limits")
        require(type(timeout) in (int, float) and 0 < timeout <= 300, "request_timeout")
        self.timeout = timeout

    def acquire(self, job_id, recipe, now):
        from .recipe import LiveRead
        from .transport import HTTPResponse, json_response
        opaque_id(job_id)
        integer(now, 0, 2**63 - 1)
        require(bool(self.headers), "invalid_credential")
        validate_open_recipe(self.campaign, recipe, self.max_reads)
        specs = recipe["reads"]
        urls = [read["url"] for read in specs]
        require(all(url.startswith(self.origin + "/") for url in urls), "source_not_allowed")
        deadline = time.monotonic() + self.timeout

        def remaining():
            value = deadline - time.monotonic()
            require(value > 0, "request_timeout")
            return value

        # The identity and history reads must not be served to an anonymous caller.
        for index in sorted({recipe["identity"]["read"], recipe["history"]["read"]}):
            probe = self.transport.probe_anonymous(urls[index], timeout=remaining(), body=specs[index].get("body"),
                                                   content_type=specs[index].get("contentType"))
            require(type(probe) is HTTPResponse and probe.tls_verified is True and probe.body == b"",
                    "unauthenticated_source")
            require(not (200 <= probe.status < 300 and probe.headers == (("content-type", "json"),)),
                    "anonymous_access_allowed")
        headers = dict(self.headers)
        if not any(name.lower() == "accept" for name in headers):
            headers["Accept"] = "application/json"
        bodies = []
        for spec in specs:
            try:
                response = self.transport.request_bank(spec["url"], headers=headers, timeout=remaining(),
                                                       max_bytes=2_000_000, open_headers=True, body=spec.get("body"),
                                                       content_type=spec.get("contentType"))
                body = json_response(response)
            except Rejected as error:
                if str(error) in {"response_not_json", "response_invalid_json"}:
                    raise Rejected("bank_response_non_json") from None
                raise
            bodies.append(body)
        identity = select(bodies[recipe["identity"]["read"]], recipe["identity"]["path"])
        require(type(identity) is int and identity >= 100 or isinstance(identity, str) and 3 <= len(identity) <= 200
                and not any(ord(char) < 33 for char in identity), "identity_path_invalid")
        rows = select(bodies[recipe["history"]["read"]], recipe["history"]["path"])
        require(isinstance(rows, list) and len(rows) <= 2000, "history_path_invalid")
        require(sum(isinstance(row, dict) and bool(row) for row in rows)
                >= self.campaign["evidenceRequirements"]["minRecords"], "insufficient_history")
        account = "open:" + self.origin + ":" + str(identity)
        return [LiveRead(job_id, spec["url"], read_method(spec), 200, body, account, now, True, True, (), True)
                for spec, body in zip(specs, bodies)]

    def close(self):
        self.headers.clear()


def _normal(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _enum_key(name, ancestors):
    normal = _normal(name)
    if not normal.endswith(ENUM_SUFFIXES):
        return False
    return not any(word in _normal(part) for part in ancestors for word in PERSONAL_ANCESTORS)


def _type(value):
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    require(isinstance(value, list), "unsafe_artifact")
    return "array"


def _sign(number):
    return "zero" if number == 0 else "pos" if number > 0 else "neg"


def _epoch(number):
    if 946684800 <= number <= 4102444800:
        return "epoch_s"
    if 946684800000 <= number <= 4102444800000:
        return "epoch_ms"
    return None


TIME_KEY = re.compile(r"(time|date|created|updated|timestamp|settled|completed|posted|expires|when|at|ts)$")


def value_format(value, name=""):
    """Closed-vocabulary description of one scalar. Never returns the value.

    Bare integers are called epoch times only under a time-like key; nine and ten
    digit identifiers fall in the same numeric range.
    """
    timed = TIME_KEY.search(_normal(name)) is not None
    if value is None or type(value) is bool:
        return None
    if type(value) is int:
        return "int:" + (timed and _epoch(value) or _sign(value) + ":" + str(min(len(str(abs(value))), 20)))
    if type(value) is float:
        text = repr(abs(value))
        fraction = len(text.split(".")[1]) if "." in text and "e" not in text else 0
        return "float:" + _sign(value) + ":" + str(min(fraction, 9))
    text = value.strip()
    if not text:
        return "empty"
    match = ISO_DATETIME.fullmatch(text)
    if match:
        return "datetime:iso8601:" + ("utc" if match.group(1) == "Z" else "offset" if match.group(1) else "naive")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return "date:iso8601"
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", text):
        return "date:slash"
    if UUID.fullmatch(text):
        return "uuid"
    if text.isascii() and text.isdigit():
        return "digits:" + (timed and _epoch(int(text)) or str(min(len(text), 20)))
    if re.fullmatch(r"-\d{1,18}", text):
        return "digits:neg:" + str(len(text) - 1)
    match = re.fullmatch(r"(-?)\d{1,18}\.(\d{1,9})", text)
    if match:
        return "decimal:" + ("neg" if match.group(1) else "pos") + ":" + str(len(match.group(2)))
    if text in ISO_CURRENCIES:
        return "currency_code"
    if re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}", text):
        return "email"
    if re.fullmatch(r"https?://\S{1,2000}", text):
        return "url"
    if len(text) <= 48 and re.search(r"\d", text) and (
            re.search(r"[$€£¥₹]", text) or any(code in text for code in ISO_CURRENCIES)):
        return "money_text"
    if len(text) >= 16 and re.fullmatch(r"[0-9a-fA-F]+", text):
        return "hex:" + ("short" if len(text) <= 40 else "long")
    size = "short" if len(text) <= 8 else "medium" if len(text) <= 32 else "long" if len(text) <= 128 else "xlong"
    charset = "alpha" if text.isascii() and text.isalpha() else "alnum" if text.isascii() and text.isalnum() else "mixed"
    return "text:" + size + ":" + charset


def _tainted(bodies):
    """Lower-cased scalar values seen under keys that are not status-like.

    A candidate retained token that also occurs as such a value is treated as
    personal or dynamic and is withheld.
    """
    found, count = set(), [0]

    def walk(value, name, ancestors):
        count[0] += 1
        require(count[0] <= 60000, "transcript_too_large")
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, key if isinstance(key, str) else "", ancestors + (name,))
        elif isinstance(value, list):
            for item in value:
                walk(item, name, ancestors)
        elif isinstance(value, str):
            if not _enum_key(name, ancestors) and 0 < len(value) <= 200:
                found.add(value.strip().lower())
        elif type(value) is int:
            found.add(str(value))

    for body in bodies:
        walk(body, "", ())
    return found


def _safe_key(key, tainted):
    if not isinstance(key, str) or not KEY.fullmatch(key) or re.search(r"\d{4,}", key):
        return "{key}"
    if key.lower() in tainted or len(key) >= 16 and re.fullmatch(r"[0-9a-fA-F-]+", key):
        return "{key}"
    return key


def _dynamic_map(value, tainted):
    if len(value) < 5:
        return False
    unsafe = sum(_safe_key(key, tainted) == "{key}" for key in value)
    if unsafe * 5 >= len(value) * 2:
        return True
    shapes = {frozenset(item) if isinstance(item, dict) and item else None for item in value.values()}
    return len(value) >= 6 and len(shapes) == 1 and None not in shapes


def _shapes(body, tainted):
    entries, objects, present, count = {}, {}, {}, [0]

    def walk(value, path, name, ancestors, depth):
        count[0] += 1
        require(depth <= 16 and count[0] <= 60000, "transcript_too_large")
        entry = entries.setdefault(path, {"types": set(), "formats": set(), "values": set(), "enum": False,
                                          "overflow": False})
        entry["types"].add(_type(value))
        if isinstance(value, dict):
            require(len(value) <= 1000, "transcript_too_large")
            objects[path] = objects.get(path, 0) + 1
            dynamic = _dynamic_map(value, tainted)
            seen = set()
            for key, item in value.items():
                child = "{key}" if dynamic else _safe_key(key, tainted)
                target = path + "." + child
                if target not in seen:
                    seen.add(target)
                    present[target] = present.get(target, 0) + 1
                walk(item, target, key if isinstance(key, str) else "", ancestors + (name,), depth + 1)
        elif isinstance(value, list):
            require(len(value) <= 2000, "transcript_too_large")
            for item in value:
                walk(item, path + "[]", name, ancestors, depth + 1)
        else:
            style = value_format(value, name)
            if style is not None:
                entry["formats"].add(style)
            if isinstance(value, str) and not path.endswith("{key}") and _enum_key(name, ancestors):
                entry["enum"] = True
                token = value.strip()
                if not TOKEN.fullmatch(token):
                    entry["overflow"] = True  # Free text under a status-like key: not an enum.
                elif token.lower() in tainted:
                    entry["withheld"] = True  # The same text occurs as an ordinary value elsewhere.
                else:
                    entry["values"].add(token)
                    entry["overflow"] = entry["overflow"] or len(entry["values"]) > MAX_ENUM_VALUES

    walk(body, "$", "", (), 0)
    result = {}
    for path in sorted(entries):
        entry = entries[path]
        item = {"types": sorted(entry["types"])}
        if entry["formats"]:
            item["formats"] = sorted(entry["formats"])[:8]
        if entry["enum"] and entry["values"] and not entry["overflow"]:
            item["values"] = sorted(entry["values"])
            if entry.get("withheld"):
                item["valuesIncomplete"] = True
        parent = path.rsplit(".", 1)[0] if not path.endswith("[]") else None
        if parent is not None and path != "$" and present.get(path, 0) < objects.get(parent, 0):
            item["optional"] = True
        result[path] = item
    return result


def shape_path(path, tainted):
    """Recipe selector rendered in transcript form: indexes become [] and unsafe keys {key}."""
    return "$" + "".join("[]" if type(part) is int else "." + _safe_key(part, tainted) for part in path)


def _template(url, tainted):
    parsed = urlsplit(url)
    parts = []
    for part in parsed.path.split("/")[1:]:
        keep = part == "" or SEGMENT.fullmatch(part) and part.lower() not in tainted
        parts.append(part if keep else "{id}")
    query = []
    for name, value in parse_qsl(parsed.query, keep_blank_values=True):
        normal = _normal(name)
        label = name if PARAM.fullmatch(name) and name.lower() not in tainted else "{param}"
        tokens = value.split(",")
        if label != "{param}" and normal in PAGINATION and re.fullmatch(r"\d{1,4}", value):
            shown = value
        elif (label != "{param}" and normal in QUERY_ENUMS and len(tokens) <= 6
              and all(TOKEN.fullmatch(token) and token.lower() not in tainted for token in tokens)):
            shown = value
        else:
            shown = "{" + (value_format(value) or "empty") + "}"
        query.append({"name": label, "value": shown})
    return "/" + "/".join(parts), query


def _body_shape(spec, tainted):
    """Request body as names and format classes; GraphQL operation names are kept."""
    from .common import strict_json
    if spec["contentType"] == "application/json":
        body = strict_json(spec["body"], maximum=16384)
        shapes = _shapes(body, tainted)
        for item in body if isinstance(body, list) else [body]:
            name = item.get("operationName") if isinstance(item, dict) else None
            target = ("$[]" if isinstance(body, list) else "$") + ".operationName"
            if isinstance(name, str) and TOKEN.fullmatch(name) and name.lower() not in tainted and target in shapes:
                shapes[target]["values"] = sorted(set(shapes[target].get("values", [])) | {name})[:MAX_ENUM_VALUES]
        return {"contentType": spec["contentType"], "fields": shapes}
    shapes = {}
    for name, value in parse_qsl(spec["body"], keep_blank_values=True):
        label = name if PARAM.fullmatch(name) and name.lower() not in tainted else "{param}"
        entry = shapes.setdefault("$." + label if KEY.fullmatch(label) else "$.{key}", {"types": ["string"], "formats": set()})
        entry["formats"].add(value_format(value, name) or "empty")
    for entry in shapes.values():
        entry["formats"] = sorted(entry["formats"])[:8]
    return {"contentType": spec["contentType"], "fields": {"$": {"types": ["object"]}, **shapes}}


def extract_transcript(campaign, reads, context):
    from .recipe import LiveRead, permitted_endpoint
    validate_open_campaign(campaign)
    require(isinstance(reads, list) and bool(reads) and all(type(read) is LiveRead for read in reads),
            "untrusted_evidence")
    require(isinstance(context, dict), "invalid_submission")
    fields(context, {"recipe", "notes", "headerNames"})
    recipe = context["recipe"]
    require(len(recipe["reads"]) == len(reads) and all(read.url == spec["url"] and read.method == read_method(spec)
            and read.authenticated is True and read.tls_verified is True and read.authentication_gate is True
            and read.status == 200 for read, spec in zip(reads, recipe["reads"])), "unauthenticated_source")
    tainted = _tainted([read.body for read in reads])
    identity_value = select(reads[recipe["identity"]["read"]].body, recipe["identity"]["path"])
    require(identity_value is not None, "identity_path_invalid")
    notes = validate_notes(context["notes"])
    lowered = notes.lower()
    private = {str(identity_value).lower()} | {value for value in tainted
                                               if len(value) >= 6 and re.search(r"[\d@]", value)}
    require(not any(value in lowered for value in private), "unsafe_notes")
    requests, total = [], 0
    for step, (read, spec) in enumerate(zip(reads, recipe["reads"]), 1):
        permitted_endpoint(campaign, read.url, read.method)
        path, query = _template(read.url, tainted)
        shapes = _shapes(read.body, tainted)
        total += len(shapes)
        request = {"step": step, "method": read.method, "origin": "https://" + urlsplit(read.url).hostname,
                   "path": path, "query": query,
                   "status": read.status, "fields": shapes}
        if read.method == "POST":
            request["body"] = _body_shape(spec, tainted)
            total += len(request["body"]["fields"])
        require(total <= MAX_FIELDS, "transcript_too_large")
        requests.append(request)
    selectors = {}
    for name, code in (("identity", "identity_path_invalid"), ("history", "history_path_invalid")):
        index = recipe[name]["read"]
        rendered = shape_path(recipe[name]["path"], tainted)
        require(rendered in requests[index]["fields"], code)
        selectors[name] = {"step": index + 1, "path": rendered}
    rows = select(reads[recipe["history"]["read"]].body, recipe["history"]["path"])
    require(isinstance(rows, list) and "array" in requests[recipe["history"]["read"]]["fields"]
            [selectors["history"]["path"]]["types"], "history_path_invalid")
    require(sum(isinstance(row, dict) and bool(row) for row in rows) >= campaign["evidenceRequirements"]["minRecords"],
            "insufficient_history")
    artifact = {"version": 2, "campaignId": campaign["id"], "bankId": campaign["bankId"],
                "sourceOrigins": sorted({request["origin"] for request in requests}),
                "credentialHeaders": list(context["headerNames"]), "requests": requests,
                "identity": selectors["identity"], "history": selectors["history"], "notes": notes,
                "coverage": {"readCount": len(reads), "historyMinimumSatisfied": True},
                "limitations": sorted(LIMITATIONS)}
    require(len(canonical(artifact)) <= MAX_ARTIFACT_BYTES, "transcript_too_large")
    validate_transcript(campaign, artifact)
    return artifact


def _validate_shapes(shapes, body=False):
    require(isinstance(shapes, dict) and 1 <= len(shapes) and "$" in shapes, "unsafe_artifact")
    for field_path, entry in shapes.items():
        require(isinstance(field_path, str) and len(field_path) <= 400 and FIELD_PATH.fullmatch(field_path)
                and isinstance(entry, dict) and "types" in entry
                and set(entry) <= {"types", "formats", "values", "valuesIncomplete", "optional"}, "unsafe_artifact")
        require(isinstance(entry["types"], list) and bool(entry["types"]) and set(entry["types"]) <= TYPES
                and entry["types"] == sorted(set(entry["types"])), "unsafe_artifact")
        if "formats" in entry:
            require(isinstance(entry["formats"], list) and 1 <= len(entry["formats"]) <= 8 and all(
                isinstance(style, str) and len(style) <= 40 and FORMAT.fullmatch(style)
                for style in entry["formats"]), "unsafe_artifact")
        if "values" in entry:
            name = field_path.rsplit(".", 1)[-1].replace("[]", "")
            require(isinstance(entry["values"], list) and 1 <= len(entry["values"]) <= MAX_ENUM_VALUES
                    and all(isinstance(token, str) and TOKEN.fullmatch(token) for token in entry["values"])
                    and (_enum_key(name, ()) or body and name == "operationName"), "unsafe_artifact")
        for flag in ("optional", "valuesIncomplete"):
            require(entry.get(flag, True) is True, "unsafe_artifact")
        require("valuesIncomplete" not in entry or "values" in entry, "unsafe_artifact")
    return len(shapes)


def validate_transcript(campaign, artifact):
    """Every retained string is a closed-vocabulary class, a safe name or a linted note."""
    descriptor = validate_open_campaign(campaign)
    fields(artifact, {"version", "campaignId", "bankId", "sourceOrigins", "credentialHeaders", "requests",
                      "identity", "history", "notes", "coverage", "limitations"})
    require(type(artifact["version"]) is int and artifact["version"] == 2
            and artifact["campaignId"] == campaign["id"] and artifact["bankId"] == campaign["bankId"],
            "unsafe_artifact")
    require(isinstance(artifact["sourceOrigins"], list) and len(artifact["sourceOrigins"]) == 1, "unsafe_artifact")
    try:
        campaign_origin(campaign, artifact["sourceOrigins"][0])
    except Rejected:
        raise Rejected("unsafe_artifact") from None
    names = artifact["credentialHeaders"]
    require(isinstance(names, list) and 1 <= len(names) <= 24 and names == sorted(set(names))
            and all(isinstance(name, str) and HEADER_NAME.fullmatch(name) and name == name.lower()
                    and name not in FORBIDDEN_HEADERS for name in names), "unsafe_artifact")
    requests = artifact["requests"]
    require(isinstance(requests, list) and 1 <= len(requests) <= descriptor["maxReads"], "unsafe_artifact")
    total = 0
    for index, request in enumerate(requests):
        require(isinstance(request, dict) and request.get("method") in {"GET", "POST"}, "unsafe_artifact")
        fields(request, {"step", "method", "origin", "path", "query", "status", "fields"}
               | ({"body"} if request["method"] == "POST" else set()))
        require(type(request["step"]) is int and request["step"] == index + 1
                and request["origin"] == artifact["sourceOrigins"][0] and type(request["status"]) is int
                and request["status"] == 200, "unsafe_artifact")
        if request["method"] == "POST":
            fields(request["body"], {"contentType", "fields"})
            require(request["body"]["contentType"] in BODY_TYPES, "unsafe_artifact")
            total += _validate_shapes(request["body"]["fields"], body=True)
        path = request["path"]
        require(isinstance(path, str) and len(path) <= 600 and path.startswith("/") and all(
            part in ("", "{id}") or SEGMENT.fullmatch(part) for part in path.split("/")[1:]), "unsafe_artifact")
        require(isinstance(request["query"], list) and len(request["query"]) <= 30, "unsafe_artifact")
        for parameter in request["query"]:
            fields(parameter, {"name", "value"})
            name, value = parameter["name"], parameter["value"]
            require(isinstance(name, str) and (name == "{param}" or PARAM.fullmatch(name)), "unsafe_artifact")
            require(isinstance(value, str) and len(value) <= 300, "unsafe_artifact")
            if value.startswith("{"):
                require(value.endswith("}") and FORMAT.fullmatch(value[1:-1]), "unsafe_artifact")
            elif _normal(name) in PAGINATION:
                require(re.fullmatch(r"\d{1,4}", value), "unsafe_artifact")
            else:
                require(_normal(name) in QUERY_ENUMS and all(TOKEN.fullmatch(token) for token in value.split(",")),
                        "unsafe_artifact")
        total += _validate_shapes(request["fields"])
    require(total <= MAX_FIELDS, "unsafe_artifact")
    for name in ("identity", "history"):
        fields(artifact[name], {"step", "path"})
        integer(artifact[name]["step"], 1, len(requests), "unsafe_artifact")
        require(artifact[name]["path"] in requests[artifact[name]["step"] - 1]["fields"], "unsafe_artifact")
    require("array" in requests[artifact["history"]["step"] - 1]["fields"][artifact["history"]["path"]]["types"],
            "unsafe_artifact")
    try:
        validate_notes(artifact["notes"])
    except Rejected:
        raise Rejected("unsafe_artifact") from None
    fields(artifact["coverage"], {"readCount", "historyMinimumSatisfied"})
    require(type(artifact["coverage"]["readCount"]) is int and artifact["coverage"]["readCount"] == len(requests)
            and artifact["coverage"]["historyMinimumSatisfied"] is True, "unsafe_artifact")
    require(isinstance(artifact["limitations"], list) and artifact["limitations"] == sorted(LIMITATIONS),
            "unsafe_artifact")
    require(len(canonical(artifact)) <= MAX_ARTIFACT_BYTES, "unsafe_artifact")
    return artifact


def parse_proposal(content):
    """Lenient extraction of the single JSON object a chat model returned."""
    from .common import strict_json
    require(isinstance(content, str) and len(content) <= 65536, "model_output_not_json")
    start, end = content.find("{"), content.rfind("}")
    require(0 <= start < end, "model_output_not_json")
    try:
        value = strict_json(content[start:end + 1], maximum=65536)
    except Rejected:
        raise Rejected("model_output_not_json") from None
    require(isinstance(value, dict) and isinstance(value.get("mapping"), dict), "model_result_invalid")
    mapping = {}
    for role in ROLES:
        path = value["mapping"].get(role)
        if isinstance(path, str) and len(path) <= 400:
            mapping[role] = path
    completed = value.get("completedStatus")
    completed = [token for token in completed if isinstance(token, str) and TOKEN.fullmatch(token)][:6] \
        if isinstance(completed, list) else []
    return {"mapping": mapping, "completedStatus": sorted(set(completed))}


def _numeric(value):
    if type(value) in (int, float):
        return True
    return isinstance(value, str) and (re.fullmatch(r"-?\d{1,18}(?:\.\d{1,9})?", value.strip()) is not None
                                       or value_format(value) == "money_text")


def _timestamp(value):
    if type(value) is int:
        return _epoch(value) is not None
    if not isinstance(value, str):
        return False
    return (value_format(value) or "").split(":")[0] in {"datetime", "date"} or (
        value.isascii() and value.isdigit() and _epoch(int(value)) is not None)


def _scalar(value):
    return type(value) is int or isinstance(value, str) and 0 < len(value.strip()) <= 300


CHECKS = {
    "paymentId": (0.9, _scalar),
    "amount": (0.9, _numeric),
    "timestamp": (0.9, _timestamp),
    "counterparty": (0.5, _scalar),
    "currency": (0.9, lambda value: isinstance(value, str) and value.strip() in ISO_CURRENCIES),
    "status": (0.9, lambda value: isinstance(value, str) and TOKEN.fullmatch(value.strip()) is not None),
}


def _verify(role, rows, suffix):
    keys = suffix[1:].split(".")
    values = [value for value in (select(row, keys) for row in rows) if value is not None and value != ""]
    coverage, check = CHECKS[role]
    if not values or len(values) < coverage * len(rows) or not all(check(value) for value in values):
        return False
    distinct = len({str(value) for value in values})
    if role == "paymentId":
        return distinct == len(values)
    if role == "status":
        return distinct <= MAX_ENUM_VALUES
    return True


def assess(campaign, reads, context, artifact, proposal):
    """Score a proposed role mapping against the private live history rows."""
    validate_open_campaign(campaign)
    fields(proposal, {"mapping", "completedStatus"})
    recipe = context["recipe"]
    rows = select(reads[recipe["history"]["read"]].body, recipe["history"]["path"])
    require(isinstance(rows, list), "history_path_invalid")
    rows = [row for row in rows if isinstance(row, dict) and row]
    require(len(rows) >= campaign["evidenceRequirements"]["minRecords"], "insufficient_history")
    history = artifact["history"]
    shapes = artifact["requests"][history["step"] - 1]["fields"]
    prefix = history["path"] + "[]"
    mapping, unverified, used = {}, [], set()
    for role in ROLES:
        path = proposal["mapping"].get(role)
        if path is None:
            continue
        suffix = path[len(prefix):] if isinstance(path, str) and path.startswith(prefix) else ""
        if path not in used and path in shapes and ROLE_SUFFIX.fullmatch(suffix) and _verify(role, rows, suffix):
            mapping[role] = path
            used.add(path)
        else:
            unverified.append(role)
    allowed = set(shapes[mapping["status"]].get("values", [])) if "status" in mapping else set()
    completed = sorted(set(proposal["completedStatus"]) & allowed)[:6]
    score = sum(ROLE_WEIGHTS[role] for role in mapping)
    requirements = campaign["evidenceRequirements"]
    useful = all(role in mapping for role in requirements["requiredFields"]) and score >= requirements["minScore"]
    return {"rubricVersion": RUBRIC, "score": score, "useful": useful, "mapping": mapping,
            "unverified": unverified, "completedStatus": completed}


def validate_model_result(campaign, artifact, result):
    """Structural check of the code-derived assessment stored beside a transcript."""
    fields(result, {"rubricVersion", "score", "useful", "mapping", "unverified", "completedStatus"})
    require(result["rubricVersion"] == RUBRIC and type(result["useful"]) is bool, "model_result_invalid")
    integer(result["score"], 0, 100, "model_result_invalid")
    history = artifact["history"]
    shapes = artifact["requests"][history["step"] - 1]["fields"]
    prefix = history["path"] + "[]"
    require(isinstance(result["mapping"], dict) and set(result["mapping"]) <= set(ROLES)
            and len(set(result["mapping"].values())) == len(result["mapping"]), "model_result_invalid")
    for path in result["mapping"].values():
        require(isinstance(path, str) and path.startswith(prefix) and ROLE_SUFFIX.fullmatch(path[len(prefix):])
                and path in shapes, "model_result_invalid")
    require(result["score"] == sum(ROLE_WEIGHTS[role] for role in result["mapping"]), "model_result_invalid")
    require(isinstance(result["unverified"], list) and set(result["unverified"]) <= set(ROLES) - set(result["mapping"])
            and len(set(result["unverified"])) == len(result["unverified"]), "model_result_invalid")
    allowed = set(shapes[result["mapping"]["status"]].get("values", [])) if "status" in result["mapping"] else set()
    require(isinstance(result["completedStatus"], list) and len(result["completedStatus"]) <= 6
            and result["completedStatus"] == sorted(set(result["completedStatus"]))
            and set(result["completedStatus"]) <= allowed, "model_result_invalid")
    requirements = campaign["evidenceRequirements"]
    require(result["useful"] == (all(role in result["mapping"] for role in requirements["requiredFields"])
                                 and result["score"] >= requirements["minScore"]), "model_result_invalid")
    return result


def check_assessment(campaign, reads, context, artifact, result):
    """Recompute at acceptance: a stored assessment must equal what the records support."""
    validate_model_result(campaign, artifact, result)
    expected = assess(campaign, reads, context, artifact, {"mapping": dict(result["mapping"]),
                                                           "completedStatus": list(result["completedStatus"])})
    require({**expected, "unverified": result["unverified"]} == result, "model_result_invalid")
    if not result["useful"]:
        missing = [role for role in campaign["evidenceRequirements"]["requiredFields"] if role not in result["mapping"]]
        raise Rejected("mapping_missing_" + missing[0] if missing else "model_rejected")
    return result
