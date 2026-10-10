"""Log group and Axiom forwarder for the transcript host's payload-free service logs.

Generate with python3 transcripts/infra/logs_template.py > transcripts/infra/logs.cfn.json.
The host writes to the group with its instance role; a Lambda outside the host forwards
the group to Axiom. Host write access is a separate reviewed additive change to the
dedicated transcript host role (see host_statements).
"""
import json
from pathlib import Path

HOST_ACTIONS = ["logs:CreateLogStream", "logs:PutLogEvents"]


def host_statements(group_arn):
    """Exact write-only statements appended to the dedicated host role policy.

    The role's catch-all DenyNotAction list must also include HOST_ACTIONS. No read,
    filter or delete action is granted: a compromised host can add lines to this one
    group and nothing else.
    """
    resources = [group_arn, group_arn + ":*"]
    return [
        {"Sid": "WriteOnlyHostLogs", "Effect": "Allow", "Action": HOST_ACTIONS, "Resource": resources},
        {"Sid": "DenyOtherLogWrites", "Effect": "Deny", "Action": HOST_ACTIONS, "NotResource": resources},
    ]


def template():
    ref = lambda name: {"Ref": name}
    arn = lambda name: {"Fn::GetAtt": [name, "Arn"]}
    tags = [{"Key": "Project", "Value": "peer-link-transcripts"}, {"Key": "Component", "Value": "service-logs"}]
    source = Path(__file__).with_name("axiom_forwarder.py").read_text()
    assert len(source) <= 4096, "inline Lambda code is limited to 4096 characters"
    parameters = {
        "LogGroupName": {"Type": "String", "Default": "/peerlink/transcripts/host", "AllowedPattern": "/[A-Za-z0-9/_-]{1,200}"},
        "RetentionDays": {"Type": "Number", "Default": 30, "AllowedValues": [7, 14, 30, 60, 90]},
        "AxiomUrl": {"Type": "String", "Default": "https://api.axiom.co", "AllowedPattern": "https://[a-z0-9.-]{4,100}"},
        "AxiomDataset": {"Type": "String", "AllowedPattern": "[a-z0-9][a-z0-9-]{1,62}"},
        "AxiomToken": {"Type": "String", "NoEcho": True, "MinLength": 20, "MaxLength": 200,
                       "Description": "Ingest-only Axiom API token scoped to AxiomDataset; never a personal token"},
    }
    resources = {
        "HostLogs": {"Type": "AWS::Logs::LogGroup", "Properties": {
            "LogGroupName": ref("LogGroupName"), "RetentionInDays": ref("RetentionDays"), "Tags": tags}},
        "ForwarderRole": {"Type": "AWS::IAM::Role", "Properties": {
            "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{
                "Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
            "ManagedPolicyArns": [{"Fn::Sub": "arn:${AWS::Partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"}],
            "Tags": tags}},
        "Forwarder": {"Type": "AWS::Lambda::Function", "Properties": {
            "Description": "Forward payload-free PeerLink transcript host logs to Axiom",
            "Runtime": "python3.12", "Handler": "index.handler", "Timeout": 20, "MemorySize": 128,
            "Role": arn("ForwarderRole"), "Code": {"ZipFile": source},
            "Environment": {"Variables": {"AXIOM_URL": ref("AxiomUrl"), "AXIOM_DATASET": ref("AxiomDataset"),
                                          "AXIOM_TOKEN": ref("AxiomToken")}},
            "Tags": tags}},
        "ForwarderPermission": {"Type": "AWS::Lambda::Permission", "Properties": {
            "Action": "lambda:InvokeFunction", "FunctionName": ref("Forwarder"), "Principal": "logs.amazonaws.com",
            "SourceArn": arn("HostLogs"), "SourceAccount": ref("AWS::AccountId")}},
        "Subscription": {"Type": "AWS::Logs::SubscriptionFilter", "DependsOn": "ForwarderPermission", "Properties": {
            "LogGroupName": ref("HostLogs"), "FilterPattern": "", "DestinationArn": arn("Forwarder")}},
    }
    return {"AWSTemplateFormatVersion": "2010-09-09",
            "Description": "Payload-free PeerLink transcript host logs: one CloudWatch group forwarded to Axiom; the host holds no Axiom token",
            "Parameters": parameters, "Resources": resources,
            "Outputs": {"LogGroupName": {"Value": ref("HostLogs")}, "LogGroupArn": {"Value": arn("HostLogs")},
                        "ForwarderName": {"Value": ref("Forwarder")}}}


if __name__ == "__main__":
    print(json.dumps(template(), indent=2))
