"""Contributor-authored read-only recipes for banks without a reviewed adapter.

The contributor's local agent chooses the requests. The enclave replays them on a
host under the campaign's bank domain with the contributor's session headers and
retains a value-free transcript: request templates, credential header names,
response field paths with type/format classes, and status tokens seen in the
history rows. A model proposes which history fields carry payment details; code
checks that proposal against the live records and derives the score itself, so an
arbitrary contributor-chosen inference endpoint cannot grant a reward.

Redaction here is a set of conservative heuristics, not a proof. Anything added
to the transcript must also be accepted by validate_transcript, which applies the
same static screens to a stored or received artifact.
"""
import copy
import json
import re
import time
import unicodedata
from urllib.parse import parse_qsl, urlsplit

from .common import Rejected, canonical, fields, integer, opaque_id, require, strict_json

KIND = "open-json-read-v1"
RUBRIC = "transcript-mapping-v1"
ROLE_WEIGHTS = {"paymentId": 25, "amount": 25, "timestamp": 20, "counterparty": 15, "status": 10, "currency": 5}
ROLES = tuple(ROLE_WEIGHTS)
OPEN_FAILURES = {"recipe_invalid", "credential_headers_invalid", "credential_not_secret", "anonymous_access_allowed",
                 "write_request_refused", "identity_path_invalid", "history_path_invalid", "unsafe_notes",
                 "transcript_too_large", "model_output_not_json", "model_output_truncated"} | {
                     "mapping_missing_" + role for role in ROLES}
LIMITATIONS = {"contributor_declared_identity", "no_human_identity_claim", "value_free_shapes_only",
               "no_payment_authenticity_claim", "heuristic_redaction", "model_mapping_code_verified"}
MAX_ARTIFACT_BYTES = 30000
MAX_FIELDS = 400
MAX_NOTES = 4000
MAX_ENUM_VALUES = 12
MAX_PAYMENT_ALIASES = 24

FORBIDDEN_HEADERS = frozenset({"host", "content-length", "content-type", "transfer-encoding", "connection",
                               "accept-encoding", "upgrade", "te", "trailer", "expect", "keep-alive",
                               "proxy-authorization", "proxy-connection", "x-http-method-override", "x-http-method",
                               "x-method-override"})
# Headers every browser sends. A credential needs at least one header outside this
# set, and the anonymous probe replays the request with only these.
PUBLIC_HEADERS = frozenset({"accept", "accept-language", "user-agent", "origin", "referer", "x-requested-with",
                            "cache-control", "pragma", "dnt", "priority", "sec-fetch-dest", "sec-fetch-mode",
                            "sec-fetch-site", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"})
HEADER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")
HOSTNAME = re.compile(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
TEST_HOST = re.compile(r"sandbox|staging|nonprod|preprod|playground|devportal|(?:^|[.-])(?:test|testing|dev|develop|"
                       r"developer|developers|stage|stg|uat|demo|docs|mock|qa|sit|beta|preview)[0-9]{0,2}(?:[.-]|$)")
# Host labels kept verbatim in a transcript; any other label under the bank
# domain may be a tenant or customer name and is shown as {sub}.
INFRA_LABEL = re.compile(r"(?:www|api|apis|app|apps|secure|online|web|m|mobile|my|login|auth|id|account|accounts|"
                         r"bank|banking|ib|ibank|ebank|ebanking|digital|connect|gateway|gw|services|service|client|"
                         r"clients|portal|pay|payments|wallet|open|openapi|public|edge|prod|production|global|"
                         r"personal|business|retail|internet|netbank|netbanking|home|main|core|rest|graphql|data|"
                         r"bff|mw)(?:[0-9]{1,3}[0-9a-f]{0,4})?")
KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,47}")
TOKEN = re.compile(r"[A-Za-z](?:[A-Za-z_.-]|[0-9](?![0-9])){0,39}")
# What a status field may hold when checking the role; wider than what is retained.
STATUS_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,39}")
FORMAT = re.compile(r"[a-z0-9_]+(?::[a-z0-9_]+){0,2}")
FIELD_PATH = re.compile(r"\$(?:\[\]|\.(?:\{key\}|[A-Za-z_][A-Za-z0-9_-]{0,47}))*")
ROLE_SUFFIX = re.compile(r"(?:\.[A-Za-z_][A-Za-z0-9_-]{0,47})+")
PARAM = re.compile(r"[A-Za-z_$][A-Za-z0-9_.$\[\]-]{0,63}")
SEGMENT_EXTENSIONS = {"json", "do", "action", "aspx", "php", "html", "jsp", "xml"}
TYPES = {"null", "boolean", "integer", "number", "string", "object", "array"}
BODY_TYPES = {"application/json", "application/x-www-form-urlencoded"}
# A read-only POST is common on bank web apps. The recipe author is responsible for
# replaying only a history view; these rules refuse the recognisable state changes.
WRITE_VERBS = frozenset({"send", "pay", "create", "update", "delete", "cancel", "submit", "confirm", "execute",
                         "approve", "initiate", "schedule", "remove", "add", "edit", "modify", "withdraw", "deposit",
                         "logout", "enroll", "register", "set", "make", "move", "capture", "freeze", "unfreeze",
                         "lock", "unlock", "block", "activate", "deactivate", "refund", "void", "reverse", "dispute",
                         "reset", "accept", "reject", "decline", "sign", "authorize", "link", "unlink", "revoke"})
WRITE_NOUNS = frozenset({"transfer", "payment", "payout", "order", "withdrawal", "now", "new", "beneficiary",
                         "payee", "recipient", "contact", "mandate"})
READ_WORDS = frozenset({"history", "list", "activity", "activities", "search", "recent", "latest", "summary",
                        "details", "detail", "statement", "statements", "export", "transactions", "entries",
                        "records", "feed", "query", "lookup", "view", "get", "fetch", "read", "find", "inquiry",
                        "enquiry"})
PAGINATION = {"limit", "size", "page", "pagesize", "perpage", "count", "offset", "skip", "top"}
QUERY_ENUMS = {"type", "types", "status", "order", "sort", "direction", "kind", "format", "currency", "sortby",
               "sortorder"}
SELECTOR_KEYS = {"sortby", "orderby", "sort", "order", "sortfield", "sortkey", "orderfield", "field", "fields",
                 "groupby", "column", "columns", "include", "expand", "select"}
PERSONAL_WORDS = frozenset({"address", "location", "geo", "contact", "owner", "holder", "person", "customer", "user",
                            "recipient", "sender", "payer", "payee", "beneficiary", "counterparty", "merchant",
                            "name", "billing", "shipping", "profile", "identity"})
GENERIC_TAIL = frozenset({"info", "details", "detail", "data", "object", "record", "dto", "model", "summary"})
_ENUM_PREFIX = (r"(?:transaction|txn|tx|payment|transfer|order|record|entry|activity|item|operation|posting|booking|"
                r"settlement|clearing|verbose|ux|display|detail|sub|original|base|quote|debit|credit|fee|amount|"
                r"instructed|charged|processing|completion|current|final|overall|payout|payin|local|foreign|internal|"
                r"external|raw|ledger|wire|ach|card)")
# A bare "state" may be a place and a "method" may be a customer-named instrument,
# so state needs a payment prefix and method is never kept. Currency codes are safe
# under any party prefix.
ENUM_KEY = re.compile(_ENUM_PREFIX + r"*(?:status|type|kind|scheme|direction|rail|network|statuscode)|"
                      + _ENUM_PREFIX + r"+state|(?:" + _ENUM_PREFIX[3:-1] + r"|source|target|from|to)*(?:currency|currencycode)")
# After one of these the next path segment names a person, account or tenant.
PATH_WORDS = frozenset({"u", "apis", "rest", "svc", "rpc", "graphql", "odata", "secure", "public", "private", "gateway",
                        "bff", "proxy", "edge", "oauth", "oauth2", "core", "digital", "retail", "prod", "production",
                        "services", "me", "my", "open", "openapi", "sdk", "mw", "gw", "ib", "net", "portal", "banking",
                        "ebanking", "ibank", "mbank", "consumer", "customer", "customers", "members", "home", "dashboard",
                        "overview", "ajax", "json", "xml", "jsonrpc", "query", "queries", "lookup", "inquiry",
                        "enquiry", "feed", "timeline", "ledger", "movements", "operations", "payments", "p2ppayments",
                        "quickpay", "billpay", "zelle", "interac", "pix", "upi", "sepa", "wires", "cards", "loans",
                        "deposits", "investments", "rewards", "en", "us", "uk", "eu", "www", "app", "apps", "web",
                        "mobile", "ios", "android", "client", "clients", "auth", "session", "sessions", "bank"})
COLLECTIONS = frozenset({"users", "user", "u", "accounts", "account", "acct", "orgs", "org", "organizations",
                         "organization", "profiles", "profile", "customers", "customer", "members", "member",
                         "people", "person", "companies", "company", "merchants", "merchant", "cards", "card",
                         "wallets", "wallet", "clients", "client", "tenants", "tenant", "businesses", "business",
                         "contacts", "contact", "recipients", "recipient", "payees", "payee", "beneficiaries",
                         "beneficiary", "workspaces", "workspace", "teams", "team", "groups", "group", "projects",
                         "project", "spaces", "space", "stores", "store", "shops", "shop", "sites", "site",
                         "entities", "entity", "households", "household"})
FOLLOW = frozenset({"history", "list", "search", "activity", "activities", "recent", "latest", "summary", "details",
                    "detail", "statement", "statements", "export", "all", "me", "current", "self", "query",
                    "transactions", "transfers", "payments", "balances", "balance", "info", "overview"})
ISO_CURRENCIES = frozenset(
    "AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD CAD "
    "CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ "
    "GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR "
    "LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN "
    "PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SYP SZL THB TJS "
    "TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VES VND VUV WST XAF XCD XOF XPF YER ZAR ZMW ZWL".split())
ISO_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(Z|[+-]\d{2}:?\d{2})?")
DATE_TEXT = re.compile(r"\d{1,4}[./-]\d{1,2}[./-]\d{1,4}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AaPp][Mm])?)?")
COMPACT_DATE = re.compile(r"(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?:[01]\d|2[0-3])?(?:[0-5]\d){0,2}")
UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
TIME_KEY = re.compile(r"(time|date|created|updated|timestamp|settled|completed|posted|expires|when|at|ts)$")
# Matched after every Unicode currency symbol has been folded to "$".
MONEY = re.compile(r"[-+(]?\s?(?:[A-Za-z]{1,4}\.?\$?\s|[A-Za-z]{1,4}\.?\$|\$\s?)?[-+]?"
                   r"(?:0|[1-9]\d{0,2}(?:[.,'\u00a0 ]\d{3})+|[1-9]\d*)(?:[.,]\d{1,4})?"
                   r"(?:\s?[$%]|\s[A-Za-z]{1,4})?\)?")
MONTH_DATE = re.compile(r"(?i)(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2},? \d{4}"
                        r"|\d{1,2} (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,? \d{4})"
                        r"(?:,? \d{1,2}:\d{2}(?::\d{2})?(?: ?[ap]m)?)?")
DOTNET_DATE = re.compile(r"/Date\(-?\d{9,14}(?:[+-]\d{4})?\)/")
NOTE_FORBIDDEN = tuple(re.compile(pattern) for pattern in (
    r"\d{6,}", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", r"[A-Za-z0-9_-]{28,}",
    r"(?i)bearer\s+[A-Za-z0-9]", r"eyJ[A-Za-z0-9_-]{8,}", r"\d{2,}\D{1,3}\d{2,}\D{1,3}\d{2,}",
    r"(?:\d[ -]?){12,}"))
# Words that field names, path segments and enum-style query values are made of.
# A name seen only once is kept when every word in it is here; a name that recurs
# across rows is kept whatever its language.
FIELD_WORDS = frozenset("""
a access account accounts acct ach action active activity additional address aba agent alias all allowed amount
amounts api app applied approval approved asc asset at atm attachment attachments attributes auth authorization
authorized available avatar avg b2b bacs balance balances bank banking base batch beneficiary bic bill billing
birth body bonus booked booking box branch brand build bulk business buy by c can cancelled canceled cap capture
captured card cards cash cashback cashtag category categories ccy chaps channel charge charged charges check cheque
child children chip city class cleared clearing client close closed closing code codes color comment company compact
completed completion config contact contactless content conversion converted correlation cost count counter
counterparty country county created creation credit crypto csv currency current cursor customer d data date
datetime day days debit decimal default delivery deposit desc description destination detail details device
digest direction disabled discount display dispute disputed district dob document documents domain done due
e earned effective email enabled end entity entries entry epoch error errors event exchange expires expiry
external extra failed failure family fednow fee fees field fields file files final first flag floor foreign
format formatted fps fraud frequency from full fx gender given gratuity gross group groups gst guid handle has
hash held hidden high history hold holder holding holdings host hour href html iban icon id ids ifsc image in
inactive inbound incoming index info initial instant institution instructed interac internal interval invoice
is isin iso issued issuer item items journal json key kind kyc label language last lat latitude ledger leg legal
legs level limit limits line link linked links list local locale location logo lon long longitude low lng mail
main major mask masked max mcc member memo merchant message meta metadata method mid middle min minor minute
mobile mode model modified month more ms multi name net network next nickname no nonce note notes number num
object of offline offset on online only open opening operation order orders org organization origin original
other out outbound outgoing overall owner p2p page pages paid parent part parts party path payee payer payin
payload payment payments payout pending percent percentage period permission permissions phone photo pin pix
plan points pos position positions postal posted posting precision preferred prefix prev previous price primary
processing product profile promo proof properties province provider purchase purpose qty quantity quote rail
rank rate ratio raw reason receipt receipts receive received receiver recipient reconciled record records
recurring ref reference refund refunded region registered related relation release released remaining request
requested response result results reversed reward rewards risk role roles routing row rows rtp running sale
scale scheduled scheme scope scopes score second secondary security self sell send sender sent sepa seq sequence
service session settled settlement share shares short side sign signature single size sort source spei spent
split splits standard start state statement status store street sub subtotal success suffix sum summary supplier
surname swift symbol t tag tags target tax team terminal text threshold ticker tid tier time timestamp
timezone tip title to token total trace tracking trade trades trading transaction transactions transfer
transfers ts tx txn type types tz uncleared unit unix updated upi uri url used user username utc uuid v value
values vat vendor verified version view visible volume vpa wallet warning was web week weight wire withdrawal
workspace year zelle zip daily weekly monthly yearly annual hourly lifetime today yesterday recent
latest oldest newest free paid premium basic savings checking joint individual personal corporate
""".split())
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
                and source["parameterNames"] == [] and source["headerNames"] == []
                and HOSTNAME.fullmatch(source["origin"][len("https://"):]), "invalid_source")
    requirements = campaign["evidenceRequirements"]
    require(requirements["historyPath"] == [] and isinstance(requirements["requiredFields"], list)
            and bool(requirements["requiredFields"])
            and len(set(requirements["requiredFields"])) == len(requirements["requiredFields"])
            and set(requirements["requiredFields"]) <= set(ROLES), "invalid_policy")
    require(sum(ROLE_WEIGHTS[role] for role in requirements["requiredFields"]) <= 100, "invalid_policy")
    return descriptor


def origin_in_domain(origin, domain_origin):
    """True when an https origin is the campaign domain or one of its subdomains."""
    if not isinstance(origin, str) or not origin.startswith("https://"):
        return False
    host, domain = origin[len("https://"):], domain_origin[len("https://"):]
    return HOSTNAME.fullmatch(host) is not None and (host == domain or host.endswith("." + domain))


def campaign_domain(campaign, origin):
    """The campaign's pinned bank domain that an origin belongs to."""
    for source in campaign["sources"]:
        if origin_in_domain(origin, source["origin"]):
            return source["origin"]
    raise Rejected("source_not_allowed")


def public_origin(campaign, origin):
    """Origin as shown in a transcript: unfamiliar host labels become {sub}."""
    domain = campaign_domain(campaign, origin)[len("https://"):]
    host = origin[len("https://"):]
    labels = host[:-len(domain)].rstrip(".").split(".") if host != domain else []
    return "https://" + ".".join([label if INFRA_LABEL.fullmatch(label) else "{sub}" for label in labels] + [domain])


def _public_origin_ok(campaign, value):
    if not isinstance(value, str) or not value.startswith("https://") or len(value) > 300:
        return False
    host = value[len("https://"):]
    for source in campaign["sources"]:
        domain = source["origin"][len("https://"):]
        if host == domain:
            return True
        if host.endswith("." + domain):
            return all(label == "{sub}" or INFRA_LABEL.fullmatch(label)
                       for label in host[:-len(domain) - 1].split("."))
    return False


def _segments(path, code):
    require(isinstance(path, list) and len(path) <= 12, code)
    for part in path:
        require(type(part) is int and 0 <= part <= 9999 or isinstance(part, str) and 1 <= len(part) <= 64, code)
    return path


def read_method(read):
    return read.get("method", "GET")


def _words(text):
    """Lower-cased words of a path segment or operation name: sendMoney -> send, money."""
    return [word.lower() for word in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+", text)]


def _graphql_read(document):
    """True when every operation in a GraphQL document is a query."""
    text = re.sub(r'"""[\s\S]*?"""|"(?:[^"\\\n]|\\.)*"|#[^\n]*', " ", document.replace("\ufeff", " "))
    depth, operations = 0, []
    for token in re.findall(r"[{}]|[A-Za-z_][A-Za-z0-9_]*", text):
        if token == "{":
            if depth == 0 and (not operations or operations[-1] is None):
                operations.append("query")  # An anonymous selection set is a query.
            depth += 1
        elif token == "}":
            depth = max(0, depth - 1)
            if depth == 0:
                operations.append(None)
        elif depth == 0 and token in {"query", "mutation", "subscription", "fragment"}:
            if operations and operations[-1] is None:
                operations.pop()
            operations.append(token)
            operations.append(token if token == "fragment" else "open")
    kinds = {kind for kind in operations if kind not in (None, "open")}
    return bool(kinds) and kinds <= {"query", "fragment"} and "query" in kinds | ({"query"} if "fragment" in kinds else set())


def _names_write(text):
    """Words naming a state change, unless a read word such as history or list is present."""
    words = _words(text)
    if not words or any(word in READ_WORDS for word in words):
        return False
    singular = [word[:-3] + "y" if word.endswith("ies") else word.rstrip("s") for word in words]
    return any(word in WRITE_VERBS or word in WRITE_NOUNS for word in words + singular)


def _write_guard(read):
    """Refuse requests that name a state change. Not a proof of read-only behaviour."""
    parts = [part.rpartition(".")[0] or part for part in urlsplit(read["url"]).path.split("/") if part]
    # Ignore trailing identifiers and version markers: /transfer/4821 and /pay/activity/v2.
    while parts and re.fullmatch(r"[0-9a-fA-F-]{3,}|\d+|v\d{1,2}", parts[-1]):
        parts.pop()
    last = parts[-1] if parts else ""
    # The final segment names the action: /payment-history and /pay/activity/list
    # read; /payments/send, /transfer/now, /wire-transfers and /beneficiaries do not.
    require(not _names_write(last), "write_request_refused")
    if not any(word in READ_WORDS for word in _words(last)):
        require(not any(_words(part) and _words(part)[0] in WRITE_VERBS for part in parts), "write_request_refused")
    if read["contentType"] == "application/json":
        try:
            body = strict_json(read["body"], maximum=65536)
        except Rejected:
            raise Rejected("recipe_invalid") from None
        items = body if isinstance(body, list) else [body]
    else:
        items = [dict(parse_qsl(read["body"], keep_blank_values=True))]
    for item in items:
        if not isinstance(item, dict):
            continue
        document, operation, method = item.get("query"), item.get("operationName"), item.get("method")
        persisted = any(name in item for name in ("extensions", "id", "queryId", "doc_id", "documentId", "sha256Hash"))
        if isinstance(document, str) and document.strip():
            require(_graphql_read(document), "write_request_refused")
        elif persisted:
            # The document cannot be inspected; only a name that says Query is replayed.
            require(isinstance(operation, str) and operation.endswith("Query"), "write_request_refused")
        if isinstance(operation, str):
            require(re.search(r"Mutation|(?<![A-Za-z])mutation", operation) is None
                    and not (_names_write(operation) and not operation.endswith("Query")), "write_request_refused")
        if isinstance(method, str):
            # RPC-style bodies name the action in "method".
            require(not _names_write(method), "write_request_refused")


def validate_open_recipe(campaign, recipe, max_reads=20):
    from .recipe import permitted_endpoint
    descriptor = validate_open_campaign(campaign)
    fields(recipe, {"version", "reads", "identity", "history"})
    require(type(recipe["version"]) is int and recipe["version"] == 3, "recipe_version")
    limit = min(max_reads, descriptor["maxReads"])
    require(isinstance(recipe["reads"], list) and 1 <= len(recipe["reads"]) <= limit, "recipe_limits")
    origins = set()
    for read in recipe["reads"]:
        require(isinstance(read, dict) and isinstance(read.get("url"), str), "recipe_invalid")
        if "method" in read:
            # A POST the bank's own site issues to display history, replayed verbatim.
            fields(read, {"url", "method", "body", "contentType"})
            require(read["method"] == "POST" and isinstance(read["contentType"], str)
                    and read["contentType"] in BODY_TYPES and isinstance(read["body"], str)
                    and len(read["body"].encode("utf-8", "replace")) <= 16384
                    and all(char in "\t\n\r" or ord(char) >= 32 and ord(char) != 127
                            and not 0xD800 <= ord(char) <= 0xDFFF for char in read["body"]), "recipe_invalid")
        else:
            fields(read, {"url"})
        permitted_endpoint(campaign, read["url"], read_method(read))
        if "method" in read:
            _write_guard(read)
        host = urlsplit(read["url"]).hostname
        # A developer sandbox or test host under the bank's domain is not the bank.
        require(TEST_HOST.search(host) is None, "source_not_allowed")
        origins.add("https://" + host)
    require(len(origins) == 1, "recipe_invalid")
    for name, code in (("identity", "identity_path_invalid"), ("history", "history_path_invalid")):
        fields(recipe[name], {"read", "path"})
        integer(recipe[name]["read"], 0, len(recipe["reads"]) - 1, code)
        _segments(recipe[name]["path"], code)
    require(len(canonical(recipe)) <= 131072, "recipe_limits")
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
                and name.lower() not in seen and re.search(r"\d{3,}", name) is None, "credential_headers_invalid")
        require(isinstance(value, str) and 1 <= len(value) <= 8192 and all(32 <= ord(char) < 127 for char in value),
                "credential_headers_invalid")
        seen.add(name.lower())
        total += len(name) + len(value)
        headers[name] = value
    require(total <= 16384, "credential_headers_invalid")
    # Something beyond what every browser sends must carry the session.
    require(any(name.lower() not in PUBLIC_HEADERS for name in headers), "credential_not_secret")
    return headers


def _alnum(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


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


def _identity_ok(value):
    return type(value) is int and value >= 100 or isinstance(value, str) and 3 <= len(value) <= 200 and not any(
        ord(char) < 33 for char in value)


def _has_rows(value, minimum=1):
    return isinstance(value, list) and sum(isinstance(row, dict) and bool(row) for row in value) >= minimum


class OpenBankClient:
    def __init__(self, campaign, credential, transport=None, *, profile_id=None, max_reads=20, timeout=45):
        from .policy import validate_campaign
        from .transport import HTTPTransport
        validate_campaign(campaign)
        self.descriptor = validate_open_campaign(campaign)
        require(profile_id is None, "invalid_profile")
        require(isinstance(credential, dict) and any(origin_in_domain(credential.get("origin"), source["origin"])
                                                     for source in campaign["sources"]), "invalid_credential")
        self.headers = credential_headers(credential, credential["origin"])
        self.origin = credential["origin"]
        self.campaign = copy.deepcopy(campaign)
        self.domain = campaign_domain(campaign, self.origin)
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
        require(all(spec["url"].startswith(self.origin + "/") for spec in specs), "source_not_allowed")
        deadline = time.monotonic() + self.timeout

        def remaining():
            value = deadline - time.monotonic()
            require(value > 0, "request_timeout")
            return value

        # Replay the identity and history reads with only the headers any browser
        # sends. Whatever answers must not contain the selected identity or history rows.
        public = {name: value for name, value in self.headers.items() if name.lower() in PUBLIC_HEADERS}
        if not any(name.lower() == "accept" for name in public):
            public["Accept"] = "application/json"
        gated = {recipe["identity"]["read"], recipe["history"]["read"]}
        for index in sorted(gated):
            probe = self.transport.probe_anonymous(specs[index]["url"], headers=public, timeout=remaining(),
                                                   body=specs[index].get("body"),
                                                   content_type=specs[index].get("contentType"))
            require(type(probe) is HTTPResponse and probe.tls_verified is True, "unauthenticated_source")
            if 200 <= probe.status < 300 and probe.body:
                try:
                    anonymous = strict_json(probe.body, maximum=2_000_000)
                except Rejected:
                    continue
                require(not (index == recipe["identity"]["read"]
                             and _identity_ok(select(anonymous, recipe["identity"]["path"])))
                        and not (index == recipe["history"]["read"]
                                 and _has_rows(select(anonymous, recipe["history"]["path"]))),
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
                require(type(response) is HTTPResponse and response.status == 200, "bank_http_unexpected_status")
                body = json_response(response)
            except Rejected as error:
                if str(error) in {"response_not_json", "response_invalid_json"}:
                    raise Rejected("bank_response_non_json") from None
                raise
            bodies.append(body)
        identity = select(bodies[recipe["identity"]["read"]], recipe["identity"]["path"])
        require(_identity_ok(identity), "identity_path_invalid")
        rows = select(bodies[recipe["history"]["read"]], recipe["history"]["path"])
        require(isinstance(rows, list) and len(rows) <= 2000, "history_path_invalid")
        require(_has_rows(rows, self.campaign["evidenceRequirements"]["minRecords"]), "insufficient_history")
        # Keyed on the bank domain so another host of the same bank cannot split one account.
        account = "open:" + self.domain + ":" + str(identity)
        return [LiveRead(job_id, spec["url"], read_method(spec), 200, body, account, now, True, True, (), index in gated)
                for index, (spec, body) in enumerate(zip(specs, bodies))]

    def close(self):
        self.headers.clear()


def _normal(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _random_like(text):
    """Dense lower-to-upper switches mark an opaque identifier, not camelCase."""
    switches = sum(1 for before, after in zip(text, text[1:]) if before.islower() and after.isupper())
    return len(text) >= 8 and switches * 4 > len(text)


def _digits_ok(text):
    # A single digit between letters (p2p, oauth2) or up to two at the end.
    return re.search(r"\d{3,}", text) is None and re.search(r"\d{2,}(?!$)", text) is None


def _known(text, extra=frozenset()):
    """Every word of a name is a common field-name word (singular or plural)."""
    if _alnum(text) in FIELD_WORDS:
        return True

    def common(word):
        forms = (word, word[:-1] if word.endswith("s") else word, word[:-3] + "y" if word.endswith("ies") else word)
        return any(form in FIELD_WORDS or form in extra for form in forms) or word.isdigit() and len(word) <= 2

    words = _words(text)
    return bool(words) and all(common(word) for word in words)


def _key_ok(key):
    """Static screen for a retained field name; shared with the validator."""
    return (isinstance(key, str) and KEY.fullmatch(key) is not None and re.search(r"\d{5,}", key) is None
            and not (len(key) >= 16 and re.fullmatch(r"[0-9a-fA-F]+", key)))


def _segment_ok(part):
    """Static screen for a retained URL path segment; shared with the validator."""
    base, dot, extension = part.rpartition(".")
    if dot:
        if extension.lower() not in SEGMENT_EXTENSIONS:
            return False
        part = base
    # A path word outside the vocabulary may be a handle or a tenant slug.
    return (re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,47}", part) is not None and _digits_ok(part)
            and not _random_like(part) and _known(part, PATH_WORDS))


def _param_ok(name):
    return isinstance(name, str) and PARAM.fullmatch(name) is not None and _digits_ok(name)


def _personal(name):
    words = [word for word in _words(name) if word not in GENERIC_TAIL]
    return bool(words) and words[-1] in PERSONAL_WORDS


def _enum_key(name, ancestors=()):
    if not isinstance(name, str) or ENUM_KEY.fullmatch(_normal(name)) is None:
        return False
    return not any(_personal(part) for part in ancestors if isinstance(part, str))


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
        if timed and _epoch(int(value)):
            return "float:" + _epoch(int(value))
        text = repr(abs(value))
        fraction = len(text.split(".")[1]) if "." in text and "e" not in text else 0
        return "float:" + _sign(value) + ":" + str(min(fraction, 9))
    text = value.strip()
    if not text:
        return "empty"
    if len(text) > 4096:
        return "text:xlong:mixed"
    match = ISO_DATETIME.fullmatch(text)
    if match:
        return "datetime:iso8601:" + ("utc" if match.group(1) == "Z" else "offset" if match.group(1) else "naive")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return "date:iso8601"
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", text):
        return "date:slash"
    if timed and COMPACT_DATE.fullmatch(text):
        return "date:compact"
    if DATE_TEXT.fullmatch(text) or MONTH_DATE.fullmatch(text):
        return "date:text"
    if DOTNET_DATE.fullmatch(text):
        return "date:dotnet"
    if UUID.fullmatch(text):
        return "uuid"
    if text.isascii() and text.isdigit():
        return "digits:" + (timed and len(text) <= 13 and _epoch(int(text)) or str(min(len(text), 20)))
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
    if text.startswith("+") and re.fullmatch(r"\+[\d\s().-]{7,20}", text) and 8 <= sum(c.isdigit() for c in text) <= 15:
        return "phone"
    if _money(text):
        return "money_text"
    if len(text) >= 16 and re.fullmatch(r"[0-9a-fA-F]+", text):
        return "hex:" + ("short" if len(text) <= 40 else "long")
    size = "short" if len(text) <= 8 else "medium" if len(text) <= 32 else "long" if len(text) <= 128 else "xlong"
    charset = "alpha" if text.isascii() and text.isalpha() else "alnum" if text.isascii() and text.isalnum() else "mixed"
    return "text:" + size + ":" + charset


def _money(text):
    """An amount written as text: digits with grouping, a sign and a currency mark."""
    if not 0 < len(text) <= 48 or re.search(r"\d", text) is None:
        return False
    folded = "".join("$" if unicodedata.category(char) == "Sc" else char for char in text)
    return MONEY.fullmatch(folded) is not None


def _tainted(bodies):
    """Lower-cased scalar values seen in the responses.

    A candidate retained name or token that also occurs as a response value is
    treated as personal or dynamic and withheld. Values under sort/field selector
    keys name schema fields and are skipped, as are status tokens in status keys.
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
            if not _enum_key(name, ancestors) and _normal(name) not in SELECTOR_KEYS and 0 < len(value) <= 200:
                found.add(value.strip().lower())
        elif type(value) is int:
            found.add(str(value))

    for body in bodies:
        walk(body, "", ())
    return found


class _Names:
    """Decides which object keys of one response are field names.

    A key that recurs across the objects at the same place (the rows of a list) is
    a field name in any language. A key seen once is kept only when it is made of
    common field-name words; anything else, such as a handle, an account nickname
    or an id used as a key, is rendered {key}.
    """
    def __init__(self, body, tainted):
        self.tainted, self.instances, self.seen, count = tainted, {}, {}, [0]

        def walk(value, path):
            count[0] += 1
            require(count[0] <= 60000 and len(path) <= 40, "transcript_too_large")
            if isinstance(value, dict):
                self.instances[path] = self.instances.get(path, 0) + 1
                for key, item in value.items():
                    self.seen[(path, key)] = self.seen.get((path, key), 0) + 1
                    walk(item, path + (key,))
            elif isinstance(value, list):
                for item in value:
                    walk(item, path + ("[]",))

        walk(body, ())

    def name(self, path, key):
        if not _key_ok(key):
            return "{key}"
        objects, holders = self.instances.get(path, 0), self.seen.get((path, key), 0)
        recurring = objects >= 2 and holders >= 2 and holders * 10 >= objects * 3
        if _known(key):
            return key
        return key if recurring and key.lower() not in self.tainted else "{key}"


def _shapes(body, tainted, enum_prefix=None, names=None):
    """Field paths with types and formats. Status tokens are kept only under
    enum_prefix (the history rows), never from profile or account reads."""
    names = names or _Names(body, tainted)
    entries, objects, present, count = {}, {}, {}, [0]

    def walk(value, path, raw, name, ancestors, depth):
        count[0] += 1
        require(depth <= 16 and count[0] <= 60000, "transcript_too_large")
        entry = entries.setdefault(path, {"types": set(), "formats": set(), "values": set(), "enum": False,
                                          "overflow": False, "withheld": False})
        entry["types"].add(_type(value))
        if isinstance(value, dict):
            require(len(value) <= 1000, "transcript_too_large")
            objects[path] = objects.get(path, 0) + 1
            seen = set()
            for key, item in value.items():
                target = path + "." + names.name(raw, key)
                if target not in seen:
                    seen.add(target)
                    present[target] = present.get(target, 0) + 1
                walk(item, target, raw + (key,), key if isinstance(key, str) else "", ancestors + (name,), depth + 1)
        elif isinstance(value, list):
            require(len(value) <= 2000, "transcript_too_large")
            for item in value:
                walk(item, path + "[]", raw + ("[]",), name, ancestors, depth + 1)
        else:
            style = value_format(value, name)
            if style is not None:
                entry["formats"].add(style)
            leaf = path.rsplit(".", 1)[-1].replace("[]", "")
            if (isinstance(value, str) and enum_prefix is not None and path.startswith(enum_prefix)
                    and leaf == name and _enum_key(name, ancestors)):
                entry["enum"] = True
                token = value.strip()
                if token.lower() in tainted and token not in ISO_CURRENCIES or (
                        not TOKEN.fullmatch(token) and STATUS_VALUE.fullmatch(token)):
                    # The same text is an ordinary value elsewhere, or the code
                    # carries a digit run: the list is kept without it.
                    entry["withheld"] = True
                elif not TOKEN.fullmatch(token):
                    entry["overflow"] = True  # Free text under a status-like key: not an enum.
                else:
                    entry["values"].add(token)
                    entry["overflow"] = entry["overflow"] or len(entry["values"]) > MAX_ENUM_VALUES

    walk(body, "$", (), "", (), 0)
    result = {}
    for path in sorted(entries):
        entry = entries[path]
        item = {"types": sorted(entry["types"])}
        if entry["formats"]:
            item["formats"] = sorted(entry["formats"])[:8]
        if entry["enum"] and entry["values"] and not entry["overflow"]:
            item["values"] = sorted(entry["values"])
            if entry["withheld"]:
                item["valuesIncomplete"] = True
        parent = path.rsplit(".", 1)[0] if not path.endswith("[]") else None
        if parent is not None and path != "$" and present.get(path, 0) < objects.get(parent, 0):
            item["optional"] = True
        result[path] = item
    return result


def shape_path(body, path, tainted, names=None):
    """Recipe selector rendered exactly as _shapes names it: indexes become [],
    and each key gets the name the response walk gives it."""
    names = names or _Names(body, tainted)
    rendered, raw = "$", ()
    for part in path:
        if type(part) is int:
            rendered, raw = rendered + "[]", raw + ("[]",)
        else:
            rendered, raw = rendered + "." + names.name(raw, part), raw + (part,)
    return rendered


def _template(url, tainted):
    parsed = urlsplit(url)
    parts, previous = [], ""
    for part in parsed.path.split("/")[1:]:
        lowered = part.lower()
        keep = part == "" or (_segment_ok(part) and lowered not in tainted
                              and not (previous in COLLECTIONS and lowered not in FOLLOW and lowered not in COLLECTIONS))
        parts.append(part if keep else "{id}")
        previous = lowered
    query = []
    for name, value in parse_qsl(parsed.query, keep_blank_values=True):
        normal = _normal(name)
        label = name if _param_ok(name) and name.lower() not in tainted else "{param}"
        tokens = value.split(",")
        if label != "{param}" and normal in PAGINATION and re.fullmatch(r"\d{1,4}", value):
            shown = value
        elif (label != "{param}" and normal in QUERY_ENUMS and len(tokens) <= 6
              and all(TOKEN.fullmatch(token) and _known(token) and token.lower() not in tainted for token in tokens)):
            shown = value
        else:
            shown = "{" + (value_format(value) or "empty") + "}"
        query.append({"name": label, "value": shown})
    return "/" + "/".join(parts), query


def _body_shape(spec, tainted):
    """Request body as names and format classes; only a GraphQL operation name is kept."""
    if spec["contentType"] == "application/json":
        body = strict_json(spec["body"], maximum=65536)
        shapes = _shapes(body, tainted)
        for item in body if isinstance(body, list) else [body]:
            name = item.get("operationName") if isinstance(item, dict) else None
            target = ("$[]" if isinstance(body, list) else "$") + ".operationName"
            if (isinstance(name, str) and TOKEN.fullmatch(name) and not _random_like(name)
                    and name.lower() not in tainted and target in shapes):
                shapes[target]["values"] = sorted(set(shapes[target].get("values", [])) | {name})[:MAX_ENUM_VALUES]
        return {"contentType": spec["contentType"], "fields": shapes}
    shapes = {}
    for name, value in parse_qsl(spec["body"], keep_blank_values=True):
        label = name if _key_ok(name) and _known(name) else "{key}"
        entry = shapes.setdefault("$." + label, {"types": ["string"], "formats": set()})
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
            and read.authenticated is True and read.tls_verified is True and read.status == 200
            for read, spec in zip(reads, recipe["reads"])), "unauthenticated_source")
    identity_read, history_read = recipe["identity"]["read"], recipe["history"]["read"]
    require(reads[identity_read].authentication_gate is True and reads[history_read].authentication_gate is True,
            "unauthenticated_source")
    bodies = [read.body for read in reads]
    tainted = _tainted(bodies)
    identity_value = select(bodies[identity_read], recipe["identity"]["path"])
    require(_identity_ok(identity_value), "identity_path_invalid")
    rows = select(bodies[history_read], recipe["history"]["path"])
    require(isinstance(rows, list), "history_path_invalid")
    require(_has_rows(rows, campaign["evidenceRequirements"]["minRecords"]), "insufficient_history")
    notes = validate_notes(context["notes"])
    lowered, squeezed = notes.lower(), _alnum(notes)
    words = set(re.findall(r"[a-z]+", lowered))
    require(str(identity_value).lower() not in lowered, "unsafe_notes")
    for value in tainted:
        # Identifier-like values, multi-word values such as names, and the same
        # text re-spaced or re-punctuated may not be copied into retained notes.
        if (len(value) >= 6 and re.search(r"[\d@]", value) or len(value) >= 5 and " " in value) and value in lowered:
            raise Rejected("unsafe_notes")
        if len(value) >= 8 and re.search(r"\d", value) and len(_alnum(value)) >= 8 and _alnum(value) in squeezed:
            raise Rejected("unsafe_notes")
        if len(value) >= 5 and value.isalpha() and value not in FIELD_WORDS and value in words:
            raise Rejected("unsafe_notes")
    selectors = {name: shape_path(bodies[recipe[name]["read"]], recipe[name]["path"], tainted)
                 for name in ("identity", "history")}
    requests, total = [], 0
    for step, (read, spec) in enumerate(zip(reads, recipe["reads"]), 1):
        permitted_endpoint(campaign, read.url, read.method)
        path, query = _template(read.url, tainted)
        shapes = _shapes(read.body, tainted, selectors["history"] + "[]" if step - 1 == history_read else None)
        total += len(shapes)
        request = {"step": step, "method": read.method,
                   "origin": public_origin(campaign, "https://" + urlsplit(read.url).hostname),
                   "path": path, "query": query, "status": read.status, "gated": read.authentication_gate is True,
                   "fields": shapes}
        if read.method == "POST":
            request["body"] = _body_shape(spec, tainted)
            total += len(request["body"]["fields"])
        require(total <= MAX_FIELDS, "transcript_too_large")
        requests.append(request)
    for name, code in (("identity", "identity_path_invalid"), ("history", "history_path_invalid")):
        require(selectors[name] in requests[recipe[name]["read"]]["fields"], code)
    require("array" in requests[history_read]["fields"][selectors["history"]]["types"], "history_path_invalid")
    artifact = {"version": 2, "campaignId": campaign["id"], "bankId": campaign["bankId"],
                "sourceOrigins": sorted({request["origin"] for request in requests}),
                "credentialHeaders": list(context["headerNames"]), "requests": requests,
                "identity": {"step": identity_read + 1, "path": selectors["identity"]},
                "history": {"step": history_read + 1, "path": selectors["history"]}, "notes": notes,
                "coverage": {"readCount": len(reads), "historyMinimumSatisfied": True},
                "limitations": sorted(LIMITATIONS)}
    require(len(canonical(artifact)) <= MAX_ARTIFACT_BYTES, "transcript_too_large")
    validate_transcript(campaign, artifact)
    return artifact


def _validate_shapes(shapes, *, enum_prefix=None, body=False):
    require(isinstance(shapes, dict) and 1 <= len(shapes) and "$" in shapes, "unsafe_artifact")
    for field_path, entry in shapes.items():
        require(isinstance(field_path, str) and len(field_path) <= 400 and FIELD_PATH.fullmatch(field_path)
                and all(part == "{key}" or _key_ok(part) for part in field_path.replace("[]", "").split(".")[1:])
                and isinstance(entry, dict) and "types" in entry
                and set(entry) <= {"types", "formats", "values", "valuesIncomplete", "optional"}, "unsafe_artifact")
        require(isinstance(entry["types"], list) and bool(entry["types"])
                and all(isinstance(kind, str) for kind in entry["types"]) and set(entry["types"]) <= TYPES
                and entry["types"] == sorted(set(entry["types"])), "unsafe_artifact")
        if "formats" in entry:
            require(isinstance(entry["formats"], list) and 1 <= len(entry["formats"]) <= 8 and all(
                isinstance(style, str) and len(style) <= 40 and FORMAT.fullmatch(style)
                for style in entry["formats"]), "unsafe_artifact")
        if "values" in entry:
            parts = field_path.replace("[]", "").split(".")[1:]
            require(isinstance(entry["values"], list) and 1 <= len(entry["values"]) <= MAX_ENUM_VALUES
                    and all(isinstance(token, str) and TOKEN.fullmatch(token) for token in entry["values"])
                    and entry["values"] == sorted(set(entry["values"])) and bool(parts), "unsafe_artifact")
            if body:
                require(parts[-1] == "operationName", "unsafe_artifact")
            else:
                # Tokens exist only on status-like fields of the history rows.
                require(enum_prefix is not None and field_path.startswith(enum_prefix)
                        and _enum_key(parts[-1], tuple(parts[:-1])), "unsafe_artifact")
        for flag in ("optional", "valuesIncomplete"):
            require(entry.get(flag, True) is True, "unsafe_artifact")
        require("valuesIncomplete" not in entry or "values" in entry, "unsafe_artifact")
    return len(shapes)


def validate_transcript(campaign, artifact):
    """Every retained string is a closed-vocabulary class, a screened name or a linted note."""
    descriptor = validate_open_campaign(campaign)
    fields(artifact, {"version", "campaignId", "bankId", "sourceOrigins", "credentialHeaders", "requests",
                      "identity", "history", "notes", "coverage", "limitations"})
    require(type(artifact["version"]) is int and artifact["version"] == 2
            and artifact["campaignId"] == campaign["id"] and artifact["bankId"] == campaign["bankId"],
            "unsafe_artifact")
    require(isinstance(artifact["sourceOrigins"], list) and len(artifact["sourceOrigins"]) == 1
            and _public_origin_ok(campaign, artifact["sourceOrigins"][0]), "unsafe_artifact")
    names = artifact["credentialHeaders"]
    require(isinstance(names, list) and 1 <= len(names) <= 24
            and all(isinstance(name, str) and HEADER_NAME.fullmatch(name) and name == name.lower()
                    and name not in FORBIDDEN_HEADERS and re.search(r"\d{3,}", name) is None for name in names)
            and names == sorted(set(names)) and any(name not in PUBLIC_HEADERS for name in names), "unsafe_artifact")
    requests = artifact["requests"]
    require(isinstance(requests, list) and 1 <= len(requests) <= descriptor["maxReads"], "unsafe_artifact")
    for name in ("identity", "history"):
        fields(artifact[name], {"step", "path"})
        integer(artifact[name]["step"], 1, len(requests), "unsafe_artifact")
        require(isinstance(artifact[name]["path"], str), "unsafe_artifact")
    total = 0
    for index, request in enumerate(requests):
        require(isinstance(request, dict) and isinstance(request.get("method"), str)
                and request["method"] in {"GET", "POST"}, "unsafe_artifact")
        fields(request, {"step", "method", "origin", "path", "query", "status", "gated", "fields"}
               | ({"body"} if request["method"] == "POST" else set()))
        require(type(request["step"]) is int and request["step"] == index + 1
                and request["origin"] == artifact["sourceOrigins"][0] and type(request["status"]) is int
                and request["status"] == 200 and type(request["gated"]) is bool, "unsafe_artifact")
        if request["method"] == "POST":
            fields(request["body"], {"contentType", "fields"})
            require(isinstance(request["body"]["contentType"], str) and request["body"]["contentType"] in BODY_TYPES,
                    "unsafe_artifact")
            total += _validate_shapes(request["body"]["fields"], body=True)
        path = request["path"]
        require(isinstance(path, str) and len(path) <= 600 and path.startswith("/") and all(
            part in ("", "{id}") or _segment_ok(part) for part in path.split("/")[1:]), "unsafe_artifact")
        require(isinstance(request["query"], list) and len(request["query"]) <= 30, "unsafe_artifact")
        for parameter in request["query"]:
            fields(parameter, {"name", "value"})
            name, value = parameter["name"], parameter["value"]
            require(name == "{param}" or _param_ok(name), "unsafe_artifact")
            require(isinstance(value, str) and len(value) <= 300, "unsafe_artifact")
            if value.startswith("{"):
                require(value.endswith("}") and FORMAT.fullmatch(value[1:-1]), "unsafe_artifact")
            elif _normal(name) in PAGINATION:
                require(re.fullmatch(r"\d{1,4}", value), "unsafe_artifact")
            else:
                require(_normal(name) in QUERY_ENUMS and all(
                    TOKEN.fullmatch(token) and _known(token) for token in value.split(",")), "unsafe_artifact")
        history = index == artifact["history"]["step"] - 1
        total += _validate_shapes(request["fields"], enum_prefix=artifact["history"]["path"] + "[]" if history else None)
    require(total <= MAX_FIELDS, "unsafe_artifact")
    for name in ("identity", "history"):
        step = requests[artifact[name]["step"] - 1]
        require(artifact[name]["path"] in step["fields"] and step["gated"] is True, "unsafe_artifact")
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
    """Find the model's role proposal in a chat reply.

    Reasoning models wrap or precede the answer with other text, so every JSON
    object in the reply is tried and the last one holding a mapping wins.
    """
    require(isinstance(content, str) and len(content) <= 65536, "model_output_not_json")
    text, kept = content, []
    while "<think>" in text:
        head, _, rest = text.partition("<think>")
        kept.append(head)
        text = rest.partition("</think>")[2]
    text = "".join(kept) + text
    decoder, value, attempts = json.JSONDecoder(), None, 0
    for match in re.finditer(r"\{", text):
        attempts += 1
        if attempts > 400:
            break
        try:
            _, end = decoder.raw_decode(text, match.start())
            candidate = strict_json(text[match.start():end], maximum=65536)
        except (ValueError, RecursionError, Rejected):
            continue
        if isinstance(candidate, dict) and isinstance(candidate.get("mapping"), dict):
            value = candidate
    require(value is not None, "model_output_not_json")
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
    return isinstance(value, str) and _money(value.strip())


def _timestamp(value):
    # Role verification knows the field is meant to be a time, so bare epoch
    # numbers and compact YYYYMMDD[hhmmss] values count here.
    if type(value) in (int, float):
        return _epoch(int(value)) is not None or value_format(str(int(value)), "date") == "date:compact"
    if not isinstance(value, str) or len(value) > 64:
        return False
    style = value_format(value, "date") or ""
    return style.split(":")[0] in {"datetime", "date"} or style in {"digits:epoch_s", "digits:epoch_ms"}


def _scalar(value):
    return type(value) is int or isinstance(value, str) and 0 < len(value.strip()) <= 300


CHECKS = {
    "paymentId": (0.9, _scalar),
    "amount": (0.9, _numeric),
    "timestamp": (0.9, _timestamp),
    "counterparty": (0.5, _scalar),
    "currency": (0.9, lambda value: isinstance(value, str) and value.strip() in ISO_CURRENCIES),
    "status": (0.9, lambda value: isinstance(value, str) and STATUS_VALUE.fullmatch(value.strip()) is not None),
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


def _history_rows(reads, context):
    recipe = context["recipe"]
    rows = select(reads[recipe["history"]["read"]].body, recipe["history"]["path"])
    require(isinstance(rows, list), "history_path_invalid")
    return [row for row in rows if isinstance(row, dict) and row]


def assess(campaign, reads, context, artifact, proposal):
    """Score a proposed role mapping against the private live history rows."""
    validate_open_campaign(campaign)
    fields(proposal, {"mapping", "completedStatus"})
    rows = _history_rows(reads, context)
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
            and all(isinstance(path, str) for path in result["mapping"].values())
            and len(set(result["mapping"].values())) == len(result["mapping"]), "model_result_invalid")
    for path in result["mapping"].values():
        require(path.startswith(prefix) and ROLE_SUFFIX.fullmatch(path[len(prefix):]) and path in shapes,
                "model_result_invalid")
    require(result["score"] == sum(ROLE_WEIGHTS[role] for role in result["mapping"]), "model_result_invalid")
    require(isinstance(result["unverified"], list) and all(isinstance(role, str) for role in result["unverified"])
            and set(result["unverified"]) <= set(ROLES) - set(result["mapping"])
            and len(set(result["unverified"])) == len(result["unverified"]), "model_result_invalid")
    allowed = set(shapes[result["mapping"]["status"]].get("values", [])) if "status" in result["mapping"] else set()
    require(isinstance(result["completedStatus"], list) and len(result["completedStatus"]) <= 6
            and all(isinstance(token, str) for token in result["completedStatus"])
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


def row_witnesses(reads, context):
    """Private overlap witnesses: the canonical form of each of the newest rows.

    The account identity is contributor-declared, so the ledger also compares these.
    Two submissions sharing at least two identical rows are the same history, which
    the two sides of one payment or small numeric ids never are.
    """
    return [canonical(row).decode() for row in _history_rows(reads, context)[:MAX_PAYMENT_ALIASES]]
