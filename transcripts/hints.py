"""Client-side next steps for fixed service codes. Never part of the measured image."""

HINTS = {
    "release_not_approved": "transcripts/release.json is not approved or has expired; pull the latest main of zkp2p/peer-link.",
    "policy_mismatch": "Local transcripts/policy.json differs from the released service; use an unmodified checkout of main.",
    "campaign_unavailable": "That campaign id is not in the released policy or is not active; run `campaigns`.",
    "campaign_capacity": "All slots for this campaign are reserved or paid; run `campaigns --live` and pick another bank.",
    "budget_exhausted": "The funded reward budget is fully reserved; try later or another campaign.",
    "duplicate_recipient": "This payout address already holds a job in this campaign; poll that job instead.",
    "duplicate_account": "This bank account or organization was already paid in this campaign.",
    "provider_not_allowed": "Provider/model is not permitted by the campaign; run `terms --campaign ID` for the routes.",
    "invalid_provider": "--base-url must be https://host[/path] without a trailing slash, port, query or credentials.",
    "state_exists": "The --state file already exists; choose a new path or poll the saved job with `job --state`.",
    "job_expired": "The ten-minute reservation lapsed; check the old job with `job`, then start a new contribution.",
    "job_replayed": "This job was already submitted; poll it with `job --state` and do not resubmit.",
    "recipe_version": "Open campaigns take recipe version 3; reviewed campaigns take the version in the skill.",
    "recipe_limits": "Too many reads, or the recipe is too large; keep to the campaign's maxReads.",
    "recipe_invalid": "Every read must be a GET on the single campaign origin.",
    "source_not_allowed": "A URL is outside the campaign origin, uses a port/fragment/encoded path, or repeats a query name.",
    "credential_headers_invalid": "Credential headers need plain ASCII names and values; drop Host, Content-Length, Connection and Accept-Encoding.",
    "invalid_credential": "credential.origin must equal the campaign origin and carry a non-empty value.",
    "anonymous_access_allowed": "The identity or history URL returns JSON without credentials; pick an endpoint that requires the session.",
    "bank_http_unauthorized": "The bank rejected the session (401/403); capture fresh headers and include every required one.",
    "bank_http_redirect": "The bank redirected; the session is probably expired or a header such as a CSRF token is missing.",
    "bank_http_client_error": "The bank returned 4xx; replay the exact request locally with `preview` first.",
    "bank_http_server_error": "The bank returned 5xx; retry later with a new reservation.",
    "bank_response_non_json": "A read did not return JSON; use the JSON API the site calls, not an HTML page.",
    "response_encoding": "The bank ignored Accept-Encoding: identity and compressed the body; try the API host instead.",
    "response_size": "A response exceeded 2 MB; lower the page size in the URL.",
    "identity_path_invalid": "recipe.identity must select a stable account/user id (a number >= 100 or a 3+ character string).",
    "history_path_invalid": "recipe.history must select the JSON array of transaction records.",
    "insufficient_history": "The history array held too few object records; widen the date range or use a busier account.",
    "unsafe_notes": "Notes may not contain ids, long digit runs, emails, tokens or values copied from the bank response.",
    "transcript_too_large": "The value-free transcript exceeded its size bound; drop non-essential reads or request smaller pages.",
    "model_output_not_json": "The model did not answer with a JSON object; pick a model that follows instructions.",
    "model_output_truncated": "The model hit the output limit; raise --max-output-tokens (reasoning models need more).",
    "model_result_invalid": "The model's answer did not match the required structure.",
    "model_rejected": "The verified field mapping scored below the campaign minimum.",
    "provider_http_bad_request": "The provider refused the request; check the exact model id for that provider.",
    "provider_http_unauthorized": "The provider rejected the inference key.",
    "provider_http_payment_required": "The inference account has no credit.",
    "provider_http_not_found": "Model or endpoint not found; --base-url must be the prefix before /chat/completions.",
    "provider_http_rate_limited": "The provider rate limited the call; wait and start a new contribution.",
    "provider_http_server_error": "The provider failed (5xx); try again or use another provider.",
    "inference_input_limit": "The prompt exceeded maxInputTokens; shorten notes or reduce reads.",
    "inference_usage_limit": "Reported token usage exceeded the reserved limits; raise --max-output-tokens.",
    "request_timeout": "Bank reads or inference exceeded the deadline; use fewer reads or a faster model.",
    "limits_exceeded": "The job ran past its deadline; raise --deadline (max 300) or use a faster model.",
    "http_transport_failed": "TLS or network failure reaching the bank or provider from the enclave.",
    "payout_paused": "Admissions are paused by the operator; try again later.",
    "service_unavailable": "The service did not answer as expected; retry `preflight` before anything else.",
    "secret_prompt_unavailable": "No controlling terminal; use --secrets-from-env or put the secrets in the stdin payload.",
    "secrets_env_missing": "Set PEERLINK_BANK_CREDENTIAL and PEERLINK_INFERENCE_KEY in the environment.",
}
for _role, _what in (("paymentId", "a unique per-record id"), ("amount", "a numeric amount"),
                     ("timestamp", "an ISO date or epoch time"), ("counterparty", "the other party's identifier"),
                     ("currency", "an ISO currency code"), ("status", "a short status token")):
    HINTS["mapping_missing_" + _role] = (
        "No history field was verified as " + _what + "; name the right field path in your notes and check it with "
        "`preview --mapping`.")


def hint(code):
    return HINTS.get(code)
