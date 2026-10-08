"""Pinned contributor inference tests over synthetic redacted schemas."""
import copy
import json
import unittest
from unittest.mock import patch

from transcripts.artifacts import extract_artifact
from transcripts.common import Rejected, canonical, digest
from transcripts.providers import ENDPOINTS, NEAR_MODEL, ProviderClient, SYSTEM_PROMPT
from transcripts.transport import HTTPResponse
from transcripts.tests.test_core import campaign, request, read
from transcripts.tests.test_transport import MockTransport


def fixture(provider='openai', model='gpt-4o-mini-2024-07-18', privacy='provider_visible'):
    policy = campaign(inferenceRoutes=[{'provider': provider, 'models': [model], 'privacyModes': [privacy]}])
    reserved = request(policy)
    reserved.update(provider=provider, model=model, privacyMode=privacy)
    reserved['limits'].update(maxInputTokens=10000, maxOutputTokens=1000)
    artifact = extract_artifact(policy, [read('synthetic-job')])
    result = {'rubricVersion': 'rubric-v1', 'score': 90, 'useful': True}
    response = {'model': model, 'choices': [{'finish_reason': 'stop', 'message': {
        'role': 'assistant', 'content': json.dumps(result)}}], 'usage': {'prompt_tokens': 400, 'completion_tokens': 40}}
    if provider == 'openrouter': response['provider'] = 'OpenAI'
    return policy, reserved, artifact, result, response


class ProviderTests(unittest.TestCase):
    def client(self, provider='openai', model='gpt-4o-mini-2024-07-18'):
        policy, reserved, artifact, result, response = fixture(provider, model)
        transport = MockTransport([HTTPResponse(200, canonical(response), (('x-serving-provider', 'near'),))
                                   if provider == 'near' else response])
        client = ProviderClient(policy, reserved, 'synthetic-key', transport)
        return client, transport, artifact, result, response
    def test_redacted_prompt_fixed_endpoint_and_receipt_metadata(self):
        client, transport, artifact, result, _ = self.client()
        self.assertEqual(client.grade(artifact, 1001), result)
        method, url, arguments = transport.calls[0]
        self.assertEqual((method, url), ('POST', ENDPOINTS['openai']))
        self.assertEqual(arguments['headers']['Authorization'], 'Bearer synthetic-key')
        payload = json.loads(arguments['body'])
        self.assertEqual(payload['messages'][0]['content'], SYSTEM_PROMPT)
        for secret in ('synthetic-key', 'private-account-1', 'private-memo', 'private-transaction-id'):
            self.assertNotIn(secret, arguments['body'].decode())
        self.assertEqual(client.metadata['requestDigest'], digest(payload))
        self.assertEqual(client.metadata['responseDigest'], digest(result))
        self.assertEqual(client.metadata['inputTokens'], 400)
        client.close()
        with self.assertRaisesRegex(Rejected, 'inference_key_required'): client.grade(artifact, 1001)
    def test_no_environment_or_provider_fallback(self):
        policy, reserved, artifact, _, _ = fixture()
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'synthetic-peer-key'}):
            with self.assertRaisesRegex(Rejected, 'inference_key_required'): ProviderClient(policy, reserved, None)
        reserved['provider'] = 'https://attacker.example'
        with self.assertRaises(Rejected): ProviderClient(policy, reserved, 'synthetic')
    def test_near_confidential_unavailable_before_network(self):
        policy, reserved, _, _, _ = fixture('near', NEAR_MODEL, 'confidential')
        transport = MockTransport([])
        with self.assertRaisesRegex(Rejected, 'confidential_adapter_unavailable'):
            ProviderClient(policy, reserved, 'synthetic', transport)
        self.assertEqual(transport.calls, [])
        client, transport, artifact, result, _ = self.client('near', NEAR_MODEL)
        self.assertEqual(client.grade(artifact, 1001), result)
        self.assertEqual(transport.calls[0][1], ENDPOINTS['near'])
    def test_near_canonical_model_schema_no_aliasing_and_single_completion(self):
        client, transport, artifact, result, _ = self.client('near', NEAR_MODEL)
        client.limits['maxCalls'] = 10
        self.assertEqual(client.grade(artifact, 1001), result)
        arguments = transport.calls[0][2]
        self.assertEqual(arguments['headers']['x-no-aliasing'], 'true')
        self.assertEqual(arguments['headers']['Authorization'], 'Bearer synthetic-key')
        payload = json.loads(arguments['body'])
        self.assertEqual(payload['model'], NEAR_MODEL)
        self.assertFalse(payload['stream'])
        self.assertEqual(payload['max_tokens'], 1000)
        schema = payload['response_format']['json_schema']
        self.assertTrue(schema['strict'])
        self.assertFalse(schema['schema']['additionalProperties'])
        self.assertEqual(schema['schema']['required'], ['rubricVersion', 'score', 'useful'])
        self.assertNotIn('synthetic-key', arguments['body'].decode())
        self.assertEqual(client.routing_metadata, {'servingProvider': 'near', 'modelResponseVerified': False})
        with self.assertRaisesRegex(Rejected, 'inference_call_limit'): client.grade(artifact, 1002)
        self.assertEqual(len(transport.calls), 1)
    def test_near_alias_models_rejected_before_any_network(self):
        for alias in ('zai-org/GLM-5.3-Flash', 'z-ai/glm-5.2', 'deepseek-ai/DeepSeek-V4-Flash', 'attacker/model'):
            policy, reserved, _, _, _ = fixture('near', alias)
            transport = MockTransport([])
            with self.assertRaisesRegex(Rejected, 'provider_not_allowed'):
                ProviderClient(policy, reserved, 'synthetic-key', transport)
            self.assertEqual(transport.calls, [])
    def test_near_disclosed_chutes_fallback_and_reasoning_not_retained(self):
        policy, reserved, artifact, result, response = fixture('near', NEAR_MODEL)
        response['choices'][0]['message']['reasoning_content'] = 'synthetic-private-model-reasoning'
        transport = MockTransport([HTTPResponse(200, canonical(response), (('X-Serving-Provider', 'chutes'),))])
        client = ProviderClient(policy, reserved, 'synthetic-key', transport)
        self.assertEqual(client.grade(artifact, 1001), result)
        self.assertEqual(client.routing_metadata, {'servingProvider': 'chutes', 'modelResponseVerified': False})
        self.assertNotIn('synthetic-private-model-reasoning', json.dumps(client.metadata))
        self.assertEqual(client.metadata['responseDigest'], digest(result))
    def test_near_missing_unknown_duplicate_or_alias_routing_fails_closed(self):
        bad_headers = [(), (('x-serving-provider', 'external'),),
                       (('x-serving-provider', 'non-attested'),),
                       (('x-serving-provider', 'near'), ('X-Serving-Provider', 'chutes')),
                       (('x-serving-provider', 'near'), ('x-model-alias-resolved', ''))]
        for headers in bad_headers:
            policy, reserved, artifact, _, response = fixture('near', NEAR_MODEL)
            transport = MockTransport([HTTPResponse(200, canonical(response), headers)])
            client = ProviderClient(policy, reserved, 'synthetic-key', transport)
            with self.assertRaisesRegex(Rejected, 'model_result_invalid'): client.grade(artifact, 1001)
            self.assertIsNone(client.metadata)
            with self.assertRaisesRegex(Rejected, 'inference_attempt_failed'): client.grade(artifact, 1002)
            self.assertEqual(len(transport.calls), 1)
    def test_near_warning_model_echo_and_structured_output_quirks_rejected(self):
        changes = [lambda body: body.update(warning='synthetic-alias-resolved'),
                   lambda body: body.update(model='glm-5.3-flash'),
                   lambda body: body['choices'][0].update(finish_reason='length'),
                   lambda body: body['choices'][0]['message'].update(content=None),
                   lambda body: body['choices'][0]['message'].update(content='```json\n{}\n```'),
                   lambda body: body['choices'][0]['message'].update(tool_calls=[{'function': {}}]),
                   lambda body: body['choices'][0]['message'].update(content='{"rubricVersion":"rubric-v1","score":90,"useful":true,"payout":10}'),
                   lambda body: body['usage'].update(completion_tokens=1001)]
        for change in changes:
            policy, reserved, artifact, _, response = fixture('near', NEAR_MODEL);change(response)
            transport = MockTransport([HTTPResponse(200, canonical(response), (('x-serving-provider', 'near'),))])
            client = ProviderClient(policy, reserved, 'synthetic-key', transport)
            with self.assertRaises(Rejected): client.grade(artifact, 1001)
            self.assertIsNone(client.metadata)
            self.assertEqual(len(transport.calls), 1)
    def test_near_key_credit_and_rate_errors_never_retry_or_fallback(self):
        for status in (401, 402, 429):
            policy, reserved, artifact, _, _ = fixture('near', NEAR_MODEL)
            transport = MockTransport([HTTPResponse(status, b'{"error":"synthetic-private-api-key"}')])
            client = ProviderClient(policy, reserved, 'synthetic-key', transport)
            with self.assertRaises(Rejected) as caught: client.grade(artifact, 1001)
            self.assertNotIn('synthetic-private-api-key', str(caught.exception))
            with self.assertRaisesRegex(Rejected, 'inference_attempt_failed'): client.grade(artifact, 1002)
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(transport.calls[0][1], ENDPOINTS['near'])
    def test_openrouter_upstream_allowlist_no_fallback(self):
        client, transport, artifact, _, _ = self.client('openrouter', 'openai/gpt-4o-mini')
        client.grade(artifact, 1001)
        routing = json.loads(transport.calls[0][2]['body'])['provider']
        self.assertEqual(routing['only'], ['OpenAI'])
        self.assertFalse(routing['allow_fallbacks'])
        self.assertEqual(routing['data_collection'], 'deny')
        policy, reserved, _, _, _ = fixture('openrouter', 'attacker/model')
        with self.assertRaises(Rejected): ProviderClient(policy, reserved, 'synthetic')
    def test_wrong_model_provider_consent_policy_or_expiry(self):
        for name, value in (('model','wrong'), ('provider','unknown'), ('consent',False), ('policyDigest','0'*64)):
            policy, reserved, _, _, _ = fixture(); reserved[name] = value
            with self.assertRaises(Rejected): ProviderClient(policy, reserved, 'synthetic')
        client, transport, artifact, _, _ = self.client()
        with self.assertRaisesRegex(Rejected, 'job_expired'): client.grade(artifact, 999999)
        self.assertEqual(transport.calls, [])
    def test_extra_grade_fields_wrong_types_and_model_never_accepted(self):
        mutations = [lambda body: body.update(model='different'),
                     lambda body: body['choices'][0].update(finish_reason='length'),
                     lambda body: body['choices'][0]['message'].update(tool_calls=[{}]),
                     lambda body: body['choices'][0]['message'].update(content='{"rubricVersion":"rubric-v1","score":true,"useful":true}'),
                     lambda body: body['choices'][0]['message'].update(content='{"rubricVersion":"rubric-v1","score":100,"useful":true,"wallet":"attacker"}'),
                     lambda body: body['choices'][0]['message'].update(content='{"rubricVersion":"rubric-v1","score":100,"score":0,"useful":true}'),
                     lambda body: body['choices'][0]['message'].update(content='not-json-synthetic-private-text'),
                     lambda body: body.pop('usage')]
        for mutation in mutations:
            client, transport, artifact, _, response = self.client(); mutation(response)
            with self.assertRaises(Rejected) as caught: client.grade(artifact, 1001)
            self.assertNotIn('synthetic-private-text', str(caught.exception))
            self.assertIsNone(client.metadata)
    def test_token_calls_limits_and_no_network_for_unsafe_artifact(self):
        client, transport, artifact, _, _ = self.client()
        client.limits['maxCalls'] = 1
        client.grade(artifact, 1001)
        with self.assertRaisesRegex(Rejected, 'inference_call_limit'): client.grade(artifact, 1002)
        self.assertEqual(len(transport.calls), 1)
        client, transport, artifact, _, _ = self.client(); client.limits['maxInputTokens'] = 1
        with self.assertRaisesRegex(Rejected, 'inference_input_limit'): client.grade(artifact, 1001)
        self.assertEqual(transport.calls, [])
        client, transport, artifact, _, _ = self.client(); artifact['secret'] = 'synthetic-session'
        with self.assertRaises(Rejected): client.grade(artifact, 1001)
        self.assertEqual(transport.calls, [])
    def test_api_response_oversized_or_redirect_or_tls_unverified(self):
        for response in (HTTPResponse(302,b'{}'), HTTPResponse(200,b'{}',tls_verified=False),
                         HTTPResponse(200,b'x'*65537)):
            client, _, artifact, _, _ = self.client(); client.transport = MockTransport([response])
            with self.assertRaises(Rejected): client.grade(artifact, 1001)
            self.assertEqual(client.calls, 1)
            with self.assertRaisesRegex(Rejected, "inference_attempt_failed"):
                client.grade(artifact, 1002)
            self.assertEqual(len(client.transport.calls), 1)


if __name__ == '__main__':
    unittest.main()
