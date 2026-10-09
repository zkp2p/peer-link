"""Persist only signed redacted artifacts; the host is an availability dependency."""
import os
import socket
import threading
from pathlib import Path
from .common import canonical,digest,fields,require
from .wire import receive,send

class ArchiveClient:
    def __init__(self,port=5102):self.port=port
    def persist(self,record):
        expected=digest(record)
        with socket.socket(socket.AF_VSOCK,socket.SOCK_STREAM) as connection:
            connection.settimeout(15);connection.connect((3,self.port))
            send(connection,{'digest':expected,'record':record});reply=receive(connection)
        require(reply=={'stored':expected},'storage_unavailable')
        return expected

def serve_archive(port,cid,directory,*,ready=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    with socket.socket(socket.AF_VSOCK,socket.SOCK_STREAM) as server:
        server.bind((socket.VMADDR_CID_ANY,port));server.listen(8)
        if ready is not None:ready.set()
        while True:
            connection,peer=server.accept()
            with connection:
                try:
                    require(peer[0]==cid,'storage_unavailable');connection.settimeout(15)
                    request=receive(connection);fields(request,{'digest','record'})
                    actual=digest(request['record']);require(request['digest']==actual,'storage_unavailable')
                    payload=canonical(request['record']);require(len(payload)<=1_100_000,'storage_unavailable')
                    target=directory/(actual+'.json')
                    if target.exists():require(target.read_bytes()==payload,'storage_unavailable')
                    else:
                        temporary=directory/(actual+'.tmp')
                        with open(temporary,'wb') as output:
                            output.write(payload);output.flush();os.fsync(output.fileno())
                        os.replace(temporary,target)
                        fd=os.open(directory,os.O_RDONLY)
                        try:os.fsync(fd)
                        finally:os.close(fd)
                    send(connection,{'stored':actual})
                except Exception:
                    try:send(connection,{'error':'storage_unavailable'})
                    except Exception:pass
