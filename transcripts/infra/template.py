"""Dedicated transcript pilot, with no production secret access or SSH.

Generate with python3 transcripts/infra/template.py > transcripts/infra/pilot.cfn.json.
This provisions infrastructure only. No EIF, release approval or secrets are seeded.
"""
import json


def ref(name):
    return {"Ref": name}


def sub(value):
    return {"Fn::Sub": value}


def arn(name):
    return {"Fn::GetAtt": [name, "Arn"]}


def template():
    ssm = ["ssm:UpdateInstanceInformation", "ssmmessages:CreateControlChannel",
           "ssmmessages:CreateDataChannel", "ssmmessages:OpenControlChannel",
           "ssmmessages:OpenDataChannel", "ec2messages:AcknowledgeMessage",
           "ec2messages:DeleteMessage", "ec2messages:FailMessage",
           "ec2messages:GetEndpoint", "ec2messages:GetMessages", "ec2messages:SendReply"]
    params = {
        "VpcId": {"Type": "AWS::EC2::VPC::Id"},
        "SubnetId": {"Type": "AWS::EC2::Subnet::Id", "Description": "Public IPv4 subnet in VpcId, with an Internet Gateway route"},
        "ImageId": {"Type": "AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>", "Default": "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"},
        "LifetimeHours": {"Type": "Number", "Default": 24, "MinValue": 1, "MaxValue": 168, "Description": "Stop this host after this supervised pilot lifetime; no automatic restart"},
        "AlarmTopicArn": {"Type": "String", "Default": "", "AllowedPattern": "(arn:[a-z-]+:sns:[a-z0-9-]+:[0-9]{12}:[A-Za-z0-9_-]{1,256})?", "Description": "Existing SNS topic with a confirmed and tested subscription; empty means operator-supervised alarms only"},
        "PayoutKmsKeyArn": {"Type": "String", "Default": "", "AllowedPattern": "(arn:(aws|aws-us-gov|aws-cn):kms:[a-z0-9-]+:[0-9]{12}:key/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|mrk-[0-9a-f]{32}))?", "Description": "Exact dedicated nonexportable ECC_SECG_P256K1 SIGN_VERIFY key; authorized host/operator custody, no native PCR authorization for KMS Sign"},
    }
    tags = [{"Key": "Project", "Value": "peer-link-transcripts"}, {"Key": "Environment", "Value": "pilot"}]
    action = {"Fn::If": ["HasAlarmTopic", [ref("AlarmTopicArn")], ref("AWS::NoValue")]}
    startup = """#!/bin/bash
set -euo pipefail
umask 077
trap 'shutdown -h now' ERR
dnf install -y aws-nitro-enclaves-cli-1.5.0 aws-nitro-enclaves-cli-devel-1.5.0 docker python3.11 python3.11-pip
test "$(nitro-cli --version)" = "Nitro CLI 1.5.0"
systemctl enable --now amazon-ssm-agent docker
printf '%s\\n' '---' 'memory_mib: 2048' 'cpu_count: 2' > /etc/nitro_enclaves/allocator.yaml
systemctl enable --now nitro-enclaves-allocator.service
install -d -m 700 /opt/peer-link-transcripts/releases /opt/peer-link-transcripts/build
# Deliberately no application listener until an operator installs a checked EIF.
"""
    r = {}
    r["HostRole"] = {"Type": "AWS::IAM::Role", "Properties": {
        "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
        "Tags": tags,
        "Policies": [{"PolicyName": "SSMAndPayoutKmsOnly", "PolicyDocument": {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": ssm, "Resource": "*"},
            {"Fn::If": ["HasPayoutKmsKey", {"Effect": "Allow", "Action": ["kms:GetPublicKey", "kms:Sign"], "Resource": ref("PayoutKmsKeyArn")}, ref("AWS::NoValue")]},
            {"Effect": "Deny", "NotAction": {"Fn::If": ["HasPayoutKmsKey", ssm + ["kms:GetPublicKey", "kms:Sign"], ssm]}, "Resource": "*"},
            {"Fn::If": ["HasPayoutKmsKey", {"Effect": "Deny", "Action": ["kms:GetPublicKey", "kms:Sign"], "NotResource": ref("PayoutKmsKeyArn")}, ref("AWS::NoValue")]},
        ]}}],
    }}
    r["HostProfile"] = {"Type": "AWS::IAM::InstanceProfile", "Properties": {"Roles": [ref("HostRole")]}}
    r["HostGroup"] = {"Type": "AWS::EC2::SecurityGroup", "Properties": {
        "VpcId": ref("VpcId"), "GroupDescription": "Ciphertext HTTP relay only; SSM administration, no SSH",
        "SecurityGroupIngress": [{"IpProtocol": "tcp", "FromPort": 8080, "ToPort": 8080, "CidrIp": "0.0.0.0/0", "Description": "Opaque application-encrypted API envelopes and public metadata"}],
        "SecurityGroupEgress": [{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIp": "0.0.0.0/0"}], "Tags": tags,
    }}
    r["Host"] = {"Type": "AWS::EC2::Instance", "DependsOn": ["ExpirySchedule", "ExpiryPermission"], "Properties": {
        "ImageId": ref("ImageId"), "InstanceType": "c6i.xlarge", "IamInstanceProfile": ref("HostProfile"),
        "EnclaveOptions": {"Enabled": True}, "MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 1},
        "InstanceInitiatedShutdownBehavior": "stop",
        "BlockDeviceMappings": [{"DeviceName": "/dev/xvda", "Ebs": {"VolumeSize": 32, "VolumeType": "gp3", "Encrypted": True, "DeleteOnTermination": True}}],
        "NetworkInterfaces": [{"DeviceIndex": "0", "AssociatePublicIpAddress": True, "SubnetId": ref("SubnetId"), "GroupSet": [ref("HostGroup")]}],
        "Tags": tags + [{"Key": "Name", "Value": sub("${AWS::StackName}-nitro")}],
        "UserData": {"Fn::Base64": startup},
    }}
    r["HostAddress"] = {"Type": "AWS::EC2::EIP", "Properties": {"Domain": "vpc", "InstanceId": ref("Host"), "Tags": tags}}
    r["Api"] = {"Type": "AWS::ApiGatewayV2::Api", "Properties": {"Name": sub("${AWS::StackName}-encrypted-api"), "ProtocolType": "HTTP", "Description": "Application ciphertext plus public attestation/status only; no bank or inference plaintext"}}
    r["ApiIntegration"] = {"Type": "AWS::ApiGatewayV2::Integration", "Properties": {
        "ApiId": ref("Api"), "IntegrationType": "HTTP_PROXY", "IntegrationMethod": "ANY",
        "IntegrationUri": sub("http://${HostAddress}:8080"), "PayloadFormatVersion": "1.0", "TimeoutInMillis": 29000,
    }}
    r["ApiRoute"] = {"Type": "AWS::ApiGatewayV2::Route", "Properties": {"ApiId": ref("Api"), "RouteKey": "$default", "Target": sub("integrations/${ApiIntegration}")}}
    r["ApiStage"] = {"Type": "AWS::ApiGatewayV2::Stage", "Properties": {
        "ApiId": ref("Api"), "StageName": "$default", "AutoDeploy": True,
        "DefaultRouteSettings": {"DetailedMetricsEnabled": True, "ThrottlingBurstLimit": 5, "ThrottlingRateLimit": 2},
        # No access logs, HTTP bodies or key-bearing headers in CloudWatch.
    }}
    r["ExpiryRole"] = {"Type": "AWS::IAM::Role", "Properties": {
        "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
        "Policies": [{"PolicyName": "StopOnlyThisStack", "PolicyDocument": {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": "ec2:DescribeInstances", "Resource": "*"},
            {"Effect": "Allow", "Action": "ec2:StopInstances", "Resource": sub("arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:instance/*"), "Condition": {"StringEquals": {"ec2:ResourceTag/aws:cloudformation:stack-id": ref("AWS::StackId")}}},
        ]}}],
    }}
    expiry = """import boto3, datetime, os
def handler(event, context):
    ec2 = boto3.client('ec2')
    rows = ec2.describe_instances(Filters=[{'Name':'tag:aws:cloudformation:stack-id','Values':[os.environ['STACK_ID']]},{'Name':'instance-state-name','Values':['running']}])
    now = datetime.datetime.now(datetime.timezone.utc)
    expired = [i['InstanceId'] for r in rows['Reservations'] for i in r['Instances'] if (now-i['LaunchTime']).total_seconds() >= int(os.environ['LIFETIME_HOURS'])*3600]
    if expired: ec2.stop_instances(InstanceIds=expired)
    return {'stopped':len(expired)}
"""
    r["Expiry"] = {"Type": "AWS::Lambda::Function", "Properties": {"Runtime": "python3.12", "Handler": "index.handler", "Role": arn("ExpiryRole"), "Timeout": 30, "MemorySize": 128, "Environment": {"Variables": {"STACK_ID": ref("AWS::StackId"), "LIFETIME_HOURS": ref("LifetimeHours")}}, "Code": {"ZipFile": expiry}}}
    r["ExpirySchedule"] = {"Type": "AWS::Events::Rule", "Properties": {"ScheduleExpression": "rate(5 minutes)", "State": "ENABLED", "Targets": [{"Arn": arn("Expiry"), "Id": "StopExpiredPilot", "RetryPolicy": {"MaximumRetryAttempts": 2, "MaximumEventAgeInSeconds": 300}}]}}
    r["ExpiryPermission"] = {"Type": "AWS::Lambda::Permission", "Properties": {"FunctionName": ref("Expiry"), "Action": "lambda:InvokeFunction", "Principal": "events.amazonaws.com", "SourceArn": arn("ExpirySchedule"), "SourceAccount": ref("AWS::AccountId")}}
    for name, namespace, metric, dimensions in [
        ("HostHealth", "AWS/EC2", "StatusCheckFailed", [{"Name": "InstanceId", "Value": ref("Host")}]),
        ("ApiErrors", "AWS/ApiGateway", "5xx", [{"Name": "ApiId", "Value": ref("Api")}]),
        ("ExpiryErrors", "AWS/Lambda", "Errors", [{"Name": "FunctionName", "Value": ref("Expiry")}]),
    ]:
        r[name] = {"Type": "AWS::CloudWatch::Alarm", "Properties": {"AlarmDescription": "Inspect only this transcript stack. No automatic reboot or live-wallet restore.", "Namespace": namespace, "MetricName": metric, "Dimensions": dimensions, "Statistic": "Sum", "Period": 300, "EvaluationPeriods": 1, "Threshold": 1, "ComparisonOperator": "GreaterThanOrEqualToThreshold", "TreatMissingData": "notBreaching", "AlarmActions": action}}
    r["ExpiryNotRunning"] = {"Type": "AWS::CloudWatch::Alarm", "Properties": {
        "Metrics": [{"Id": "calls", "MetricStat": {"Metric": {"Namespace": "AWS/Lambda", "MetricName": "Invocations", "Dimensions": [{"Name": "FunctionName", "Value": ref("Expiry")}]}, "Period": 300, "Stat": "Sum"}, "ReturnData": False}, {"Id": "heartbeat", "Expression": "FILL(calls, 0)", "ReturnData": True}],
        "EvaluationPeriods": 3, "DatapointsToAlarm": 3, "Threshold": 1, "ComparisonOperator": "LessThanThreshold", "TreatMissingData": "breaching", "AlarmActions": action,
    }}
    return {"AWSTemplateFormatVersion": "2010-09-09", "Description": "Dedicated PeerLink Nitro transcript pilot, SSM administration, encrypted-envelope HTTPS ingress; optional exact-key KMS operator custody", "Parameters": params, "Conditions": {"HasAlarmTopic": {"Fn::Not": [{"Fn::Equals": [ref("AlarmTopicArn"), ""]}]}, "HasPayoutKmsKey": {"Fn::Not": [{"Fn::Equals": [ref("PayoutKmsKeyArn"), ""]}]}}, "Resources": r,
            "Outputs": {"InstanceId": {"Value": ref("Host")}, "ApiUrl": {"Value": {"Fn::GetAtt": ["Api", "ApiEndpoint"]}}, "RelayAddress": {"Value": sub("http://${HostAddress}:8080")}, "HostRoleArn": {"Value": arn("HostRole")}, "ExpiryFunction": {"Value": ref("Expiry")}}}


if __name__ == "__main__":
    print(json.dumps(template(), indent=2))
