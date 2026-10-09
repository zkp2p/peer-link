"""Retained ciphertext authority resources; no host or pilot lifetime changes.

Generate state.cfn.json from this file. Start with ApprovedImageSha384 empty,
then authorize the actual independently reviewed PCR0 after the measured build.
The host's existing explicit deny must be adjusted separately after review.
"""
import hashlib
import json
from pathlib import Path


def template():
    ref = lambda name: {"Ref": name}
    sub = lambda value: {"Fn::Sub": value}
    arn = lambda name: {"Fn::GetAtt": [name, "Arn"]}
    source = Path(__file__).with_name("state_authority.py").read_text()
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    tags = [{"Key": "Project", "Value": "peer-link-transcripts"}, {"Key": "Component", "Value": "durable-state"}]
    admin_actions = ["kms:DescribeKey", "kms:GetKeyPolicy", "kms:PutKeyPolicy", "kms:EnableKey", "kms:DisableKey",
                     "kms:UpdateKeyDescription", "kms:ScheduleKeyDeletion", "kms:CancelKeyDeletion",
                     "kms:List*", "kms:TagResource", "kms:UntagResource", "kms:EnableKeyRotation",
                     "kms:DisableKeyRotation", "kms:GetKeyRotationStatus"]
    resources = {
        "StateTable": {"Type": "AWS::DynamoDB::Table", "DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain",
            "Properties": {"BillingMode": "PAY_PER_REQUEST", "AttributeDefinitions": [{"AttributeName": "namespace", "AttributeType": "S"}],
                "KeySchema": [{"AttributeName": "namespace", "KeyType": "HASH"}], "DeletionProtectionEnabled": True,
                "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True, "RecoveryPeriodInDays": 35},
                # AWS-owned at-rest encryption; the item is separately enclave
                # encrypted. Do not require the authority to decrypt account keys.
                "SSESpecification": {"SSEEnabled": False}, "Tags": tags}},
        "StateKey": {"Type": "AWS::KMS::Key", "DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain",
            "Properties": {"Description": "Enclave-only persistent state/dedup secret; separate from operator-recoverable payout key",
                "KeySpec": "SYMMETRIC_DEFAULT", "KeyUsage": "ENCRYPT_DECRYPT", "EnableKeyRotation": True,
                "KeyPolicy": {"Version": "2012-10-17", "Statement": [
                    {"Sid": "AccountAdministrationNoPlaintextUse", "Effect": "Allow", "Principal": {"AWS": sub("arn:${AWS::Partition}:iam::${AWS::AccountId}:root")},
                     "Action": admin_actions, "Resource": "*"},
                    {"Fn::If": ["HasApprovedImage", {"Sid": "OnlyApprovedRecipientAndRole", "Effect": "Allow",
                        "Principal": {"AWS": ref("HostRoleArn")}, "Action": ["kms:GenerateDataKey", "kms:Decrypt"], "Resource": "*",
                        "Condition": {"StringEqualsIgnoreCase": {"kms:RecipientAttestation:ImageSha384": ref("ApprovedImageSha384"),
                                                               "kms:RecipientAttestation:PCR3": ref("HostRolePcr3")},
                                      "StringEquals": {"kms:EncryptionContext:Namespace": ref("StateNamespace")}}}, ref("AWS::NoValue")]},
                ]}, "Tags": tags}},
        "AuthorityRole": {"Type": "AWS::IAM::Role", "DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain", "Properties": {
            "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
            "Policies": [{"PolicyName": "MonotonicStateOnly", "PolicyDocument": {"Version": "2012-10-17", "Statement": [
                {"Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem"], "Resource": arn("StateTable"),
                 "Condition": {"ForAllValues:StringEquals": {"dynamodb:LeadingKeys": [ref("StateNamespace")]}}},
                {"Effect": "Deny", "NotAction": {"Fn::If": ["HasLambdaEnvironmentKey",
                    ["dynamodb:GetItem", "dynamodb:UpdateItem", "kms:Decrypt"],
                    ["dynamodb:GetItem", "dynamodb:UpdateItem"]]}, "Resource": "*"},
                {"Effect": "Deny", "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem"], "NotResource": arn("StateTable")},
                # Lambda must decrypt its public environment configuration before
                # the handler starts. This exception never covers the state key.
                # The verified AWS-managed key policy restricts Lambda origin/context.
                {"Fn::If": ["HasLambdaEnvironmentKey", {"Sid": "LambdaEnvironmentOnly", "Effect": "Allow",
                    "Action": "kms:Decrypt", "Resource": ref("LambdaEnvironmentKeyArn"),
                    "Condition": {"StringEquals": {"kms:EncryptionContext:aws:lambda:FunctionArn": ref("LambdaEnvironmentFunctionArn")}}}, ref("AWS::NoValue")]},
                {"Fn::If": ["HasLambdaEnvironmentKey", {"Sid": "DenyAllOtherKeyDecrypt", "Effect": "Deny",
                    "Action": "kms:Decrypt", "NotResource": ref("LambdaEnvironmentKeyArn")}, ref("AWS::NoValue")]},
                {"Fn::If": ["HasLambdaEnvironmentKey", {"Sid": "DenyOtherLambdaEnvironment", "Effect": "Deny",
                    "Action": "kms:Decrypt", "Resource": ref("LambdaEnvironmentKeyArn"),
                    "Condition": {"StringNotEquals": {"kms:EncryptionContext:aws:lambda:FunctionArn": ref("LambdaEnvironmentFunctionArn")}}}, ref("AWS::NoValue")]},
            ]}}], "Tags": tags}},
        "Authority": {"Type": "AWS::Lambda::Function", "DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain", "Properties": {"Runtime": "python3.12", "Handler": "index.handler",
            "Role": arn("AuthorityRole"), "Code": {"ZipFile": source}, "Timeout": 15, "MemorySize": 128,
            "RuntimeManagementConfig": {"UpdateRuntimeOn": "FunctionUpdate"},
            "Environment": {"Variables": {"TABLE_NAME": ref("StateTable"), "STATE_NAMESPACE": ref("StateNamespace")}},
            "Description": "Opaque CAS-only authority source SHA256 " + source_hash, "Tags": tags}},
        "AuthorityVersion": {"Type": "AWS::Lambda::Version", "DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain",
            "Properties": {"FunctionName": ref("Authority"), "Description": "Reviewed authority source SHA256 " + source_hash}},
    }
    return {"AWSTemplateFormatVersion": "2010-09-09", "Description": "Retained enclave-ciphertext state authority; no host replacement, no plaintext secret grants",
        "Parameters": {
            "HostRoleArn": {"Type": "String", "AllowedPattern": "arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+"},
            "HostRolePcr3": {"Type": "String", "AllowedPattern": "(?!0{96}$)[a-f0-9]{96}"},
            "StateNamespace": {"Type": "String", "AllowedPattern": "[a-z0-9][a-z0-9-]{0,63}"},
            "LambdaEnvironmentKeyArn": {"Type": "String", "Default": "",
                "AllowedPattern": "(arn:aws:kms:[a-z0-9-]+:[0-9]{12}:key/[a-f0-9-]{36})?",
                "Description": "Exact independently verified AWS-managed aws/lambda environment key; no state-master decrypt grant"},
            "LambdaEnvironmentFunctionArn": {"Type": "String", "Default": "",
                "AllowedPattern": "(arn:aws:lambda:[a-z0-9-]+:[0-9]{12}:function:[A-Za-z0-9_-]+)?",
                "Description": "Exact unqualified authority ARN observed in successful Lambda environment decrypt context"},
            "ApprovedImageSha384": {"Type": "String", "Default": "", "AllowedPattern": "((?!0{96}$)[a-f0-9]{96})?",
                "Description": "Empty keeps all secret operations denied; set only independently reviewed actual PCR0"}},
        "Conditions": {"HasApprovedImage": {"Fn::Not": [{"Fn::Equals": [ref("ApprovedImageSha384"), ""]}]},
                       "HasLambdaEnvironmentKey": {"Fn::Not": [{"Fn::Equals": [ref("LambdaEnvironmentKeyArn"), ""]}]}},
        "Resources": resources, "Outputs": {
            "StateTableName": {"Value": ref("StateTable")}, "StateTableArn": {"Value": arn("StateTable")},
            "StateKeyArn": {"Value": arn("StateKey")}, "StateNamespace": {"Value": ref("StateNamespace")},
            "AuthorityVersionArn": {"Value": ref("AuthorityVersion")}, "AuthoritySourceSha256": {"Value": source_hash}}}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Prepare retained state resources; no AWS mutation")
    parser.add_argument("--retained-import-template", type=Path,
                        help="Preserve imported physical names when preparing a later reviewed update")
    args = parser.parse_args()
    result = template()
    if args.retained_import_template:
        imported = json.loads(args.retained_import_template.read_text())
        for logical, property_name in [("StateTable", "TableName"), ("AuthorityRole", "RoleName"), ("Authority", "FunctionName")]:
            result["Resources"][logical]["Properties"][property_name] = imported["Resources"][logical]["Properties"][property_name]
    print(json.dumps(result, indent=2))
