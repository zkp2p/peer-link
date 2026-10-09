"""Synthetic bind failures and service ordering; no VSOCK, AWS or credentials."""
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from transcripts.infra.listener_ready import notify_ready, start_listeners
from transcripts.kms_broker import serve
from transcripts.server import egress_server
from transcripts.storage import serve_archive


class StartupTests(unittest.TestCase):
    def test_notification_handles_abstract_socket_and_only_main_thread(self):
        fake = Mock()
        fake.__enter__ = Mock(return_value=fake)
        fake.__exit__ = Mock(return_value=False)
        with patch.dict("os.environ", {"NOTIFY_SOCKET": "@synthetic-notify"}), \
             patch("socket.socket", return_value=fake):
            notify_ready()
            fake.connect.assert_called_once_with("\0synthetic-notify")
            fake.sendall.assert_called_once_with(b"READY=1")
            fake.reset_mock()
            result = []
            def worker():
                try:
                    notify_ready()
                except RuntimeError as error:
                    result.append(str(error))
            thread = threading.Thread(target=worker); thread.start(); thread.join(1)
            self.assertEqual(result, ["listener_start_failed"])
            fake.sendall.assert_not_called()

    def test_each_listener_bind_failure_prevents_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            for target, args in [(egress_server, (5101, 16, set())),
                                 (serve_archive, (5102, 16, directory)),
                                 (serve, (5103, 16, Mock()))]:
                ready = threading.Event()
                fake = Mock()
                fake.__enter__ = Mock(return_value=fake)
                fake.__exit__ = Mock(return_value=False)
                fake.bind.side_effect = OSError("synthetic private diagnostic")
                with patch("socket.socket", return_value=fake), \
                     patch("socket.AF_VSOCK", 40, create=True), \
                     patch("socket.VMADDR_CID_ANY", 0xFFFFFFFF, create=True):
                    with self.assertRaises(OSError):
                        target(*args, ready=ready)
                    self.assertFalse(ready.is_set())
                    fake.listen.assert_not_called()
                    with self.assertRaisesRegex(RuntimeError, "^listener_start_failed$"):
                        start_listeners([(target, args)], timeout=0.2)

    def test_all_listener_binds_are_required_before_startup_returns(self):
        entered, permit, stop = threading.Event(), threading.Event(), threading.Event()
        def first(*, ready):
            ready.set(); stop.wait(2)
        def last(*, ready):
            entered.set(); permit.wait(2); ready.set(); stop.wait(2)
        complete = threading.Event()
        def launch():
            start_listeners([(first, ()), (last, ())], timeout=1)
            complete.set()
        worker = threading.Thread(target=launch); worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertFalse(complete.is_set())
            permit.set(); self.assertTrue(complete.wait(1))
        finally:
            stop.set(); worker.join(2)

    def test_bound_startup_timeout_never_reports_ready(self):
        stop = threading.Event()
        def listener(*, ready):
            stop.wait(1)
        try:
            with self.assertRaisesRegex(RuntimeError, "^listener_start_failed$"):
                start_listeners([(listener, ())], timeout=0.02)
        finally:
            stop.set()

    def test_systemd_has_no_enclave_egress_dependency_cycle(self):
        source = Path("transcripts/infra/install_release.sh").read_text()
        enclave = re.search(r"peer-link-transcript-enclave.service <<'UNIT'\n(.*?)\nUNIT", source, re.S).group(1)
        relay = re.search(r"peer-link-transcript-relay.service <<'UNIT'\n(.*?)\nUNIT", source, re.S).group(1)
        self.assertIn("Requires=nitro-enclaves-allocator.service peer-link-transcript-relay.service", enclave)
        self.assertNotIn("peer-link-transcript-enclave.service", relay)
        self.assertIn("Type=notify", relay)
        credential = Path("transcripts/infra/install_credentials.sh").read_text()
        self.assertIn("Type=notify", credential)
        self.assertIn('Requires=$durable_dependencies', source)
        self.assertIn('TimeoutStopSec=75', source)


if __name__ == "__main__":
    unittest.main()
