#!/usr/bin/env python3
"""Generate the standalone commercial-tools CSV.

The repository already contains an 83-row GitHub open-source inventory.  This
script deliberately reads that inventory only for a non-overlap assertion; it
never appends commercial products to it or rewrites any of its files.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "research" / "commercial_tools"
DEFAULT_SOURCE = HERE / "商业工具目录源数据_2026-08-15.json"
DEFAULT_OUTPUT = HERE / "商业工具明细_2026-08-15.csv"
OPEN_SOURCE_CSV = ROOT / "research" / "GitHub_AI_小说_剧本_视频生成项目明细_2026-08-13.csv"
EXPECTED_COUNT = 138
SNAPSHOT_DATE = "2026-08-15"

FIELDNAMES = [
    "序号",
    "分类",
    "工具",
    "提供方",
    "官网",
    "产品类型",
    "核心能力",
    "适用场景",
    "商业模式",
    "商用/许可边界",
    "数据/部署",
    "快照日期",
    "来源类型",
    "与83项关系",
]

CATEGORY_DEFAULTS: dict[str, dict[str, str]] = {
    "通用模型与写作助手": {
        "product_type": "通用模型 / AI 写作 SaaS",
        "scene": "小说构思、剧本草稿、文案、资料整理与改写",
        "delivery": "主要为云端网页/移动端；部分产品另提供 API。",
    },
    "小说、剧本与故事工作台": {
        "product_type": "小说/剧本/故事工作台",
        "scene": "长篇小说、剧本、世界观、分镜或影视前期制作",
        "delivery": "网页 SaaS 或商业桌面软件；协作和模型调用依产品而异。",
    },
    "视频生成与剪辑": {
        "product_type": "AI 视频生成 / 在线剪辑 SaaS",
        "scene": "短视频、广告、数字人、小说/脚本视觉化与社交内容",
        "delivery": "主要为云端服务，通常按订阅、点数或渲染额度计费。",
    },
    "图像与设计": {
        "product_type": "AI 图像生成 / 设计 SaaS",
        "scene": "角色与场景概念、封面、商品图、海报和品牌素材",
        "delivery": "网页/移动端 SaaS；部分产品提供 API 或桌面工作流。",
    },
    "语音、音乐与音频": {
        "product_type": "AI 语音 / 音乐 / 音频服务",
        "scene": "旁白、角色配音、播客、背景音乐和短视频后期",
        "delivery": "云端 SaaS 或云 API；声音克隆和商业额度需单独核对。",
    },
}


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"源数据不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"源数据不是有效 JSON：{path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("tools"), list):
        raise ValueError("源数据必须是包含 tools 数组的 JSON 对象")
    return data


def read_open_source_inventory(path: Path) -> tuple[set[str], set[str]]:
    """Return repository names and URLs used by the original 83-row inventory."""
    if not path.exists():
        raise ValueError(f"原有 GitHub 开源库存不存在：{path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 83:
        raise ValueError(f"原有 GitHub 开源库存应为 83 项，实际为 {len(rows)} 项")
    names = {str(row.get("项目", "")).strip().casefold() for row in rows}
    urls = {str(row.get("GitHub", "")).strip().rstrip("/").casefold() for row in rows}
    return names, urls


def build_rows(source: dict[str, Any], open_source_path: Path) -> list[dict[str, str]]:
    tools = source["tools"]
    if source.get("catalog_count") != EXPECTED_COUNT:
        raise ValueError(
            f"源数据 catalog_count 应为 {EXPECTED_COUNT}，实际为 {source.get('catalog_count')}"
        )
    if len(tools) != EXPECTED_COUNT:
        raise ValueError(f"商业工具源数据应为 {EXPECTED_COUNT} 项，实际为 {len(tools)} 项")
    if source.get("snapshot_date") != SNAPSHOT_DATE:
        raise ValueError(f"源数据快照日期必须为 {SNAPSHOT_DATE}")

    open_source_names, open_source_urls = read_open_source_inventory(open_source_path)
    seen_names: set[str] = set()
    seen_urls: set[str] = set()
    rows: list[dict[str, str]] = []

    for number, item in enumerate(tools, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {number} 项不是对象")
        required = ("name", "provider", "url", "category", "focus")
        missing = [key for key in required if not str(item.get(key, "")).strip()]
        if missing:
            raise ValueError(f"第 {number} 项缺少字段：{', '.join(missing)}")

        name = str(item["name"]).strip()
        url = str(item["url"]).strip().rstrip("/")
        name_key = name.casefold()
        url_key = url.casefold()
        if name_key in seen_names:
            raise ValueError(f"商业工具名称重复：{name}")
        if url_key in seen_urls:
            raise ValueError(f"商业工具官网重复：{url}")
        if name_key in open_source_names:
            raise ValueError(f"商业工具与原有开源项目名称重叠：{name}")
        if url_key in open_source_urls:
            raise ValueError(f"商业工具与原有开源项目 URL 重叠：{url}")
        seen_names.add(name_key)
        seen_urls.add(url_key)

        category = str(item["category"]).strip()
        if category not in CATEGORY_DEFAULTS:
            raise ValueError(f"第 {number} 项使用未知分类：{category}")
        defaults = CATEGORY_DEFAULTS[category]
        delivery = str(item.get("delivery") or defaults["delivery"]).strip()
        commercial_model = str(
            item.get("commercial_model")
            or "免费层/试用 + 订阅、点数或企业方案；具体价格以官网为准"
        ).strip()
        rows.append(
            {
                "序号": str(number),
                "分类": category,
                "工具": name,
                "提供方": str(item["provider"]).strip(),
                "官网": url,
                "产品类型": str(item.get("product_type") or defaults["product_type"]).strip(),
                "核心能力": str(item["focus"]).strip(),
                "适用场景": str(item.get("use_case") or defaults["scene"]).strip(),
                "商业模式": commercial_model,
                "商用/许可边界": (
                    "这是商业产品/服务目录，不代表输出、模型、声音、素材或 API 结果自动获得无限制商用权；"
                    "使用前应按官网当前服务条款、计划、地区和第三方许可逐项确认。"
                ),
                "数据/部署": delivery,
                "快照日期": SNAPSHOT_DATE,
                "来源类型": "官方产品页（静态目录快照）",
                "与83项关系": "商业产品/服务；不纳入原有 GitHub 开源 83 项",
            }
        )
    return rows


def write_csv(rows: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=FIELDNAMES,
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="源数据 JSON")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出 CSV")
    parser.add_argument(
        "--open-source-csv",
        type=Path,
        default=OPEN_SOURCE_CSV,
        help="原有 83 项 GitHub 开源库存，仅用于隔离校验",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        source = load_json(args.source)
        rows = build_rows(source, args.open_source_csv)
        if len(rows) != EXPECTED_COUNT:
            raise ValueError(f"生成行数应为 {EXPECTED_COUNT}，实际为 {len(rows)}")
        write_csv(rows, args.output)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    counts = Counter(row["分类"] for row in rows)
    print(f"wrote {args.output} ({len(rows)} tools; {len(FIELDNAMES)} columns)")
    for category, count in counts.items():
        print(f"  {category}: {count}")
    print("verified: original GitHub inventory remains a separate 83-row input")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
