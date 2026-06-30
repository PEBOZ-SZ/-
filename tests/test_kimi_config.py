from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class KimiConfigTests(unittest.TestCase):
    def test_moonshot_provider_reads_moonshot_key_and_model_even_when_openai_exists(self) -> None:
        from kimi_client import get_kimi_config

        env = {
            "LLM_PROVIDER": "moonshot",
            "OPENAI_API_KEY": "openai-key",
            "OPENAI_BASE_URL": "https://code.example.test/v1",
            "OPENAI_MODEL": "gpt-forbidden",
            "MOONSHOT_API_KEY": "moonshot-key",
            "MOONSHOT_BASE_URL": "https://api.moonshot.cn/v1",
            "KIMI_MODEL": "kimi-k2.6",
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_kimi_config()

        self.assertEqual(config.api_key, "moonshot-key")
        self.assertEqual(config.api_key_source, "MOONSHOT_API_KEY")
        self.assertEqual(config.base_url, "https://api.moonshot.cn/v1")
        self.assertEqual(config.model, "kimi-k2.6")

    def test_without_provider_falls_back_to_kimi_key_when_openai_key_missing(self) -> None:
        from kimi_client import get_kimi_config

        env = {
            "KIMI_API_KEY": "kimi-key",
            "KIMI_BASE_URL": "https://api.moonshot.cn/v1",
            "KIMI_MODEL": "kimi-k2.6",
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_kimi_config()

        self.assertEqual(config.api_key, "kimi-key")
        self.assertEqual(config.api_key_source, "KIMI_API_KEY")
        self.assertEqual(config.base_url, "https://api.moonshot.cn/v1")
        self.assertEqual(config.model, "kimi-k2.6")


if __name__ == "__main__":
    unittest.main()
