from __future__ import annotations

from typing import Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

try:
    from .klog_app import KlogApp  # type: ignore
except Exception:  # pragma: no cover
    from klog_app import KlogApp


@register("klog", "yugz", "个人规划/日报/任务管理（QQ 专用）", "0.1.0")
class KlogPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._app: Optional[KlogApp] = None

    async def initialize(self):
        self._app = KlogApp(self.context, plugin_name=getattr(self, "name", "klog"))
        await self._app.initialize()

    @filter.command("kplog")
    async def kplog(self, event: AstrMessageEvent):
        if not self._app:
            yield event.plain_result("kplog 初始化中，请稍后再试。")
            return

        try:
            resp = await self._app.handle_event(event)
        except Exception as e:
            logger.exception("kplog handle_event error")
            yield event.plain_result(f"kplog 发生错误：{e}")
            return

        if resp is None:
            return

        if isinstance(resp, str):
            yield event.plain_result(resp)
            return

        # 默认按文本输出
        yield resp

    async def terminate(self):
        if self._app:
            await self._app.terminate()
