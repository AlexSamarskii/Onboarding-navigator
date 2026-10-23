import pytest
import yaml
from telegram_rag_bot import config_loader
from test_mode_loader_new_fields import bundle


def product():
    return dict(modes={'directory':'modes'},rag={'score_threshold':0.65},
                integrations={'ticketing':{'url':'${TICKETING_WEBHOOK_URL}','hr_chat_id':'${HR_CHAT_ID}'}},
                i18n={'default_locale':'ru'},ADMIN_IDS='${ADMIN_IDS}',session={'ttl_seconds':86400},
                retrieval={'async_mode':False},llm={'providers':['gigachat','yandexgpt']})


def test_product_load_relative_and_placeholder_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(config_loader.os, 'environ', {})
    modes = tmp_path/'modes'
    modes.mkdir()
    bundle(modes)
    path = tmp_path/'config.yaml'
    path.write_text(yaml.safe_dump(product()))
    loaded = config_loader.ConfigLoader.load_config(str(path))
    assert loaded['ADMIN_IDS'] == '${ADMIN_IDS}'
    assert loaded['integrations']['ticketing']['url'] == '${TICKETING_WEBHOOK_URL}'
    assert loaded['modes_directory'] == str(modes.resolve())
    assert loaded['llm']['providers'] == ['gigachat','yandexgpt']
    assert config_loader.reload_config(str(path)) == loaded


@pytest.mark.parametrize('value, expected', [('[101, 202]',[101,202]),('101,202',[101,202]),('',[])])
def test_synthetic_environment_ids(tmp_path, monkeypatch, value, expected):
    monkeypatch.setattr(config_loader.os, 'environ', {'ADMIN_IDS':value,'TICKETING_WEBHOOK_URL':'https://example.invalid/tickets'})
    config = config_loader.ConfigLoader._substitute_env_vars(product(), preserve_missing=True)
    config['ADMIN_IDS'] = config_loader.ConfigLoader._parse_admin_ids(config['ADMIN_IDS'])
    config_loader.ConfigLoader._validate_config(config)
    assert config['ADMIN_IDS'] == expected


@pytest.mark.parametrize('section,field,value', [
    ('rag','score_threshold',True),('rag','score_threshold',float('nan')),('rag','score_threshold',1.1),
    ('modes','directory','/absolute'),('modes','directory','../escape'),
    ('integrations','ticketing',{'url':'file:///bad'}),('integrations','ticketing',{'url':3}),
    ('integrations','ticketing',{'url':'https://example.invalid','hr_chat_id':12}),
    ('session','ttl_seconds',True),('session','ttl_seconds',-1),('retrieval','async_mode','false'),
    ('llm','providers',[]),('llm','providers',[1]),('i18n','default_locale','../bad'),
])
def test_invalid_product(tmp_path, section, field, value):
    config = product()
    config[section][field] = value
    with pytest.raises(ValueError):
        config_loader.ConfigLoader._validate_config(config)


@pytest.mark.parametrize('value', [[True], [1,'2'], {}, '1,no', '[true]', '["1"]'])
def test_invalid_admins(value):
    config = product()
    config['ADMIN_IDS'] = value
    with pytest.raises(ValueError):
        config_loader.ConfigLoader._validate_config(config)


def test_legacy_and_platform_validation(monkeypatch):
    monkeypatch.setattr(config_loader.os,'environ',{'TELEGRAM_TOKEN':'synthetic-only'})
    config = {'telegram':{'token':'${TELEGRAM_TOKEN}'},'orchestrator':{},'modes':{'directory':'modes'}}
    expanded = config_loader.ConfigLoader._substitute_env_vars(config)
    assert expanded['telegram']['token'] == 'synthetic-only'
    config_loader.ConfigLoader._validate_config(expanded)
    config['platform'] = {'callback_url':'https://example.invalid'}
    with pytest.raises(ValueError, match='tenant_id'):
        config_loader.ConfigLoader._validate_config(config)
    monkeypatch.setattr(config_loader.os,'environ',{})
    with pytest.raises(ValueError,match='TELEGRAM_TOKEN'):
        config_loader.ConfigLoader._substitute_env_vars(config)


def test_checked_in_product_loads_without_live_environment(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(config_loader.os,'environ',{})
    path=Path(__file__).resolve().parents[3]/'config'/'config.yaml'
    loaded=config_loader.ConfigLoader.load_config(str(path))
    assert set(loaded['modes'])=={'it_support','benefits','learning','culture','onboarding_plan'}
    assert loaded['rag']['score_threshold']==0.65
    assert loaded['retrieval']['async_mode'] is False
