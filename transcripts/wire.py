"""Bounded JSON framing; no pickle, shell commands or raw exception responses."""
import struct
from .common import canonical, require, strict_json
MAX_WIRE = 3_000_000

def exact(sock,length):
    chunks=[]
    while length:
        data=sock.recv(min(length,65536))
        require(bool(data),'connection_closed')
        chunks.append(data);length-=len(data)
    return b''.join(chunks)

def receive(sock):
    length=struct.unpack('!I',exact(sock,4))[0]
    require(0<length<=MAX_WIRE,'input_size')
    return strict_json(exact(sock,length),MAX_WIRE)

def send(sock,value):
    data=canonical(value);require(len(data)<=MAX_WIRE,'output_size')
    sock.sendall(struct.pack('!I',len(data))+data)
