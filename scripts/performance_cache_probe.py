"""Offline checks for cached knowledge and queued vector persistence."""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings
from backend.core import business_knowledge, memory_policy


class FakeVectorStore:
    def __init__(self, directory: Path):
        self._persist_directory = directory
        self.batches: list[list[str]] = []
        self.cleanup_calls = 0

    def add(self, documents, metadatas, ids=None):
        self.batches.append(list(documents))
        return True

    def query(self, text, top_k=5):
        return []

    def cleanup_old(self, **kwargs):
        self.cleanup_calls += 1
        return 0


def main():
    original_base = settings.base_dir
    with tempfile.TemporaryDirectory() as temp:
        settings.base_dir = Path(temp)
        try:
            knowledge = settings.config_dir / "knowledge"
            knowledge.mkdir(parents=True)
            (knowledge / "router.json").write_text(
                json.dumps({"rain": {"signals": ["下雨"]}}, ensure_ascii=False),
                encoding="utf-8",
            )
            guide = knowledge / "rain.md"
            guide.write_text("雨天场景规则 A", encoding="utf-8")
            assert business_knowledge.load_relevant_knowledge("外面下雨了") == "雨天场景规则 A"
            guide.write_text("雨天场景规则 B", encoding="utf-8")
            os.utime(guide, None)
            assert business_knowledge.load_relevant_knowledge("外面下雨了") == "雨天场景规则 B"

            character = "probe"
            directory = settings.get_vector_dir(character)
            fake = FakeVectorStore(directory)
            memory_policy.clear_vector_store_cache(character)
            memory_policy._vector_stores[character] = fake
            assert memory_policy.vector_store(character) is fake

            assert memory_policy.queue_vector_chat_pair(character, "我喜欢蓝莓", "我记住了蓝莓。")
            assert memory_policy.queue_vector_chat_pair(character, "我们在书店见面", "她在书架前等你。")
            recalled = memory_policy.recall_vector_context(character, "你还记得我喜欢什么吗？")
            assert "蓝莓" in recalled
            assert memory_policy.flush_pending_vector_writes(character) == 2
            assert len(fake.batches) == 1 and len(fake.batches[0]) == 2
            assert not memory_policy.has_pending_vector_writes(character)

            memory_policy._vector_cleanup_write_counts[character] = 49
            memory_policy.queue_vector_chat_pair(character, "第三条", "已记录")
            assert memory_policy.flush_pending_vector_writes(character) == 1
            assert fake.cleanup_calls == 1
            memory_policy.clear_vector_store_cache(character)
            assert character not in memory_policy._vector_stores
            print("performance cache probe: ok")
        finally:
            settings.base_dir = original_base
            memory_policy.clear_vector_store_cache()


if __name__ == "__main__":
    main()
