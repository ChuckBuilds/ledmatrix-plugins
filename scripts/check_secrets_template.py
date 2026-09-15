#!/usr/bin/env python3
"""Keep config_secrets.template.json in step with the plugins' x-secret fields.

The core stores secrets in ``config/config_secrets.json``, namespaced by plugin
id, and deep-merges them into that plugin's config at load time. A field is a
secret when its config_schema.json marks it ``"x-secret": true``; the web UI
then routes it to the secrets file. The root template in this repo is the one
place a user can see every secret the official plugins take -- and it had
drifted to listing only a GitHub token while ten plugins declared secrets.

Fails when:
- an x-secret field has no entry at ``template[plugin_id][...path]``;
- the template holds a value that is not a placeholder ("" or "YOUR_...");
- a plugin-namespaced template entry is not an x-secret field any more
  (stale), or names a plugin that does not exist.

Secret discovery mirrors the core's ``src/web_interface/secret_helpers.py:
find_secret_fields``: recurse into ``type: object`` properties and ``type:
array`` items, and nothing else. A field the core would not treat as secret is
not demanded here.

    python scripts/check_secrets_template.py

Exit codes: 0 pass, 1 fail.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"
TEMPLATE = REPO_ROOT / "config_secrets.template.json"

# Top-level template keys that belong to the core, not to a plugin.
CORE_NAMESPACES = {"github"}

MIN_PLAUSIBLE_SCHEMAS = 20


def find_secret_fields(properties, prefix: str = "") -> set[str]:
    """Same traversal as the core's secret_helpers.find_secret_fields."""
    fields: set[str] = set()
    if not isinstance(properties, dict):
        return fields
    for name, props in properties.items():
        if not isinstance(props, dict):
            continue
        path = f"{prefix}.{name}" if prefix else name
        if props.get("x-secret", False):
            fields.add(path)
        if props.get("type") == "object" and "properties" in props:
            fields |= find_secret_fields(props["properties"], path)
        if props.get("type") == "array" and isinstance(props.get("items"), dict):
            items = props["items"]
            if items.get("x-secret", False):
                fields.add(f"{path}[]")
            if items.get("type") == "object" and "properties" in items:
                fields |= find_secret_fields(items["properties"], f"{path}[]")
    return fields


def _template_has(node, path: str) -> bool:
    """Is `path` (dot-separated, `[]` for arrays) present under `node`?

    An array segment can't carry a per-item placeholder meaningfully, so the
    key holding the array is enough.
    """
    for segment in path.split("."):
        is_array = segment.endswith("[]")
        key = segment[:-2] if is_array else segment
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
        if is_array:
            return True
    return True


def _leaves(node, prefix: str = ""):
    """(path, value) for every non-dict value in the template."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _leaves(value, f"{prefix}.{key}" if prefix else key)
    else:
        yield prefix, node


def _is_placeholder(value) -> bool:
    if isinstance(value, str):
        return value == "" or value.startswith("YOUR_")
    return value in ([], None)


def find_problems(plugins_dir: Path, template_path: Path):
    """Returns (problems, schemas_read, secret_field_count)."""
    problems: list[str] = []
    template = json.loads(template_path.read_text(encoding="utf-8"))
    if not isinstance(template, dict):
        return [f"{template_path.name} is not a JSON object"], 0, 0

    secrets: dict[str, set[str]] = {}
    schemas_read = 0
    for schema_path in sorted(plugins_dir.glob("*/config_schema.json")):
        pid = schema_path.parent.name
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            problems.append(f"{pid}: config_schema.json could not be read ({e})")
            continue
        schemas_read += 1
        fields = find_secret_fields(schema.get("properties", {}))
        if fields:
            secrets[pid] = fields

    for pid, fields in sorted(secrets.items()):
        for field in sorted(fields):
            if not _template_has(template.get(pid), field):
                problems.append(
                    f"{pid}: x-secret field '{field}' has no placeholder in "
                    f"{template_path.name} (expected under \"{pid}\")")

    plugin_ids = {p.name for p in plugins_dir.iterdir() if p.is_dir()}
    for top, value in template.items():
        if top in CORE_NAMESPACES:
            continue
        if top not in plugin_ids:
            problems.append(f"template key '{top}' is not a plugin id (and not "
                            f"a core namespace: {sorted(CORE_NAMESPACES)})")
            continue
        declared = {f.split("[]")[0] for f in secrets.get(top, set())}
        for leaf, _ in _leaves(value):
            if not any(leaf == d or leaf.startswith(d + ".") for d in declared):
                problems.append(f"{top}: template entry '{leaf}' is not an "
                                f"x-secret field in its config_schema.json (stale?)")

    for leaf, value in _leaves(template):
        if not _is_placeholder(value):
            problems.append(f"template value at '{leaf}' is not a placeholder; "
                            f"use \"\" or \"YOUR_...\" -- never a real secret")

    return problems, schemas_read, sum(len(f) for f in secrets.values())


def main(plugins_dir: Path = PLUGINS_DIR, template_path: Path = TEMPLATE,
         min_schemas: int = MIN_PLAUSIBLE_SCHEMAS) -> int:
    try:
        problems, n_schemas, n_fields = find_problems(plugins_dir, template_path)
    except (OSError, ValueError) as e:
        print(f"FAIL could not read {template_path}: {e}")
        return 1
    if n_schemas < min_schemas:
        problems.append(f"only {n_schemas} config schemas read under {plugins_dir}; "
                        f"the check is not looking at the plugin tree")
    for p in problems:
        print(f"FAIL {p}")
    if problems:
        return 1
    print(f"PASS {n_fields} x-secret field(s) across {n_schemas} schemas all have "
          f"placeholders in {template_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
