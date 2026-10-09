"""Synthetic exact-resource IAM preparation checks; no AWS access."""
import copy
import unittest

from transcripts.infra.host_state_policy import extend

AUTHORITY = "arn:aws:lambda:us-east-1:111122223333:function:synthetic-authority:1"
KEY = "arn:aws:kms:us-east-1:111122223333:key/12345678-1234-1234-1234-123456789abc"
PAYOUT = "arn:aws:kms:us-east-1:111122223333:key/12345678-1234-1234-1234-123456789def"


class HostStatePolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": ["ssm:UpdateInstanceInformation"], "Resource": "*"},
            {"Effect": "Allow", "Action": ["kms:GetPublicKey", "kms:Sign"], "Resource": PAYOUT},
            {"Effect": "Deny", "NotAction": ["ssm:UpdateInstanceInformation", "kms:GetPublicKey", "kms:Sign"], "Resource": "*"},
            {"Effect": "Deny", "Action": ["kms:GetPublicKey", "kms:Sign"], "NotResource": PAYOUT},
        ]}

    def test_exact_authority_recipient_key_and_existing_custody(self):
        original = copy.deepcopy(self.policy)
        result = extend(self.policy, AUTHORITY, KEY, "synthetic-v1")
        self.assertEqual(self.policy, original)
        self.assertEqual(result["Statement"][:2], original["Statement"][:2])
        self.assertEqual(result["Statement"][3], original["Statement"][3])
        grants = {s["Sid"]: s for s in result["Statement"][4:]}
        self.assertEqual(grants["InvokeOnlyPinnedStateAuthority"]["Resource"], AUTHORITY)
        self.assertEqual(grants["DenyOtherStateAuthority"]["NotResource"], AUTHORITY)
        self.assertEqual(grants["OnlyRecipientStateKey"]["Resource"], KEY)
        self.assertEqual(grants["OnlyRecipientStateKey"]["Condition"],
                         {"StringEquals": {"kms:EncryptionContext:Namespace": "synthetic-v1"}})
        self.assertEqual(grants["DenyNonRecipientStateKey"]["Condition"],
                         {"Null": {"kms:RecipientAttestation:ImageSha384": "true"}})
        allowed = result["Statement"][2]["NotAction"]
        self.assertFalse(any(a.startswith("dynamodb:") for a in allowed))
        self.assertNotIn("kms:Encrypt", allowed)
        self.assertNotIn("kms:GenerateDataKeyWithoutPlaintext", allowed)

    def test_rejects_mutable_authority_and_cross_account_or_region(self):
        for authority, key in [(AUTHORITY.rsplit(":", 1)[0], KEY),
                               (AUTHORITY.rsplit(":", 1)[0] + ":latest", KEY),
                               (AUTHORITY, KEY.replace("us-east-1", "us-west-2")),
                               (AUTHORITY, KEY.replace("111122223333", "999988887777"))]:
            with self.assertRaises(ValueError):
                extend(self.policy, authority, key, "synthetic-v1")

    def test_refuses_unsafe_existing_grants_and_repeat_extension(self):
        for action in ["dynamodb:UpdateItem", "kms:Encrypt", "kms:GenerateDataKeyWithoutPlaintext"]:
            policy = copy.deepcopy(self.policy)
            policy["Statement"][2]["NotAction"].append(action)
            with self.assertRaisesRegex(ValueError, "host_state_mutation_forbidden"):
                extend(policy, AUTHORITY, KEY, "synthetic-v1")
        amended = extend(self.policy, AUTHORITY, KEY, "synthetic-v1")
        with self.assertRaisesRegex(ValueError, "state_grants_already_present"):
            extend(amended, AUTHORITY, KEY, "synthetic-v1")


if __name__ == "__main__":
    unittest.main()
