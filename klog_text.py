from __future__ import annotations


def help_text() -> str:
    return (
        "klog 指令总览（QQ 专用）\n"
        "\n"
        "规划：\n"
        "- /klog plan add <name> [--alias <alias>] [--note <text>]\n"
        "- /klog plan ls\n"
        "- /klog plan show <P#|alias>\n"
        "\n"
        "阶段：\n"
        "- /klog stage add <P#|alias> <name> --start <dt> --end <dt>\n"
        "- /klog stage ls <P#|alias>\n"
        "\n"
        "任务：\n"
        "- /klog task add <S#> <name> [--order <n>]\n"
        "- /klog task prog <T#> <0-100> [--note <text>]\n"
        "- /klog task state <T#> <todo|doing|done> [--note <text>]\n"
        "\n"
        "计时：\n"
        "- /klog timer start <T#> [--remind <minutes|off>]\n"
        "- /klog timer stop [--note <text>]\n"
        "- /klog timer status\n"
        "\n"
        "日志：\n"
        "- /klog log add <text> [--task <T#>] [--min <n>] [--prog <0-100>]\n"
        "- /klog log ls <T#> [--date <YYYY-MM-DD>]\n"
        "\n"
        "日报：\n"
        "- /klog daily open <YYYY-MM-DD> [--plan <P#|alias>]\n"
        "- /klog daily add done|block|next|note <text>\n"
        "- /klog daily gen <YYYY-MM-DD> [--plan <P#|alias>]\n"
    )

