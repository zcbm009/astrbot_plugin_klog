from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ParsedCommand:
    # tokens after stripping /kplog prefix
    argv: list[str]
    raw: str


def strip_klog_prefix(message_str: str) -> str:
    s = message_str.strip()
    for prefix in ("/kplog", "kplog", "/ＫＰＬＯＧ", "/KPLOG", "KPLOG"):
        if s.startswith(prefix):
            rest = s[len(prefix) :].strip()
            return rest
    return s


def split_argv(s: str) -> list[str]:
    s = s.strip()
    if not s:
        return []
    try:
        return shlex.split(s)
    except Exception:
        return s.split()


def parse_command(message_str: str) -> ParsedCommand:
    raw = strip_klog_prefix(message_str)
    argv = split_argv(raw)
    return ParsedCommand(argv=argv, raw=raw)


def pop_flag_value(argv: list[str], flag: str) -> Optional[str]:
    if flag not in argv:
        return None
    i = argv.index(flag)
    if i == len(argv) - 1:
        raise ValueError(f"{flag} 缺少参数")
    v = argv[i + 1]
    del argv[i : i + 2]
    return v


def pop_flag_present(argv: list[str], flag: str) -> bool:
    if flag in argv:
        argv.remove(flag)
        return True
    return False
