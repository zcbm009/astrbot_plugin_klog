from __future__ import annotations


def help_text() -> str:
    return (
        "kplog 指令总览（QQ 专用）\n"
        "\n"
        "子命令帮助：\n"
        "- /kplog plan help | /kplog stage help | /kplog task help | /kplog timer help | /kplog log help | /kplog daily help | /kplog prog help\n"
        "\n"
        "帮助：\n"
        "- /kplog help\n"
        "\n"
        "规划：\n"
        "- /kplog plan add <name> [--alias <alias>] [--note <text>]\n"
        "- /kplog plan ls [--active]\n"
        "- /kplog plan show <P#|alias>\n"
        "- /kplog plan rename <P#|alias> <new_name>\n"
        "- /kplog plan alias <P#|alias> <alias>\n"
        "- /kplog plan archive <P#|alias>\n"
        "\n"
        "阶段：\n"
        "- /kplog stage add <P#|alias> <name> --start <dt> --end <dt> [--note <text>]\n"
        "- /kplog stage ls <P#|alias>\n"
        "- /kplog stage show <S#>\n"
        "- /kplog stage time <S#> --start <dt> --end <dt>\n"
        "- /kplog stage rename <S#> <new_name>\n"
        "\n"
        "任务：\n"
        "- /kplog task add <S#> <name> [--order <n>] [--note <text>]\n"
        "- /kplog task ls <S#> [--all]\n"
        "- /kplog task show <T#>\n"
        "- /kplog task order <T#> <n>\n"
        "- /kplog task rename <T#> <new_name>\n"
        "- /kplog task prog <T#> <0-100> [--note <text>]\n"
        "- /kplog task state <T#> <todo|doing|done> [--note <text>]\n"
        "\n"
        "计时：\n"
        "- /kplog timer start <T#> [--remind <minutes|off>] [--to <session>]\n"
        "- /kplog timer stop [--note <text>]\n"
        "- /kplog timer status\n"
        "- /kplog timer remind <minutes|off>\n"
        "\n"
        "快捷推进：\n"
        "- /kplog prog <0-100> [--note <text>]\n"
        "\n"
        "日志：\n"
        "- /kplog log add <text> [--task <T#>] [--min <n>] [--prog <0-100>]\n"
        "- /kplog log ls <T#> [--date <YYYY-MM-DD>]\n"
        "\n"
        "日报：\n"
        "- /kplog daily open [<YYYY-MM-DD>] [--plan <P#|alias>]\n"
        "- /kplog daily add done|block|next|note <text>\n"
        "- /kplog daily show [<YYYY-MM-DD>] [--plan <P#|alias>]\n"
        "- /kplog daily gen  [<YYYY-MM-DD>] [--plan <P#|alias>]\n"
    )


def sub_help_text(sub: str) -> str:
    sub = (sub or "").strip().lower()

    if sub == "plan":
        return (
            "【plan 规划】\n"
            "- 创建：/kplog plan add <name> [--alias <alias>] [--note <text>]\n"
            "- 列表：/kplog plan ls [--active]\n"
            "- 查看：/kplog plan show <P#|alias>\n"
            "- 重命名：/kplog plan rename <P#|alias> <new_name>\n"
            "- 设置别名：/kplog plan alias <P#|alias> <alias>\n"
            "- 归档：/kplog plan archive <P#|alias>\n"
            "\n"
            "示例：\n"
            "- /kplog plan add AI技术 --alias ai\n"
            "- /kplog plan show ai\n"
        )

    if sub == "stage":
        return (
            "【stage 阶段】\n"
            "- 创建：/kplog stage add <P#|alias> <name> --start <dt> --end <dt> [--note <text>]\n"
            "- 列表：/kplog stage ls <P#|alias>\n"
            "- 查看：/kplog stage show <S#>\n"
            "- 调整预计时间：/kplog stage time <S#> --start <dt> --end <dt>\n"
            "- 重命名：/kplog stage rename <S#> <new_name>\n"
            "\n"
            "dt 格式：YYYY-MM-DD HH:mm 或 YYYY/MM/DD HH:mm\n"
            "示例：\n"
            "- /kplog stage add ai 入门期 --start \"2026-03-25 21:30\" --end \"2026-04-10 22:00\"\n"
        )

    if sub == "task":
        return (
            "【task 任务】\n"
            "- 创建：/kplog task add <S#> <name> [--order <n>] [--note <text>]\n"
            "- 列表：/kplog task ls <S#> [--all]\n"
            "- 查看：/kplog task show <T#>\n"
            "- 设置顺序号：/kplog task order <T#> <n>\n"
            "- 重命名：/kplog task rename <T#> <new_name>\n"
            "- 更新进度：/kplog task prog <T#> <0-100> [--note <text>]\n"
            "- 更新状态：/kplog task state <T#> <todo|doing|done> [--note <text>]\n"
            "\n"
            "示例：\n"
            "- /kplog task add S1 了解基础概念 --order 1\n"
            "- /kplog task prog T1 30 --note \"完成第1章\"\n"
        )

    if sub == "timer":
        return (
            "【timer 计时】（同一时刻只允许 1 个活动计时）\n"
            "- 开始：/kplog timer start <T#> [--remind <minutes|off>] [--to <session>]\n"
            "- 状态：/kplog timer status\n"
            "- 停止：/kplog timer stop [--note <text>]\n"
            "- 修改提醒：/kplog timer remind <minutes|off>\n"
            "\n"
            "示例：\n"
            "- /kplog timer start T1 --remind 20\n"
            "- /kplog timer stop --note \"收尾\"\n"
        )

    if sub == "log":
        return (
            "【log 执行日志】\n"
            "- 追加：/kplog log add <text> [--task <T#>] [--min <n>] [--prog <0-100>]\n"
            "- 列表：/kplog log ls <T#> [--date <YYYY-MM-DD>]\n"
            "\n"
            "说明：不传 --task 时默认作用于当前计时任务。\n"
            "示例：\n"
            "- /kplog log add \"看完第1章\" --min 20 --prog 30\n"
        )

    if sub == "daily":
        return (
            "【daily 日报】（日期不传则默认为今天）\n"
            "- 打开/创建：/kplog daily open [<YYYY-MM-DD>] [--plan <P#|alias>]\n"
            "- 追加字段：/kplog daily add done|block|next|note <text>\n"
            "- 查看：/kplog daily show [<YYYY-MM-DD>] [--plan <P#|alias>]\n"
            "- 生成草稿：/kplog daily gen  [<YYYY-MM-DD>] [--plan <P#|alias>]\n"
            "\n"
            "示例：\n"
            "- /kplog daily open --plan ai\n"
            "- /kplog daily add done 跑通了入门示例\n"
            "- /kplog daily gen --plan ai\n"
        )

    if sub == "prog":
        return (
            "【prog 快捷推进】\n"
            "- 用法：/kplog prog <0-100> [--note <text>]\n"
            "说明：推进“当前活动计时器对应任务”的进度。\n"
            "示例：\n"
            "- /kplog prog 50 --note \"过半\"\n"
        )

    return "未知子命令。可用：plan/stage/task/timer/log/daily/prog。发送 /kplog help 查看总览。"
