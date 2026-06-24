#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量报价表计算一致性检查 CLI。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from batch_quote_audit import (  # noqa: E402
    batch_audit_directory,
    list_xlsx_files,
    write_audit_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="批量检查 Excel 报价表计算一致性（只读）")
    parser.add_argument("input_dir", type=Path, help="待检查 .xlsx 目录")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="报告输出路径（默认：输入目录/batch_quote_audit.xlsx）",
    )
    parser.add_argument(
        "--format",
        choices=("xlsx", "csv"),
        default="xlsx",
        help="报告格式（默认 xlsx）",
    )
    parser.add_argument(
        "--fail-on-red",
        action="store_true",
        help="存在红色问题时返回退出码 1",
    )
    args = parser.parse_args()

    input_dir = args.input_dir
    if not input_dir.is_dir():
        print(f"输入目录不存在或不是文件夹：{input_dir}")
        return 1

    files = list_xlsx_files(input_dir)
    if not files:
        print(f"目录中未找到 .xlsx 文件：{input_dir}")
        return 0

    summaries, issues = batch_audit_directory(input_dir)
    ext = ".xlsx" if args.format == "xlsx" else ".csv"
    output_path = args.output or (input_dir / f"batch_quote_audit{ext}")
    written = write_audit_report(summaries, issues, output_path, fmt=args.format)

    red_files = sum(1 for s in summaries if s.severity == "red")
    yellow_files = sum(1 for s in summaries if s.severity == "yellow")
    green_files = sum(1 for s in summaries if s.severity == "green")
    print(
        f"批量检查完成：文件 {len(files)} 个 | 绿 {green_files} 黄 {yellow_files} 红 {red_files} | "
        f"问题 {len(issues)} 条"
    )
    print(f"报告已写入：{written}")

    if args.fail_on_red and red_files:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
