#!/usr/bin/env python3
"""Validate every repository in the AI creation comparison via GitHub API.

The script never stores credentials. It asks the authenticated GitHub CLI for a
short-lived token, uses it only in request headers, and writes an evidence
snapshot, a validation CSV, a Markdown report, and validation columns back to
the main comparison CSV.

Confidence measures repository evidence, not generated-content quality:
- data confidence: identity, metadata, README/category/feature evidence, license;
- static run confidence: entry manifests, source tree, setup docs, tests, CI,
  releases, and recency;
- overall: 60% data + 40% static run confidence.
"""
from __future__ import annotations

import base64
import csv
import json
import math
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research"
DATE = date(2026, 8, 13)
MAIN_CSV = RESEARCH / "GitHub_AI_小说_剧本_视频生成项目明细_2026-08-13.csv"
VALIDATION_CSV = RESEARCH / "GitHub_AI_项目逐一验证明细_2026-08-13.csv"
SNAPSHOT_JSON = RESEARCH / "GitHub_AI_项目验证快照_2026-08-13.json"
REPORT_MD = RESEARCH / "GitHub_AI_项目逐一验证与置信度_2026-08-13.md"
API = "https://api.github.com"

MANIFESTS = {
    "package.json", "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg",
    "go.mod", "cargo.toml", "composer.json", "gemfile", "pom.xml", "build.gradle",
    "build.gradle.kts", "mix.exs", "pubspec.yaml", "environment.yml", "makefile",
    "dockerfile", "docker-compose.yml", "compose.yml", "uv.lock", "pnpm-lock.yaml",
}
SKILL_ENTRIES = {"skill.md", "agents.md", "claude.md", "reasonix-plugin.json"}
SOURCE_DIRS = {
    "src", "app", "apps", "backend", "frontend", "server", "client", "core",
    "packages", "web", "api", "agent", "agents", "inference", "model", "models",
    "tools", "skills", "scripts", "hyvideo", "mm_story_agent", "novel_bot",
}
TEST_ENTRIES = {
    "test", "tests", "__tests__", "pytest.ini", "tox.ini", "vitest.config.ts",
    "vitest.config.js", "jest.config.js", "jest.config.ts", "playwright.config.ts",
}
DOC_ENTRIES = {"docs", "documentation", "examples", "example", "demo", "demos"}
SETUP_RE = re.compile(
    r"quick\s*start|quickstart|getting\s+started|installation|install\b|usage|"
    r"快速开始|快速上手|安装|部署|使用方法|运行|环境要求",
    re.I,
)
COMMAND_RE = re.compile(r"```(?:bash|sh|shell|powershell|cmd|console)?\s*[\s\S]{20,}?```", re.I)

CATEGORY_TERMS = {
    "小说与长故事": ["novel", "fiction", "story", "writing", "writer", "小说", "网文", "长篇", "写作", "故事"],
    "剧本与分镜": ["screenplay", "script", "storyboard", "shot", "剧本", "短剧", "分镜", "镜头"],
    "视频生产工作台": ["video", "storyboard", "ffmpeg", "tts", "short drama", "视频", "短剧", "漫剧", "分镜", "成片"],
    "互动叙事与故事生态": ["interactive", "roleplay", "rpg", "story", "character", "world", "互动", "角色", "故事", "世界"],
    "视频基础模型": ["video generation", "text-to-video", "image-to-video", "t2v", "i2v", "视频生成", "文生视频", "图生视频"],
}

FEATURE_GROUPS = {
    "agent": ["agent", "智能体"],
    "multi_agent": ["multi-agent", "multi agent", "多 agent", "多智能体"],
    "memory": ["memory", "记忆", "state", "状态"],
    "rag": ["rag", "retrieval", "向量", "检索"],
    "world": ["world", "worldbuilding", "世界", "世界观"],
    "character": ["character", "角色", "人物"],
    "outline": ["outline", "大纲", "章纲", "卷纲"],
    "review": ["review", "audit", "审稿", "审核", "审查"],
    "continuity": ["continuity", "consistency", "连续性", "一致性", "伏笔"],
    "checkpoint": ["checkpoint", "resume", "recover", "断点", "恢复"],
    "export": ["export", "epub", "docx", "导出", "成书"],
    "workflow": ["workflow", "pipeline", "工作流", "流水线"],
    "skill": ["skill", "技能"],
    "graph": ["graph", "neo4j", "图谱"],
    "local": ["local", "self-host", "本地", "自托管"],
    "provider": ["provider", "openai", "anthropic", "gemini", "ollama", "模型"],
    "interactive": ["interactive", "roleplay", "rpg", "互动", "开放世界"],
    "script": ["screenplay", "script", "storyboard", "剧本", "分镜"],
    "video": ["video", "t2v", "i2v", "视频", "成片"],
    "audio": ["audio", "tts", "voice", "speech", "音频", "配音", "语音"],
    "image": ["image", "illustration", "图像", "图片", "插画", "封面"],
    "training": ["train", "fine-tun", "lora", "训练", "微调"],
    "version": ["version", "snapshot", "git", "版本", "快照", "回滚"],
}


def gh_token() -> str:
    return subprocess.check_output(["gh", "auth", "token"], text=True).strip()


def api_get(token: str, path: str, *, accept: str = "application/vnd.github+json") -> tuple[int, Any]:
    url = path if path.startswith("http") else API + path
    headers = {
        "Accept": accept,
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "arena-ai-project-validator/1.0",
    }
    for attempt in range(4):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            body = exc.read()
            if exc.code in {404, 409, 422}:
                try:
                    return exc.code, json.loads(body) if body else None
                except json.JSONDecodeError:
                    return exc.code, None
            if exc.code in {403, 429, 500, 502, 503, 504} and attempt < 3:
                time.sleep(1.5 * (2**attempt))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < 3:
                time.sleep(1.5 * (2**attempt))
                continue
            raise
    raise RuntimeError(f"request failed: {url}")


def decode_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    content = payload.get("content") or ""
    if payload.get("encoding") == "base64":
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            return ""
    return str(content)


def has_any(text: str, terms: list[str]) -> bool:
    low = text.lower()
    return any(term.lower() in low for term in terms)


def feature_match(claim: str, readme: str) -> tuple[float, list[str], list[str]]:
    claim_low = claim.lower()
    readme_low = readme.lower()
    expected: list[str] = []
    matched: list[str] = []
    for group, terms in FEATURE_GROUPS.items():
        if any(term.lower() in claim_low for term in terms):
            expected.append(group)
            if any(term.lower() in readme_low for term in terms):
                matched.append(group)
    if not expected:
        return 0.8, expected, matched
    return len(matched) / len(expected), expected, matched


def expected_license_terms(expected: str) -> list[str]:
    low = expected.lower()
    if "agpl" in low:
        return ["affero general public license", "agpl"]
    if "gpl" in low:
        return ["general public license", "gpl"]
    if "apache" in low:
        return ["apache license", "apache-2.0"]
    if "mit" in low:
        return ["mit license", "permission is hereby granted"]
    if "hunyuan" in low:
        return ["tencent hunyuan community license"]
    if "ltx" in low:
        return ["ltx-2", "community license"]
    if "skywork" in low:
        return ["skywork", "community license"]
    if "个人学习" in expected or "非商业" in expected:
        return ["非商业", "个人学习"]
    return []


def classify_level(score: int) -> str:
    if score >= 90:
        return "很高"
    if score >= 80:
        return "高"
    if score >= 70:
        return "中高"
    if score >= 60:
        return "中"
    return "低"


def age_days(iso_date: str) -> int:
    try:
        return (DATE - date.fromisoformat(iso_date[:10])).days
    except Exception:
        return 9999


def validate_one(token: str, row: dict[str, str]) -> dict[str, Any]:
    repo_name = row["项目"]
    encoded = "/".join(urllib.parse.quote(part, safe="") for part in repo_name.split("/"))
    repo_status, repo = api_get(token, f"/repos/{encoded}")
    if repo_status != 200 or not isinstance(repo, dict):
        return {
            "repo": repo_name,
            "ok": False,
            "error": f"repo API HTTP {repo_status}",
            "data_confidence": 0,
            "run_confidence": 0,
            "overall_confidence": 0,
            "confidence_level": "低",
        }

    branch = repo.get("default_branch") or "main"
    q_branch = urllib.parse.quote(branch, safe="")
    endpoints = {
        "readme": f"/repos/{encoded}/readme?ref={q_branch}",
        "license": f"/repos/{encoded}/license?ref={q_branch}",
        "root": f"/repos/{encoded}/contents?ref={q_branch}",
        "releases": f"/repos/{encoded}/releases?per_page=1",
        "workflows": f"/repos/{encoded}/actions/workflows?per_page=100",
        "runs": f"/repos/{encoded}/actions/runs?branch={q_branch}&per_page=5",
    }
    fetched: dict[str, tuple[int, Any]] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(api_get, token, url): key for key, url in endpoints.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                fetched[key] = future.result()
            except Exception as exc:  # retain partial evidence
                fetched[key] = (0, {"error": str(exc)})

    readme_status, readme_payload = fetched["readme"]
    readme = decode_content(readme_payload) if readme_status == 200 else ""
    license_status_code, license_payload = fetched["license"]
    license_text = decode_content(license_payload) if license_status_code == 200 else ""
    api_spdx = "NOASSERTION"
    api_license_name = "未检测"
    license_url = ""
    if isinstance(license_payload, dict):
        lic_obj = license_payload.get("license") or {}
        api_spdx = lic_obj.get("spdx_id") or "NOASSERTION"
        api_license_name = lic_obj.get("name") or "Other"
        license_url = license_payload.get("html_url") or ""

    root_payload = fetched["root"][1]
    root_entries = root_payload if isinstance(root_payload, list) else []
    root_names = {str(item.get("name", "")).lower() for item in root_entries if isinstance(item, dict)}
    root_dirs = {str(item.get("name", "")).lower() for item in root_entries if isinstance(item, dict) and item.get("type") == "dir"}
    root_files = {str(item.get("name", "")).lower() for item in root_entries if isinstance(item, dict) and item.get("type") == "file"}

    releases_payload = fetched["releases"][1]
    releases = releases_payload if isinstance(releases_payload, list) else []
    release = releases[0] if releases else None
    workflows_payload = fetched["workflows"][1]
    workflows = workflows_payload.get("workflows", []) if isinstance(workflows_payload, dict) else []
    runs_payload = fetched["runs"][1]
    runs = runs_payload.get("workflow_runs", []) if isinstance(runs_payload, dict) else []
    latest_run = runs[0] if runs else None

    # Data confidence (100)
    data_score = 15  # repository exists
    metadata_points = 0
    if repo.get("html_url") == row["GitHub"]:
        metadata_points += 2
    try:
        old_stars, now_stars = int(row["Stars"]), int(repo.get("stargazers_count", 0))
        if abs(old_stars - now_stars) <= max(5, math.ceil(max(old_stars, 1) * 0.02)):
            metadata_points += 3
    except Exception:
        pass
    try:
        old_forks, now_forks = int(row["Forks"]), int(repo.get("forks_count", 0))
        if abs(old_forks - now_forks) <= max(3, math.ceil(max(old_forks, 1) * 0.03)):
            metadata_points += 2
    except Exception:
        pass
    if (repo.get("language") or "-") == row["主语言"]:
        metadata_points += 1
    if (repo.get("pushed_at") or "")[:10] == row["最近推送"]:
        metadata_points += 2
    data_score += metadata_points  # max 10

    if len(readme) >= 3000:
        readme_points = 15
    elif len(readme) >= 1000:
        readme_points = 12
    elif len(readme) >= 300:
        readme_points = 8
    elif readme:
        readme_points = 4
    else:
        readme_points = 0
    data_score += readme_points

    category_terms = CATEGORY_TERMS.get(row["分类"], [])
    category_hits = sum(1 for term in category_terms if term.lower() in readme.lower())
    category_ratio = category_hits / max(1, min(5, len(category_terms)))
    category_points = min(15, round(category_ratio * 15))
    data_score += category_points

    claims = " ".join([row.get("子类型", ""), row.get("输入→输出", ""), row.get("核心能力", ""), row.get("适合场景", "")])
    match_ratio, expected_features, matched_features = feature_match(claims, readme)
    feature_points = round(match_ratio * 20)
    data_score += feature_points

    expected_license = row["许可证"]
    license_terms = expected_license_terms(expected_license)
    license_match = bool(license_terms and has_any(license_text, license_terms))
    if license_status_code == 200 and license_text:
        if api_spdx != "NOASSERTION":
            license_points = 14 + (6 if license_match or api_spdx.lower() in expected_license.lower() else 0)
        else:
            license_points = 13 + (7 if license_match else 0)
    else:
        has_root_license = any(name.startswith(("license", "licence", "copying")) for name in root_names)
        readme_claims_license = "license" in readme.lower() or "许可证" in readme or "开源协议" in readme
        license_points = 10 if has_root_license else (5 if readme_claims_license else 0)
    data_score += license_points

    canonical_points = 0
    if not repo.get("fork"):
        canonical_points += 3
    if repo.get("description"):
        canonical_points += 2
    data_score += canonical_points
    # Static inspection cannot justify absolute certainty: README feature claims
    # were not exhaustively traced through every code path.
    data_score = max(0, min(98, data_score))

    # Static run confidence (100)
    manifest_hits = sorted(name for name in root_files if name in MANIFESTS)
    skill_hits = sorted(name for name in root_files if name in SKILL_ENTRIES)
    has_skill_tree = "skills" in root_dirs or "agents" in root_dirs
    is_skillish = "skill" in row["子类型"].lower() or "skill" in row["核心能力"].lower() or "模板" in row["子类型"]
    if manifest_hits:
        entry_points = 20
    elif skill_hits or (is_skillish and has_skill_tree):
        entry_points = 20
    elif root_dirs & SOURCE_DIRS:
        entry_points = 12
    elif len(root_entries) >= 4:
        entry_points = 7
    else:
        entry_points = 2

    source_hits = sorted(root_dirs & SOURCE_DIRS)
    source_points = 10 if source_hits else (6 if len(root_entries) >= 8 else 2)
    setup_points = 15 if SETUP_RE.search(readme) and COMMAND_RE.search(readme) else (9 if SETUP_RE.search(readme) else 2)
    test_hits = sorted(root_names & TEST_ENTRIES)
    if test_hits:
        test_points = 15
    elif re.search(r"pytest|vitest|jest|playwright|go test|npm test|测试", readme, re.I):
        test_points = 9
    elif workflows:
        test_points = 5
    else:
        test_points = 0
    workflow_points = 10 if workflows else 0
    if latest_run:
        conclusion = latest_run.get("conclusion") or latest_run.get("status") or "unknown"
        if conclusion == "success":
            ci_points = 10
        elif conclusion in {"neutral", "skipped"}:
            ci_points = 7
        elif conclusion in {"queued", "in_progress", "requested", "waiting", "pending"}:
            ci_points = 6
        else:
            ci_points = 3
    elif workflows:
        conclusion = "无运行记录"
        ci_points = 4
    else:
        conclusion = "无 Actions"
        ci_points = 0
    release_points = 10 if release else 0
    days = age_days((repo.get("pushed_at") or "")[:10])
    if days <= 30:
        activity_points = 10
    elif days <= 90:
        activity_points = 8
    elif days <= 180:
        activity_points = 6
    elif days <= 365:
        activity_points = 3
    else:
        activity_points = 0
    run_score = entry_points + source_points + setup_points + test_points + workflow_points + ci_points + release_points + activity_points
    # No repository was installed end-to-end in this pass, so static run
    # confidence is intentionally capped below 100.
    run_score = max(0, min(95, run_score))

    overall = round(data_score * 0.60 + run_score * 0.40)
    if license_points < 10:
        overall = min(overall, 65)
    if not readme:
        overall = min(overall, 45)
    if repo.get("archived"):
        overall = min(overall, 60)
    if category_points < 6:
        overall = min(overall, 65)
    level = classify_level(overall)

    if overall >= 85:
        verdict = "通过：仓库静态证据充分"
    elif overall >= 75:
        verdict = "基本通过：存在少量工程证据缺口"
    elif overall >= 65:
        verdict = "谨慎通过：主要依赖 README 或缺少 CI/Release"
    else:
        verdict = "低置信：需要人工安装或许可证复核"

    evidence_parts = [
        f"README {len(readme):,}B" if readme else "无 README",
        f"许可证 {api_spdx if api_spdx != 'NOASSERTION' else api_license_name}",
    ]
    if manifest_hits or skill_hits:
        evidence_parts.append("入口 " + "/".join((manifest_hits + skill_hits)[:3]))
    elif source_hits:
        evidence_parts.append("源码目录 " + "/".join(source_hits[:3]))
    if workflows:
        evidence_parts.append(f"Actions {len(workflows)} 个，最新 {conclusion}")
    else:
        evidence_parts.append("无 Actions 工作流证据")
    if release:
        evidence_parts.append("Release " + str(release.get("tag_name") or release.get("name") or "存在"))
    else:
        evidence_parts.append("无 GitHub Release")
    evidence_parts.append(f"最近推送 {days} 天前")

    if row["分类"] == "视频基础模型":
        unverified = "未下载权重或实测显存/速度/画质；checkpoint 与依赖许可证仍需单独核对"
    elif row["分类"] == "视频生产工作台":
        unverified = "未部署完整多模态链路；第三方图像/视频/TTS API、费用与成片质量未实测"
    elif row["分类"] == "互动叙事与故事生态":
        unverified = "未进行长会话压力测试；角色一致性、长期 canon 与本地模型效果未实测"
    else:
        unverified = "未逐仓库安装并生成完整作品；文学质量、超长连续性、Token 成本与故障恢复未实测"
    if conclusion not in {"success", "无 Actions", "无运行记录"}:
        unverified += f"；最新 Actions 结论为 {conclusion}"
    if not release:
        unverified += "；缺少 GitHub Release 交付证据"

    return {
        "repo": repo_name,
        "ok": True,
        "category": row["分类"],
        "subtype": row["子类型"],
        "url": repo.get("html_url"),
        "default_branch": branch,
        "archived": bool(repo.get("archived")),
        "fork": bool(repo.get("fork")),
        "stars_now": repo.get("stargazers_count", 0),
        "forks_now": repo.get("forks_count", 0),
        "language_now": repo.get("language") or "-",
        "pushed_at": (repo.get("pushed_at") or "")[:10],
        "age_days": days,
        "readme_status": readme_status,
        "readme_bytes": len(readme),
        "category_hits": category_hits,
        "category_points": category_points,
        "feature_expected": expected_features,
        "feature_matched": matched_features,
        "feature_match_ratio": round(match_ratio, 3),
        "license_http_status": license_status_code,
        "license_spdx": api_spdx,
        "license_name": api_license_name,
        "license_url": license_url,
        "license_expected": expected_license,
        "license_match": license_match,
        "license_points": license_points,
        "root_entries": sorted(root_names),
        "manifest_hits": manifest_hits,
        "skill_hits": skill_hits,
        "source_hits": source_hits,
        "test_hits": test_hits,
        "docs_present": bool(root_names & DOC_ENTRIES),
        "setup_docs": bool(SETUP_RE.search(readme)),
        "command_examples": bool(COMMAND_RE.search(readme)),
        "workflow_count": len(workflows),
        "latest_ci_conclusion": conclusion,
        "latest_ci_url": latest_run.get("html_url", "") if latest_run else "",
        "latest_release": (release.get("tag_name") or release.get("name") or "") if release else "",
        "latest_release_url": release.get("html_url", "") if release else "",
        "data_confidence": data_score,
        "run_confidence": run_score,
        "overall_confidence": overall,
        "confidence_level": level,
        "verdict": verdict,
        "evidence_summary": "；".join(evidence_parts),
        "unverified": unverified,
    }


def md_escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def main() -> int:
    if not MAIN_CSV.exists():
        print(f"missing {MAIN_CSV}", file=sys.stderr)
        return 2
    with MAIN_CSV.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("main CSV is empty", file=sys.stderr)
        return 2

    token = gh_token()
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(validate_one, token, row): row["项目"] for row in rows}
        completed = 0
        for future in as_completed(futures):
            repo = futures[future]
            try:
                results[repo] = future.result()
            except Exception as exc:
                results[repo] = {
                    "repo": repo,
                    "ok": False,
                    "error": str(exc),
                    "data_confidence": 0,
                    "run_confidence": 0,
                    "overall_confidence": 0,
                    "confidence_level": "低",
                    "verdict": "验证失败",
                    "evidence_summary": f"API 验证异常：{exc}",
                    "unverified": "需重新运行验证脚本",
                }
            completed += 1
            print(f"[{completed:02d}/{len(rows)}] {repo}: {results[repo]['overall_confidence']}")

    ordered = [results[row["项目"]] for row in rows]
    snapshot = {
        "snapshot_date": DATE.isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "GitHub REST API static evidence validation",
        "weights": {"data_confidence": 0.60, "static_run_confidence": 0.40},
        "quality_tested": False,
        "repositories": ordered,
    }
    SNAPSHOT_JSON.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validation_fields = [
        "分类", "子类型", "项目", "GitHub", "仓库可访问", "当前Stars", "当前Forks", "当前主语言",
        "当前最近推送", "README字节", "许可证预期", "许可证API", "许可证匹配", "入口证据",
        "源码目录证据", "测试证据", "Actions工作流数", "最新CI结论", "最新Release", "资料置信度",
        "静态可运行置信度", "综合置信度", "置信等级", "验证结论", "证据摘要", "未实测/风险",
    ]
    with VALIDATION_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=validation_fields)
        writer.writeheader()
        for row, result in zip(rows, ordered):
            writer.writerow({
                "分类": row["分类"], "子类型": row["子类型"], "项目": row["项目"], "GitHub": row["GitHub"],
                "仓库可访问": "是" if result.get("ok") else "否",
                "当前Stars": result.get("stars_now", ""), "当前Forks": result.get("forks_now", ""),
                "当前主语言": result.get("language_now", ""), "当前最近推送": result.get("pushed_at", ""),
                "README字节": result.get("readme_bytes", 0), "许可证预期": row["许可证"],
                "许可证API": result.get("license_spdx") if result.get("license_spdx") != "NOASSERTION" else result.get("license_name", "未检测"),
                "许可证匹配": "是" if result.get("license_match") else ("自定义/人工复核" if result.get("license_http_status") == 200 else "否"),
                "入口证据": "/".join((result.get("manifest_hits", []) + result.get("skill_hits", []))[:6]),
                "源码目录证据": "/".join(result.get("source_hits", [])[:6]),
                "测试证据": "/".join(result.get("test_hits", [])), "Actions工作流数": result.get("workflow_count", 0),
                "最新CI结论": result.get("latest_ci_conclusion", ""), "最新Release": result.get("latest_release", ""),
                "资料置信度": result.get("data_confidence", 0), "静态可运行置信度": result.get("run_confidence", 0),
                "综合置信度": result.get("overall_confidence", 0), "置信等级": result.get("confidence_level", "低"),
                "验证结论": result.get("verdict", ""), "证据摘要": result.get("evidence_summary", ""),
                "未实测/风险": result.get("unverified", ""),
            })

    # Add/refresh validation fields in main comparison CSV.
    base_fields = [name for name in rows[0] if name not in {
        "验证日期", "资料置信度", "静态可运行置信度", "综合置信度", "置信等级", "验证结论", "验证证据", "未实测风险"
    }]
    extra_fields = ["验证日期", "资料置信度", "静态可运行置信度", "综合置信度", "置信等级", "验证结论", "验证证据", "未实测风险"]
    with MAIN_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=base_fields + extra_fields)
        writer.writeheader()
        for row, result in zip(rows, ordered):
            clean = {key: row.get(key, "") for key in base_fields}
            clean.update({
                "验证日期": DATE.isoformat(), "资料置信度": result.get("data_confidence", 0),
                "静态可运行置信度": result.get("run_confidence", 0), "综合置信度": result.get("overall_confidence", 0),
                "置信等级": result.get("confidence_level", "低"), "验证结论": result.get("verdict", ""),
                "验证证据": result.get("evidence_summary", ""), "未实测风险": result.get("unverified", ""),
            })
            writer.writerow(clean)

    valid = [r for r in ordered if r.get("ok")]
    levels = Counter(r["confidence_level"] for r in valid)
    avg_data = round(sum(r["data_confidence"] for r in valid) / max(1, len(valid)), 1)
    avg_run = round(sum(r["run_confidence"] for r in valid) / max(1, len(valid)), 1)
    avg_overall = round(sum(r["overall_confidence"] for r in valid) / max(1, len(valid)), 1)
    license_matches = sum(1 for r in valid if r.get("license_match"))
    ci_success = sum(1 for r in valid if r.get("latest_ci_conclusion") == "success")
    with_releases = sum(1 for r in valid if r.get("latest_release"))

    report: list[str] = [
        "# GitHub AI 小说、剧本与视频项目逐一验证与置信度",
        "",
        f"> **验证日期：{DATE.isoformat()}**  ",
        f"> **逐一验证：{len(rows)} 个仓库；成功访问 {len(valid)} 个**  ",
        "> 这是仓库证据与静态可运行性验证，不是文学质量、画质或生产稳定性的实机横评。",
        "",
        f"配套数据：[`{VALIDATION_CSV.name}`](./{VALIDATION_CSV.name}) · [原始验证快照 JSON](./{SNAPSHOT_JSON.name})",
        "",
        "## 1. 验证方法",
        "",
        "每个项目均重新请求并检查：GitHub 仓库元数据、README、LICENSE、默认分支根目录、安装/运行入口、源码目录、测试入口、GitHub Actions、最近 CI 结论、Release 和最近推送时间。",
        "",
        "- **资料置信度（0–100）**：仓库身份与元数据 25%，README 完整度 15%，类别证据 15%，功能声明匹配 20%，许可证 20%，非 Fork/描述 5%。",
        "- **静态可运行置信度（0–100）**：入口清单 20%，源码结构 10%，安装文档 15%，测试 15%，Actions 10%，最近 CI 10%，Release 10%，活跃度 10%。",
        "- **综合置信度**：资料置信度 × 60% + 静态可运行置信度 × 40%。",
        "- **等级**：很高 ≥90；高 80–89；中高 70–79；中 60–69；低 <60。",
        "- **静态验证上限**：由于没有穷举审计全部代码路径，也没有逐项目安装，资料分有意封顶 98，静态可运行分封顶 95；不存在‘100% 已验证可用’的结论。",
        "",
        "### 重要边界",
        "",
        "1. 有 README、CI 和 Release 只能提高‘仓库描述可信/较可能可安装’的置信度，不能证明生成质量优秀。",
        "2. 本轮没有下载大型模型权重，也没有为 83 个项目分别购买或配置外部 API，因此画质、文笔、Token 成本和长篇稳定性仍标记为未实测。",
        "3. 无 Actions/Release 不代表项目不可用；Skill、研究代码和纯前端项目天然可能不发布 Release，因此分数用于证据排序，不用于简单淘汰。",
        "4. 许可证匹配只检查仓库当前许可证文件与表中记录；模型权重、素材、字体、数据和云 API 仍需独立审查。",
        "",
        "## 2. 汇总结论",
        "",
        f"- 平均资料置信度：**{avg_data}**",
        f"- 平均静态可运行置信度：**{avg_run}**",
        f"- 平均综合置信度：**{avg_overall}**",
        f"- 置信等级分布：" + "；".join(f"{key} {levels.get(key, 0)}" for key in ["很高", "高", "中高", "中", "低"]),
        f"- LICENSE 内容与表中预期明确匹配：**{license_matches}/{len(valid)}**",
        f"- 最新 Actions 结论为 success：**{ci_success}/{len(valid)}**",
        f"- 检测到 GitHub Release：**{with_releases}/{len(valid)}**",
        "",
    ]

    weak = sorted(valid, key=lambda r: r["overall_confidence"])[:15]
    report += ["### 证据最弱、最需要手工安装复核的项目", "", "| 项目 | 综合 | 主要缺口 |", "|---|---:|---|"]
    for r in weak:
        report.append(f"| [{md_escape(r['repo'])}]({r['url']}) | {r['overall_confidence']} | {md_escape(r['evidence_summary'])} |")

    ci_attention = [
        r for r in valid
        if r.get("latest_ci_conclusion") not in {"success", "neutral", "skipped", "无 Actions", "无运行记录"}
    ]
    report += ["", "### 最新 CI 需要关注的项目", "", "| 项目 | 最新结论 | CI 链接 |", "|---|---|---|"]
    if ci_attention:
        for r in ci_attention:
            link = r.get("latest_ci_url") or r.get("url")
            report.append(f"| [{md_escape(r['repo'])}]({r['url']}) | {md_escape(r.get('latest_ci_conclusion'))} | [查看]({link}) |")
    else:
        report.append("| — | 未发现失败或待处理的最新 CI | — |")

    report += ["", "## 3. 83 个项目逐一验证", ""]
    categories = []
    for row in rows:
        if row["分类"] not in categories:
            categories.append(row["分类"])
    for category in categories:
        report += [f"### {category}", "", "| 项目 | 资料 | 静态运行 | 综合 | 等级 | 许可证 | 验证结论与证据 | 未实测项 |", "|---|---:|---:|---:|---|---|---|---|"]
        for row, result in zip(rows, ordered):
            if row["分类"] != category:
                continue
            license_display = result.get("license_spdx")
            if not license_display or license_display == "NOASSERTION":
                license_display = result.get("license_name", "未检测")
            report.append(
                f"| [{md_escape(row['项目'])}]({row['GitHub']}) | {result.get('data_confidence', 0)} | "
                f"{result.get('run_confidence', 0)} | **{result.get('overall_confidence', 0)}** | "
                f"{result.get('confidence_level', '低')} | {md_escape(license_display)} | "
                f"{md_escape(result.get('verdict', ''))}；{md_escape(result.get('evidence_summary', ''))} | "
                f"{md_escape(result.get('unverified', ''))} |"
            )
        report.append("")

    report += [
        "## 4. 如何使用这些分数",
        "",
        "- **选型初筛**：先看综合 ≥80，再结合许可证与‘未实测项’决定是否安装。",
        "- **准备商用**：不要只看综合分；优先审查许可证文件、模型权重条款、素材来源和 SaaS/多租户条件。",
        "- **准备实机 PoC**：从每类挑 2–3 个高分项目，用同一题材、同一模型、同一预算完成 10 章或 20 镜头对照测试。",
        "- **低分项目**：可能只是没有 CI/Release，而非功能差；如果核心架构独特，仍可人工安装验证。",
        "",
        "## 5. 下一阶段建议的实机验证矩阵",
        "",
        "若继续做实机验证，建议不要同时安装 83 个项目，而是分层抽样：",
        "",
        "1. **InkOS 同类长篇 Agent**：InkOS、Goink、Siming、OpenFic、Denova、NeuroBook、LiPu-jpg/Openwrite。",
        "2. **超长网文**：webnovel-writer、ainovel-cli、oh-story-claudecode、ProseForge。",
        "3. **互动世界**：SillyTavern + KoboldCpp、OneDay、Covel、openovel。",
        "4. **小说到视频**：Toonflow、ArcReel、ViMax、AIComicBuilder。",
        "5. **本地视频模型**：Wan2.2、HunyuanVideo-1.5、CogVideo、MAGI-1。",
        "",
        "统一记录：安装成功率、首次产出耗时、Token/API 成本、20 章一致性、断点恢复、角色漂移、人工修改次数和许可证阻碍。",
    ]
    REPORT_MD.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"wrote {VALIDATION_CSV}")
    print(f"wrote {SNAPSHOT_JSON}")
    print(f"wrote {REPORT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
