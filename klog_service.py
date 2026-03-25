from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from astrbot.api import logger

try:
    from .klog_db import KlogDB  # type: ignore
    from .klog_utils import (  # type: ignore
        compute_next_remind_at,
        fmt_dt_minute,
        fmt_dt_range,
        from_iso,
        now_dt,
        parse_date,
        parse_dt,
        parse_int,
        to_iso,
    )
except Exception:  # pragma: no cover
    from klog_db import KlogDB
    from klog_utils import (
        compute_next_remind_at,
        fmt_dt_minute,
        fmt_dt_range,
        from_iso,
        now_dt,
        parse_date,
        parse_dt,
        parse_int,
        to_iso,
    )


TASK_STATES = {"todo", "doing", "done"}


def _strip_prefix_id(token: str, prefix: str) -> Optional[int]:
    if not token:
        return None
    if token[0].upper() != prefix.upper():
        return None
    digits = token[1:]
    if not digits.isdigit():
        return None
    return int(digits)


@dataclass(frozen=True)
class ActiveTimer:
    timer_id: int
    task_id: int
    start_at: str
    remind_minutes: Optional[int]
    next_remind_at: Optional[str]
    unified_msg_origin: str


class KlogService:
    def __init__(self, db: KlogDB, user_id: str):
        self.db = db
        self.user_id = user_id

    # ------------------------
    # settings
    # ------------------------
    def get_setting(self, key: str) -> Optional[str]:
        row = self.db.fetchone(
            "SELECT value FROM settings WHERE user_id=? AND key=?;",
            (self.user_id, key),
        )
        return row["value"] if row else None

    def set_setting(self, key: str, value: Optional[str]) -> None:
        self.db.execute(
            """
            INSERT INTO settings(user_id, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET
              value=excluded.value,
              updated_at=excluded.updated_at;
            """,
            (self.user_id, key, value, to_iso(now_dt())),
        )

    # ------------------------
    # ref resolving
    # ------------------------
    def resolve_plan_id(self, ref: str) -> int:
        plan_id = _strip_prefix_id(ref, "P")
        if plan_id is not None:
            row = self.db.fetchone("SELECT id FROM plans WHERE id=? AND user_id=?;", (plan_id, self.user_id))
            if not row:
                raise ValueError(f"规划 {ref} 不存在")
            return int(row["id"])

        row = self.db.fetchone("SELECT id FROM plans WHERE alias=? AND user_id=?;", (ref, self.user_id))
        if not row:
            raise ValueError(f"规划 {ref} 不存在（也不是别名）")
        return int(row["id"])

    def resolve_stage_id(self, ref: str) -> int:
        stage_id = _strip_prefix_id(ref, "S")
        if stage_id is None:
            raise ValueError("阶段引用格式不正确，使用 S<number>，例如 S1")
        row = self.db.fetchone("SELECT id FROM stages WHERE id=? AND user_id=?;", (stage_id, self.user_id))
        if not row:
            raise ValueError(f"阶段 {ref} 不存在")
        return int(row["id"])

    def resolve_task_id(self, ref: str) -> int:
        task_id = _strip_prefix_id(ref, "T")
        if task_id is None:
            raise ValueError("任务引用格式不正确，使用 T<number>，例如 T1")
        row = self.db.fetchone("SELECT id FROM tasks WHERE id=? AND user_id=?;", (task_id, self.user_id))
        if not row:
            raise ValueError(f"任务 {ref} 不存在")
        return int(row["id"])

    # ------------------------
    # plan
    # ------------------------
    def plan_add(self, name: str, alias: Optional[str], note: Optional[str]) -> str:
        now = to_iso(now_dt())
        try:
            cur = self.db.execute(
                """
                INSERT INTO plans(user_id, name, alias, note, start_at, done_at, archived_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?);
                """,
                (self.user_id, name, alias, note, now, now),
            )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"创建规划失败：{e}")

        plan_id = int(cur.lastrowid)
        return f"已创建规划 P{plan_id}：{name}" + (f"（alias={alias}）" if alias else "")

    def plan_progress(self, plan_id: int) -> int:
        row = self.db.fetchone(
            """
            SELECT
              COUNT(*) AS stage_cnt,
              COALESCE(AVG(stage_progress), 0) AS avg_progress
            FROM (
              SELECT s.id AS stage_id,
                     CASE
                       WHEN COUNT(t.id)=0 THEN 0
                       ELSE AVG(t.progress)
                     END AS stage_progress
              FROM stages s
              LEFT JOIN tasks t ON t.stage_id = s.id
              WHERE s.plan_id=? AND s.user_id=?
              GROUP BY s.id
            );
            """,
            (plan_id, self.user_id),
        )
        if not row:
            return 0
        stage_cnt = int(row["stage_cnt"] or 0)
        if stage_cnt == 0:
            return 0
        return int(round(float(row["avg_progress"] or 0)))

    def plan_ls(self, active_only: bool = False) -> str:
        where = "AND archived_at IS NULL" if active_only else ""
        rows = self.db.fetchall(
            f"""
            SELECT id, name, alias, archived_at
            FROM plans
            WHERE user_id=? {where}
            ORDER BY id ASC;
            """,
            (self.user_id,),
        )
        if not rows:
            return "暂无规划。使用：/kplog plan add <name>"

        lines = ["规划列表："]
        for r in rows:
            pid = int(r["id"])
            alias = f" alias={r['alias']}" if r["alias"] else ""
            archived = " [已归档]" if r["archived_at"] else ""
            progress = self.plan_progress(pid)
            lines.append(f"- P{pid} {r['name']}（{progress}%）{alias}{archived}")
        return "\n".join(lines)

    def plan_show(self, ref: str) -> str:
        plan_id = self.resolve_plan_id(ref)
        plan = self.db.fetchone(
            """
            SELECT id, name, alias, note, start_at, done_at, archived_at
            FROM plans
            WHERE id=? AND user_id=?;
            """,
            (plan_id, self.user_id),
        )
        if not plan:
            raise ValueError("规划不存在")
        progress = self.plan_progress(plan_id)
        stages = self.db.fetchall(
            """
            SELECT id, name, plan_start_at, plan_end_at
            FROM stages
            WHERE plan_id=? AND user_id=?
            ORDER BY id ASC;
            """,
            (plan_id, self.user_id),
        )
        lines = [
            f"P{plan['id']} {plan['name']}",
            f"- 进度：{progress}%",
            f"- alias：{plan['alias'] or '-'}",
            f"- 实际开始：{fmt_dt_minute(plan['start_at'])}",
            f"- 实际完成：{fmt_dt_minute(plan['done_at'])}",
            f"- 备注：{(plan['note'] or '-').strip()}",
        ]
        if stages:
            lines.append("阶段：")
            for s in stages:
                sp = self.stage_progress(int(s["id"]))
                lines.append(f"- S{s['id']} {s['name']}（{sp}%） 预计 {fmt_dt_range(s['plan_start_at'], s['plan_end_at'])}")
        else:
            lines.append("阶段：无（使用 /kplog stage add ... 创建）")
        return "\n".join(lines)

    def plan_rename(self, ref: str, new_name: str) -> str:
        plan_id = self.resolve_plan_id(ref)
        now = to_iso(now_dt())
        try:
            self.db.execute(
                "UPDATE plans SET name=?, updated_at=? WHERE id=? AND user_id=?;",
                (new_name, now, plan_id, self.user_id),
            )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"重命名失败：{e}")
        return f"已重命名规划 P{plan_id} 为：{new_name}"

    def plan_alias(self, plan_ref: str, alias: str) -> str:
        plan_id = self.resolve_plan_id(plan_ref)
        now = to_iso(now_dt())
        try:
            self.db.execute(
                "UPDATE plans SET alias=?, updated_at=? WHERE id=? AND user_id=?;",
                (alias, now, plan_id, self.user_id),
            )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"设置别名失败：{e}")
        return f"已设置规划 P{plan_id} 的别名为：{alias}"

    def plan_archive(self, ref: str) -> str:
        plan_id = self.resolve_plan_id(ref)
        now = to_iso(now_dt())
        self.db.execute(
            "UPDATE plans SET archived_at=?, updated_at=? WHERE id=? AND user_id=?;",
            (now, now, plan_id, self.user_id),
        )
        return f"已归档规划 P{plan_id}"

    # ------------------------
    # stage
    # ------------------------
    def stage_add(self, plan_ref: str, name: str, start_s: str, end_s: str, note: Optional[str]) -> str:
        plan_id = self.resolve_plan_id(plan_ref)
        start = parse_dt(start_s)
        end = parse_dt(end_s)
        if end <= start:
            raise ValueError("预计结束时间必须晚于开始时间")
        now = to_iso(now_dt())
        try:
            cur = self.db.execute(
                """
                INSERT INTO stages(user_id, plan_id, name, note, plan_start_at, plan_end_at, start_at, done_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?);
                """,
                (self.user_id, plan_id, name, note, to_iso(start), to_iso(end), now, now),
            )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"创建阶段失败：{e}")
        sid = int(cur.lastrowid)
        return f"已创建阶段 S{sid}：{name}"

    def stage_progress(self, stage_id: int) -> int:
        row = self.db.fetchone(
            """
            SELECT
              COUNT(id) AS task_cnt,
              COALESCE(AVG(progress), 0) AS avg_progress
            FROM tasks
            WHERE stage_id=? AND user_id=?;
            """,
            (stage_id, self.user_id),
        )
        if not row:
            return 0
        task_cnt = int(row["task_cnt"] or 0)
        if task_cnt == 0:
            return 0
        return int(round(float(row["avg_progress"] or 0)))

    def stage_ls(self, plan_ref: str) -> str:
        plan_id = self.resolve_plan_id(plan_ref)
        rows = self.db.fetchall(
            """
            SELECT id, name, plan_start_at, plan_end_at
            FROM stages
            WHERE plan_id=? AND user_id=?
            ORDER BY id ASC;
            """,
            (plan_id, self.user_id),
        )
        if not rows:
            return "该规划下暂无阶段。使用：/kplog stage add ..."
        lines = [f"阶段列表（P{plan_id}）："]
        for r in rows:
            sp = self.stage_progress(int(r["id"]))
            lines.append(f"- S{r['id']} {r['name']}（{sp}%） 预计 {fmt_dt_range(r['plan_start_at'], r['plan_end_at'])}")
        return "\n".join(lines)

    def stage_show(self, stage_ref: str) -> str:
        stage_id = self.resolve_stage_id(stage_ref)
        stage = self.db.fetchone(
            """
            SELECT id, plan_id, name, note, plan_start_at, plan_end_at, start_at, done_at
            FROM stages
            WHERE id=? AND user_id=?;
            """,
            (stage_id, self.user_id),
        )
        if not stage:
            raise ValueError("阶段不存在")
        sp = self.stage_progress(stage_id)
        lines = [
            f"S{stage['id']} {stage['name']}",
            f"- 规划：P{stage['plan_id']}",
            f"- 进度：{sp}%",
            f"- 预计：{fmt_dt_range(stage['plan_start_at'], stage['plan_end_at'])}",
            f"- 实际开始：{fmt_dt_minute(stage['start_at'])}",
            f"- 实际完成：{fmt_dt_minute(stage['done_at'])}",
            f"- 备注：{(stage['note'] or '-').strip()}",
        ]
        tasks = self.db.fetchall(
            """
            SELECT id, name, order_no, state, progress
            FROM tasks
            WHERE stage_id=? AND user_id=?
            ORDER BY
              CASE WHEN order_no IS NULL THEN 1 ELSE 0 END,
              order_no ASC,
              id ASC;
            """,
            (stage_id, self.user_id),
        )
        if tasks:
            lines.append("任务：")
            for t in tasks:
                order = f"#{t['order_no']} " if t["order_no"] is not None else ""
                lines.append(f"- T{t['id']} {order}{t['name']} [{t['state']}] {t['progress']}%")
        else:
            lines.append("任务：无（使用 /kplog task add ... 创建）")
        return "\n".join(lines)

    def stage_time(self, stage_ref: str, start_s: str, end_s: str) -> str:
        stage_id = self.resolve_stage_id(stage_ref)
        start = parse_dt(start_s)
        end = parse_dt(end_s)
        if end <= start:
            raise ValueError("预计结束时间必须晚于开始时间")
        now = to_iso(now_dt())
        self.db.execute(
            "UPDATE stages SET plan_start_at=?, plan_end_at=?, updated_at=? WHERE id=? AND user_id=?;",
            (to_iso(start), to_iso(end), now, stage_id, self.user_id),
        )
        return f"已更新阶段 S{stage_id} 的预计时间"

    def stage_rename(self, stage_ref: str, new_name: str) -> str:
        stage_id = self.resolve_stage_id(stage_ref)
        now = to_iso(now_dt())
        try:
            self.db.execute(
                "UPDATE stages SET name=?, updated_at=? WHERE id=? AND user_id=?;",
                (new_name, now, stage_id, self.user_id),
            )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"重命名失败：{e}")
        return f"已重命名阶段 S{stage_id} 为：{new_name}"

    # ------------------------
    # task
    # ------------------------
    def task_add(self, stage_ref: str, name: str, order_no: Optional[int], note: Optional[str]) -> str:
        stage_id = self.resolve_stage_id(stage_ref)
        now = to_iso(now_dt())
        try:
            cur = self.db.execute(
                """
                INSERT INTO tasks(user_id, stage_id, name, note, order_no, state, progress, start_at, done_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'todo', 0, NULL, NULL, ?, ?);
                """,
                (self.user_id, stage_id, name, note, order_no, now, now),
            )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"创建任务失败：{e}")
        tid = int(cur.lastrowid)
        return f"已创建任务 T{tid}：{name}" + (f"（顺序 {order_no}）" if order_no is not None else "")

    def task_ls(self, stage_ref: str, show_all: bool = False) -> str:
        stage_id = self.resolve_stage_id(stage_ref)
        where = "" if show_all else "AND state!='done'"
        rows = self.db.fetchall(
            f"""
            SELECT id, name, order_no, state, progress
            FROM tasks
            WHERE stage_id=? AND user_id=? {where}
            ORDER BY
              CASE WHEN order_no IS NULL THEN 1 ELSE 0 END,
              order_no ASC,
              id ASC;
            """,
            (stage_id, self.user_id),
        )
        if not rows:
            return "暂无任务。使用：/kplog task add ..."
        lines = [f"任务列表（S{stage_id}）："]
        for r in rows:
            order = f"#{r['order_no']} " if r["order_no"] is not None else ""
            lines.append(f"- T{r['id']} {order}{r['name']} [{r['state']}] {r['progress']}%")
        return "\n".join(lines)

    def task_show(self, task_ref: str) -> str:
        task_id = self.resolve_task_id(task_ref)
        task = self.db.fetchone(
            """
            SELECT id, stage_id, name, note, order_no, state, progress, start_at, done_at
            FROM tasks
            WHERE id=? AND user_id=?;
            """,
            (task_id, self.user_id),
        )
        if not task:
            raise ValueError("任务不存在")
        lines = [
            f"T{task['id']} {task['name']}",
            f"- 阶段：S{task['stage_id']}",
            f"- 状态：{task['state']}",
            f"- 进度：{task['progress']}%",
            f"- 顺序：{task['order_no'] if task['order_no'] is not None else '-'}",
            f"- 开始：{fmt_dt_minute(task['start_at'])}",
            f"- 完成：{fmt_dt_minute(task['done_at'])}",
            f"- 备注：{(task['note'] or '-').strip()}",
        ]
        return "\n".join(lines)

    def task_order(self, task_ref: str, order_s: str) -> str:
        task_id = self.resolve_task_id(task_ref)
        order_no = parse_int(order_s, "order", min_value=1)
        now = to_iso(now_dt())
        self.db.execute(
            "UPDATE tasks SET order_no=?, updated_at=? WHERE id=? AND user_id=?;",
            (order_no, now, task_id, self.user_id),
        )
        return f"已设置 T{task_id} 的顺序号为 {order_no}"

    def task_rename(self, task_ref: str, new_name: str) -> str:
        task_id = self.resolve_task_id(task_ref)
        now = to_iso(now_dt())
        try:
            self.db.execute(
                "UPDATE tasks SET name=?, updated_at=? WHERE id=? AND user_id=?;",
                (new_name, now, task_id, self.user_id),
            )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"重命名失败：{e}")
        return f"已重命名任务 T{task_id} 为：{new_name}"

    def task_set_progress(self, task_id: int, progress: int, note: Optional[str], log_type: str) -> str:
        if progress < 0 or progress > 100:
            raise ValueError("进度必须在 0~100 之间")

        task = self.db.fetchone(
            "SELECT id, stage_id, state, progress, start_at, done_at FROM tasks WHERE id=? AND user_id=?;",
            (task_id, self.user_id),
        )
        if not task:
            raise ValueError("任务不存在")

        state = str(task["state"])
        start_at = task["start_at"]
        done_at = task["done_at"]
        now = to_iso(now_dt())

        new_state = state
        new_done_at = done_at
        new_start_at = start_at

        if state == "todo" and progress > 0:
            new_state = "doing"
            if not start_at:
                new_start_at = now

        if progress == 100:
            new_state = "done"
            if not done_at:
                new_done_at = now
            if not start_at:
                new_start_at = now

        if state == "done" and progress < 100:
            new_state = "doing" if progress > 0 else "todo"
            new_done_at = None

        self.db.execute(
            """
            UPDATE tasks
            SET state=?, progress=?, start_at=?, done_at=?, updated_at=?
            WHERE id=? AND user_id=?;
            """,
            (new_state, progress, new_start_at, new_done_at, now, task_id, self.user_id),
        )
        self.db.execute(
            """
            INSERT INTO worklogs(user_id, task_id, type, minutes, note, progress, created_at)
            VALUES (?, ?, ?, NULL, ?, ?, ?);
            """,
            (self.user_id, task_id, log_type, note, progress, now),
        )

        stage_id = int(task["stage_id"])
        plan_id = int(
            self.db.fetchone("SELECT plan_id FROM stages WHERE id=? AND user_id=?;", (stage_id, self.user_id))["plan_id"]
        )
        self._update_stage_plan_times(stage_id=stage_id, plan_id=plan_id)

        warn = self._order_warning(task_id=task_id)
        base = f"已更新 T{task_id} 进度：{progress}%（{new_state}）"
        if warn:
            return base + "\n" + warn
        return base

    def task_set_state(self, task_id: int, new_state: str, note: Optional[str]) -> str:
        if new_state not in TASK_STATES:
            raise ValueError("state 必须是 todo|doing|done")

        task = self.db.fetchone(
            "SELECT id, stage_id, state, progress, start_at, done_at FROM tasks WHERE id=? AND user_id=?;",
            (task_id, self.user_id),
        )
        if not task:
            raise ValueError("任务不存在")

        now = to_iso(now_dt())
        start_at = task["start_at"]
        done_at = task["done_at"]
        progress = int(task["progress"])

        if new_state == "todo":
            if progress == 100:
                progress = 0
            done_at = None
        elif new_state == "doing":
            if not start_at:
                start_at = now
            if progress == 0:
                progress = 1
            if progress == 100:
                progress = 99
            done_at = None
        elif new_state == "done":
            if not start_at:
                start_at = now
            done_at = done_at or now
            progress = 100

        self.db.execute(
            """
            UPDATE tasks
            SET state=?, progress=?, start_at=?, done_at=?, updated_at=?
            WHERE id=? AND user_id=?;
            """,
            (new_state, progress, start_at, done_at, now, task_id, self.user_id),
        )
        self.db.execute(
            """
            INSERT INTO worklogs(user_id, task_id, type, minutes, note, progress, created_at)
            VALUES (?, ?, 'state_change', NULL, ?, ?, ?);
            """,
            (self.user_id, task_id, note, progress, now),
        )

        stage_id = int(task["stage_id"])
        plan_id = int(
            self.db.fetchone("SELECT plan_id FROM stages WHERE id=? AND user_id=?;", (stage_id, self.user_id))["plan_id"]
        )
        self._update_stage_plan_times(stage_id=stage_id, plan_id=plan_id)

        warn = self._order_warning(task_id=task_id)
        base = f"已更新 T{task_id} 状态：{new_state}（{progress}%）"
        if warn:
            return base + "\n" + warn
        return base

    def _order_warning(self, task_id: int) -> Optional[str]:
        row = self.db.fetchone(
            "SELECT stage_id, order_no FROM tasks WHERE id=? AND user_id=?;",
            (task_id, self.user_id),
        )
        if not row:
            return None
        stage_id = int(row["stage_id"])
        order_no = row["order_no"]
        if order_no is None:
            return None
        rows = self.db.fetchall(
            """
            SELECT id, order_no
            FROM tasks
            WHERE stage_id=? AND user_id=?
              AND order_no IS NOT NULL
              AND order_no < ?
              AND state != 'done'
            ORDER BY order_no ASC, id ASC;
            """,
            (stage_id, self.user_id, int(order_no)),
        )
        if not rows:
            return None
        tips = ", ".join([f"T{r['id']}#{r['order_no']}" for r in rows])
        return f"顺序提示：在你当前任务之前还有未完成的顺序任务：{tips}"

    def _update_stage_plan_times(self, stage_id: int, plan_id: int) -> None:
        now = to_iso(now_dt())
        st = self.db.fetchone("SELECT start_at, done_at FROM stages WHERE id=? AND user_id=?;", (stage_id, self.user_id))
        if st:
            if not st["start_at"]:
                row = self.db.fetchone(
                    "SELECT MIN(start_at) AS min_start FROM tasks WHERE stage_id=? AND user_id=? AND start_at IS NOT NULL;",
                    (stage_id, self.user_id),
                )
                if row and row["min_start"]:
                    self.db.execute(
                        "UPDATE stages SET start_at=?, updated_at=? WHERE id=? AND user_id=?;",
                        (row["min_start"], now, stage_id, self.user_id),
                    )

            stats = self.db.fetchone(
                """
                SELECT
                  COUNT(id) AS cnt,
                  SUM(CASE WHEN state='done' THEN 1 ELSE 0 END) AS done_cnt,
                  MAX(done_at) AS max_done
                FROM tasks
                WHERE stage_id=? AND user_id=?;
                """,
                (stage_id, self.user_id),
            )
            if stats and int(stats["cnt"] or 0) > 0 and int(stats["done_cnt"] or 0) == int(stats["cnt"] or 0):
                if not st["done_at"]:
                    self.db.execute(
                        "UPDATE stages SET done_at=?, updated_at=? WHERE id=? AND user_id=?;",
                        (stats["max_done"] or now, now, stage_id, self.user_id),
                    )
            else:
                if st["done_at"]:
                    self.db.execute(
                        "UPDATE stages SET done_at=NULL, updated_at=? WHERE id=? AND user_id=?;",
                        (now, stage_id, self.user_id),
                    )

        pl = self.db.fetchone("SELECT start_at, done_at FROM plans WHERE id=? AND user_id=?;", (plan_id, self.user_id))
        if pl:
            if not pl["start_at"]:
                row = self.db.fetchone(
                    """
                    SELECT MIN(start_at) AS min_start
                    FROM stages
                    WHERE plan_id=? AND user_id=? AND start_at IS NOT NULL;
                    """,
                    (plan_id, self.user_id),
                )
                if row and row["min_start"]:
                    self.db.execute(
                        "UPDATE plans SET start_at=?, updated_at=? WHERE id=? AND user_id=?;",
                        (row["min_start"], now, plan_id, self.user_id),
                    )

            stats = self.db.fetchone(
                """
                SELECT
                  COUNT(id) AS cnt,
                  SUM(CASE WHEN done_at IS NOT NULL THEN 1 ELSE 0 END) AS done_cnt,
                  MAX(done_at) AS max_done
                FROM stages
                WHERE plan_id=? AND user_id=?;
                """,
                (plan_id, self.user_id),
            )
            if stats and int(stats["cnt"] or 0) > 0 and int(stats["done_cnt"] or 0) == int(stats["cnt"] or 0):
                if not pl["done_at"]:
                    self.db.execute(
                        "UPDATE plans SET done_at=?, updated_at=? WHERE id=? AND user_id=?;",
                        (stats["max_done"] or now, now, plan_id, self.user_id),
                    )
            else:
                if pl["done_at"]:
                    self.db.execute(
                        "UPDATE plans SET done_at=NULL, updated_at=? WHERE id=? AND user_id=?;",
                        (now, plan_id, self.user_id),
                    )

    # ------------------------
    # timer
    # ------------------------
    def timer_get_active(self) -> Optional[ActiveTimer]:
        row = self.db.fetchone(
            """
            SELECT id, task_id, start_at, remind_minutes, next_remind_at, unified_msg_origin
            FROM timers
            WHERE user_id=? AND end_at IS NULL
            ORDER BY id DESC
            LIMIT 1;
            """,
            (self.user_id,),
        )
        if not row:
            return None
        return ActiveTimer(
            timer_id=int(row["id"]),
            task_id=int(row["task_id"]),
            start_at=str(row["start_at"]),
            remind_minutes=int(row["remind_minutes"]) if row["remind_minutes"] is not None else None,
            next_remind_at=str(row["next_remind_at"]) if row["next_remind_at"] is not None else None,
            unified_msg_origin=str(row["unified_msg_origin"]),
        )

    def timer_start(self, task_ref: str, remind_minutes: Optional[int], remind_off: bool, unified_msg_origin: str) -> str:
        if self.timer_get_active():
            raise ValueError("已存在活动计时器，请先执行：/kplog timer stop")

        task_id = self.resolve_task_id(task_ref)
        task = self.db.fetchone(
            "SELECT id, stage_id, state, progress FROM tasks WHERE id=? AND user_id=?;",
            (task_id, self.user_id),
        )
        if not task:
            raise ValueError("任务不存在")
        if str(task["state"]) == "done":
            raise ValueError("该任务已完成。如需重新计时，请先将任务回退到 doing/todo。")

        default_remind = self.get_setting("default_remind_minutes")
        if remind_off:
            remind_val = None
        elif remind_minutes is not None:
            remind_val = remind_minutes
        elif default_remind is not None:
            remind_val = int(default_remind)
        else:
            remind_val = 20

        now = to_iso(now_dt())
        if str(task["state"]) == "todo":
            self.db.execute(
                """
                UPDATE tasks
                SET state='doing',
                    start_at=COALESCE(start_at, ?),
                    progress=CASE WHEN progress=0 THEN 1 ELSE progress END,
                    updated_at=?
                WHERE id=? AND user_id=?;
                """,
                (now, now, task_id, self.user_id),
            )
            self.db.execute(
                """
                INSERT INTO worklogs(user_id, task_id, type, minutes, note, progress, created_at)
                VALUES (?, ?, 'state_change', NULL, 'timer start => doing', NULL, ?);
                """,
                (self.user_id, task_id, now),
            )

        next_remind_at = None
        if remind_val is not None:
            next_dt = compute_next_remind_at(from_iso(now), remind_val, now_dt())
            next_remind_at = to_iso(next_dt)

        cur = self.db.execute(
            """
            INSERT INTO timers(user_id, task_id, start_at, end_at, remind_minutes, next_remind_at, unified_msg_origin, created_at, updated_at)
            VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?);
            """,
            (self.user_id, task_id, now, remind_val, next_remind_at, unified_msg_origin, now, now),
        )
        timer_id = int(cur.lastrowid)

        stage_id = int(task["stage_id"])
        plan_id = int(
            self.db.fetchone("SELECT plan_id FROM stages WHERE id=? AND user_id=?;", (stage_id, self.user_id))["plan_id"]
        )
        self._update_stage_plan_times(stage_id=stage_id, plan_id=plan_id)

        return f"已开始计时：timer#{timer_id} 任务 T{task_id}" + (
            f"（提醒 {remind_val} 分钟）" if remind_val is not None else "（提醒已关闭）"
        )

    def timer_stop(self, note: Optional[str]) -> str:
        active = self.timer_get_active()
        if not active:
            return "当前没有活动计时器。"

        start_dt = from_iso(active.start_at)
        end_dt = now_dt()
        mins = int((end_dt - start_dt).total_seconds() // 60)
        mins = max(mins, 0)
        now = to_iso(end_dt)

        self.db.execute(
            "UPDATE timers SET end_at=?, updated_at=? WHERE id=? AND user_id=?;",
            (now, now, active.timer_id, self.user_id),
        )
        self.db.execute(
            """
            INSERT INTO worklogs(user_id, task_id, type, minutes, note, progress, created_at)
            VALUES (?, ?, 'timer_stop', ?, ?, NULL, ?);
            """,
            (self.user_id, active.task_id, mins, note, now),
        )
        return f"已停止计时：T{active.task_id} 本次 {mins} 分钟"

    def timer_status(self) -> str:
        active = self.timer_get_active()
        if not active:
            return "当前没有活动计时器。"
        task = self.db.fetchone(
            "SELECT name, progress, state FROM tasks WHERE id=? AND user_id=?;",
            (active.task_id, self.user_id),
        )
        task_name = task["name"] if task else "-"
        elapsed = int((now_dt() - from_iso(active.start_at)).total_seconds() // 60)
        elapsed = max(elapsed, 0)
        remind = f"{active.remind_minutes} 分钟" if active.remind_minutes is not None else "关闭"
        nxt = fmt_dt_minute(active.next_remind_at)
        return (
            f"计时中：T{active.task_id} {task_name}\n"
            f"- 已累计：{elapsed} 分钟\n"
            f"- 任务：{task['state'] if task else '-'} {task['progress'] if task else '-'}%\n"
            f"- 提醒：{remind}\n"
            f"- 下次提醒：{nxt}"
        )

    def timer_set_remind(self, minutes: Optional[int]) -> str:
        active = self.timer_get_active()
        if not active:
            if minutes is None:
                self.set_setting("default_remind_minutes", None)
                return "已清空默认提醒间隔。"
            self.set_setting("default_remind_minutes", str(minutes))
            return f"已设置默认提醒间隔为 {minutes} 分钟（下次 timer start 生效）"

        now = to_iso(now_dt())
        next_remind_at = None
        if minutes is not None:
            next_dt = compute_next_remind_at(from_iso(active.start_at), minutes, now_dt())
            next_remind_at = to_iso(next_dt)

        self.db.execute(
            """
            UPDATE timers
            SET remind_minutes=?, next_remind_at=?, updated_at=?
            WHERE id=? AND user_id=?;
            """,
            (minutes, next_remind_at, now, active.timer_id, self.user_id),
        )
        if minutes is None:
            return "已关闭当前计时器的提醒。"
        return f"已更新当前计时器提醒间隔为 {minutes} 分钟"

    def timer_update_next_remind(self, next_remind_at: str) -> None:
        active = self.timer_get_active()
        if not active:
            return
        now = to_iso(now_dt())
        self.db.execute(
            "UPDATE timers SET next_remind_at=?, updated_at=? WHERE id=? AND user_id=?;",
            (next_remind_at, now, active.timer_id, self.user_id),
        )

    # ------------------------
    # worklog
    # ------------------------
    def log_add(self, text: str, task_ref: Optional[str], minutes: Optional[int], prog: Optional[int]) -> str:
        if task_ref:
            task_id = self.resolve_task_id(task_ref)
        else:
            active = self.timer_get_active()
            if not active:
                raise ValueError("未指定任务且当前没有活动计时器。使用：/kplog log add ... --task T#")
            task_id = active.task_id

        now = to_iso(now_dt())
        # 先按用户输入写一条日志（只写一次）
        self.db.execute(
            """
            INSERT INTO worklogs(user_id, task_id, type, minutes, note, progress, created_at)
            VALUES (?, ?, 'manual', ?, ?, ?, ?);
            """,
            (self.user_id, task_id, minutes, text, prog, now),
        )

        if prog is None:
            return f"已记录日志：T{task_id}" + (f" {minutes} 分钟" if minutes is not None else "")

        # 如携带 --prog，则推进任务进度（不再额外写第二条 worklog）
        task = self.db.fetchone(
            "SELECT id, stage_id, state, progress, start_at, done_at FROM tasks WHERE id=? AND user_id=?;",
            (task_id, self.user_id),
        )
        if not task:
            raise ValueError("任务不存在")

        state = str(task["state"])
        start_at = task["start_at"]
        done_at = task["done_at"]
        new_state = state
        new_start_at = start_at
        new_done_at = done_at

        if state == "todo" and prog > 0:
            new_state = "doing"
            if not start_at:
                new_start_at = now

        if prog == 100:
            new_state = "done"
            if not done_at:
                new_done_at = now
            if not start_at:
                new_start_at = now

        if state == "done" and prog < 100:
            new_state = "doing" if prog > 0 else "todo"
            new_done_at = None

        self.db.execute(
            """
            UPDATE tasks
            SET state=?, progress=?, start_at=?, done_at=?, updated_at=?
            WHERE id=? AND user_id=?;
            """,
            (new_state, prog, new_start_at, new_done_at, now, task_id, self.user_id),
        )

        stage_id = int(task["stage_id"])
        plan_id = int(
            self.db.fetchone("SELECT plan_id FROM stages WHERE id=? AND user_id=?;", (stage_id, self.user_id))["plan_id"]
        )
        self._update_stage_plan_times(stage_id=stage_id, plan_id=plan_id)

        warn = self._order_warning(task_id=task_id)
        base = f"已记录日志并更新进度：T{task_id} {prog}%（{new_state}）"
        if minutes is not None:
            base += f"；本次 {minutes} 分钟"
        if warn:
            base += "\n" + warn
        return base

    def log_ls(self, task_ref: str, date_s: Optional[str]) -> str:
        task_id = self.resolve_task_id(task_ref)
        params: list[object] = [self.user_id, task_id]
        where = ""
        if date_s:
            d = parse_date(date_s)
            start = f"{d}T00:00:00+08:00"
            end = f"{d}T23:59:59+08:00"
            where = "AND created_at BETWEEN ? AND ?"
            params.extend([start, end])

        rows = self.db.fetchall(
            f"""
            SELECT id, type, minutes, note, progress, created_at
            FROM worklogs
            WHERE user_id=? AND task_id=? {where}
            ORDER BY id DESC
            LIMIT 50;
            """,
            params,
        )
        if not rows:
            return "暂无日志。"
        lines = [f"日志列表（T{task_id}，最多 50 条）："]
        for r in rows:
            mins = f"{r['minutes']}m " if r["minutes"] is not None else ""
            prog = f"{r['progress']}% " if r["progress"] is not None else ""
            note = (r["note"] or "").strip()
            if len(note) > 40:
                note = note[:40] + "…"
            lines.append(f"- #{r['id']} [{r['type']}] {mins}{prog}{fmt_dt_minute(r['created_at'])} {note}")
        return "\n".join(lines)

    # ------------------------
    # daily
    # ------------------------
    def daily_open(self, date_s: str, plan_ref: Optional[str]) -> str:
        date = parse_date(date_s)
        plan_id = self.resolve_plan_id(plan_ref) if plan_ref else None
        now = to_iso(now_dt())
        self.db.execute(
            """
            INSERT INTO dailies(user_id, date, plan_id, done, block, next, note, created_at, updated_at)
            VALUES (?, ?, ?, '', '', '', '', ?, ?)
            ON CONFLICT(user_id, date, plan_id) DO UPDATE SET updated_at=excluded.updated_at;
            """,
            (self.user_id, date, plan_id, now, now),
        )
        self.set_setting("current_daily_date", date)
        self.set_setting("current_daily_plan_id", str(plan_id) if plan_id is not None else "")
        scope = f"P{plan_id}" if plan_id is not None else "全局"
        return f"已打开日报：{date}（{scope}）"

    def _daily_current_scope(self) -> tuple[str, Optional[int]]:
        date = self.get_setting("current_daily_date")
        if not date:
            raise ValueError("未打开日报。使用：/kplog daily open <YYYY-MM-DD> [--plan P#|alias]")
        plan_id_s = self.get_setting("current_daily_plan_id") or ""
        plan_id = int(plan_id_s) if plan_id_s.strip().isdigit() else None
        return date, plan_id

    def daily_add(self, field: str, text: str) -> str:
        if field not in {"done", "block", "next", "note"}:
            raise ValueError("daily add 字段必须是 done|block|next|note")
        date, plan_id = self._daily_current_scope()

        row = self.db.fetchone(
            "SELECT id, done, block, next, note FROM dailies WHERE user_id=? AND date=? AND plan_id IS ?;",
            (self.user_id, date, plan_id),
        )
        if not row:
            self.daily_open(date, f"P{plan_id}" if plan_id is not None else None)
            row = self.db.fetchone(
                "SELECT id, done, block, next, note FROM dailies WHERE user_id=? AND date=? AND plan_id IS ?;",
                (self.user_id, date, plan_id),
            )

        cur_val = (row[field] or "").rstrip()
        line = text.strip()
        if not line:
            raise ValueError("内容不能为空")
        if not line.startswith("- "):
            line = "- " + line
        new_val = (cur_val + "\n" + line).strip() if cur_val else line

        now = to_iso(now_dt())
        self.db.execute(
            f"UPDATE dailies SET {field}=?, updated_at=? WHERE id=?;",
            (new_val, now, int(row["id"])),
        )
        return f"已追加日报 {field}：{text}"

    def daily_show(self, date_s: str, plan_ref: Optional[str]) -> str:
        date = parse_date(date_s)
        plan_id = self.resolve_plan_id(plan_ref) if plan_ref else None
        row = self.db.fetchone(
            "SELECT done, block, next, note FROM dailies WHERE user_id=? AND date=? AND plan_id IS ?;",
            (self.user_id, date, plan_id),
        )
        if not row:
            return "日报不存在。使用：/kplog daily open ..."
        scope = f"P{plan_id}" if plan_id is not None else "全局"
        return (
            f"日报 {date}（{scope}）\n"
            f"\n【今日完成】\n{(row['done'] or '').strip() or '-'}\n"
            f"\n【阻塞问题】\n{(row['block'] or '').strip() or '-'}\n"
            f"\n【明日计划】\n{(row['next'] or '').strip() or '-'}\n"
            f"\n【心得反思】\n{(row['note'] or '').strip() or '-'}"
        )

    def daily_gen(self, date_s: str, plan_ref: Optional[str]) -> str:
        date = parse_date(date_s)
        plan_id = self.resolve_plan_id(plan_ref) if plan_ref else None
        start = f"{date}T00:00:00+08:00"
        end = f"{date}T23:59:59+08:00"
        params: list[object] = [self.user_id, start, end]
        plan_where = ""
        if plan_id is not None:
            plan_where = "AND p.id=?"
            params.append(plan_id)

        rows = self.db.fetchall(
            f"""
            SELECT
              p.id AS plan_id,
              p.name AS plan_name,
              s.id AS stage_id,
              s.name AS stage_name,
              t.id AS task_id,
              t.name AS task_name,
              SUM(COALESCE(w.minutes, 0)) AS total_minutes,
              COUNT(w.id) AS log_cnt
            FROM worklogs w
            JOIN tasks t ON t.id=w.task_id
            JOIN stages s ON s.id=t.stage_id
            JOIN plans p ON p.id=s.plan_id
            WHERE w.user_id=? AND w.created_at BETWEEN ? AND ?
              {plan_where}
            GROUP BY p.id, s.id, t.id
            ORDER BY total_minutes DESC, w.task_id ASC;
            """,
            params,
        )
        scope = f"P{plan_id}" if plan_id is not None else "全局"
        if not rows:
            return f"日报草稿 {date}（{scope}）：\n- 今天没有记录到执行日志。"

        lines = [f"日报草稿 {date}（{scope}）", "", "【自动汇总（可复制修改）】"]
        total = 0
        for r in rows:
            mins = int(r["total_minutes"] or 0)
            total += mins
            lines.append(
                f"- P{r['plan_id']} {r['plan_name']} / S{r['stage_id']} {r['stage_name']} / "
                f"T{r['task_id']} {r['task_name']}：{mins} 分钟（{r['log_cnt']} 条）"
            )
        lines.append("")
        lines.append(f"总计：{total} 分钟")
        lines.append("")
        lines.append("可继续用：/kplog daily add done|block|next|note ... 逐项完善。")
        return "\n".join(lines)
