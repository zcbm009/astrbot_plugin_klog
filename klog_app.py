from __future__ import annotations

from pathlib import Path
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context

try:
    from .klog_db import KlogDB  # type: ignore
    from .klog_parse import ParsedCommand, parse_command, pop_flag_present, pop_flag_value  # type: ignore
    from .klog_service import KlogService  # type: ignore
    from .klog_text import help_text  # type: ignore
    from .klog_timer import TimerManager  # type: ignore
    from .klog_utils import parse_int  # type: ignore
except Exception:  # pragma: no cover
    from klog_db import KlogDB
    from klog_parse import ParsedCommand, parse_command, pop_flag_present, pop_flag_value
    from klog_service import KlogService
    from klog_text import help_text
    from klog_timer import TimerManager
    from klog_utils import parse_int


def is_qq_unified_msg_origin(origin: str) -> bool:
    """
    仅允许 QQ 平台。统一来源字符串通常形如：
    - aiocqhttp:GroupMessage:xxxx
    - onebot:...
    - mirai:...
    这里用白名单前缀做最小判断。
    """
    if not origin:
        return False
    origin = str(origin)
    for p in ("aiocqhttp:", "onebot:", "mirai:", "qq:"):
        if origin.startswith(p):
            return True
    return False


class KlogApp:
    def __init__(self, context: Context, plugin_name: str = "klog"):
        self.context = context
        self.plugin_name = plugin_name or "klog"
        self.db: Optional[KlogDB] = None
        self.timer_mgr: Optional[TimerManager] = None
        self._timer_user_id: Optional[str] = None

    async def initialize(self) -> None:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        base = get_astrbot_data_path()
        db_dir = Path(base) / "plugin_data" / self.plugin_name
        db_path = db_dir / "klog.db"

        self.db = KlogDB(db_path)
        self.db.migrate()

        # 重启恢复：如果存在活动计时器，启动提醒循环（无需等待用户再次发命令）
        row = self.db.fetchone("SELECT user_id FROM timers WHERE end_at IS NULL ORDER BY id DESC LIMIT 1;")
        if row:
            user_id = str(row["user_id"])
            service = KlogService(self.db, user_id=user_id)
            self.timer_mgr = TimerManager(self.context, service)
            self._timer_user_id = user_id
            await self.timer_mgr.initialize()

    async def terminate(self) -> None:
        if self.timer_mgr:
            await self.timer_mgr.terminate()
            self.timer_mgr = None
        if self.db:
            self.db.close()
            self.db = None

    async def handle_event(self, event: AstrMessageEvent) -> Optional[str]:
        origin = getattr(event, "unified_msg_origin", "") or ""
        if not is_qq_unified_msg_origin(origin):
            return "klog 仅支持 QQ 平台。"

        user_id = str(event.get_sender_id())
        if not self.db:
            return "klog 数据库未初始化。"

        service = KlogService(self.db, user_id=user_id)

        # timer manager 简化为单 user：个人使用场景默认足够
        if self.timer_mgr is None or (self._timer_user_id is not None and self._timer_user_id != user_id):
            if self.timer_mgr:
                await self.timer_mgr.terminate()
            self.timer_mgr = TimerManager(self.context, service)
            self._timer_user_id = user_id
            await self.timer_mgr.initialize()

        parsed = parse_command(event.message_str)
        argv = parsed.argv

        if not argv:
            return help_text()

        if argv[0] in {"help", "-h", "--help"}:
            return help_text()

        try:
            resp = self._dispatch(service, origin, argv)
        except ValueError as e:
            return f"参数错误：{e}\n\n" + help_text()

        # 涉及 timer 状态变更的命令需要 refresh
        if argv and argv[0] == "timer":
            await self.timer_mgr.refresh()

        return resp

    def _dispatch(self, service: KlogService, origin: str, argv: list[str]) -> str:
        cmd = argv[0]

        if cmd == "plan":
            return self._cmd_plan(service, argv[1:])
        if cmd == "stage":
            return self._cmd_stage(service, argv[1:])
        if cmd == "task":
            return self._cmd_task(service, argv[1:])
        if cmd == "timer":
            return self._cmd_timer(service, origin, argv[1:])
        if cmd == "log":
            return self._cmd_log(service, argv[1:])
        if cmd == "daily":
            return self._cmd_daily(service, argv[1:])
        if cmd == "prog":
            return self._cmd_prog(service, argv[1:])

        return "未知子命令。\n\n" + help_text()

    def _cmd_plan(self, service: KlogService, argv: list[str]) -> str:
        if not argv:
            raise ValueError("plan 缺少子命令")
        sub = argv[0]

        if sub == "add":
            if len(argv) < 2:
                raise ValueError("用法：/klog plan add <name> [--alias <alias>] [--note <text>]")
            args = argv[1:].copy()
            alias = pop_flag_value(args, "--alias")
            note = pop_flag_value(args, "--note")
            name = " ".join([a for a in args if not a.startswith("--")]).strip()
            if not name:
                raise ValueError("name 不能为空")
            return service.plan_add(name=name, alias=alias, note=note)

        if sub == "ls":
            args = argv[1:].copy()
            active_only = pop_flag_present(args, "--active")
            return service.plan_ls(active_only=active_only)

        if sub == "show":
            if len(argv) < 2:
                raise ValueError("用法：/klog plan show <P#|alias>")
            return service.plan_show(argv[1])

        if sub == "rename":
            if len(argv) < 3:
                raise ValueError("用法：/klog plan rename <P#|alias> <new_name>")
            return service.plan_rename(argv[1], " ".join(argv[2:]).strip())

        if sub == "alias":
            if len(argv) < 3:
                raise ValueError("用法：/klog plan alias <P#|alias> <alias>")
            return service.plan_alias(argv[1], argv[2])

        if sub == "archive":
            if len(argv) < 2:
                raise ValueError("用法：/klog plan archive <P#|alias>")
            return service.plan_archive(argv[1])

        raise ValueError("未知 plan 子命令")

    def _cmd_stage(self, service: KlogService, argv: list[str]) -> str:
        if not argv:
            raise ValueError("stage 缺少子命令")
        sub = argv[0]

        if sub == "add":
            if len(argv) < 3:
                raise ValueError("用法：/klog stage add <P#|alias> <name> --start <dt> --end <dt>")
            args = argv[1:].copy()
            note = pop_flag_value(args, "--note")
            start = pop_flag_value(args, "--start")
            end = pop_flag_value(args, "--end")
            if not start or not end:
                raise ValueError("--start/--end 必填")
            plan_ref = args[0]
            name = " ".join(args[1:]).strip()
            return service.stage_add(plan_ref=plan_ref, name=name, start_s=start, end_s=end, note=note)

        if sub == "ls":
            if len(argv) < 2:
                raise ValueError("用法：/klog stage ls <P#|alias>")
            return service.stage_ls(argv[1])

        if sub == "show":
            if len(argv) < 2:
                raise ValueError("用法：/klog stage show <S#>")
            return service.stage_show(argv[1])

        if sub == "time":
            if len(argv) < 2:
                raise ValueError("用法：/klog stage time <S#> --start <dt> --end <dt>")
            args = argv[1:].copy()
            start = pop_flag_value(args, "--start")
            end = pop_flag_value(args, "--end")
            if not start or not end:
                raise ValueError("--start/--end 必填")
            stage_ref = args[0]
            return service.stage_time(stage_ref, start_s=start, end_s=end)

        if sub == "rename":
            if len(argv) < 3:
                raise ValueError("用法：/klog stage rename <S#> <new_name>")
            return service.stage_rename(argv[1], " ".join(argv[2:]).strip())

        raise ValueError("未知 stage 子命令")

    def _cmd_task(self, service: KlogService, argv: list[str]) -> str:
        if not argv:
            raise ValueError("task 缺少子命令")
        sub = argv[0]

        if sub == "add":
            if len(argv) < 3:
                raise ValueError("用法：/klog task add <S#> <name> [--order <n>] [--note <text>]")
            args = argv[1:].copy()
            note = pop_flag_value(args, "--note")
            order_s = pop_flag_value(args, "--order")
            order_no = parse_int(order_s, "order", 1) if order_s else None
            stage_ref = args[0]
            name = " ".join(args[1:]).strip()
            return service.task_add(stage_ref=stage_ref, name=name, order_no=order_no, note=note)

        if sub == "ls":
            if len(argv) < 2:
                raise ValueError("用法：/klog task ls <S#> [--all]")
            args = argv[1:].copy()
            show_all = pop_flag_present(args, "--all")
            return service.task_ls(args[0], show_all=show_all)

        if sub == "show":
            if len(argv) < 2:
                raise ValueError("用法：/klog task show <T#>")
            return service.task_show(argv[1])

        if sub == "order":
            if len(argv) < 3:
                raise ValueError("用法：/klog task order <T#> <n>")
            return service.task_order(argv[1], argv[2])

        if sub == "rename":
            if len(argv) < 3:
                raise ValueError("用法：/klog task rename <T#> <new_name>")
            return service.task_rename(argv[1], " ".join(argv[2:]).strip())

        if sub == "prog":
            if len(argv) < 3:
                raise ValueError("用法：/klog task prog <T#> <0-100> [--note <text>]")
            args = argv[1:].copy()
            note = pop_flag_value(args, "--note")
            task_id = service.resolve_task_id(args[0])
            prog = parse_int(args[1], "progress", 0, 100)
            return service.task_set_progress(task_id, prog, note, log_type="progress_change")

        if sub == "state":
            if len(argv) < 3:
                raise ValueError("用法：/klog task state <T#> <todo|doing|done> [--note <text>]")
            args = argv[1:].copy()
            note = pop_flag_value(args, "--note")
            task_id = service.resolve_task_id(args[0])
            return service.task_set_state(task_id, args[1], note)

        raise ValueError("未知 task 子命令")

    def _cmd_timer(self, service: KlogService, origin: str, argv: list[str]) -> str:
        if not argv:
            raise ValueError("timer 缺少子命令")
        sub = argv[0]

        if sub == "start":
            if len(argv) < 2:
                raise ValueError("用法：/klog timer start <T#> [--remind <minutes|off>] [--to <session>]")
            args = argv[1:].copy()
            remind_s = pop_flag_value(args, "--remind")
            to_origin = pop_flag_value(args, "--to") or origin

            remind_off = False
            remind_minutes: Optional[int] = None
            if remind_s:
                if remind_s.lower() == "off":
                    remind_off = True
                else:
                    remind_minutes = parse_int(remind_s, "remind", 1, 24 * 60)

            task_ref = args[0]
            return service.timer_start(task_ref, remind_minutes=remind_minutes, remind_off=remind_off, unified_msg_origin=to_origin)

        if sub == "stop":
            args = argv[1:].copy()
            note = pop_flag_value(args, "--note")
            return service.timer_stop(note=note)

        if sub == "status":
            return service.timer_status()

        if sub == "remind":
            if len(argv) < 2:
                raise ValueError("用法：/klog timer remind <minutes|off>")
            v = argv[1]
            if v.lower() == "off":
                return service.timer_set_remind(None)
            minutes = parse_int(v, "remind", 1, 24 * 60)
            return service.timer_set_remind(minutes)

        raise ValueError("未知 timer 子命令")

    def _cmd_log(self, service: KlogService, argv: list[str]) -> str:
        if not argv:
            raise ValueError("log 缺少子命令")
        sub = argv[0]

        if sub == "add":
            if len(argv) < 2:
                raise ValueError("用法：/klog log add <text> [--task T#] [--min n] [--prog 0-100]")
            args = argv[1:].copy()
            task_ref = pop_flag_value(args, "--task")
            min_s = pop_flag_value(args, "--min")
            prog_s = pop_flag_value(args, "--prog")
            minutes = parse_int(min_s, "min", 0, 24 * 60) if min_s else None
            prog = parse_int(prog_s, "prog", 0, 100) if prog_s else None
            text = " ".join(args).strip()
            return service.log_add(text=text, task_ref=task_ref, minutes=minutes, prog=prog)

        if sub == "ls":
            if len(argv) < 2:
                raise ValueError("用法：/klog log ls <T#> [--date YYYY-MM-DD]")
            args = argv[1:].copy()
            date_s = pop_flag_value(args, "--date")
            return service.log_ls(args[0], date_s=date_s)

        raise ValueError("未知 log 子命令")

    def _cmd_daily(self, service: KlogService, argv: list[str]) -> str:
        if not argv:
            raise ValueError("daily 缺少子命令")
        sub = argv[0]

        if sub == "open":
            if len(argv) < 2:
                raise ValueError("用法：/klog daily open <YYYY-MM-DD> [--plan P#|alias]")
            args = argv[1:].copy()
            plan_ref = pop_flag_value(args, "--plan")
            date_s = args[0]
            return service.daily_open(date_s, plan_ref=plan_ref)

        if sub == "add":
            if len(argv) < 3:
                raise ValueError("用法：/klog daily add done|block|next|note <text>")
            field = argv[1]
            text = " ".join(argv[2:]).strip()
            return service.daily_add(field, text)

        if sub == "show":
            if len(argv) < 2:
                raise ValueError("用法：/klog daily show <YYYY-MM-DD> [--plan P#|alias]")
            args = argv[1:].copy()
            plan_ref = pop_flag_value(args, "--plan")
            return service.daily_show(args[0], plan_ref=plan_ref)

        if sub == "gen":
            if len(argv) < 2:
                raise ValueError("用法：/klog daily gen <YYYY-MM-DD> [--plan P#|alias]")
            args = argv[1:].copy()
            plan_ref = pop_flag_value(args, "--plan")
            return service.daily_gen(args[0], plan_ref=plan_ref)

        raise ValueError("未知 daily 子命令")

    def _cmd_prog(self, service: KlogService, argv: list[str]) -> str:
        if len(argv) < 1:
            raise ValueError("用法：/klog prog <0-100> [--note <text>]")
        args = argv.copy()
        note = pop_flag_value(args, "--note")
        prog = parse_int(args[0], "progress", 0, 100)
        active = service.timer_get_active()
        if not active:
            raise ValueError("当前没有活动计时器，无法确定要推进的任务。")
        return service.task_set_progress(active.task_id, prog, note, log_type="progress_change")
