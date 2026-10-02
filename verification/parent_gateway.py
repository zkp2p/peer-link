"""Loopback-only opaque frame gateway for an operator-established SSM tunnel.

No plaintext session, signing authority, HTTP API or public listener. Run only
with the CID returned by the reviewed current enclave launch. No payload logs.
"""
import argparse
import socket
import struct
import time

# Longer than the enclave's worst execute (20 s bank reader + 10 s Wasm worker +
# signing/attestation) and shorter than owner_client.RESPONSE_SECONDS.
ENCLAVE_RESPONSE_SECONDS = 40


def frame(stream, maximum, timeout=5):
    end = time.monotonic() + timeout
    def exact(size):
        value = bytearray()
        while len(value) < size:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise ValueError('frame_timeout')
            stream.settimeout(remaining)
            piece = stream.recv(size - len(value))
            if not piece:
                raise ValueError('truncated_frame')
            value.extend(piece)
        return bytes(value)
    header = exact(4)
    size = struct.unpack('!I', header)[0]
    if not 0 < size <= maximum:
        raise ValueError('frame_size')
    return header + exact(size)


def serve(cid, port):
    if not 4 <= cid < 2**32 - 1 or not 1024 <= port <= 65535:
        raise ValueError('invalid_endpoint')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', port))
        listener.listen(4)
        while True:
            client, _ = listener.accept()
            with client:
                try:
                    client.settimeout(5)
                    request = frame(client, 3 * 1024 * 1024)
                    with socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM) as enclave:
                        enclave.settimeout(ENCLAVE_RESPONSE_SECONDS)
                        enclave.connect((cid, 5000))
                        enclave.sendall(request)
                        client.sendall(frame(enclave, 65536, ENCLAVE_RESPONSE_SECONDS))
                except Exception:
                    pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cid', type=int, required=True)
    parser.add_argument('--port', type=int, default=8443)
    args = parser.parse_args()
    serve(args.cid, args.port)
