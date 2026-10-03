"""Invoke-only GitHub OIDC authority, separate from deployment and signing.

Requires a numeric, reviewed Lambda version and the account's verified GitHub
OIDC provider. Main-only environment rules and owner approval are also required.
"""
import json

from .manual_template import allow, policy, ref, sub


def template():
    version = ref('ControllerVersionArn')
    return {
        'AWSTemplateFormatVersion': '2010-09-09',
        'Description': 'Peer Link protected workflow: invoke one immutable controller only.',
        'Parameters': {
            'ControllerVersionArn': {'Type': 'String', 'AllowedPattern':
                r'arn:aws:lambda:us-east-1:[0-9]{12}:function:peer-link-[a-z0-9-]+:[1-9][0-9]*'},
            # Read the repository's OIDC customization before deployment. Newer
            # repositories include immutable owner/repository IDs in this claim.
            'OidcSubject': {'Type': 'String', 'AllowedPattern':
                r'(repo:zkp2p/peer-link|repo:zkp2p@[1-9][0-9]*/peer-link@[1-9][0-9]*):environment:peer-link-verification'},
        },
        'Resources': {
            'Role': {'Type': 'AWS::IAM::Role', 'Properties': {
                'RoleName': 'peer-link-github-invoke',
                'MaxSessionDuration': 3600,
                'AssumeRolePolicyDocument': policy([{
                    'Effect': 'Allow', 'Action': 'sts:AssumeRoleWithWebIdentity',
                    'Principal': {'Federated': sub('arn:${AWS::Partition}:iam::${AWS::AccountId}:oidc-provider/token.actions.githubusercontent.com')},
                    'Condition': {'StringEquals': {
                        'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
                        'token.actions.githubusercontent.com:sub': ref('OidcSubject'),
                    }},
                }]),
                'Policies': [{'PolicyName': 'InvokeReviewedVersionOnly', 'PolicyDocument': policy([
                    allow('lambda:InvokeFunction', version),
                    {'Effect': 'Deny', 'NotAction': 'lambda:InvokeFunction', 'Resource': '*'},
                    {'Effect': 'Deny', 'Action': 'lambda:InvokeFunction', 'NotResource': version},
                ])}],
                'Tags': [{'Key': 'Project', 'Value': 'peer-link'}],
            }},
        },
        'Outputs': {'RoleArn': {'Value': {'Fn::GetAtt': ['Role', 'Arn']}}},
    }


if __name__ == '__main__':
    print(json.dumps(template(), indent=2))
