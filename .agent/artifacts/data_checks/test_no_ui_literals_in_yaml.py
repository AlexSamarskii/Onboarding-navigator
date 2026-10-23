from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[3]
LOCALE = yaml.safe_load((ROOT / 'config/i18n/ru.yaml').read_text())


def assert_key(value):
    node = LOCALE
    for part in value.split('.'):
        node = node[part]
    assert isinstance(node, str)


def test_yaml_ui_values_are_locale_keys():
    paths = list((ROOT / 'config/modes').glob('*/mode.yaml'))
    paths.append(ROOT / 'config/modes/it_support/diagnostics.yaml')
    assert len(paths) == 6
    def scan(value, path=()):
        if isinstance(value, dict):
            for key, item in value.items():
                assert not re.search('[А-Яа-яЁё]', str(key))
                scan(item, (*path, key))
        elif isinstance(value, list):
            for item in value:
                scan(item, path)
        elif isinstance(value, str):
            if 'source_titles' not in path and path[-1] != 'description':
                assert not re.search('[А-Яа-яЁё]', value), (path, value)
            if path[-1] == 'display_name' or path[-1].endswith('_key'):
                assert_key(value)
    for path in paths:
        scan(yaml.safe_load(path.read_text()))
