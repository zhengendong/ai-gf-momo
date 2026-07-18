"""
向量存储模块
基于 ChromaDB 实现语义记忆检索
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)



# 吞咽记忆上限：超出时删除最旧的条目（保证检索质量）
MAX_VECTORS = 2000

class VectorStore:
    """ChromaDB 向量存储封装，每角色一个 collection"""

    def __init__(self, persist_directory: Path):
        self._persist_directory = persist_directory
        self._client = None
        self._collection = None

    def _ensure_init(self):
        """延迟初始化 ChromaDB"""
        if self._client is not None:
            return

        try:
            import chromadb

            self._persist_directory.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(self._persist_directory)
            )
            self._collection = self._client.get_or_create_collection(
                name="memories",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                f"ChromaDB 初始化: {self._persist_directory}, "
                f"已有 {self._collection.count()} 条记录"
            )
        except ImportError:
            logger.warning("chromadb 未安装，向量存储不可用")
            self._client = None
        except Exception as e:
            logger.error(f"ChromaDB 初始化失败: {e}")
            self._client = None

    def add(self, documents: list[str], metadatas: list[dict], ids: list[str] = None):
        """
        添加记忆向量

        Args:
            documents: 文本内容列表
            metadatas: 元数据列表，每项包含 {source, date, type, importance, tags}
            ids: 唯一 ID 列表（可选，自动生成）
        """
        self._ensure_init()
        if self._collection is None:
            return False

        try:
            import uuid

            if ids is None:
                ids = [str(uuid.uuid4()) for _ in documents]

            # tags 列表转为逗号分隔字符串（ChromaDB metadata 只支持 str/int/float）
            clean_metadatas = []
            for m in metadatas:
                cm = {}
                for k, v in m.items():
                    if k == "tags" and isinstance(v, list):
                        cm[k] = ",".join(v)
                    else:
                        cm[k] = v
                clean_metadatas.append(cm)

            self._collection.add(
                documents=documents,
                metadatas=clean_metadatas,
                ids=ids,
            )
            logger.info(f"向量存储: 添加 {len(documents)} 条记录")
            return True
        except Exception as e:
            logger.error(f"向量存储添加失败: {e}")
            return False

    def query(self, text: str, top_k: int = 5) -> list[dict]:
        """
        语义检索

        Args:
            text: 查询文本
            top_k: 返回条数

        Returns:
            [{content: str, metadata: dict, distance: float}]
        """
        self._ensure_init()
        if self._collection is None or not text.strip():
            return []

        try:
            if self._collection.count() == 0:
                return []

            results = self._collection.query(
                query_texts=[text],
                n_results=min(top_k, self._collection.count()),
            )

            items = []
            if results and results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    meta = {}
                    if results.get("metadatas") and results["metadatas"][0]:
                        meta = results["metadatas"][0][i]
                        # tags 字符串转回列表
                        if "tags" in meta and isinstance(meta["tags"], str):
                            meta["tags"] = [
                                t.strip() for t in meta["tags"].split(",") if t.strip()
                            ]

                    distance = 0.0
                    if results.get("distances") and results["distances"][0]:
                        distance = results["distances"][0][i]

                    items.append({
                        "content": doc,
                        "metadata": meta,
                        "distance": distance,
                    })

            return items
        except Exception as e:
            logger.error(f"向量存储查询失败: {e}")
            return []

    def count(self) -> int:
        """当前记忆条数"""
        self._ensure_init()
        if self._collection is None:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    def cleanup_old(self, max_count: int = None, retention_days: int = None) -> int:
        """
        吞咽记忆清理：
        1. 如果总条数 > max_count，删除最旧的（保留最新的 max_count 条）
        2. 如果 retention_days 指定，删除 metadata.date 小于截止日期的条目
        
        Returns:
            删除的条数
        """
        self._ensure_init()
        if self._collection is None:
            return 0
        try:
            total = self._collection.count()
            if total == 0:
                return 0
            
            # Get all entries (id + metadata)
            all_data = self._collection.get(include=["metadatas"])
            ids = all_data.get("ids", [])
            metas = all_data.get("metadatas", [])
            if not ids:
                return 0
            
            to_delete = set()
            
            # 1. 超阈删除：按 metadata.date 升序，删除最旧的
            if max_count and total > max_count:
                indexed = list(zip(ids, metas))
                # 按 date 排序（无 date 的放最后）
                def _date_key(item):
                    return item[1].get("date", "")
                indexed.sort(key=_date_key)
                excess = total - max_count
                for i in range(excess):
                    to_delete.add(indexed[i][0])
            
            # 2. 过期删除
            if retention_days and retention_days > 0:
                from datetime import date, timedelta
                cutoff = (date.today() - timedelta(days=retention_days)).isoformat()
                for _id, meta in zip(ids, metas):
                    d = meta.get("date", "")
                    if d and d < cutoff:
                        to_delete.add(_id)
            
            if to_delete:
                self._collection.delete(ids=list(to_delete))
                logger.info(f"ChromaDB cleanup: deleted {len(to_delete)} / {total} entries")
            return len(to_delete)
        except Exception as e:
            logger.error(f"ChromaDB cleanup failed: {e}")
            return 0
