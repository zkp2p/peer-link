"""Untrusted host relay: public metadata, ciphertext ingress and opaque TLS egress."""
import argparse
import functools
import ipaddress
import json
import re
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from .common import Rejected,canonical,require,strict_json
from .wire import MAX_WIRE,send,receive
from .storage import serve_archive

PUBLIC_GET={'/health':'health','/v1/campaigns':'campaigns','/v1/release':'release'}
PUBLIC_POST={'/v1/reservations':'reserve','/v1/challenges':'challenge','/v1/submissions':'submit','/v1/attest':'attest','/v1/operator':'operator'}


# Operational events. Each is one JSON line on stdout with fixed, public fields only:
# never a request or response body, ciphertext, payout address, client address or bank
# host chosen by a contributor. The host log shipper forwards these lines unchanged.
SAFE={'jobId':re.compile(r'[0-9a-f]{32}'),'campaignId':re.compile(r'[a-z0-9][a-z0-9-]{0,63}'),
      'state':re.compile(r'[a-z_]{1,32}'),'reportedState':re.compile(r'[a-z_]{1,32}'),
      'reason':re.compile(r'[a-z0-9_]{1,64}'),'error':re.compile(r'[a-z0-9_]{1,64}'),
      'provider':re.compile(r'[a-z_]{1,32}'),'model':re.compile(r'[A-Za-z0-9._:/@-]{1,100}'),
      'transactionId':re.compile(r'0x[0-9a-f]{64}'),'action':re.compile(r'[a-z]{1,16}')}
PROVIDER_HOSTS={'api.openai.com':'openai','openrouter.ai':'openrouter','cloud-api.near.ai':'near'}


def emit(event):
    try:print(json.dumps(event,sort_keys=True,separators=(',',':')),flush=True)
    except Exception:pass


def safe_fields(source,names):
    """The named fields of a dict whose values match their fixed public pattern."""
    found={}
    for name in names:
        value=source.get(name) if isinstance(source,dict) else None
        if isinstance(value,str) and SAFE[name].fullmatch(value):found[name]=value
    return found


def request_event(method,command,body,result,code,started,request_bytes,response_bytes):
    name=command['command'] if isinstance(command,dict) else 'unrouted'
    event={'event':'request','command':name,'method':method if method in ('GET','POST') else 'other','status':code,
           'ms':int((time.monotonic()-started)*1000),'requestBytes':request_bytes,'responseBytes':response_bytes}
    if isinstance(command,dict):event.update(safe_fields(command.get('body'),('jobId',)))
    if name=='reserve':event.update(safe_fields(body,('campaignId','provider','model')))
    if name=='operator':event.update(safe_fields(body.get('payload') if isinstance(body,dict) else None,('action',)))
    if name in {'reserve','submit','status','receipt','operator'}:
        # A signed receipt carries the job under payload.job; a status is the job itself.
        job=result.get('payload',{}).get('job') if isinstance(result,dict) and isinstance(result.get('payload'),dict) else result
        event.update(safe_fields(job,('jobId','campaignId','state','reportedState','reason','transactionId')))
    event.update(safe_fields(result,('error',)))
    if name=='health' and isinstance(result,dict) and type(result.get('accepting')) is bool:event['accepting']=result['accepting']
    return event


def egress_target(host,policy):
    """A public label for an egress destination: a fixed service host, the campaign's
    bank domain, a named model provider, or "other" for a contributor-chosen endpoint."""
    if not isinstance(host,str):return 'invalid'
    if host in PROVIDER_HOSTS:return PROVIDER_HOSTS[host]
    if host in policy.get('egressHosts',()):return host
    for campaign in policy.get('campaigns',()):
        for source in campaign.get('sources',()):
            domain=str(source.get('origin','')).removeprefix('https://')
            if 'openSource' in campaign and domain and (host==domain or host.endswith('.'+domain)):return domain
    return 'other'


def route(method,path,body):
    require('?' not in path and '%' not in path and len(path)<200,'route_not_found')
    if method=='GET' and path in PUBLIC_GET:return {'command':PUBLIC_GET[path],'body':{}}
    if method=='GET' and path.startswith('/v1/jobs/'):
        parts=path.split('/');require(len(parts) in (4,5),'route_not_found')
        job=parts[3];require(len(job)==32 and all(c in '0123456789abcdef' for c in job),'route_not_found')
        action='status' if len(parts)==4 else parts[4]
        require(action in {'status','artifact','receipt'},'route_not_found')
        return {'command':action,'body':{'jobId':job}}
    require(method=='POST' and path in PUBLIC_POST,'route_not_found')
    return {'command':PUBLIC_POST[path],'body':body}


def connect_public(host):
    addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    require(bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses),'egress_denied')
    # Connect to the validated numeric address, never resolve again between check/use.
    for family,kind,proto,_,address in addresses:
        sock=socket.socket(family,kind,proto);sock.settimeout(30)
        try:sock.connect(address);return sock
        except OSError:sock.close()
    raise Rejected('egress_unavailable')


HOSTNAME=re.compile(r'(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}')


def egress_permitted(host,allowed,public):
    # public: any DNS name on 443 whose every answer is a global address. The
    # relay only moves TLS bytes; the enclave decides what it sends and to whom.
    return isinstance(host,str) and (host in allowed or public and HOSTNAME.fullmatch(host) is not None)


def egress_connection(conn,allowed,public=False,policy=None):
    started=time.monotonic();host=None;count=0;outcome='error'
    try:
        conn.settimeout(10);line=bytearray()
        while not line.endswith(b'\n'):
            require(len(line)<512,'egress_denied')
            byte=conn.recv(1);require(bool(byte),'connection_closed');line.extend(byte)
        request=strict_json(bytes(line),512)
        host=request.get('host') if isinstance(request,dict) else None
        require(set(request)=={'host','port'} and egress_permitted(request['host'],allowed,public) and request['port']==443,'egress_denied')
        outcome='unavailable'
        with connect_public(request['host']) as upstream:
            conn.sendall(b'OK\n');conn.settimeout(30)
            outcome='idle'
            while True:
                ready,_,_=select.select([conn,upstream],[],[],30)
                if not ready:break
                for source in ready:
                    data=source.recv(65536)
                    if not data:outcome='closed';return
                    count+=len(data);require(count<=8_000_000,'egress_limit')
                    (upstream if source is conn else conn).sendall(data)
    except Rejected as error:
        if str(error) in {'egress_denied','egress_limit','egress_unavailable'}:outcome=str(error).removeprefix('egress_')
    except Exception:pass
    finally:
        conn.close()
        if policy is not None:
            emit({'event':'egress','target':egress_target(host,policy),'outcome':outcome,
                  'ms':int((time.monotonic()-started)*1000),'bytes':count})


def egress_server(port,cid,allowed,*,ready=None,public=False,policy=None):
    with socket.socket(socket.AF_VSOCK,socket.SOCK_STREAM) as listener:
        listener.bind((socket.VMADDR_CID_ANY,port));listener.listen(16)
        if ready is not None:ready.set()
        slots=threading.BoundedSemaphore(16)
        while True:
            conn,peer=listener.accept()
            if peer[0]!=cid or not slots.acquire(blocking=False):conn.close();continue
            def run(connection=conn):
                try:egress_connection(connection,allowed,public,policy)
                finally:slots.release()
            threading.Thread(target=run,daemon=True).start()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8080);parser.add_argument('--enclave-cid',type=int,default=16)
    parser.add_argument('--vsock-port',type=int,default=5100);parser.add_argument('--egress-port',type=int,default=5101)
    parser.add_argument('--archive-port',type=int,default=5102);parser.add_argument('--archive-dir',default='/var/lib/peer-link-transcripts/artifacts')
    parser.add_argument('--kms-port',type=int,default=5103)
    args=parser.parse_args()
    from .infra.listener_ready import notify_ready,start_listeners
    listeners=[(serve_archive,(args.archive_port,args.enclave_cid,args.archive_dir))]
    policy=json.loads((Path(__file__).parent/'policy.json').read_text())
    authority=policy.get('payoutAuthority',{})
    if authority.get('kind')=='aws_kms':
        from .kms_broker import KmsBroker,serve
        broker=KmsBroker(authority['keyId'],authority['wallet'])
        broker.public_key()  # Fail startup on a wrong key, wallet, or inaccessible role.
        listeners.append((serve,(args.kms_port,args.enclave_cid,broker)))
    listeners.append((functools.partial(egress_server,public=policy.get('egressPolicy')=='public_https',policy=policy),
                      (args.egress_port,args.enclave_cid,set(policy['egressHosts']))))
    start_listeners(listeners)
    slots=threading.BoundedSemaphore(20)
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_GET(self):self.invoke()
        def do_POST(self):self.invoke()
        def invoke(self):
            code=200;started=time.monotonic();command=body=None;length=0
            if not slots.acquire(blocking=False):
                emit({'event':'request','command':'busy','method':self.command if self.command in ('GET','POST') else 'other',
                      'status':503,'ms':0,'requestBytes':0,'responseBytes':0})
                self.send_error(503);return
            try:
                self.connection.settimeout(15)
                require(not self.headers.get('Transfer-Encoding'),'input_size')
                lengths=self.headers.get_all('Content-Length',[])
                require(len(lengths)<=1,'input_size')
                length=int(lengths[0]) if lengths else 0
                require(0<=length<=MAX_WIRE and (self.command=='POST' or length==0),'input_size')
                body=strict_json(self.rfile.read(length),MAX_WIRE) if length else {}
                command=route(self.command,self.path,body)
                with socket.socket(socket.AF_VSOCK,socket.SOCK_STREAM) as channel:
                    channel.settimeout(25);channel.connect((args.enclave_cid,args.vsock_port));send(channel,command);result=receive(channel)
                if 'error' in result:code=400
                elif command['command']=='submit':code=202
            except Exception:code,result=503,{'error':'service_unavailable'}
            finally:slots.release()
            data=canonical(result)
            # Local probes poll health every minute; only a change in the answer is worth a line.
            if not (isinstance(command,dict) and command['command']=='health' and code==200 and self.client_address[0]=='127.0.0.1'):
                emit(request_event(self.command,command,body,result,code,started,length,len(data)))
            self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    with ThreadingHTTPServer(('0.0.0.0',args.port),Handler) as http:
        notify_ready()
        http.serve_forever()

if __name__=='__main__':main()
