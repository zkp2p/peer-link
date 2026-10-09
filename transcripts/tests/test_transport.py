"""Synthetic transport tests: no bank sessions, DNS lookups or remote connections."""
import copy
import socket
import ssl
import unittest
from unittest.mock import Mock, patch

from transcripts.common import Rejected, canonical
from transcripts.recipe import validate_live_reads
from transcripts.transport import BankClient, HTTPResponse, HTTPTransport, public_socket, tunnel_socket
from transcripts.tests.test_core import campaign


WISE = 'https://api.wise.com'


def wise_policy():
    return campaign(bankId='wise', sources=[{
        'origin': WISE, 'paths': ['/v1/profiles', '/v4/profiles/{id}/balances',
            '/v1/profiles/{id}/balance-statements/{id}/statement.json'], 'methods': ['GET'],
        'parameterNames': ['types', 'currency', 'intervalStart', 'intervalEnd', 'type'], 'headerNames': []}])


def recipe(profile=12, balance=34):
    return {'version': 1, 'reads': [
        {'method': 'GET', 'url': WISE + '/v1/profiles'},
        {'method': 'GET', 'url': WISE + f'/v4/profiles/{profile}/balances?types=STANDARD'},
        {'method': 'GET', 'url': WISE + f'/v1/profiles/{profile}/balance-statements/{balance}/statement.json'
            '?currency=USD&intervalStart=2026-01-01&intervalEnd=2026-02-01&type=COMPACT'}]}


class MockTransport:
    def __init__(self, bodies):
        self.bodies = iter(bodies)
        self.calls = []
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        value = next(self.bodies)
        return value if isinstance(value, HTTPResponse) else HTTPResponse(200, canonical(value))


class BankTests(unittest.TestCase):
    def client(self, bodies, **kwargs):
        transport = MockTransport(bodies)
        return BankClient(wise_policy(), {'origin': WISE, 'kind': 'bearer', 'value': 'synthetic-session'},
                          transport, **kwargs), transport
    def responses(self):
        return [[{'id': 12, 'type': 'personal'}], [{'id': 34, 'type': 'STANDARD'}],
                {'transactions': [{'id': 'synthetic-id', 'amount': 1, 'currency': 'USD', 'status': 'settled'}]}]
    def test_identity_from_authenticated_profile_and_balance(self):
        client, transport = self.client(self.responses())
        reads = client.acquire('synthetic-job', recipe(), 1000)
        self.assertEqual(len(reads), 3)
        self.assertEqual(validate_live_reads(wise_policy(), reads, 'synthetic-job', 1000, 1000), 'wise-profile:12')
        self.assertTrue(all(read.authenticated and read.tls_verified for read in reads))
        self.assertEqual(transport.calls[0][2]['headers']['Authorization'], 'Bearer synthetic-session')
        client.close()
        self.assertEqual(client.credential, {})
    def test_forged_selected_profile_stops_before_history(self):
        client, transport = self.client([[{'id': 99}]])
        with self.assertRaisesRegex(Rejected, 'account_evidence_missing'):
            client.acquire('synthetic-job', recipe(), 1000)
        self.assertEqual(len(transport.calls), 1)
    def test_multiple_profiles_require_explicit_selection(self):
        responses = self.responses(); responses[0] = [{'id': 12}, {'id': 99}]
        client, transport = self.client(responses)
        with self.assertRaisesRegex(Rejected, 'ambiguous_account'):
            client.acquire('synthetic-job', recipe(), 1000)
        client, _ = self.client(responses, profile_id=12)
        self.assertEqual(client.acquire('synthetic-job', recipe(), 1000)[0].account_id, 'wise-profile:12')
    def test_balance_membership_and_cross_profile_mismatch(self):
        client, transport = self.client(self.responses())
        with self.assertRaisesRegex(Rejected, 'account_evidence_missing'):
            client.acquire('synthetic-job', recipe(balance=999), 1000)
        self.assertEqual(len(transport.calls), 2)
        responses = self.responses(); responses[1][0]['profileId'] = 99
        client, _ = self.client(responses)
        with self.assertRaisesRegex(Rejected, 'ambiguous_account'):
            client.acquire('synthetic-job', recipe(), 1000)
    def test_unapproved_origin_method_or_path_never_receives_secret(self):
        for change in ({'method': 'POST'}, {'url': 'https://evil.example/v1/profiles'},
                       {'url': WISE + '/v1/profiles?extra=1'}, {'url': WISE + '/v1/profiles/12'}):
            client, transport = self.client(self.responses())
            candidate = recipe(); candidate['reads'][0].update(change)
            with self.assertRaises(Rejected): client.acquire('synthetic-job', candidate, 1000)
            self.assertEqual(transport.calls, [])
    def test_discovery_counted_and_malformed_or_tls_failure_rejected(self):
        client, transport = self.client(self.responses(), max_reads=2)
        with self.assertRaisesRegex(Rejected, 'recipe_limits'): client.acquire('synthetic-job', recipe(), 1000)
        self.assertEqual(transport.calls, [])
        for response in (HTTPResponse(302, b'[]'), HTTPResponse(200, b'[]', tls_verified=False),
                         HTTPResponse(200, b'{"id":1,"id":2}'), HTTPResponse(200, b'NaN')):
            client, _ = self.client([response])
            with self.assertRaises(Rejected): client.acquire('synthetic-job', recipe(), 1000)
    def test_unknown_bank_credential_injection_and_profile_argument_rejected(self):
        for credential in ({'origin': 'https://evil.example', 'kind': 'bearer', 'value': 'synthetic'},
                           {'origin': WISE, 'kind': 'cookie', 'value': 'synthetic'},
                           {'origin': WISE, 'kind': 'bearer', 'value': 'synthetic\r\nX-Extra: injected'}):
            with self.assertRaises(Rejected): BankClient(wise_policy(), credential)
        with self.assertRaises(Rejected): self.client(self.responses(), profile_id='12/../99')


class PlumbingTests(unittest.TestCase):
    def framed_response(self, framing, body=b'{"result":"0x2105"}', *, max_bytes=1000):
        # Keep the real HTTPSConnection/HTTPResponse and socket.makefile lifecycle.
        # Only TLS wrapping/DNS are replaced: no network or credentials are used.
        client,server=socket.socketpair()
        header=b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n'
        if framing=='length':
            header+=b'Content-Length: '+str(len(body)).encode()+b'\r\n'
        elif framing=='truncated':
            header+=b'Content-Length: '+str(len(body)+3).encode()+b'\r\n'
        elif framing=='chunked':
            header+=b'Transfer-Encoding: chunked\r\n'
            body=hex(len(body))[2:].encode()+b'\r\n'+body+b'\r\n0\r\n\r\n'
        server.sendall(header+b'\r\n'+body)
        server.shutdown(socket.SHUT_WR)
        context=Mock();context.wrap_socket.return_value=client
        try:
            with patch('transcripts.transport.public_socket',return_value=client), \
                 patch('ssl.create_default_context',return_value=context):
                return HTTPTransport('direct').request('POST','https://rpc.example/',body=b'{}',max_bytes=max_bytes)
        finally:
            client.close();server.close()

    def test_real_connection_close_lifecycle_for_all_response_framings(self):
        for framing in ('length','chunked','eof'):
            with self.subTest(framing=framing):
                response=self.framed_response(framing)
                self.assertEqual(response.body,b'{"result":"0x2105"}')
                self.assertTrue(response.tls_verified)

    def test_response_framing_keeps_size_and_completeness_checks(self):
        for framing in ('length','chunked','eof'):
            with self.subTest(framing=framing):
                with self.assertRaisesRegex(Rejected,'response_size'):
                    self.framed_response(framing,b'x'*11,max_bytes=10)
        with self.assertRaisesRegex(Rejected,'response_incomplete'):
            self.framed_response('truncated')

    def test_no_aliasing_header_only_for_exact_near_completion_route(self):
        for method, url, value in [('GET', 'https://cloud-api.near.ai/v1/chat/completions', 'true'),
                ('POST', WISE + '/v1/profiles', 'true'),
                ('POST', 'https://cloud-api.near.ai/v1/check_api_key', 'true'),
                ('POST', 'https://cloud-api.near.ai/v1/chat/completions?route=other', 'true'),
                ('POST', 'https://cloud-api.near.ai/v1/chat/completions', 'false')]:
            with patch('transcripts.transport.public_socket') as connector:
                with self.assertRaisesRegex(Rejected, 'unsafe_headers'):
                    HTTPTransport('direct').request(method, url, headers={'x-no-aliasing': value})
                connector.assert_not_called()
        response = Mock(status=200)
        response.isclosed.return_value=False;response.length=None
        response.getheaders.return_value = [('Content-Type', 'application/json')]
        response.read1.side_effect = [b'{}', b'']
        connection = Mock();connection.getresponse.return_value = response
        with patch('transcripts.transport.public_socket'), patch('ssl.create_default_context'), \
             patch('http.client.HTTPSConnection', return_value=connection):
            HTTPTransport('direct').request('POST', 'https://cloud-api.near.ai/v1/chat/completions',
                headers={'x-no-aliasing': 'true'}, body=b'{}')
        self.assertEqual(connection.request.call_args.kwargs['headers']['x-no-aliasing'], 'true')
    def test_ssrf_rejects_all_mixed_dns_answers(self):
        for bad in ('127.0.0.1', '169.254.169.254', '10.0.0.1', '::1', '::ffff:127.0.0.1'):
            answers = [(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 443)),
                       (socket.AF_INET, socket.SOCK_STREAM, 0, '', (bad, 443))]
            with patch('socket.getaddrinfo', return_value=answers), patch('socket.socket') as creator:
                with self.assertRaises(Rejected): public_socket('api.wise.com')
                creator.assert_not_called()
    def test_dns_pinned_socket_and_tls_hostname_verification(self):
        sock = Mock()
        answer = [(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 443))]
        with patch('socket.getaddrinfo', return_value=answer), patch('socket.socket', return_value=sock):
            self.assertIs(public_socket('api.wise.com'), sock)
            sock.connect.assert_called_once_with(('8.8.8.8', 443))
        real_context = ssl.create_default_context()
        self.assertTrue(real_context.check_hostname)
        self.assertEqual(real_context.verify_mode, ssl.CERT_REQUIRED)
        context = Mock()
        response = Mock(status=200)
        response.isclosed.return_value=False;response.length=None
        response.getheaders.return_value = [('Content-Type', 'application/json')]
        response.read1.side_effect = [b'{"safe":true}', b'']
        connection = Mock()
        connection.getresponse.return_value = response
        with patch('transcripts.transport.public_socket', return_value=sock), \
             patch('ssl.create_default_context', return_value=context), \
             patch('http.client.HTTPSConnection', return_value=connection):
            result = HTTPTransport('direct').request('GET', WISE + '/v1/profiles')
        context.wrap_socket.assert_called_once_with(sock, server_hostname='api.wise.com')
        self.assertTrue(result.tls_verified)
        connection.close.assert_called_once()
    def test_redirect_size_and_compression_fail_closed(self):
        for status, headers, chunks in ((302, [('Content-Type', 'application/json')], []),
                (200, [('Content-Type', 'text/html')], []),
                (200, [('Content-Type', 'application/json'), ('Content-Encoding', 'gzip')], []),
                (200, [('Content-Type', 'application/json')], [b'x' * 11])):
            response = Mock(status=status); response.getheaders.return_value = headers
            response.isclosed.return_value=False;response.length=None
            response.read1.side_effect = chunks
            connection = Mock(); connection.getresponse.return_value = response
            with patch('transcripts.transport.public_socket'), patch('ssl.create_default_context'), \
                 patch('http.client.HTTPSConnection', return_value=connection):
                with self.assertRaises(Rejected): HTTPTransport('direct').request('GET', WISE + '/v1/profiles', max_bytes=10)
                self.assertEqual(connection.request.call_count, 1)
    def test_vsock_protocol_never_contains_credential(self):
        stream = Mock(); stream.recv.side_effect = [b'O', b'K', b'\n']
        with patch.object(socket, 'AF_VSOCK', 40, create=True), patch('socket.socket', return_value=stream):
            self.assertIs(tunnel_socket('api.wise.com'), stream)
        stream.connect.assert_called_once_with((3, 5101))
        self.assertEqual(stream.sendall.call_args.args[0], b'{"host":"api.wise.com","port":443}\n')
    def test_raw_network_exception_sanitized(self):
        with patch('transcripts.transport.public_socket', side_effect=OSError('synthetic-private-session')):
            with self.assertRaisesRegex(Rejected, '^http_transport_failed$'):
                HTTPTransport('direct').request('GET', WISE + '/v1/profiles')


if __name__ == '__main__':
    unittest.main()
