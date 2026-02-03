#!/usr/bin/env python3
"""
Audit FE/BE contract for monthly-close-rate.
Outputs:
  - docs/AUDIT_MONTHLY_CLOSE_RATE.md
  - output/audit_monthly_close_rate.json
Also prints top FAIL checks and immediate crash summary.
"""

import argparse
import ast
import json
import re
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_js_string_array(text: str, name: str) -> Tuple[List[str], Optional[int]]:
    m = re.search(rf"const\s+{re.escape(name)}\s*=\s*\[([^\]]*)\]", text, re.S)
    if not m:
        return [], None
    body = m.group(1)
    vals = re.findall(r'"([^"]+)"', body)
    line_no = text[: m.start()].count("\n") + 1
    return vals, line_no


def extract_js_scope_keys(text: str, const_name: str) -> Tuple[List[str], Optional[int]]:
    m = re.search(rf"const\s+{re.escape(const_name)}\s*=\s*\[([^\]]*)\]", text, re.S)
    if not m:
        return [], None
    body = m.group(1)
    keys = re.findall(r'key\s*:\s*"([^"]+)"', body)
    line_no = text[: m.start()].count("\n") + 1
    return keys, line_no


def extract_fe_rowkey_pattern(text: str) -> bool:
    return "${course}||${metric}" in text or "${course}||${metric}" in text


def extract_python_list_constant(src: str, name: str) -> Tuple[List[str], Optional[int]]:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        vals = []
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                vals.append(elt.value)
                        return vals, getattr(node, "lineno", None)
    return [], None


def extract_scope_keys_from_py(src: str) -> Tuple[List[str], Optional[int]]:
    m = re.search(r"def _perf_close_rate_scope_members\(.*?\):", src)
    lineno = src[: m.start()].count("\n") + 1 if m else None
    keys = re.findall(r'scope\s*==\s*"([^"]+)"', src)
    return keys, lineno


def extract_api_params(text: str, route: str) -> List[str]:
    m = re.search(rf'@router.get\("{re.escape(route)}"\)\s*def\s+\w+\((.*?)\)\s*(?:->[^:]*)?:', text, re.S)
    if not m:
        return []
    params = []
    args = m.group(1)
    for line in args.splitlines():
        if "Query(" not in line:
            continue
        name_match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", line)
        if not name_match:
            continue
        name = name_match.group(1)
        params.append(name)
        alias = re.search(r'alias\s*=\s*"([^"]+)"', line)
        if alias:
            params.append(alias.group(1))
    return params


def extract_fe_fetch_params(text: str, func: str) -> List[str]:
    m = re.search(rf"async function {re.escape(func)}\([^\)]*\)\s*\{{(.*?)\}}", text, re.S)
    if not m:
        return []
    body = m.group(1)
    params = re.findall(r'params\.set\("([^"]+)"', body)
    return params


def check_match(label: str, fe: List[str], be: List[str]) -> Dict[str, Any]:
    return {
        "id": label,
        "status": "PASS" if fe == be else "FAIL",
        "fe": fe,
        "be": be,
        "diff": {"missing_in_fe": [v for v in be if v not in fe], "missing_in_be": [v for v in fe if v not in be]},
    }


def check_params_subset(label: str, fe: List[str], be: List[str]) -> Dict[str, Any]:
    missing_in_be = [v for v in fe if v not in be]
    missing_in_fe = [v for v in be if v not in fe]
    status = "PASS" if not missing_in_be else "FAIL"
    return {
        "id": label,
        "status": status,
        "fe": fe,
        "be": be,
        "diff": {"missing_in_be": missing_in_be, "missing_in_fe": missing_in_fe},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--out-md", default="docs/AUDIT_MONTHLY_CLOSE_RATE.md")
    ap.add_argument("--out-json", default="output/audit_monthly_close_rate.json")
    args = ap.parse_args()

    root = Path(args.repo_root).resolve()
    fe_path = root / "org_tables_v2.html"
    be_path = root / "dashboard/server/database.py"
    api_path = root / "dashboard/server/org_tables_api.py"

    fe_txt = read_text(fe_path)
    be_txt = read_text(be_path)
    api_txt = read_text(api_path)

    fe_course, fe_course_line = extract_js_string_array(fe_txt, "CLOSE_RATE_COURSE_GROUPS")
    fe_metrics, fe_metrics_line = extract_js_string_array(fe_txt, "CLOSE_RATE_METRICS")
    fe_scope, fe_scope_line = extract_js_scope_keys(fe_txt, "CLOSE_RATE_SCOPE_OPTIONS")
    fe_customer, fe_customer_line = extract_js_scope_keys(fe_txt, "CLOSE_RATE_CUSTOMER_OPTIONS")
    fe_size_defined, fe_size_line = extract_js_string_array(fe_txt, "INQUIRY_SIZE_GROUPS")
    fe_rowkey_pattern = extract_fe_rowkey_pattern(fe_txt)
    fe_size_usages = len(re.findall(r"INQUIRY_SIZE_GROUPS", fe_txt))

    be_course, be_course_line = extract_python_list_constant(be_txt, "CLOSE_RATE_COURSE_GROUPS")
    be_metrics, be_metrics_line = extract_python_list_constant(be_txt, "CLOSE_RATE_METRICS")
    be_size, be_size_line = extract_python_list_constant(be_txt, "INQUIRY_SIZE_GROUPS")
    be_scope, be_scope_line = extract_scope_keys_from_py(be_txt)

    api_summary_params = extract_api_params(api_txt, "/performance/monthly-close-rate/summary")
    api_deals_params = extract_api_params(api_txt, "/performance/monthly-close-rate/deals")

    fe_summary_params = extract_fe_fetch_params(fe_txt, "loadPerfMonthlyCloseRateSummary")
    fe_deals_params = extract_fe_fetch_params(fe_txt, "loadPerfMonthlyCloseRateDeals")

    checks: List[Dict[str, Any]] = []

    # 1) FE undefined INQUIRY_SIZE_GROUPS
    if not fe_size_defined and fe_size_usages > 0:
        checks.append(
            {
                "id": "FE_UNDEFINED_INQUIRY_SIZE_GROUPS",
                "status": "FAIL",
                "evidence": [f"org_tables_v2.html uses INQUIRY_SIZE_GROUPS {fe_size_usages} times but no const definition found"],
                "details": {"line": fe_size_line},
            }
        )
    else:
        checks.append(
            {
                "id": "FE_UNDEFINED_INQUIRY_SIZE_GROUPS",
                "status": "PASS",
                "evidence": [],
                "details": {"line": fe_size_line},
            }
        )

    # 2) course groups match
    checks.append(
        {
          **check_match("COURSE_GROUPS_MATCH", fe_course, be_course),
          "evidence": [f"FE line {fe_course_line}", f"BE line {be_course_line}"],
        }
    )
    # 3) metrics match
    checks.append(
        {
          **check_match("METRICS_MATCH", fe_metrics, be_metrics),
          "evidence": [f"FE line {fe_metrics_line}", f"BE line {be_metrics_line}"],
        }
    )
    # 4) rowKey contract
    checks.append(
        {
            "id": "ROWKEY_PATTERN",
            "status": "PASS" if fe_rowkey_pattern else "FAIL",
            "evidence": ["FE uses `${course}||${metric}` pattern" if fe_rowkey_pattern else "Pattern not found in FE"],
            "details": {"be_parsing": "database.py expects course_group||metric (split('||'))"},
        }
    )
    # 5) params match
    checks.append(
        {
            **check_params_subset("SUMMARY_PARAMS_FE_BE_MATCH", fe_summary_params, api_summary_params),
            "evidence": [f"FE params: {fe_summary_params}", f"BE params: {api_summary_params}"],
        }
    )
    checks.append(
        {
            **check_params_subset("DEALS_PARAMS_FE_BE_MATCH", fe_deals_params, api_deals_params),
            "evidence": [f"FE params: {fe_deals_params}", f"BE params: {api_deals_params}"],
        }
    )
    # 6) scope options match
    checks.append(
        {
            "id": "SCOPE_KEYS_MATCH",
            "status": "PASS" if set(fe_scope) == set(be_scope) else "FAIL",
            "evidence": [f"FE scope keys: {fe_scope}", f"BE scope keys: {be_scope}"],
            "details": {
                "missing_in_fe": [s for s in be_scope if s not in fe_scope],
                "missing_in_be": [s for s in fe_scope if s not in be_scope],
            },
        }
    )
    # 7) size groups match
    checks.append(
        {
            "id": "SIZE_GROUPS_MATCH",
            "status": "PASS" if fe_size_defined == be_size else "FAIL",
            "evidence": [f"FE size groups: {fe_size_defined}", f"BE size groups: {be_size}"],
        }
    )
    # 8) API routes existence
    checks.append(
        {
            "id": "API_ROUTES_PRESENT",
            "status": "PASS" if api_summary_params and api_deals_params else "FAIL",
            "evidence": [f"summary params: {api_summary_params}", f"deals params: {api_deals_params}"],
        }
    )
    # 9) months generation hint
    checks.append(
        {
            "id": "MONTH_RANGE_FUNCTION_USED",
            "status": "PASS" if "_month_range_keys" in be_txt else "WARN",
            "evidence": ["_month_range_keys present in database.py"],
        }
    )
    # 10) meta_debug presence
    checks.append(
        {
            "id": "META_DEBUG_PRESENT",
            "status": "PASS" if "meta_debug" in be_txt else "WARN",
            "evidence": ["meta_debug string present in database.py summary payload"],
        }
    )

    # Diff summary
    diff = {
        "course_groups_mismatch": {"fe": fe_course, "be": be_course},
        "metrics_mismatch": {"fe": fe_metrics, "be": be_metrics},
        "scope_mismatch": {"fe": fe_scope, "be": be_scope},
        "size_mismatch": {"fe": fe_size_defined, "be": be_size},
    }

    now = datetime.utcnow().isoformat() + "Z"
    next_actions: List[str] = []
    if any(c["id"] == "FE_UNDEFINED_INQUIRY_SIZE_GROUPS" and c["status"] == "FAIL" for c in checks):
        next_actions.append("Define INQUIRY_SIZE_GROUPS in FE or stop using it to avoid ReferenceError")
    if any(c["id"] == "METRICS_MATCH" and c["status"] == "FAIL" for c in checks):
        next_actions.append("Align CLOSE_RATE_METRICS order with BE (must include 'total')")
    if any(c["id"] == "SCOPE_KEYS_MATCH" and c["status"] == "FAIL" for c in checks):
        next_actions.append("Ensure scope keys match between FE buttons and BE _perf_close_rate_scope_members")
    if any(c["status"] == "FAIL" for c in checks) and not next_actions:
        next_actions.append("Inspect FAIL items above and align FE/BE contracts")
    if not next_actions:
        next_actions.append("All close-rate contract checks passed.")

    out_json = {
        "timestamp": now,
        "files": {
            "fe": str(fe_path),
            "be": str(be_path),
            "api": str(api_path),
        },
        "checks": checks,
        "diffs": diff,
        "next_actions": next_actions,
    }

    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(out_json, ensure_ascii=False, indent=2), encoding="utf-8")

    # Build markdown report
    md_lines = []
    md_lines.append("# 2026 체결률 현황 계약 감사 보고서\n")
    md_lines.append(f"- 생성시각: {now}\n")
    md_lines.append("## Executive Summary\n")
    failed = [c for c in checks if c["status"] == "FAIL"]
    md_lines.append(f"- FAIL: {len(failed)} / {len(checks)} 항목\n")
    if failed:
        for c in failed:
            md_lines.append(f"  - ❌ {c['id']}: {c.get('evidence', [])}\n")
    md_lines.append("\n## SSOT Tables\n")
    md_lines.append(f"- FE CLOSE_RATE_COURSE_GROUPS: {fe_course} (line {fe_course_line})\n")
    md_lines.append(f"- BE CLOSE_RATE_COURSE_GROUPS: {be_course} (line {be_course_line})\n")
    md_lines.append(f"- FE CLOSE_RATE_METRICS: {fe_metrics} (line {fe_metrics_line})\n")
    md_lines.append(f"- BE CLOSE_RATE_METRICS: {be_metrics} (line {be_metrics_line})\n")
    md_lines.append(f"- FE scope keys: {fe_scope} (line {fe_scope_line})\n")
    md_lines.append(f"- BE scope keys: {be_scope} (line {be_scope_line})\n")
    md_lines.append(f"- FE size groups (defined?): {fe_size_defined} (uses: {fe_size_usages})\n")
    md_lines.append(f"- BE size groups: {be_size}\n")
    md_lines.append("\n## Contract Diff\n")
    for c in checks:
        if c["status"] != "PASS":
            md_lines.append(f"- {c['id']}: {c['status']} | Evidence: {c.get('evidence')}\n")
    md_lines.append("\n## API Contract Check\n")
    md_lines.append(f"- FE summary params: {fe_summary_params}\n- BE summary params: {api_summary_params}\n")
    md_lines.append(f"- FE deals params: {fe_deals_params}\n- BE deals params: {api_deals_params}\n")
    md_lines.append("\n## Risk Hotspots\n")
    if not fe_size_defined and fe_size_usages:
        md_lines.append("- FE ReferenceError: INQUIRY_SIZE_GROUPS is used but not defined.\n")
    if fe_metrics != be_metrics:
        md_lines.append("- Metric list mismatch (total/ordering).\n")
    if set(fe_scope) != set(be_scope):
        md_lines.append("- Scope options mismatch between FE buttons and BE filter.\n")
    md_lines.append("\n## Next Fix Order\n")
    md_lines.append("1) Define or remove INQUIRY_SIZE_GROUPS in FE close-rate screen (prevents immediate crash).\n")
    md_lines.append("2) Align CLOSE_RATE_METRICS in FE with BE (must include 'total').\n")
    md_lines.append("3) Ensure scope button keys == _perf_close_rate_scope_members keys.\n")

    Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_md).write_text("\n".join(md_lines), encoding="utf-8")

    # Console summary
    fail_top = [c for c in checks if c["status"] == "FAIL"][:10]
    print("=== TOP FAILS ===")
    for c in fail_top:
        print(f"{c['id']}: {c.get('evidence')}")
    immediate = "INQUIRY_SIZE_GROUPS undefined in FE" if (not fe_size_defined and fe_size_usages) else "No immediate crash found"
    print(f"Immediate crash risk: {immediate}")
    print("Next fix priorities:")
    for i, action in enumerate(out_json["next_actions"][:5], 1):
        print(f"{i}. {action}")


if __name__ == "__main__":
    main()
