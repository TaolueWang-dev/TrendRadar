import unittest
from types import SimpleNamespace
from unittest.mock import patch
from trendradar.ai.client import AIClient


class AIResponseTests(unittest.TestCase):
    def test_extra_body_and_response_validation(self):
        client = AIClient({'MODEL': 'deepseek/test', 'EXTRA_PARAMS': {
            'extra_body': {'thinking': {'type': 'disabled'}}}})
        for content, finish, raises in [('ok', 'stop', False), ('', 'stop', True), ('partial', 'length', True)]:
            response = SimpleNamespace(choices=[SimpleNamespace(
                finish_reason=finish, message=SimpleNamespace(content=content))])
            with patch('trendradar.ai.client.completion', return_value=response) as call:
                if raises:
                    with self.assertRaises(ValueError):
                        client.chat([])
                else:
                    self.assertEqual(client.chat([]), 'ok')
                self.assertEqual(call.call_args.kwargs['extra_body'], {'thinking': {'type': 'disabled'}})
