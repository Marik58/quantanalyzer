"""Tiny on-disk pickle cache with TTL. Keeps yfinance calls under control."""
from __future__ import annotations

import hashlib
import os
import pickle
import time
from pathlib import Path
from typing import Any, Callable

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _key_to_path(key: str) -> Path:
    h = hashlib.sha1(key.encode()).hexdigest()
    return CACHE_DIR / f"{h}.pkl"


def get(key: str, ttl_seconds: int) -> Any | None:
    path = _key_to_path(key)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > ttl_seconds:
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def set_(key: str, value: Any) -> None:
    path = _key_to_path(key)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(value, f)
    tmp.replace(path)


def cached(ttl_seconds: int, key_fn: Callable[..., str]):
    def deco(fn):
        def wrapper(*args, **kwargs):
            key = key_fn(*args, **kwargs)
            hit = get(key, ttl_seconds)
            if hit is not None:
                return hit
            value = fn(*args, **kwargs)
            if value is not None:
                set_(key, value)
            return value
        return wrapper
    return deco
