"""任务队列：light 和 gpu 两条单线程队列，负责派发、写进度、失败处理和重试。

v1.4 新增排队位置跟踪（Job.queue_position）：_waiting 按队列记录当前"已提交但还没开始执行"
的任务 id，顺序即执行顺序（每条队列只有一个 worker）；任务一旦开始执行就从列表移除，
所以只有真正处于 queued 状态的任务才有非 None 的位置，服务重启后 _waiting 从空列表开始，
不会残留导致负数或脏数据。
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .db import Database
from .errors import ApiError

log = logging.getLogger("outfit.jobs")

# kind -> queue
QUEUE_OF = {"prepare_garment": "light", "tryon": "gpu", "turntable": "gpu"}


class JobRunner:
    """sync=True 时同步执行（测试用），否则派发到对应队列的单线程池。"""

    def __init__(self, db: Database, sync: bool = False):
        self.db = db
        self.sync = sync
        self.handlers: dict[str, Callable[[str], Callable[[Callable], None]]] = {}
        self._executors = {"light": ThreadPoolExecutor(max_workers=1), "gpu": ThreadPoolExecutor(max_workers=1)}
        self._queue_lock = threading.Lock()
        self._waiting: dict[str, list[str]] = {"light": [], "gpu": []}

    def register(self, kind: str, builder: Callable[[str], Callable[[Callable], None]]):
        """builder(target_id) -> fn(report)：由路由模块注册，负责具体的业务处理和落库。"""
        self.handlers[kind] = builder

    def submit(self, kind: str, target_id: str, user_id: str, total: int = 1) -> str:
        job = self.db.create_job(kind=kind, target_id=target_id, user_id=user_id, total=total)
        self._enqueue(job["id"], kind, target_id)
        return job["id"]

    def retry(self, job_id: str, user_id: str,
             on_before_dispatch: Callable[[dict], None] | None = None) -> dict:
        """on_before_dispatch(job)：在确认任务存在且为 failed、重新派发前调用（v1.4 供额度检查使用）。"""
        job = self.db.get_job_for_user(job_id, user_id)
        if job is None:
            raise ApiError(404, "not_found", "任务不存在")
        if job["status"] != "failed":
            raise ApiError(409, "job_not_failed", "只有失败的任务可以重试")
        if on_before_dispatch:
            on_before_dispatch(job)
        self.db.reset_job_for_retry(job_id)
        self._enqueue(job_id, job["kind"], job["target_id"])
        return self.db.get_job(job_id)

    def queue_position(self, job_id: str) -> int | None:
        """status 为 queued 时，返回同一队列里排在它前面的任务数（0 表示下一个执行）；否则为 None。"""
        with self._queue_lock:
            for waiting in self._waiting.values():
                if job_id in waiting:
                    return waiting.index(job_id)
        return None

    def close(self):
        for ex in self._executors.values():
            ex.shutdown(wait=False)

    def _enqueue(self, job_id: str, kind: str, target_id: str):
        queue = QUEUE_OF[kind]
        with self._queue_lock:
            self._waiting[queue].append(job_id)
        fn = self.handlers[kind](target_id)
        if self.sync:
            self._run(job_id, queue, fn)
        else:
            self._executors[queue].submit(self._run, job_id, queue, fn)

    def _run(self, job_id: str, queue: str, fn: Callable[[Callable], None]):
        with self._queue_lock:
            waiting = self._waiting[queue]
            if job_id in waiting:
                waiting.remove(job_id)
        self.db.update_job(job_id, status="running")

        def report(done: int, total: int, note: str):
            self.db.update_job(job_id, progress_done=done, progress_total=total, progress_note=note)

        try:
            fn(report)
            self.db.update_job(job_id, status="succeeded")
        except ApiError as e:
            self.db.update_job(job_id, status="failed", error_code=e.code, error_message=e.message)
        except Exception as e:
            log.exception("任务 %s 执行失败", job_id)
            self.db.update_job(job_id, status="failed", error_code="internal_error", error_message=str(e))
