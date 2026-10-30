"""Run the local manufacturing-quality Agent demo."""

from __future__ import annotations

import argparse
from pathlib import Path

from agent.workflow import QualityAgent, render_text_report
from data.demo_data import load_records


DEFAULT_DATA_PATH = Path("data/datasets/quality_records_2026.csv")
DEFAULT_QUESTION = "请分析 2026-01-01 到 2026-01-31 A产线的不良率异常"


def main() -> None:
    parser = argparse.ArgumentParser(description="制造质量根因分析 Agent 本地演示")
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--data", default=str(DEFAULT_DATA_PATH), help="CSV 数据路径")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.is_file():
        raise SystemExit(f"数据文件不存在：{data_path.resolve()}。请从 data/datasets 中选择年度数据集。")
    records = load_records(data_path)

    report = QualityAgent(records, log_dir=Path("logs"), csv_path=data_path).answer(args.question)
    print(render_text_report(report))


if __name__ == "__main__":
    main()
