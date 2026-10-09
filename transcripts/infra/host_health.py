"""Bounded public-metadata checks; never fetch contributor or encrypted state data."""
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from transcripts.artifacts import validate_epoch_descriptor
from transcripts.common import digest, strict_json


def policy_at(root):
    policy = strict_json((Path(root)/'transcripts/policy.json').read_bytes(), 1_000_000)
    if not isinstance(policy.get('stateAuthority'), dict):
        raise ValueError('durable_policy_required')
    return policy


def read_health():
    with build_opener(ProxyHandler({})).open('http://127.0.0.1:8080/health', timeout=5) as response:
        if response.status != 200:
            raise ValueError('runtime_unavailable')
        return strict_json(response.read(16_385), 16_384)


def checked_health(health, policy, paused=False):
    if (health.get('service') != 'peerlink-transcripts' or health.get('version') != 1
            or health.get('mode') != 'nitro-pilot' or health.get('policyDigest') != digest(policy)
            or type(health.get('accepting')) is not bool
            or (paused and health['accepting'])):
        raise ValueError('runtime_unavailable')
    validate_epoch_descriptor(health.get('epoch'), policy)
    return health
