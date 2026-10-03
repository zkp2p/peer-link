"""Persistent Peer Link artifacts, release signing and redacted alarm delivery.

This stack grants no bank access or worker deployment authority. Create/reuse the
account's GitHub OIDC provider separately after checking its exact URL/audience.
"""
import json

from .manual_template import allow, arn, policy, ref, sub


def template():
    tags = [{'Key': 'Project', 'Value': 'peer-link'}]
    resources = {
        'Artifacts': {'Type': 'AWS::S3::Bucket', 'DeletionPolicy': 'Retain',
            'UpdateReplacePolicy': 'Retain', 'Properties': {
                'VersioningConfiguration': {'Status': 'Enabled'},
                'BucketEncryption': {'ServerSideEncryptionConfiguration': [
                    {'ServerSideEncryptionByDefault': {'SSEAlgorithm': 'AES256'}}]},
                'PublicAccessBlockConfiguration': {k: True for k in (
                    'BlockPublicAcls', 'IgnorePublicAcls', 'BlockPublicPolicy', 'RestrictPublicBuckets')},
                'OwnershipControls': {'Rules': [{'ObjectOwnership': 'BucketOwnerEnforced'}]},
                'LifecycleConfiguration': {'Rules': [{'Id': 'AbortIncompleteUploads', 'Status': 'Enabled',
                    'AbortIncompleteMultipartUpload': {'DaysAfterInitiation': 1}}]},
                'Tags': tags,
            }},
        'ArtifactPolicy': {'Type': 'AWS::S3::BucketPolicy', 'Properties': {
            'Bucket': ref('Artifacts'), 'PolicyDocument': policy([{
                'Effect': 'Deny', 'Principal': '*', 'Action': 's3:*',
                'Resource': [arn('Artifacts'), sub('${Artifacts.Arn}/*')],
                'Condition': {'Bool': {'aws:SecureTransport': 'false'}},
            }])}},
        'SigningRole': {'Type': 'AWS::IAM::Role', 'Properties': {
            'RoleName': 'peer-link-release-signing', 'MaxSessionDuration': 3600,
            'AssumeRolePolicyDocument': policy([{
                'Effect': 'Allow', 'Principal': {'AWS': ref('OperatorArn')}, 'Action': 'sts:AssumeRole',
            }]), 'Tags': tags,
        }},
        'SigningKey': {'Type': 'AWS::KMS::Key', 'DeletionPolicy': 'Retain',
            'UpdateReplacePolicy': 'Retain', 'Properties': {
                'Description': 'Peer Link EIF signatures only; no Peer settlement authority.',
                'KeySpec': 'ECC_NIST_P384', 'KeyUsage': 'SIGN_VERIFY',
                'KeyPolicy': policy([
                    {'Effect': 'Allow', 'Principal': {'AWS': ref('OperatorArn')},
                     'Action': ['kms:DescribeKey', 'kms:GetKeyPolicy', 'kms:PutKeyPolicy',
                                'kms:List*', 'kms:EnableKey', 'kms:DisableKey', 'kms:TagResource',
                                'kms:UntagResource', 'kms:ScheduleKeyDeletion', 'kms:CancelKeyDeletion'],
                     'Resource': '*'},
                    {'Effect': 'Allow', 'Principal': {'AWS': arn('SigningRole')},
                     'Action': ['kms:Sign', 'kms:GetPublicKey', 'kms:DescribeKey'], 'Resource': '*'},
                    {'Effect': 'Deny', 'Principal': '*', 'Action': 'kms:Sign', 'Resource': '*',
                     'Condition': {'ArnNotEquals': {'aws:PrincipalArn': arn('SigningRole')}}},
                ]), 'Tags': tags,
            }},
        'SigningPolicy': {'Type': 'AWS::IAM::Policy', 'Properties': {
            'PolicyName': 'OnlyPeerLinkReleaseSigning', 'Roles': [ref('SigningRole')],
            'PolicyDocument': policy([
                allow(['kms:Sign', 'kms:GetPublicKey', 'kms:DescribeKey'], arn('SigningKey')),
                {'Effect': 'Deny', 'NotAction': ['kms:Sign', 'kms:GetPublicKey', 'kms:DescribeKey'], 'Resource': '*'},
                {'Effect': 'Deny', 'Action': 'kms:*', 'NotResource': arn('SigningKey')},
            ]),
        }},
        'AlarmTopic': {'Type': 'AWS::SNS::Topic', 'Properties': {
            'TopicName': 'peer-link-verification-alerts', 'Tags': tags,
        }},
        'AlarmTopicPolicy': {'Type': 'AWS::SNS::TopicPolicy', 'Properties': {
            'Topics': [ref('AlarmTopic')], 'PolicyDocument': policy([{
                'Effect': 'Allow', 'Principal': {'Service': 'cloudwatch.amazonaws.com'},
                'Action': 'sns:Publish', 'Resource': ref('AlarmTopic'),
                'Condition': {'StringEquals': {'aws:SourceAccount': ref('AWS::AccountId')},
                    'ArnLike': {'aws:SourceArn': sub('arn:${AWS::Partition}:cloudwatch:${AWS::Region}:${AWS::AccountId}:alarm:peer-link-*')}},
            }]),
        }},
        'AlarmQueue': {'Type': 'AWS::SQS::Queue', 'Properties': {
            'SqsManagedSseEnabled': True, 'MessageRetentionPeriod': 604800, 'Tags': tags,
        }},
        'AlarmQueuePolicy': {'Type': 'AWS::SQS::QueuePolicy', 'Properties': {
            'Queues': [ref('AlarmQueue')], 'PolicyDocument': policy([{
                'Effect': 'Allow', 'Principal': {'Service': 'sns.amazonaws.com'},
                'Action': 'sqs:SendMessage', 'Resource': arn('AlarmQueue'),
                'Condition': {'ArnEquals': {'aws:SourceArn': ref('AlarmTopic')},
                    'StringEquals': {'aws:SourceAccount': ref('AWS::AccountId')}},
            }]),
        }},
        'AlarmQueueSubscription': {'Type': 'AWS::SNS::Subscription', 'DependsOn': 'AlarmQueuePolicy',
            'Properties': {'TopicArn': ref('AlarmTopic'), 'Protocol': 'sqs', 'Endpoint': arn('AlarmQueue')}},
        'EmailSubscription': {'Type': 'AWS::SNS::Subscription', 'Condition': 'HasEmail',
            'Properties': {'TopicArn': ref('AlarmTopic'), 'Protocol': 'email', 'Endpoint': ref('AlertEmail')}},
    }
    return {
        'AWSTemplateFormatVersion': '2010-09-09',
        'Description': 'Peer Link separate signing authority, private artifacts and persistent monitoring.',
        'Parameters': {
            'OperatorArn': {'Type': 'String', 'AllowedPattern': r'arn:aws:iam::[0-9]{12}:user/[A-Za-z0-9+=,.@_/-]+'},
            'AlertEmail': {'Type': 'String', 'Default': ''},
        },
        'Conditions': {'HasEmail': {'Fn::Not': [{'Fn::Equals': [ref('AlertEmail'), '']}]}},
        'Resources': resources,
        'Outputs': {name: {'Value': value} for name, value in {
            'ArtifactBucket': ref('Artifacts'), 'SigningKeyArn': arn('SigningKey'),
            'SigningRoleArn': arn('SigningRole'), 'AlarmTopicArn': ref('AlarmTopic'),
            'AlarmQueueUrl': ref('AlarmQueue'),
        }.items()},
    }


if __name__ == '__main__':
    print(json.dumps(template(), indent=2))
