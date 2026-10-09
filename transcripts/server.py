"""Untrusted host relay: public metadata, ciphertext ingress and opaque TLS egress."""
import argparse
import ipaddress
import json
import select
import socket
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from .common import Rejected,canonical,require,strict_json
from .wire import MAX_WIRE,send,receive
from .storage import serve_archive

PUBLIC_GET={'/health':'health','/v1/campaigns':'campaigns','/v1/release':'release'}
PUBLIC_POST={'/v1/reservations':'reserve','/v1/challenges':'challenge','/v1/submissions':'submit','/v1/attest':'attest','/v1/operator':'operator'}


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


def egress_connection(conn,allowed):
    try:
        conn.settimeout(10);line=bytearray()
        while not line.endswith(b'\n'):
            require(len(line)<512,'egress_denied')
            byte=conn.recv(1);require(bool(byte),'connection_closed');line.extend(byte)
        request=strict_json(bytes(line),512)
        require(set(request)=={'host','port'} and request['host'] in allowed and request['port']==443,'egress_denied')
        with connect_public(request['host']) as upstream:
            conn.sendall(b'OK\n');conn.settimeout(30)
            count=0
            while True:
                ready,_,_=select.select([conn,upstream],[],[],30)
                if not ready:break
                for source in ready:
                    data=source.recv(65536)
                    if not data:return
                    count+=len(data);require(count<=8_000_000,'egress_limit')
                    (upstream if source is conn else conn).sendall(data)
    except Exception:pass
    finally:conn.close()


def egress_server(port,cid,allowed):
    with socket.socket(socket.AF_VSOCK,socket.SOCK_STREAM) as listener:
        listener.bind((socket.VMADDR_CID_ANY,port));listener.listen(16)
        slots=threading.BoundedSemaphore(16)
        while True:
            conn,peer=listener.accept()
            if peer[0]!=cid or not slots.acquire(blocking=False):conn.close();continue
            def run(connection=conn):
                try:egress_connection(connection,allowed)
                finally:slots.release()
            threading.Thread(target=run,daemon=True).start()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8080);parser.add_argument('--enclave-cid',type=int,default=16)
    parser.add_argument('--vsock-port',type=int,default=5100);parser.add_argument('--egress-port',type=int,default=5101)
    parser.add_argument('--archive-port',type=int,default=5102);parser.add_argument('--archive-dir',default='/var/lib/peer-link-transcripts/artifacts')
    parser.add_argument('--kms-port',type=int,default=5103)
    args=parser.parse_args()
    threading.Thread(target=serve_archive,args=(args.archive_port,args.enclave_cid,args.archive_dir),daemon=True).start()
    policy=json.loads((Path(__file__).parent/'policy.json').read_text())
    authority=policy.get('payoutAuthority',{})
    if authority.get('kind')=='aws_kms':
        from .kms_broker import KmsBroker,serve
        broker=KmsBroker(authority['keyId'],authority['wallet'])
        broker.public_key()  # Fail startup on a wrong key, wallet, or inaccessible role.
        threading.Thread(target=serve,args=(args.kms_port,args.enclave_cid,broker),daemon=True).start()
    threading.Thread(target=egress_server,args=(args.egress_port,args.enclave_cid,set(policy['egressHosts'])),daemon=True).start()
    slots=threading.BoundedSemaphore(20)
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_GET(self):self.invoke()
        def do_POST(self):self.invoke()
        def invoke(self):
            code=200
            if not slots.acquire(blocking=False):
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
            self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    ThreadingHTTPServer(('0.0.0.0',args.port),Handler).serve_forever()

if __name__=='__main__':main()
