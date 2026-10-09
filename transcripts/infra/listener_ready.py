"""Host-only bounded startup readiness; never inspect or log request data."""
import os
import socket
import threading
import time


def notify_ready():
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("listener_start_failed") from None
    address = os.environ.get("NOTIFY_SOCKET")
    if address is None:
        return  # Direct operator/test invocation has no systemd notification socket.
    if address.startswith("@"):
        address = "\0" + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
        channel.connect(address)
        channel.sendall(b"READY=1")


def start_listeners(specifications, timeout=30):
    """Each target sets its ready Event only after successful bind/listen.

    A bind failure or exited listener fails startup with a fixed diagnostic.
    No enclave launches until systemd receives readiness from the main process.
    """
    failed = threading.Event()
    workers = []
    events = []
    for target, args in specifications:
        ready = threading.Event()
        def run(function=target, arguments=args, event=ready):
            try:
                function(*arguments, ready=event)
            except Exception:
                pass
            finally:
                failed.set()
        worker = threading.Thread(target=run, daemon=True)
        workers.append(worker)
        events.append(ready)
        worker.start()
    deadline = time.monotonic() + timeout
    while True:
        if failed.is_set() or any(not worker.is_alive() for worker in workers):
            raise RuntimeError("listener_start_failed") from None
        if all(event.is_set() for event in events):
            return workers
        if time.monotonic() >= deadline:
            raise RuntimeError("listener_start_failed") from None
        failed.wait(min(0.05, max(0, deadline - time.monotonic())))
