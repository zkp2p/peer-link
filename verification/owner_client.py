"""Owner-operated local client for an approved, short-lived manual attempt.

Use an independently obtained release and adapter digest. The operator's request
bundle contains public permission metadata only. Bank input is read from a TTY
without echo, kept in memory, encrypted to the verified enclave and never logged.
The localhost endpoint is an operator-established SSM port forward, not a URL
chosen by a contributor. This client never reads an existing browser session.
"""
import argparse
import getpass
import hashlib
import json
import resource
import socket
import struct
import sys
from pathlib import Path

from .acquisition_process import PROCESS_DEADLINE_SECONDS
from .attestation import policy_digest, verify_document
from .client import verified_session
from .common import b64, canonical, digest, fields, require, strict_json, unb64
from .receipts import verify as verify_receipt
from .runtime import receive
from .sandbox import MAX_MODULE, TIMEOUT_SECONDS as SANDBOX_SECONDS

# An execute reply can take the bank-reader deadline plus the Wasm deadline, then
# signing and a fresh quote. A reply lost to a short wait still burns the session.
RESPONSE_SECONDS = PROCESS_DEADLINE_SECONDS + SANDBOX_SECONDS + 15


def transport(port, request):
    require(type(port) is int and 1024 <= port <= 65535, 'invalid_port')
    body = canonical(request)
    require(len(body) <= 3 * 1024 * 1024, 'frame_size')
    with socket.create_connection(('127.0.0.1', port), timeout=5) as stream:
        stream.settimeout(RESPONSE_SECONDS)
        stream.sendall(struct.pack('!I', len(body)) + body)
        # First wait for completion; receive then bounds the remaining frame.
        prefix = stream.recv(1, socket.MSG_PEEK)
        require(bool(prefix), 'truncated_frame')
        response = receive(stream, 65536)
    require(isinstance(response, dict) and 'error' not in response, 'worker_refused')
    return response


def complete(bundle, *, release, expected_adapter, call, collect_session):
    fields(bundle, ('module', 'binding', 'context', 'permit'))
    fields(bundle['binding'], ('revision', 'release', 'policy', 'prompt'))
    module = unb64(bundle['module'], MAX_MODULE)
    require(hashlib.sha256(module).hexdigest() == expected_adapter == bundle['binding']['revision'],
            'adapter_mismatch')
    require(bundle['binding']['release'] == digest(release) and
            bundle['binding']['policy'] == release.get('policyDigest'), 'release_binding')
    require(release.get('liveVerification') is True, 'live_verification_unavailable')
    context = bundle['context']
    fields(context, ('protocol', 'attempt', 'bindingDigest', 'nonce', 'expiresAt'))
    require(context['bindingDigest'] == digest(bundle['binding']), 'session_binding_mismatch')
    nonce = bytes.fromhex(digest(context))
    quote = call({'operation': 'attest', 'nonce': b64(nonce)})
    fields(quote, ('attestation', 'publicKey', 'policyDigest'))
    public_key = unb64(quote['publicKey'], 4096)
    verified = verify_document(unb64(quote['attestation'], 32768), nonce=nonce,
        public_key_der=public_key, release=release)
    require(quote['policyDigest'] == verified['policyDigest'], 'policy_mismatch')
    # The caller displays the independently pinned scope and asks for explicit
    # consent only AFTER attestation succeeds, before collecting bank input.
    session = collect_session()
    # Reading the scope and typing hidden input can outlast the 60-second quote
    # window. Re-attest immediately before encryption, to the same verified key.
    fresh = call({'operation': 'attest', 'nonce': b64(nonce)})
    fields(fresh, ('attestation', 'publicKey', 'policyDigest'))
    require(unb64(fresh['publicKey'], 4096) == public_key, 'session_key_changed')
    envelope = verified_session(fresh, nonce=nonce, release=release, context=context,
        attempt=context['attempt'], binding_digest=digest(bundle['binding']),
        session=session, consent=True)
    session = None
    report = call({'operation': 'execute', 'module': bundle['module'],
        'binding': bundle['binding'], 'permit': bundle['permit'], 'envelope': envelope})
    fields(report, ('receipt', 'quote'))
    receipt_quote = report['quote']
    fields(receipt_quote, ('attestation', 'publicKey', 'policyDigest'))
    require(unb64(receipt_quote['publicKey']) == public_key, 'receipt_key_changed')
    require(receipt_quote['policyDigest'] == verified['policyDigest'], 'policy_mismatch')
    verify_receipt(report['receipt'], attestation=unb64(receipt_quote['attestation']),
        nonce=bytes.fromhex(digest(report['receipt'])),
        public_key_der=public_key, release=release)
    claims = report['receipt']['claims']
    require(claims['attempt'] == context['attempt'] and
            claims['bindingDigest'] == digest(bundle['binding']), 'receipt_binding')
    return report


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    parser.add_argument('--approved-request', required=True)
    parser.add_argument('--expected-adapter-sha256', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--verifier-directory', default=str(Path(__file__).parent),
                        help='Independently reviewed local verifier source/policies')
    args = parser.parse_args()
    require(sys.stdin.isatty(), 'owner_terminal_required')
    release = strict_json(Path(args.release).read_bytes())
    bundle = strict_json(Path(args.approved_request).read_bytes(), 3 * 1024 * 1024)
    directory = Path(args.verifier_directory)
    policies = [strict_json((directory / 'policies' / name).read_bytes()) for name in
                ('service.json', 'mercury.json', 'model-trust.json', 'operator-trust.json')]
    prompt = (directory / 'prompts/payment-review-v1.txt').read_text()
    require(policy_digest(policies[0], prompt, *policies[1:]) == release.get('policyDigest'),
            'policy_mismatch')
    source = policies[1]
    require(source.get('enabled') is True and source.get('status') == 'approved' and
            len(source.get('origins', [])) == len(source.get('operations', [])) == 1,
            'source_policy_not_approved')
    operation = source['operations'][0]

    def collect():
        # No approval is inferred from being signed in to a bank.
        print('Approved release digest:', digest(release))
        print('Approved adapter digest:', args.expected_adapter_sha256)
        print('Approved capability:', source['capability'])
        print('Bank destination:', source['origins'][0], operation['method'], operation['path'])
        print('One selected existing transaction; no payments or account changes.')
        if operation['id'] == 'mercury-history-v1':
            print('The bank history read can return up to 100 records inside the enclave.')
            print('Only required fields of the selected transaction reach the adapter sandbox.')
        print('Required transaction fields stay in the enclave. Only a minimal report returns.')
        require(input('Type CONSENT to share this session with the verified enclave: ') == 'CONSENT',
                'consent_required')
        credentials = {name: getpass.getpass('Approved '+name+' (hidden): ')
                       for name in operation['credentialHeaders']}
        context = None
        if operation['id'] == 'mercury-history-v1':
            context = {'organizationId': getpass.getpass('Organization ID (hidden): ')}
        return {'credentials': credentials, 'sourceContext': context,
                'transactionId': getpass.getpass('Selected transaction ID (hidden): ')}

    report = complete(bundle, release=release, expected_adapter=args.expected_adapter_sha256,
        call=lambda request: transport(args.port, request), collect_session=collect)
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt):
        # Never print an exception derived from bank input or network payloads.
        print('{"error":"verification_failed_or_expired"}')
        raise SystemExit(1)
