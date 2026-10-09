"""Private retained bucket for signed, redacted transcript archive records.

Generate with python3 transcripts/infra/archive_template.py > transcripts/infra/archive.cfn.json.
This creates storage only. Host write access is a separate reviewed additive
change to the dedicated transcript host role; nothing here grants any principal access.
"""
import json

RECORD_PREFIXES = ("records/", "by-bank/")


def bucket_name(account):
    return "peerlink-transcripts-" + account


def host_statements(bucket):
    """Exact write-only statements appended to the dedicated host role policy.

    The role's catch-all DenyNotAction list must also include s3:PutObject. No
    read, list or delete action is granted: a compromised host cannot inspect or
    remove records that already left it.
    """
    resources = ["arn:aws:s3:::" + bucket + "/" + prefix + "*" for prefix in RECORD_PREFIXES]
    return [
        {"Sid": "WriteOnlyTranscriptArchive", "Effect": "Allow", "Action": "s3:PutObject", "Resource": resources},
        {"Sid": "DenyOtherArchiveWrites", "Effect": "Deny", "Action": "s3:PutObject", "NotResource": resources},
    ]


def template():
    name = {"Fn::Sub": "peerlink-transcripts-${AWS::AccountId}"}
    bucket = {
        "Type": "AWS::S3::Bucket",
        "DeletionPolicy": "Retain",
        "UpdateReplacePolicy": "Retain",
        "Properties": {
            "BucketName": name,
            "PublicAccessBlockConfiguration": {"BlockPublicAcls": True, "BlockPublicPolicy": True,
                                               "IgnorePublicAcls": True, "RestrictPublicBuckets": True},
            "OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
            "VersioningConfiguration": {"Status": "Enabled"},
            "BucketEncryption": {"ServerSideEncryptionConfiguration": [
                {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
            "Tags": [{"Key": "Project", "Value": "peer-link-transcripts"}, {"Key": "Environment", "Value": "pilot"}],
        },
    }
    policy = {
        "Type": "AWS::S3::BucketPolicy",
        "DeletionPolicy": "Retain",
        "UpdateReplacePolicy": "Retain",
        "Properties": {"Bucket": {"Ref": "Archive"}, "PolicyDocument": {"Version": "2012-10-17", "Statement": [{
            "Sid": "DenyInsecureTransport", "Effect": "Deny", "Principal": "*", "Action": "s3:*",
            "Resource": [{"Fn::GetAtt": ["Archive", "Arn"]}, {"Fn::Sub": "${Archive.Arn}/*"}],
            "Condition": {"Bool": {"aws:SecureTransport": "false"}}}]}},
    }
    return {"AWSTemplateFormatVersion": "2010-09-09",
            "Description": "Private retained archive of signed redacted PeerLink transcript records; no public access, no expiry",
            "Resources": {"Archive": bucket, "ArchivePolicy": policy},
            "Outputs": {"BucketName": {"Value": {"Ref": "Archive"}}, "BucketArn": {"Value": {"Fn::GetAtt": ["Archive", "Arn"]}}}}


if __name__ == "__main__":
    print(json.dumps(template(), indent=2))
