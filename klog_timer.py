from __future__ import annotations

import asyncio
from typing import Optional

from astrbot.api import logger
from astrbot.api.star import Context

try:
    from .klog_service import KlogService  # type: ignore
    from .klog_utils import compute_next_remind_at, from_iso, now_dt, to_iso  # type: ignore
except Exception:  # pragma: no cover
    from klog_service import KlogService
    from klog_utils import compute_next_remind_at, from_iso, now_dt, to_iso


class TimerManager:
    def __init__(self, context: Context, service: KlogService):
        self.context = context
        self.service = service
        self._task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        await self.refresh()

    async def terminate(self) -> None:
        await self._cancel()

    async def refresh(self) -> None:
        """
        根据 DB 的活动计时器状态，确保提醒循环存在或取消。
        """
        active = self.service.timer_get_active()
        if not active or active.remind_minutes is None:
            await self._cancel()
            return

        # 已经有循环就不重复建；循环内部会自己跟随 DB 变化
        if self._task and not self._task.done():
            return

        self._task = asyncio.create_task(self._loop(), name="klog_remind_loop")

    async def _cancel(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("kplog remind loop cancel error")
        self._task = None

    async def _loop(self) -> None:
        while True:
            active = self.service.timer_get_active()
            if not active:
                return
            if active.remind_minutes is None:
                return

            try:
                interval = int(active.remind_minutes)
                start_dt = from_iso(active.start_at)
                if active.next_remind_at:
                    next_dt = from_iso(active.next_remind_at)
                else:
                    next_dt = compute_next_remind_at(start_dt, interval, now_dt())
                    self.service.timer_update_next_remind(to_iso(next_dt))

                now = now_dt()
                sleep_s = max((next_dt - now).total_seconds(), 0)
                # 避免 0s 的忙等
                await asyncio.sleep(min(sleep_s, 3600))

                # 重新读取，确保未 stop / 未关提醒
                active2 = self.service.timer_get_active()
                if not active2 or active2.timer_id != active.timer_id:
                    continue
                if active2.remind_minutes is None:
                    continue

                # 到点（或已过点）就发提醒，并更新 next_remind_at
                now2 = now_dt()
                # 可能因为 sleep 被截断为 3600 而未到点
                if active2.next_remind_at and from_iso(active2.next_remind_at) > now2:
                    continue

                await self._send_remind(active2.unified_msg_origin, active2.task_id, active2.start_at)

                next_dt2 = compute_next_remind_at(start_dt, int(active2.remind_minutes), now2)
                self.service.timer_update_next_remind(to_iso(next_dt2))
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("kplog remind loop error")
                await asyncio.sleep(10)

    async def _send_remind(self, unified_msg_origin: str, task_id: int, start_at: str) -> None:
        elapsed = int((now_dt() - from_iso(start_at)).total_seconds() // 60)
        elapsed = max(elapsed, 0)
        text = (
            f"kplog 提醒：你正在计时 T{task_id}，已累计 {elapsed} 分钟。\n"
            f"- 记录日志：/kplog log add <心得> [--min <分钟>] [--prog <0-100>]\n"
            f"- 推进进度：/kplog prog <0-100> [--note <text>]\n"
            f"- 停止计时：/kplog timer stop"
        )
        # 主动消息：使用 docs 中建议的 context.send_message(unified_msg_origin, chains)
        # 这里用最简单的纯文本消息链
        from astrbot.api.event import MessageChain

        chain = MessageChain().message(text)
        await self.context.send_message(unified_msg_origin, chain)
