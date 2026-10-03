"""Generate the fixed manual-controller stack; no credentials or source fetching.

Requires a private, versioned worker bundle with a reviewed SHA-256. Deploy disabled,
seed the single global budget including earlier costs, and verify protected GitHub
controls before enabling invocation. Bank sessions never reach these Lambdas.
"""
import json
from pathlib import Path

def ref(name):return {'Ref':name}
def sub(value):return {'Fn::Sub':value}
def arn(name):return {'Fn::GetAtt':[name,'Arn']}
def policy(statements):return {'Version':'2012-10-17','Statement':statements}
def trust(service):return policy([{'Effect':'Allow','Principal':{'Service':service},'Action':'sts:AssumeRole'}])
def allow(actions,resource,**extra):return {'Effect':'Allow','Action':actions,'Resource':resource,**extra}

def template():
 r={}
 params={name:{'Type':'String'} for name in ['VpcId','SubnetId','ArtifactBucket','ArtifactKey','ArtifactVersion','ArtifactSha256','ReleaseDigest']}
 for name in ['ArtifactSha256','ReleaseDigest']:params[name]['AllowedPattern']='[a-f0-9]{64}'
 params['LedgerTableName']={'Type':'String','Default':'','AllowedPattern':'([A-Za-z0-9_.-]{3,255})?'}
 params['ControllerName']={'Type':'String','Default':'peer-link-manual-launch','AllowedPattern':'peer-link-[a-z0-9-]{1,48}'}
 params['DispatchEnabled']={'Type':'String','Default':'false','AllowedValues':['false','true']}
 params['ImageId']={'Type':'AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>','Default':'/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64'}
 # Optional existing SNS topic with a tested, confirmed subscription. Empty means no route.
 params['AlarmTopicArn']={'Type':'String','Default':'','AllowedPattern':'(arn:aws:sns:[a-z0-9-]+:[0-9]{12}:[A-Za-z0-9_-]{1,256})?'}
 conditions={'CreateLedger':{'Fn::Equals':[ref('LedgerTableName'),'']},'HasAlarmTopic':{'Fn::Not':[{'Fn::Equals':[ref('AlarmTopicArn'),'']}]}}
 alarm_actions={'Fn::If':['HasAlarmTopic',[ref('AlarmTopicArn')],ref('AWS::NoValue')]}
 table={'Fn::If':['CreateLedger',ref('Ledger'),ref('LedgerTableName')]}
 table_arn={'Fn::If':['CreateLedger',arn('Ledger'),sub('arn:${AWS::Partition}:dynamodb:${AWS::Region}:${AWS::AccountId}:table/${LedgerTableName}')]}
 # The ledger is the durable $50/concurrency authority: guard against deletion and overwrite.
 r['Ledger']={'Type':'AWS::DynamoDB::Table','Condition':'CreateLedger','DeletionPolicy':'Retain','UpdateReplacePolicy':'Retain','Properties':{'BillingMode':'PAY_PER_REQUEST','AttributeDefinitions':[{'AttributeName':'id','AttributeType':'S'}],'KeySchema':[{'AttributeName':'id','KeyType':'HASH'}],'SSESpecification':{'SSEEnabled':True},'DeletionProtectionEnabled':True,'PointInTimeRecoverySpecification':{'PointInTimeRecoveryEnabled':True}}}
 ssm=['ssm:UpdateInstanceInformation','ssmmessages:CreateControlChannel','ssmmessages:CreateDataChannel','ssmmessages:OpenControlChannel','ssmmessages:OpenDataChannel','ec2messages:AcknowledgeMessage','ec2messages:DeleteMessage','ec2messages:FailMessage','ec2messages:GetEndpoint','ec2messages:GetMessages','ec2messages:SendReply']
 bundle=sub('arn:${AWS::Partition}:s3:::${ArtifactBucket}/${ArtifactKey}')
 # The account is shared with Peer production. Explicit denies stop any resource policy
 # (S3, SQS, SNS, Lambda, ECR, ...) that names this role or "*" from widening it.
 host_policy=[allow(ssm,'*'),allow('s3:GetObjectVersion',bundle,Condition={'StringEquals':{'s3:VersionId':ref('ArtifactVersion')}}),{'Effect':'Deny','Action':['ssm:GetParameter*','secretsmanager:*','kms:*','sts:AssumeRole','iam:*'],'Resource':'*'},{'Effect':'Deny','NotAction':ssm+['s3:GetObjectVersion'],'Resource':'*'},{'Effect':'Deny','Action':'s3:*','NotResource':bundle}]
 # An Allow condition is only an implicit deny for other versions. A same-account
 # bucket policy can grant them, so explicitly reject every unapproved version.
 host_policy.append({'Effect':'Deny','Action':'s3:GetObjectVersion','Resource':bundle,'Condition':{'StringNotEquals':{'s3:VersionId':ref('ArtifactVersion')}}})
 r['HostRole']={'Type':'AWS::IAM::Role','Properties':{'AssumeRolePolicyDocument':trust('ec2.amazonaws.com'),'Policies':[{'PolicyName':'OnlyApprovedWorkerAndSessionTransport','PolicyDocument':policy(host_policy)}]}}
 r['HostProfile']={'Type':'AWS::IAM::InstanceProfile','Properties':{'Roles':[ref('HostRole')]}}
 r['WorkerGroup']={'Type':'AWS::EC2::SecurityGroup','Properties':{'VpcId':ref('VpcId'),'GroupDescription':'Peer Link manual worker: no ingress, outbound TLS only','SecurityGroupEgress':[{'IpProtocol':'tcp','FromPort':443,'ToPort':443,'CidrIp':'0.0.0.0/0'}]}}
 startup='''#!/bin/bash
set -euo pipefail
umask 077
shutdown -h +110
trap 'shutdown -h now' ERR
dnf install -y aws-nitro-enclaves-cli-1.5.0 aws-nitro-enclaves-cli-devel-1.5.0 python3.11 python3.11-pip
printf '%s\\n' '---' 'memory_mib: 2048' 'cpu_count: 2' > /etc/nitro_enclaves/allocator.yaml
systemctl enable --now nitro-enclaves-allocator.service
install -d -m 700 /opt/peer-link
cd /opt/peer-link
aws s3api get-object --region ${AWS::Region} --bucket '${ArtifactBucket}' --key '${ArtifactKey}' --version-id '${ArtifactVersion}' worker.tar.gz >/dev/null
echo '${ArtifactSha256}  worker.tar.gz' | sha256sum -c -
tar --no-same-owner -xzf worker.tar.gz
python3.11 -m venv venv
venv/bin/pip install --disable-pip-version-check --no-cache-dir -r verification/requirements.lock -r verification/requirements-sandbox.lock
nitro-cli run-enclave --eif-path synthetic.eif --cpu-count 2 --memory 2048 --enclave-cid 16 > enclave.json
nohup venv/bin/python -m verification.relay --enclave-cid 16 </dev/null >/dev/null 2>&1 &
nohup venv/bin/python -m verification.parent_gateway --cid 16 --port 8443 </dev/null >/dev/null 2>&1 &
'''
 # Parameter strings enter a shell only after CFN validation. Object coordinates
 # have a restricted alphabet, never caller-supplied runtime inputs.
 for name,pattern in [('ArtifactBucket','[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]'),('ArtifactKey','[A-Za-z0-9/_-]+[.]tar[.]gz'),('ArtifactVersion','[-A-Za-z0-9._/+=]+')]:params[name]['AllowedPattern']=pattern
 tags=[{'Key':'Project','Value':'peer-link'},{'Key':'PeerLinkControlStack','Value':ref('AWS::StackId')}]
 r['WorkerTemplate']={'Type':'AWS::EC2::LaunchTemplate','Properties':{'LaunchTemplateData':{'ImageId':ref('ImageId'),'InstanceType':'c6i.xlarge','IamInstanceProfile':{'Arn':{'Fn::GetAtt':['HostProfile','Arn']}},'EnclaveOptions':{'Enabled':True},'MetadataOptions':{'HttpTokens':'required','HttpPutResponseHopLimit':1},'InstanceInitiatedShutdownBehavior':'terminate','BlockDeviceMappings':[{'DeviceName':'/dev/xvda','Ebs':{'VolumeSize':24,'VolumeType':'gp3','Encrypted':True,'DeleteOnTermination':True}}],'NetworkInterfaces':[{'DeviceIndex':0,'AssociatePublicIpAddress':True,'SubnetId':ref('SubnetId'),'Groups':[ref('WorkerGroup')]}],'TagSpecifications':[{'ResourceType':kind,'Tags':tags} for kind in ['instance','volume']],'UserData':{'Fn::Base64':sub(startup)}}}}
 lt_arn=sub('arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:launch-template/${WorkerTemplate}')
 controller_policy=[allow(['dynamodb:GetItem','dynamodb:PutItem','dynamodb:UpdateItem','dynamodb:ConditionCheckItem'],table_arn),allow('iam:PassRole',arn('HostRole'),Condition={'StringEquals':{'iam:PassedToService':'ec2.amazonaws.com'}}),allow('ec2:RunInstances','*',Condition={'ArnEquals':{'ec2:LaunchTemplate':lt_arn},'StringEqualsIfExists':{'ec2:InstanceType':'c6i.xlarge'}}),allow('ec2:CreateTags',sub('arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:*/*'),Condition={'StringEquals':{'ec2:CreateAction':'RunInstances','aws:RequestTag/Project':'peer-link'}})]
 r['ControllerRole']={'Type':'AWS::IAM::Role','Properties':{'AssumeRolePolicyDocument':trust('lambda.amazonaws.com'),'Policies':[{'PolicyName':'FixedTemplateAndLedgerOnly','PolicyDocument':policy(controller_policy)}]}}
 r['Controller']={'Type':'AWS::Lambda::Function','Properties':{'FunctionName':ref('ControllerName'),'Runtime':'python3.12','Handler':'index.handler','Role':arn('ControllerRole'),'Timeout':30,'MemorySize':128,'Environment':{'Variables':{'TABLE':table,'LAUNCH_TEMPLATE':ref('WorkerTemplate'),'TEMPLATE_VERSION':{'Fn::GetAtt':['WorkerTemplate','LatestVersionNumber']},'RELEASE_DIGEST':ref('ReleaseDigest'),'DISPATCH_ENABLED':ref('DispatchEnabled')}},'Code':{'ZipFile':Path(__file__).with_name('launch_controller.py').read_text()}}}
 expiry='''import boto3,datetime,os,time

def handler(event,context):
 ec2=boto3.client('ec2');ddb=boto3.client('dynamodb');table=os.environ['TABLE']
 response=ec2.describe_instances(Filters=[{'Name':'tag:PeerLinkControlStack','Values':[os.environ['STACK_ID']]},{'Name':'instance-state-name','Values':['pending','running','stopping','stopped']}])
 now=datetime.datetime.now(datetime.timezone.utc)
 active=[i for r in response['Reservations'] for i in r['Instances']]
 expired=[i['InstanceId'] for i in active if (now-i['LaunchTime']).total_seconds()>6600 or i['State']['Name'] in ('stopping','stopped')]
 if expired:ec2.terminate_instances(InstanceIds=expired)
 lease=ddb.get_item(TableName=table,Key={'id':{'S':'active'}},ConsistentRead=True).get('Item')
 if lease and not active:
  done=int(lease['expiresAt']['N'])<time.time()
  if 'instanceId' in lease:
   try:
    status=ec2.describe_instances(InstanceIds=[lease['instanceId']['S']])['Reservations'][0]['Instances'][0]
    done=status['State']['Name']=='terminated'
   except ec2.exceptions.ClientError as error:
    # Terminated records age out of EC2 (~1h); a new ID can also be briefly unknown.
    # Treat unknown as gone only after the lease lifetime, never earlier.
    if error.response['Error']['Code']!='InvalidInstanceID.NotFound':raise
  if done:ddb.delete_item(TableName=table,Key={'id':{'S':'active'}},ConditionExpression='approvalId = :approval',ExpressionAttributeValues={':approval':lease['approvalId']})
 return {'terminated':len(expired),'active':len(active)}
'''
 r['ExpiryRole']={'Type':'AWS::IAM::Role','Properties':{'AssumeRolePolicyDocument':trust('lambda.amazonaws.com'),'Policies':[{'PolicyName':'ReconcileOnlyThisController','PolicyDocument':policy([allow('ec2:DescribeInstances','*'),allow('ec2:TerminateInstances',sub('arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:instance/*'),Condition={'StringEquals':{'ec2:ResourceTag/PeerLinkControlStack':ref('AWS::StackId')}}),allow(['dynamodb:GetItem','dynamodb:DeleteItem'],table_arn,Condition={'ForAllValues:StringEquals':{'dynamodb:LeadingKeys':['active']}})])}]}}
 r['Expiry']={'Type':'AWS::Lambda::Function','Properties':{'Runtime':'python3.12','Handler':'index.handler','Role':arn('ExpiryRole'),'Timeout':30,'MemorySize':128,'Environment':{'Variables':{'TABLE':table,'STACK_ID':ref('AWS::StackId')}},'Code':{'ZipFile':expiry}}}
 r['Schedule']={'Type':'AWS::Events::Rule','Properties':{'ScheduleExpression':'rate(5 minutes)','State':'ENABLED','Targets':[{'Arn':arn('Expiry'),'Id':'ExpireWorkers','RetryPolicy':{'MaximumRetryAttempts':2,'MaximumEventAgeInSeconds':300}}]}}
 r['ExpiryPermission']={'Type':'AWS::Lambda::Permission','Properties':{'FunctionName':ref('Expiry'),'Action':'lambda:InvokeFunction','Principal':'events.amazonaws.com','SourceArn':arn('Schedule'),'SourceAccount':ref('AWS::AccountId')}}
 r['ExpiryErrors']={'Type':'AWS::CloudWatch::Alarm','Properties':{'Namespace':'AWS/Lambda','MetricName':'Errors','Dimensions':[{'Name':'FunctionName','Value':ref('Expiry')}],'Statistic':'Sum','Period':300,'EvaluationPeriods':1,'Threshold':1,'ComparisonOperator':'GreaterThanOrEqualToThreshold','TreatMissingData':'notBreaching','AlarmActions':alarm_actions}}
 # A disabled/deleted schedule or throttled reaper emits no Errors; alarm on silence too.
 # Sparse metrics can retain old healthy datapoints beyond the evaluation window.
 # Fill each missing interval with zero so a stopped reaper cannot appear healthy.
 heartbeat=[{'Id':'invocations','MetricStat':{'Metric':{'Namespace':'AWS/Lambda','MetricName':'Invocations','Dimensions':[{'Name':'FunctionName','Value':ref('Expiry')}]},'Period':300,'Stat':'Sum'},'ReturnData':False},{'Id':'heartbeat','Expression':'FILL(invocations, 0)','ReturnData':True}]
 r['ExpiryNotRunning']={'Type':'AWS::CloudWatch::Alarm','Properties':{'Metrics':heartbeat,'EvaluationPeriods':3,'DatapointsToAlarm':3,'Threshold':1,'ComparisonOperator':'LessThanThreshold','TreatMissingData':'breaching','AlarmActions':alarm_actions}}
 return {'AWSTemplateFormatVersion':'2010-09-09','Description':'Peer Link isolated manual controller; disabled by default. No bank credentials.','Parameters':params,'Conditions':conditions,'Resources':r,'Outputs':{'Table':{'Value':table},'Controller':{'Value':ref('Controller')},'Expiry':{'Value':ref('Expiry')},'Template':{'Value':ref('WorkerTemplate')}}}

if __name__=='__main__':print(json.dumps(template(),indent=2))
