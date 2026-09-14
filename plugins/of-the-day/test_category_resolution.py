#!/usr/bin/env python3
"""
Regression tests: the display and the web UI agree on what a category is.

The file manager (scripts/list_files.py) lists every .json in of_the_day/ as
an enabled category unless config says otherwise. The display used to load
only categories written into config['categories'] -- empty on a fresh
install -- so both bundled lists showed as enabled while the panel said
"No Data", and toggling them failed with "not found in config".

Run from the core LEDMatrix tree (needs src.*):
    cd /path/to/LEDMatrix
    python -m pytest /path/to/of-the-day/test_category_resolution.py -q
"""

import json
import os
import subprocess
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from manager import OfTheDayPlugin  # noqa: E402

WORD = "word_of_the_day"
SLOVENIAN = "slovenian_word_of_the_day"


def _plugin(config=None):
    from src.plugin_system.testing import (
        MockCacheManager, MockPluginManager, VisualTestDisplayManager)
    cfg = {"enabled": True}
    cfg.update(config or {})
    return OfTheDayPlugin("of-the-day", cfg, VisualTestDisplayManager(128, 32),
                          MockCacheManager(), MockPluginManager())


class TestResolveCategories:
    def test_empty_config_loads_every_bundled_file(self):
        p = _plugin({"categories": {}, "category_order": []})
        assert set(p.data_files) == {WORD, SLOVENIAN}
        assert p.categories[WORD]["data_file"] == f"of_the_day/{WORD}.json"
        assert set(p.category_order) == {WORD, SLOVENIAN}

    def test_missing_keys_behave_like_empty(self):
        p = _plugin()
        assert set(p.data_files) == {WORD, SLOVENIAN}

    def test_config_entry_disables_a_bundled_file(self):
        p = _plugin({"categories": {SLOVENIAN: {"enabled": False}}})
        assert set(p.data_files) == {WORD}
        # Partial entries keep the file's defaults.
        assert p.categories[SLOVENIAN]["data_file"] == f"of_the_day/{SLOVENIAN}.json"

    def test_category_order_first_then_the_rest(self):
        p = _plugin({"category_order": [SLOVENIAN, "gone", SLOVENIAN]})
        assert p.category_order == [SLOVENIAN, WORD]

    def test_configured_category_outside_the_data_dir_is_kept(self):
        p = _plugin({"categories": {"custom": {
            "enabled": True, "data_file": "nowhere/custom.json",
            "display_name": "Custom"}}})
        assert "custom" in p.category_order
        assert set(p.data_files) == {WORD, SLOVENIAN}  # file missing: skipped

    def test_on_config_change_uses_the_same_rule(self):
        p = _plugin({"categories": {WORD: {"enabled": False}}})
        assert set(p.data_files) == {SLOVENIAN}
        p.on_config_change({"enabled": True, "categories": {}})
        assert set(p.data_files) == {WORD, SLOVENIAN}


def _toggle(tmp_path, params, config):
    (tmp_path / "config").mkdir(exist_ok=True)
    config_path = tmp_path / "config" / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    env = dict(os.environ, LEDMATRIX_ROOT=str(tmp_path))
    proc = subprocess.run(
        [sys.executable, os.path.join(PLUGIN_DIR, "scripts", "toggle_category.py")],
        input=json.dumps(params), capture_output=True, text=True, env=env)
    return proc, json.loads(proc.stdout), json.loads(config_path.read_text(encoding="utf-8"))


class TestToggleScript:
    def test_toggling_an_unconfigured_data_file_creates_its_entry(self, tmp_path):
        proc, out, config = _toggle(
            tmp_path, {"category_name": SLOVENIAN, "enabled": False},
            {"of-the-day": {"enabled": True}})
        assert proc.returncode == 0, out
        assert config["of-the-day"]["categories"][SLOVENIAN] == {
            "enabled": False,
            "data_file": f"of_the_day/{SLOVENIAN}.json",
            "display_name": "Slovenian Word Of The Day",
        }
        assert config["of-the-day"]["enabled"] is True

    def test_existing_entry_is_only_flipped(self, tmp_path):
        entry = {"enabled": True, "data_file": "x.json", "display_name": "X"}
        proc, _, config = _toggle(
            tmp_path, {"category_name": WORD},
            {"of-the-day": {"categories": {WORD: dict(entry)}}})
        assert proc.returncode == 0
        assert config["of-the-day"]["categories"][WORD] == dict(entry, enabled=False)

    def test_unknown_category_still_fails_with_a_message(self, tmp_path):
        proc, out, _ = _toggle(tmp_path, {"category_name": "nope"}, {})
        assert proc.returncode == 1
        assert "nope" in out["message"]
