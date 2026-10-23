from pathlib import Path
import pytest
import yaml
from telegram_rag_bot.mode_loader import ModeLoader, ModeValidationError


def bundle(tmp_path, name='test_mode', **fields):
    root = tmp_path / name
    root.mkdir()
    data = dict(name=name, display_name='mode.it_support', description='baseline', enabled=True,
                files=dict(system_prompt='system_prompt.md', faq='faq.md'), timeout_seconds=30)
    data.update(fields)
    (root / 'mode.yaml').write_text(yaml.safe_dump(data), encoding='utf-8')
    (root / 'system_prompt.md').write_text('baseline prompt', encoding='utf-8')
    (root / 'faq.md').write_text('baseline faq', encoding='utf-8')
    return root, data


def test_additive_fields_preserve_baseline(tmp_path):
    root, data = bundle(tmp_path, source_titles={'faq.md':'source.faq'},
                        diagnostics_file='diagnostics.yaml', plans_directory='plans')
    (root/'diagnostics.yaml').write_text('{}')
    (root/'plans').mkdir()
    loaded = ModeLoader(tmp_path)._load_mode(root)
    for key, value in data.items():
        assert loaded[key] == value and type(loaded[key]) is type(value)
    assert Path(loaded['faq_file']).is_absolute()


@pytest.mark.parametrize('field,value', [
    ('source_titles', []), ('source_titles', {'faq.md':4}), ('source_titles', {4:'title'}),
    ('source_titles', {'../escape':'x'}), ('source_titles', {'C:/escape':'x'}),
    ('diagnostics_file','../escape'), ('diagnostics_file','/tmp/escape'),
    ('diagnostics_file','C:\\escape'), ('diagnostics_file','.env.example'),
    ('diagnostics_file','missing.yaml'), ('plans_directory','../plans'),
    ('plans_directory','Plans'), ('plans_directory','nested/plans'), ('plans_directory',''),
])
def test_bad_optional_fields(tmp_path, field, value):
    root, _ = bundle(tmp_path, **{field:value})
    with pytest.raises(ModeValidationError):
        ModeLoader(tmp_path)._load_mode(root)


def test_symlink_escape(tmp_path):
    root, _ = bundle(tmp_path, diagnostics_file='link.yaml')
    outside = tmp_path/'outside.yaml'
    outside.write_text('{}')
    (root/'link.yaml').symlink_to(outside)
    with pytest.raises(ModeValidationError):
        ModeLoader(tmp_path)._load_mode(root)


@pytest.mark.parametrize('name', ['it_support','benefits','learning','culture','onboarding_plan'])
def test_mandatory_failure_is_not_swallowed(tmp_path, name):
    bundle(tmp_path, name=name, diagnostics_file='../bad')
    with pytest.raises(ModeValidationError):
        ModeLoader(tmp_path).load_all_modes()


def test_optional_and_disabled_keep_skip_behavior(tmp_path):
    bundle(tmp_path, name='optional', diagnostics_file='../bad')
    bundle(tmp_path, name='it_support', enabled=False, diagnostics_file='../bad')
    assert ModeLoader(tmp_path).load_all_modes() == {}


@pytest.mark.parametrize('bad_name', ['', None])
def test_mandatory_missing_name_fails(tmp_path, bad_name):
    bundle(tmp_path,name='it_support')
    path=tmp_path/'it_support'/'mode.yaml'
    data=yaml.safe_load(path.read_text())
    if bad_name is None:
        del data['name']
    else:
        data['name']=bad_name
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ModeValidationError):
        ModeLoader(tmp_path).load_all_modes()


def test_mandatory_identity_even_with_other_folder(tmp_path):
    root,_=bundle(tmp_path,name='custom_directory')
    data=yaml.safe_load((root/'mode.yaml').read_text())
    data['name']='it_support'
    data['files']['system_prompt']='missing.md'
    (root/'mode.yaml').write_text(yaml.safe_dump(data))
    with pytest.raises(ModeValidationError):
        ModeLoader(tmp_path).load_all_modes()


def test_disabled_mandatory_without_name_is_skipped(tmp_path):
    root,_=bundle(tmp_path,name='it_support',enabled=False)
    data=yaml.safe_load((root/'mode.yaml').read_text())
    del data['name']
    data['files']={}
    (root/'mode.yaml').write_text(yaml.safe_dump(data))
    assert ModeLoader(tmp_path).load_all_modes()=={}
