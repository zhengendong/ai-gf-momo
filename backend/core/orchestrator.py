"""
后台任务注册器
追踪所有后台 asyncio.Task，支持优雅关闭
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


class BackgroundTasks:
    """后台任务管理器"""

    def __init__(self):
        self._tasks: set[asyncio.Task] = set()

    def schedule(self, coro) -> asyncio.Task:
        """
        调度一个后台任务

        Args:
            coro: 协程对象

        Returns:
            asyncio.Task
        """
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    def _on_done(self, task: asyncio.Task):
        """任务完成回调"""
        self._tasks.discard(task)
        if task.cancelled():
            return
        if task.exception():
            logger.error(f"后台任务异常: {task.exception()}", exc_info=task.exception())

    async def shutdown(self):
        """优雅关闭：取消所有待处理任务"""
        if not self._tasks:
            return

        logger.info(f"关闭 {len(self._tasks)} 个后台任务...")
        for task in list(self._tasks):
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("后台任务已全部关闭")

    @property
    def active_count(self) -> int:
        return len(self._tasks)


# 全局单例
bg_tasks = BackgroundTasks()
