import pytest
from telegram_rag_bot import mode_loader
from test_mode_loader_new_fields import bundle


@pytest.mark.parametrize('locale_available', [True, False])
def test_legacy_greeting_with_and_without_locale(tmp_path, monkeypatch, locale_available):
    markers = {'loader.greeting_header':'# ПРИВЕТСТВИЕ',
               'loader.greeting_instruction':'Используйте это приветствие',
               'loader.role_header':'# РОЛЬ И ПОВЕДЕНИЕ'}
    calls = []
    def translate(key):
        calls.append(key)
        if not locale_available:
            raise RuntimeError('locale unavailable')
        return markers[key]
    monkeypatch.setattr(mode_loader, 't', translate)
    root, _ = bundle(tmp_path)
    (root/'system_prompt.md').write_text('# ПРИВЕТСТВИЕ\nПривет!\nВторая строка.\nИспользуйте это приветствие всегда.\n---\n# РОЛЬ И ПОВЕДЕНИЕ\nHR assistant.', encoding='utf-8')
    result = mode_loader.ModeLoader(tmp_path)._load_mode(root)
    assert result['greeting'] == 'Привет!\nВторая строка.'
    assert result['system_prompt'] == 'HR assistant.'
    assert calls == list(markers)


def test_no_greeting_is_unchanged(tmp_path):
    root, _ = bundle(tmp_path)
    assert mode_loader.ModeLoader(tmp_path)._load_mode(root)['system_prompt'] == 'baseline prompt'


def test_original_markers_work_when_loaded_locale_differs(tmp_path,monkeypatch):
    monkeypatch.setattr(mode_loader,'t',lambda key:'different-marker-'+key)
    root,_=bundle(tmp_path)
    (root/'system_prompt.md').write_text('# ПРИВЕТСТВИЕ\nПривет!\nИспользуйте это приветствие.\n---\n# РОЛЬ И ПОВЕДЕНИЕ\nHR.',encoding='utf-8')
    result=mode_loader.ModeLoader(tmp_path)._load_mode(root)
    assert result['greeting']=='Привет!'
    assert result['system_prompt']=='HR.'
