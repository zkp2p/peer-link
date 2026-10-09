"""Prepare a reviewed host-role policy extension; never apply IAM mutations.

The existing policy and exact public resource ARNs are inputs. Keep its SSM and
operator-recoverable payout grants, add only immutable authority invocation and
Recipient state-key operations, and keep DynamoDB fully denied to the host.
"""
import argparse
import copy
import json
import re
from pathlib import Path


def extend(policy, authority_arn, state_key_arn, namespace):
    if not re.fullmatch(r"arn:aws:lambda:[a-z0-9-]+:[0-9]{12}:function:[A-Za-z0-9_-]+:[1-9][0-9]*", authority_arn):
        raise ValueError("immutable_authority_arn_required")
    if not re.fullmatch(r"arn:aws:kms:[a-z0-9-]+:[0-9]{12}:key/[a-f0-9-]{36}", state_key_arn):
        raise ValueError("state_key_arn_required")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", namespace):
        raise ValueError("state_namespace_required")
    if authority_arn.split(":")[3:5] != state_key_arn.split(":")[3:5]:
        raise ValueError("state_region_account_mismatch")
    result = copy.deepcopy(policy)
    statements = result["Statement"]
    denies = [s for s in statements if s.get("Effect") == "Deny" and "NotAction" in s]
    if len(denies) != 1 or not isinstance(denies[0]["NotAction"], list):
        raise ValueError("reviewed_host_deny_missing")
    if any("State" in s.get("Sid", "") for s in statements):
        raise ValueError("state_grants_already_present_review_required")
    actions = ["lambda:InvokeFunction", "kms:GenerateDataKey", "kms:Decrypt"]
    denies[0]["NotAction"] += [a for a in actions if a not in denies[0]["NotAction"]]
    statements += [
        {"Sid": "InvokeOnlyPinnedStateAuthority", "Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": authority_arn},
        {"Sid": "DenyOtherStateAuthority", "Effect": "Deny", "Action": "lambda:InvokeFunction", "NotResource": authority_arn},
        {"Sid": "OnlyRecipientStateKey", "Effect": "Allow", "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
         "Resource": state_key_arn, "Condition": {"StringEquals": {"kms:EncryptionContext:Namespace": namespace}}},
        {"Sid": "DenyOtherStateKeys", "Effect": "Deny", "Action": ["kms:GenerateDataKey", "kms:Decrypt"], "NotResource": state_key_arn},
        {"Sid": "DenyNonRecipientStateKey", "Effect": "Deny", "Action": ["kms:GenerateDataKey", "kms:Decrypt"], "Resource": state_key_arn,
         "Condition": {"Null": {"kms:RecipientAttestation:ImageSha384": "true"}}},
    ]
    # The original explicit deny still covers every DynamoDB/S3/secrets action.
    if any(a.startswith("dynamodb:") or a in {"kms:Encrypt", "kms:GenerateDataKeyWithoutPlaintext"} for a in denies[0]["NotAction"]):
        raise ValueError("host_state_mutation_forbidden")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare public host IAM policy for review only")
    parser.add_argument("existing_policy", type=Path)
    parser.add_argument("authority_version_arn")
    parser.add_argument("state_key_arn")
    parser.add_argument("namespace")
    args = parser.parse_args()
    policy = json.loads(args.existing_policy.read_text())
    print(json.dumps(extend(policy.get("PolicyDocument", policy), args.authority_version_arn,
                            args.state_key_arn, args.namespace), indent=2))
