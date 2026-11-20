"""会话临时存储：数据只在当前页面会话内存在。

- 每个会话一个系统临时目录（不在项目仓库、不写数据库）；
- 前端页面关闭 / 离开时调用 destroy，TTL 定时兜底清理，服务退出时全量清理；
- 产物按会话隔离，resolve() 只认已登记的键，杜绝路径穿越；
- StorageBackend 是接口，将来上云可换成共享存储实现，业务层不改。
"""
from __future__ import annotations

import atexit
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app import config


@dataclass
class Session:
    id: str
    root: Path
    created_at: float
    uploads: dict[str, Path] = field(default_factory=dict)
    artifacts: dict[str, Path] = field(default_factory=dict)
    tables: Any = None                 # 内存中的 ParsedTable 列表，随会话销毁
    status: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.created_at = time.time()


class StorageBackend(Protocol):
    def create(self) -> Session: ...
    def get(self, session_id: str) -> Session | None: ...
    def destroy(self, session_id: str) -> None: ...


class SessionStore:
    """内存索引 + 系统临时目录。小规模内部自用足够，接口可替换。"""

    def __init__(self, root: Path | None = None,
                 ttl: int | None = None, sweep: int | None = None) -> None:
        self.root = root or config.SESSION_ROOT
        self.ttl = ttl if ttl is not None else config.SESSION_TTL_SECONDS
        self.sweep = sweep if sweep is not None else config.SESSION_SWEEP_SECONDS
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def create(self) -> Session:
        self.root.mkdir(parents=True, exist_ok=True)
        sid = uuid.uuid4().hex
        path = Path(tempfile.mkdtemp(prefix=f"sess-{sid[:12]}-", dir=str(self.root)))
        session = Session(id=sid, root=path, created_at=time.time())
        with self._lock:
            self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                return None
            if time.time() - s.created_at > self.ttl:
                self._destroy_locked(session_id)
                return None
            s.touch()
            return s

    def destroy(self, session_id: str) -> None:
        with self._lock:
            self._destroy_locked(session_id)

    def _destroy_locked(self, session_id: str) -> None:
        s = self._sessions.pop(session_id, None)
        if s is None:
            return
        # 只删本模块自建的会话临时目录
        if s.root.parent == self.root and s.root.is_dir():
            shutil.rmtree(s.root, ignore_errors=True)

    def resolve(self, session_id: str, name: str) -> Path | None:
        s = self.get(session_id)
        if s is None:
            return None
        path = s.artifacts.get(name) or s.uploads.get(name)
        if path is None or not path.exists() or s.root not in path.parents:
            return None
        return path

    def register_artifact(self, session_id: str, key: str, path: Path) -> None:
        s = self.get(session_id)
        if s is None:
            raise KeyError("会话不存在或已过期")
        s.artifacts[key] = path

    def purge_expired(self) -> int:
        with self._lock:
            expired = [sid for sid, s in self._sessions.items()
                       if time.time() - s.created_at > self.ttl]
            for sid in expired:
                self._destroy_locked(sid)
        return len(expired)

    def start_sweeper(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop() -> None:
            while not self._stop.wait(self.sweep):
                self.purge_expired()

        self._thread = threading.Thread(target=loop, name="session-sweeper", daemon=True)
        self._thread.start()

    def stop_sweeper(self) -> None:
        self._stop.set()

    def destroy_all(self) -> None:
        with self._lock:
            for sid in list(self._sessions):
                self._destroy_locked(sid)

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)


STORE = SessionStore()
atexit.register(STORE.destroy_all)
