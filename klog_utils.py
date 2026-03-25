from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


SH_TZ = timezone(timedelta(hours=8))


def now_dt() -> datetime:
    return datetime.now(tz=SH_TZ)


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SH_TZ)
    return dt.isoformat(timespec="seconds")


def from_iso(s: str) -> datetime:
    # datetime.fromisoformat 支持 `YYYY-MM-DDTHH:MM:SS+08:00`
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SH_TZ)
    return dt


def fmt_dt_minute(s: Optional[str]) -> str:
    """
    将 DB 中存储的 ISO8601 时间串格式化为用户可读的 `YYYY-MM-DD HH:mm`（分钟精度）。
    """
    if not s:
        return "-"
    try:
        dt = from_iso(str(s))
        dt = dt.astimezone(SH_TZ)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        # 兜底：如果不是 ISO 格式，就原样输出（避免影响业务）
        return str(s)


def fmt_dt_range(start: Optional[str], end: Optional[str]) -> str:
    if not start and not end:
        return "-"
    return f"{fmt_dt_minute(start)} ~ {fmt_dt_minute(end)}"


def parse_dt(s: str) -> datetime:
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=SH_TZ)
        except ValueError:
            pass
    raise ValueError("时间格式不正确，使用 YYYY-MM-DD HH:mm 或 YYYY/MM/DD HH:mm")


def parse_date(s: str) -> str:
    s = s.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise ValueError("日期格式不正确，使用 YYYY-MM-DD")
    return s


def minutes_between(start: datetime, end: datetime) -> int:
    delta = end - start
    mins = int(delta.total_seconds() // 60)
    return max(mins, 0)


def floor_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def compute_next_remind_at(start_at: datetime, remind_minutes: int, now: datetime) -> datetime:
    """
    计算下一次提醒时间：start_at 起每 remind_minutes 分钟提醒一次，返回最接近但大于 now 的那次。
    """
    if remind_minutes <= 0:
        raise ValueError("remind_minutes must be positive")
    if now <= start_at:
        return start_at + timedelta(minutes=remind_minutes)

    elapsed_minutes = int((now - start_at).total_seconds() // 60)
    k = elapsed_minutes // remind_minutes + 1
    return start_at + timedelta(minutes=k * remind_minutes)


def parse_int(s: str, name: str, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    try:
        v = int(s)
    except Exception:
        raise ValueError(f"{name} 必须是整数")
    if min_value is not None and v < min_value:
        raise ValueError(f"{name} 不能小于 {min_value}")
    if max_value is not None and v > max_value:
        raise ValueError(f"{name} 不能大于 {max_value}")
    return v
