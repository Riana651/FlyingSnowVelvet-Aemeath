"""Shared config storage merge helpers."""

from __future__ import annotations

import ast
import re

from config.shared_storage_paths import (
    get_project_config_path,
    get_shared_config_path,
    local_pending_sync_path,
    pending_sync_path,
)
from config.shared_storage_io import read_text_best_effort, write_shared_text

DEFAULT_REFRESH_RULES: dict[str, dict[str, dict[str, tuple[object, ...]]]] = {
    'ollama_config.py': {
        'OLLAMA': {
            'gsv_temperature': (1.3,),
        },
    },
}


def dict_block_pattern(dict_name: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?ms)^(\s*{re.escape(dict_name)}\s*=\s*\{{)(.*?)(^\s*\}})",
    )


def find_dict_body(text: str, dict_name: str) -> str | None:
    m = dict_block_pattern(dict_name).search(text)
    return m.group(2) if m else None


def replace_dict_body(text: str, dict_name: str, new_body: str) -> str:
    pattern = dict_block_pattern(dict_name)
    return pattern.sub(lambda m: f'{m.group(1)}{new_body}{m.group(3)}', text, count=1)


def detect_top_level_indent(body: str) -> str:
    for line in body.splitlines():
        m = re.match(r"^(\s*)'[^'\r\n]+'\s*:\s*.*,\s*(?:#.*)?$", line)
        if m:
            return m.group(1)
    return ''


def iter_top_level_keys(body: str) -> list[str]:
    indent = detect_top_level_indent(body)
    keys: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^(\s*)'([^'\r\n]+)'\s*:\s*.*,\s*(?:#.*)?$", line)
        if not m:
            continue
        if indent and m.group(1) != indent:
            continue
        keys.append(m.group(2))
    return keys


def find_dict_item_value(body: str, key: str, indent: str) -> str | None:
    pattern = re.compile(
        rf"(?m)^{re.escape(indent)}'{re.escape(key)}'\s*:\s*(.*?)(,\s*(?:#.*)?)$",
    )
    m = pattern.search(body)
    return m.group(1).rstrip() if m else None


def normalize_python_literal(text: str) -> object:
    raw = str(text or '').strip()
    if not raw:
        return ''
    try:
        return ast.literal_eval(raw)
    except Exception:
        return re.sub(r'\s+', ' ', raw)


def replace_dict_item_value(body: str, key: str, indent: str, new_value: str) -> str:
    pattern = re.compile(
        rf"(?m)^({re.escape(indent)}'{re.escape(key)}'\s*:\s*).*(,\s*(?:#.*)?)$",
    )
    return pattern.sub(lambda m: f'{m.group(1)}{new_value}{m.group(2)}', body, count=1)


def merge_dict_body(template_body: str, external_body: str, refresh_rules: dict[str, tuple[object, ...]] | None = None) -> str:
    merged = template_body
    indent = detect_top_level_indent(template_body)
    for key in iter_top_level_keys(template_body):
        tpl_val = find_dict_item_value(template_body, key, indent)
        ext_val = find_dict_item_value(external_body, key, indent)
        if ext_val is None:
            continue
        if tpl_val is not None and refresh_rules:
            default_values = refresh_rules.get(key)
            if default_values and normalize_python_literal(ext_val) in default_values:
                continue
        merged = replace_dict_item_value(merged, key, indent, ext_val)
    return merged


def merge_single_assignment(text: str, external_text: str, name: str) -> str:
    src_pattern = re.compile(
        rf"(?m)^(\s*{re.escape(name)}\s*=\s*)([^#\r\n]*?)(\s*(?:#.*)?)$",
    )
    src_match = src_pattern.search(external_text)
    if not src_match:
        return text
    src_value = src_match.group(2).strip()
    if not src_value:
        return text

    dst_pattern = re.compile(
        rf"(?m)^(\s*{re.escape(name)}\s*=\s*).*(\s*(?:#.*)?)$",
    )
    if not dst_pattern.search(text):
        return text
    return dst_pattern.sub(lambda m: f'{m.group(1)}{src_value}{m.group(2)}', text, count=1)


def merge_python_config_text(template_text: str, external_text: str, rel_name: str, single_assignments: tuple[str, ...]) -> str:
    merged = template_text
    file_refresh_rules = DEFAULT_REFRESH_RULES.get(rel_name, {})
    dict_name_pattern = re.compile(r'(?m)^([A-Za-z_]\w*)\s*=\s*\{')
    dict_names = [m.group(1) for m in dict_name_pattern.finditer(template_text)]
    for dict_name in dict_names:
        tpl_body = find_dict_body(merged, dict_name)
        ext_body = find_dict_body(external_text, dict_name)
        if tpl_body is None or ext_body is None:
            continue
        merged_body = merge_dict_body(tpl_body, ext_body, file_refresh_rules.get(dict_name))
        merged = replace_dict_body(merged, dict_name, merged_body)

    for name in single_assignments:
        merged = merge_single_assignment(merged, external_text, name)
    return merged


def sync_managed_python_file(rel_name: str, single_assignments: tuple[str, ...]) -> None:
    local_path = get_project_config_path(rel_name)
    shared_path = get_shared_config_path(rel_name)
    if not local_path.exists():
        return

    local_text = local_path.read_text(encoding='utf-8')
    pending_path = pending_sync_path(shared_path)
    local_pending_path = local_pending_sync_path(shared_path)
    if shared_path.exists():
        external_text = read_text_best_effort(shared_path)
    elif pending_path.exists():
        external_text = read_text_best_effort(pending_path)
    elif local_pending_path.exists():
        external_text = read_text_best_effort(local_pending_path)
    else:
        external_text = local_text

    merged = merge_python_config_text(local_text, external_text, rel_name, single_assignments)
    shared_path.parent.mkdir(parents=True, exist_ok=True)
    write_shared_text(shared_path, merged, encoding='utf-8')
