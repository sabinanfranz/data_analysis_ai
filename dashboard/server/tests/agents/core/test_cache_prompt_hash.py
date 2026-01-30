import tempfile
import unittest
from pathlib import Path

from dashboard.server.agents.core.cache_store import build_cache_key, load, save_atomic


class CachePromptHashTest(unittest.TestCase):
    def test_prompt_hash_changes_cache_key(self):
        key1 = build_cache_key(llm_input_hash="a", prompt_hash="p1", model="m")
        key2 = build_cache_key(llm_input_hash="a", prompt_hash="p2", model="m")
        self.assertNotEqual(key1, key2)

    def test_cache_read_write_separate_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path1 = Path(tmp) / "cache1.json"
            path2 = Path(tmp) / "cache2.json"
            save_atomic(path1, {"v": 1})
            save_atomic(path2, {"v": 2})
            self.assertEqual(load(path1)["v"], 1)
            self.assertEqual(load(path2)["v"], 2)


if __name__ == "__main__":
    unittest.main()
