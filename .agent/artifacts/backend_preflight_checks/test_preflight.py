"""Offline contract checks for the three authorized preflight additions."""

import importlib.util
import json
from pathlib import Path
from string import Formatter
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "workspace/telegram-rag-bot-src/telegram_rag_bot/i18n.py"
LOCALE = ROOT / "config/i18n/ru.yaml"
INPUT = json.loads((ROOT / ".agent/artifacts/backend_preflight_input.json").read_text())


def new_module():
    spec = importlib.util.spec_from_file_location("preflight_i18n", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module():
    return new_module()


def test_exact_config():
    config = yaml.safe_load((ROOT / "config/config.yaml").read_text())
    assert config == INPUT["config"]
    assert config["retrieval"]["async_mode"] is False


def test_import_has_no_locale_io_or_telegram_import():
    import builtins
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert "telegram" not in name and "handlers" not in name
        return original(name, *args, **kwargs)

    with patch.object(Path, "open", side_effect=AssertionError("unexpected read")):
        with patch("builtins.__import__", side_effect=guarded):
            module = new_module()
    with pytest.raises(RuntimeError):
        module.t("commands.start")


def test_required_locale_and_all_templates(module):
    catalog = module.load_locale(LOCALE)
    for key, expected in INPUT["locale_required"].items():
        assert module.t(key) == expected
    for key in INPUT["locale_sections"]:
        node = catalog
        for part in key.split("."):
            node = node[part]
        assert node

    def visit(node, prefix=""):
        for key, value in node.items():
            dotted = prefix + key
            if isinstance(value, dict):
                visit(value, dotted + ".")
            else:
                fields = {field: "тест" for _, field, _, _ in Formatter().parse(value) if field}
                assert isinstance(module.t(dotted, **fields), str)
    visit(catalog)
    assert module.t("citation.reference", source="FAQ", quote="Точный факт") == "Источник: FAQ\nЦитата: «Точный факт»"
    assert catalog["diagnostics"]["vpn"]["escalation"]
    assert catalog["diagnostics"]["mail"]["escalation"]
    assert len(catalog["diagnostics"]["vpn"]) >= 8
    assert len(catalog["diagnostics"]["mail"]) >= 8


def test_catalog_copy_cannot_change_active_state(module):
    catalog = module.load_locale(LOCALE)
    catalog["admin"]["denied"] = "mutated"
    assert module.t("admin.denied") == "недостаточно прав"


@pytest.mark.parametrize("key", ["missing", "commands", "commands.start.child"])
def test_missing_or_nonleaf_keys_raise(module, key):
    module.load_locale(LOCALE)
    with pytest.raises(KeyError):
        module.t(key)


@pytest.mark.parametrize("key", ["", ".key", "key.", "a..b", None])
def test_invalid_keys_raise(module, key):
    module.load_locale(LOCALE)
    with pytest.raises(ValueError):
        module.t(key)


def test_interpolation_missing_values_not_silenced(module):
    module.load_locale(LOCALE)
    with pytest.raises(KeyError):
        module.t("citation.reference", source="FAQ")
    assert module.t("admin.denied", extra="ignored") == "недостаточно прав"


@pytest.mark.parametrize("content", [
    "", "[]", "false", "x: 3", "x: null", "x: []", "x: {}", "1: text",
    "a.b: text", "'': text", 'x: "{user.name}"', 'x: "{user[0]}"',
    'x: "{}"', 'x: "{value!r}"', 'x: "{value:04d}"', 'x: "{"',
    "x: &x\n  recursive: *x", "x: [",
])
def test_invalid_load_keeps_previous_locale(module, tmp_path, content):
    module.load_locale(LOCALE)
    candidate = tmp_path / "invalid.yaml"
    candidate.write_text(content)
    with pytest.raises((ValueError, yaml.YAMLError)):
        module.load_locale(candidate)
    assert module.t("admin.denied") == "недостаточно прав"


def test_io_failure_keeps_previous_locale(module, tmp_path):
    module.load_locale(LOCALE)
    with pytest.raises(FileNotFoundError):
        module.load_locale(tmp_path / "missing.yaml")
    assert module.t("admin.denied") == "недостаточно прав"


def test_generic_locale_is_not_hardcoded_to_ru(module, tmp_path):
    candidate = tmp_path / "fixture.yaml"
    candidate.write_text('sample:\n  nested: "{{literal}} {name}"\n', encoding="utf-8")
    assert module.load_locale(candidate) == {"sample": {"nested": "{{literal}} {name}"}}
    assert module.t("sample.nested", name="Тест") == "{literal} Тест"
