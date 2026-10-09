"""Host-only fixed numeric health metrics; no requests, credentials or state logging."""
import argparse
import json
import os
import re
import signal
import subprocess
import threading

from transcripts.infra.host_health import checked_health, policy_at, read_health

NAMESPACE = 'PeerLink/Transcripts'


def role_environment():
    # Force instance-role credentials and official endpoints. Ignore operator
    # profiles, credential injection, CA overrides and alternate metadata origins.
    env = dict(os.environ)
    for key in list(env):
        if (key.startswith(('AWS_ENDPOINT_URL', 'AWS_CONTAINER_', 'AWS_EC2_METADATA_SERVICE_'))
                or key in {'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
                           'AWS_SECURITY_TOKEN', 'AWS_CREDENTIAL_FILE', 'BOTO_CONFIG', 'AWS_PROFILE', 'AWS_DEFAULT_PROFILE',
                           'AWS_WEB_IDENTITY_TOKEN_FILE', 'AWS_ROLE_ARN', 'AWS_ROLE_SESSION_NAME',
                           'AWS_CA_BUNDLE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE',
                           'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'}):
            env.pop(key, None)
    env.update(AWS_CONFIG_FILE='/dev/null', AWS_SHARED_CREDENTIALS_FILE='/dev/null',
               AWS_PAGER='', AWS_EC2_METADATA_DISABLED='false', AWS_MAX_ATTEMPTS='1',
               AWS_IGNORE_CONFIGURED_ENDPOINT_URLS='true', NO_PROXY='169.254.169.254')
    return env


def sample(policy, instance, health=read_health):
    available = accepting = 0
    try:
        current = checked_health(health(), policy)
        available, accepting = 1, int(current['accepting'])
    except Exception:
        pass
    return [{'MetricName': name, 'Dimensions': [{'Name': 'InstanceId', 'Value': instance}],
             'Unit': 'Count', 'Value': value}
            for name, value in [('RuntimeHealth', available), ('AdmissionsOpen', accepting)]]


def publish(metrics, region):
    subprocess.run(['aws', 'cloudwatch', 'put-metric-data', '--region', region,
                    '--endpoint-url', 'https://monitoring.' + region + '.amazonaws.com',
                    '--namespace', NAMESPACE, '--metric-data', json.dumps(metrics),
                    '--cli-connect-timeout', '5', '--cli-read-timeout', '10'],
                   env=role_environment(), check=True, capture_output=True, timeout=20)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--instance-id', required=True)
    parser.add_argument('--region', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'i-[0-9a-f]{17}', args.instance_id) or not re.fullmatch(r'[a-z]{2}-[a-z]+-[0-9]', args.region):
        raise SystemExit('health_publisher_failed')
    policy = policy_at(args.root)
    stop = threading.Event()
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda *_: stop.set())
    while not stop.is_set():
        try:
            publish(sample(policy, args.instance_id), args.region)
        except Exception:
            pass  # Missing-metric alarm catches publishing failure; no private logs.
        stop.wait(60)


if __name__ == '__main__':
    main()
