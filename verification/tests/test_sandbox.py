import hashlib
import json
import unittest

import wasmtime

from verification.common import Rejected
from verification.sandbox import run_adapter


def emit_module(body=b'{"outcome":"supported"}', extra='', prefix=''):
    escaped = ''.join('\\%02x' % b for b in body)
    return wasmtime.wat2wasm(f'''(module
      (import "wasi_snapshot_preview1" "fd_write" (func $write (param i32 i32 i32 i32) (result i32)))
      {extra}
      (memory (export "memory") 1 1024)
      (data (i32.const 128) "{escaped}")
      (func (export "_start")
        {prefix}
        (i32.store (i32.const 0) (i32.const 128))
        (i32.store (i32.const 4) (i32.const {len(body)}))
        (drop (call $write (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 16)))))''')


class SandboxTests(unittest.TestCase):
    def run_wasm(self, module):
        module = bytes(module)
        return run_adapter(module, {}, artifact_digest=hashlib.sha256(module).hexdigest())

    def test_bounded_json_result_and_exact_artifact(self):
        module = bytes(emit_module())
        self.assertEqual(self.run_wasm(module), {'outcome': 'supported'})
        with self.assertRaisesRegex(Rejected, 'sandbox_artifact_mismatch'):
            run_adapter(module, {}, artifact_digest='00' * 32)

    def test_files_network_and_unknown_imports_never_link(self):
        for name in ('path_open', 'sock_open', 'random_get'):
            module = emit_module(extra=f'(import "wasi_snapshot_preview1" "{name}" (func))')
            with self.assertRaises(Rejected): self.run_wasm(module)

    def test_infinite_loop_runs_out_of_fuel(self):
        module = wasmtime.wat2wasm('(module (func (export "_start") (loop $forever (br $forever))))')
        with self.assertRaises(Rejected): self.run_wasm(module)

    def test_out_of_bounds_io_and_output_flood_fail(self):
        with self.assertRaises(Rejected): self.run_wasm(emit_module(b'x' * 8193))
        with self.assertRaises(Rejected): self.run_wasm(emit_module(prefix='(drop (call $write (i32.const 1) (i32.const -1) (i32.const 64) (i32.const 16)))'))

    def test_environment_is_empty_and_memory_growth_is_capped(self):
        extra = '(import "wasi_snapshot_preview1" "environ_sizes_get" (func $env (param i32 i32) (result i32)))'
        prefix = '''(drop (call $env (i32.const 24) (i32.const 28)))
          (if (i32.ne (i32.load (i32.const 24)) (i32.const 0)) (then unreachable))
          (if (i32.ne (memory.grow (i32.const 1024)) (i32.const -1)) (then unreachable))'''
        self.assertEqual(self.run_wasm(emit_module(extra=extra, prefix=prefix)), {'outcome': 'supported'})

    def test_in_limit_output_survives_canonical_reencoding(self):
        # The worker re-encodes guest JSON with ASCII escapes and float repr. An output
        # within MAX_OUTPUT must not turn into a different, guest-selected error code.
        text = json.dumps({'outcome': 'unsupported', 'reason': '\u2014' * 2700}, ensure_ascii=False)
        cases = [(text.encode(), {'outcome': 'unsupported', 'reason': '\u2014' * 2700}),
                 (b'"' + b'\x7f' * 8190 + b'"', '\x7f' * 8190),  # 1 byte -> 6-byte escape
                 (b'[' + b','.join([b'9e15'] * 1638) + b']', [9e15] * 1638)]
        for body, expected in cases:
            self.assertLessEqual(len(body), 8192)
            with self.subTest(size=len(body)):
                self.assertEqual(self.run_wasm(emit_module(body)), expected)

    def test_unneeded_wasm_proposals_are_disabled(self):
        # GC objects live outside the 64 MiB linear-memory limit; Javy output needs
        # neither GC nor exceptions, so such modules must not compile.
        gc = emit_module(extra='(type $a (array (mut i64))) (global $k (mut (ref null $a)) (ref.null $a))',
                         prefix='(global.set $k (array.new $a (i64.const 7) (i32.const 8000000)))')
        exceptions = emit_module(extra='(tag $t)', prefix='(try_table (throw $t))')
        for module in (gc, exceptions):
            with self.assertRaisesRegex(Rejected, '^sandbox_failed$'):
                self.run_wasm(module)

    def test_guest_errors_and_non_json_never_escape(self):
        for body in (b'private error text', b'{"a":1,"a":2}'):
            with self.assertRaisesRegex(Rejected, '^sandbox_failed$'): self.run_wasm(emit_module(body))
