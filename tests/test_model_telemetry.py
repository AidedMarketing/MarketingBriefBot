import unittest
from unittest.mock import MagicMock, patch

import ai_provider


class ModelTelemetryTests(unittest.TestCase):
    def test_success_log_includes_latency_model_and_usage_without_prompt(self):
        response = MagicMock()
        response.json.return_value = {
            "output_text": "A concise answer",
            "usage": {"input_tokens": 42, "output_tokens": 13},
        }

        with patch.object(ai_provider, "OPENAI_API_KEY", "test-key"), \
             patch.object(ai_provider, "OPENAI_MODEL", "gpt-6-luna"), \
             patch.object(ai_provider.httpx, "post", return_value=response), \
             self.assertLogs("ai_provider", level="INFO") as captured:
            result = ai_provider._call_openai("instructions", "private user prompt")

        self.assertEqual(result, "A concise answer")
        record = captured.records[0]
        self.assertEqual(record.model_name, "gpt-6-luna")
        self.assertEqual(record.input_tokens, 42)
        self.assertEqual(record.output_tokens, 13)
        self.assertGreaterEqual(record.request_duration_ms, 0)
        self.assertNotIn("private user prompt", captured.output[0])


if __name__ == "__main__":
    unittest.main()
