"""Baseline 시점의 트래커 전체 아이템을 PC에 저장해 두고 다시 쓰는 저장소.

Baseline 내용은 만든 뒤 바뀌지 않는다. 한 번 받은 전체 아이템 원본을 파일로 남기면
다음 계층 조회와 비교를 서버 요청 없이 바로 처리할 수 있다.

- 서버·사용자별로 나눈다. 계정마다 볼 수 있는 아이템이 다르기 때문이다.
- 서버가 준 원본을 그대로 저장하고, 읽을 때 다시 해석한다. 앱의 모델이 바뀌어도
  저장 형식이 깨지지 않는다.
- 파일은 실행 기록·일괄 수정 기록과 같은 사용자 설정 폴더에 평문 gzip JSON으로 둔다.
- 전체 크기가 상한을 넘으면 가장 오래 쓰지 않은 파일부터 지운다.
"""

from __future__ import annotations

import contextlib
import gzip
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any


BASELINE_CACHE_DIR_NAME = "baseline_cache"
# 파일 안의 형식 번호. 형식을 바꾸면 올려서 예전 파일을 쓰지 않게 한다.
BASELINE_CACHE_VERSION = 1
DEFAULT_BASELINE_CACHE_MAX_BYTES = 500 * 1024 * 1024
_FILE_SUFFIX = ".json.gz"


@dataclass(frozen=True)
class BaselineCacheKey:
    """저장본 하나를 가리키는 조건. 하나라도 다르면 다른 저장본이다."""

    base_url: str
    username: str
    tracker_id: int
    baseline_id: int
    # 서버에 보낸 조회 조건(CBQL과 정렬). 조회 방식이 바뀌면 예전 저장본을 쓰지 않는다.
    query: str

    def fields(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "username": self.username,
            "tracker_id": self.tracker_id,
            "baseline_id": self.baseline_id,
            "query": self.query,
        }

    def file_name(self) -> str:
        digest = sha256(json.dumps(self.fields(), sort_keys=True).encode("utf-8")).hexdigest()
        return f"{digest[:40]}{_FILE_SUFFIX}"


@dataclass(frozen=True)
class BaselineCacheEntry:
    items: list[dict[str, Any]]
    # 서버에서 받은 시각(ISO 8601, UTC).
    saved_at: str


class BaselineItemCache:
    def __init__(
        self,
        root: str | Path,
        *,
        max_bytes: int = DEFAULT_BASELINE_CACHE_MAX_BYTES,
    ) -> None:
        self.root = Path(root)
        self.max_bytes = int(max_bytes)

    def load(self, key: BaselineCacheKey) -> BaselineCacheEntry | None:
        """저장본을 읽는다. 없거나 깨졌거나 조건이 다르면 None."""
        path = self.root / key.file_name()
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, EOFError):
            # 깨진 파일은 다시 받을 수 있게 지운다.
            with contextlib.suppress(OSError):
                path.unlink()
            return None
        if (
            not isinstance(payload, dict)
            or payload.get("version") != BASELINE_CACHE_VERSION
            or payload.get("key") != key.fields()
            or not isinstance(payload.get("items"), list)
        ):
            return None
        # 오래 쓰지 않은 순서로 지우므로 읽을 때도 시각을 갱신한다.
        with contextlib.suppress(OSError):
            os.utime(path)
        return BaselineCacheEntry(
            items=[item for item in payload["items"] if isinstance(item, dict)],
            saved_at=str(payload.get("saved_at") or ""),
        )

    def save(self, key: BaselineCacheKey, items: list[dict[str, Any]]) -> None:
        """저장본을 남긴다. 저장은 부가 기능이라 실패해도 조회 흐름을 끊지 않는다."""
        payload = {
            "version": BASELINE_CACHE_VERSION,
            "key": key.fields(),
            "saved_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "items": items,
        }
        temporary_path = ""
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            # 끝까지 쓴 뒤 바꿔 넣어 반쯤 쓴 파일이 저장본으로 읽히지 않게 한다.
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".baseline-",
                suffix=".tmp",
                dir=str(self.root),
                delete=False,
            ) as handle:
                temporary_path = handle.name
                with gzip.GzipFile(fileobj=handle, mode="wb") as compressed:
                    compressed.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            os.replace(temporary_path, self.root / key.file_name())
            temporary_path = ""
            self._evict()
        except OSError:
            return
        finally:
            if temporary_path:
                with contextlib.suppress(OSError):
                    os.unlink(temporary_path)

    def total_bytes(self) -> int:
        return sum(size for _path, size, _mtime in self._files())

    def clear(self) -> int:
        """저장본을 모두 지우고 지운 파일 수를 돌려준다."""
        removed = 0
        for path, _size, _mtime in self._files():
            with contextlib.suppress(OSError):
                path.unlink()
                removed += 1
        return removed

    def _files(self) -> list[tuple[Path, int, float]]:
        if not self.root.is_dir():
            return []
        files: list[tuple[Path, int, float]] = []
        for path in self.root.glob(f"*{_FILE_SUFFIX}"):
            with contextlib.suppress(OSError):
                stat = path.stat()
                files.append((path, stat.st_size, stat.st_mtime))
        return files

    def _evict(self) -> None:
        files = sorted(self._files(), key=lambda entry: entry[2])
        total = sum(size for _path, size, _mtime in files)
        for path, size, _mtime in files:
            if total <= self.max_bytes:
                break
            with contextlib.suppress(OSError):
                path.unlink()
                total -= size


def default_baseline_cache_dir(root_dir: str | Path) -> Path:
    return Path(root_dir) / BASELINE_CACHE_DIR_NAME


def describe_saved_at(saved_at: str) -> str:
    """저장본을 받은 시각을 이 PC 시간대로 짧게 보여 준다."""
    try:
        return datetime.fromisoformat(saved_at).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return saved_at


__all__ = [
    "BASELINE_CACHE_DIR_NAME",
    "DEFAULT_BASELINE_CACHE_MAX_BYTES",
    "BaselineCacheEntry",
    "BaselineCacheKey",
    "BaselineItemCache",
    "default_baseline_cache_dir",
    "describe_saved_at",
]
