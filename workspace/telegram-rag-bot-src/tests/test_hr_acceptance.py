"""Offline HR acceptance examples: factual fixtures and public adapter behavior."""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import re
import shutil

import pytest
import yaml
from langchain_core.documents import Document
from telegram_rag_bot.citations import extract_citation
from telegram_rag_bot.diagnostics import load_graph, InvalidGraph
from telegram_rag_bot.handlers import TelegramHandlers
from telegram_rag_bot.hr_adapter import _Facade, LowScoreFallback
from telegram_rag_bot.i18n import load_locale, t
from telegram_rag_bot.mode_loader import ModeLoader
from telegram_rag_bot.utils.session_manager import SessionManager

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'workspace/telegram-rag-bot-src/telegram_rag_bot'
PAIRS = [
    ('s1_vpn', 'it_support', 'Как подключиться к VPN?', ['клиент VPN', 'контакт IT']),
    ('s1_mail', 'it_support', 'Не приходит письмо на корпоративную почту', ['Спам', 'квоту', 'контакт IT']),
    ('s1_git', 'it_support', 'Как получить доступ к Git?', ['заявку', 'согласование руководителя']),
    ('s2_insurance', 'benefits', 'Какие льготы по ДМС?', ['полис', 'HR-контакт']),
    ('s2_vacation', 'benefits', 'Сколько дней отпуска?', ['28 календарных дней']),
    ('s2_sick_leave', 'benefits', 'Как оформить больничный?', ['получите', 'сообщите', 'HR-контакт']),
    ('s3_courses', 'learning', 'Какие курсы доступны?', ['https://learning.example.invalid/catalog']),
    ('s3_approval', 'learning', 'Как согласовать обучение?', ['отправьте руководителю', 'дождитесь согласования']),
    ('s3_budget', 'learning', 'Есть ли бюджет на обучение?', ['10000', 'за календарный год']),
    ('s5_schedule', 'culture', 'Какой график работы?', ['гибкий график', '11:00–16:00']),
    ('s5_dress_code', 'culture', 'Есть ли дресс-код?', ['повседневный аккуратный дресс-код']),
    ('s5_business_trip', 'culture', 'Как оформить командировку?', ['согласуйте', 'направьте заявку HR', 'HR-контакт']),
]


def faq_section(mode, question):
    """Associate each control query with its own FAQ answer, not another section."""
    faq = (ROOT / 'config/modes' / mode / 'faq.md').read_text(encoding='utf-8')
    match = re.search(r'^## ' + re.escape(question) + r'\n(.*?)(?=\n<a |\n## |\Z)', faq, re.M | re.S)
    assert match, question
    return match.group(1)


def _fact_check(pair):
    _, mode, question, facts = pair
    answer = faq_section(mode, question)
    for fact in facts:
        assert fact.casefold() in answer.casefold(), (question, fact)


# Explicit test names provide a stable mapping to all twelve approved pairs.
def test_ac_s1_vpn_fact(): _fact_check(PAIRS[0])
def test_ac_s1_mail_fact(): _fact_check(PAIRS[1])
def test_ac_s1_git_fact(): _fact_check(PAIRS[2])
def test_ac_s2_insurance_fact(): _fact_check(PAIRS[3])
def test_ac_s2_vacation_fact(): _fact_check(PAIRS[4])
def test_ac_s2_sick_leave_fact(): _fact_check(PAIRS[5])
def test_ac_s3_courses_fact(): _fact_check(PAIRS[6])
def test_ac_s3_approval_fact(): _fact_check(PAIRS[7])
def test_ac_s3_budget_fact(): _fact_check(PAIRS[8])
def test_ac_s5_schedule_fact(): _fact_check(PAIRS[9])
def test_ac_s5_dress_code_fact(): _fact_check(PAIRS[10])
def test_ac_s5_business_trip_fact(): _fact_check(PAIRS[11])


@pytest.mark.parametrize('pair', PAIRS, ids=[p[0] for p in PAIRS])
def test_u01_twelve_verbatim_context_citations(pair):
    _, mode, question, facts = pair
    text = faq_section(mode, question)
    source = str(ROOT / 'config/modes' / mode / 'faq.md')
    doc = Document(page_content=text, metadata={'source': source})
    load_locale(ROOT / 'config/i18n/ru.yaml')
    citation = extract_citation([doc], {source: 'mode.' + mode})
    assert citation and citation.quote == text
    assert citation.quote in doc.page_content
    assert citation.source_display == t('mode.' + mode)
    assert all(f.casefold() in citation.quote.casefold() for f in facts)


def test_u01_negative_context():
    assert extract_citation([], {'faq.md': 'mode.it_support'}) is None
    assert extract_citation([Document(page_content='unapproved', metadata={'source': 'unknown'})], {'faq.md': 'mode.it_support'}) is None


@pytest.mark.parametrize('similarity', [0.0, 0.649, 0.650, 0.651, 1.0])
def test_score_boundary_is_inclusive(similarity):
    doc = Document(page_content='verified fact', metadata={'source': 'faq.md'})
    distance = float('inf') if similarity == 0.0 else 1.0 / similarity - 1.0
    search = Mock(return_value=[(doc, distance)])
    store = SimpleNamespace(index=SimpleNamespace(metric_type=1), similarity_search_with_score=search)
    retriever = _Facade(store, .65).as_retriever()
    if similarity < .65:
        with pytest.raises(LowScoreFallback) as error:
            retriever.invoke('question')
        assert error.value.candidates == []
    else:
        result = retriever.invoke('question')
        assert result[0].metadata['score'] == pytest.approx(similarity)
    search.assert_called_once_with('question', k=3)


def handler(mode='onboarding_plan', root=None):
    load_locale(ROOT / 'config/i18n/ru.yaml')
    message = SimpleNamespace(text='query', reply_text=AsyncMock())
    update = SimpleNamespace(message=message, effective_message=message,
                             effective_user=SimpleNamespace(id=101, username=None), callback_query=None)
    instance = TelegramHandlers(Mock(), SessionManager(),
        {'modes': {mode: {'display_name': 'mode.' + mode, 'plans_directory': 'plans'}}}, Mock(),
        coordinator=Mock(), modes_directory=root or ROOT / 'config/modes', unanswered_writer=Mock())
    return instance, update


def replies(update):
    return '\n'.join(c.args[0] for c in update.message.reply_text.call_args_list).replace('\\', '')


@pytest.mark.asyncio
async def test_profile_ttl_is_from_last_explicit_input(monkeypatch):
    manager = SessionManager()
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(manager, '_now', lambda: now[0])
    await manager.set_session(101, {'mode': 'onboarding_plan'})
    now[0] += timedelta(hours=23)
    await manager.set_profile(101, 'developer', 'engineering')
    now[0] += timedelta(hours=23)
    await manager.set_session(101, await manager.get_session(101))
    assert (await manager.get_session(101))['profile']['role'] == 'developer'
    now[0] += timedelta(hours=1)
    assert (await manager.get_session(101))['profile'] == {}


@pytest.mark.asyncio
async def test_profile_prompts_role_then_department():
    h, u = handler()
    await h.handle_message(u, None)
    assert t('profile.ask_role') in replies(u)
    u.message.text = 'developer'
    await h.handle_message(u, None)
    assert t('profile.ask_department') in replies(u)
    u.message.text = 'engineering'
    await h.handle_message(u, None)
    assert (await h.session_manager.get_session(101))['profile']['department'] == 'engineering'


@pytest.mark.asyncio
async def test_plan_priority_and_missing_default(tmp_path):
    directory = tmp_path / 'onboarding_plan/plans'
    directory.mkdir(parents=True)
    files = {'developer__engineering.md': 'SPECIFIC', 'developer.md': 'ROLE', 'default.md': 'GENERAL'}
    for name, text in files.items(): (directory / name).write_text(text)
    h, u = handler(root=tmp_path)
    await h.session_manager.set_profile(101, 'developer', 'engineering')
    await h.handle_message(u, None)
    assert 'SPECIFIC' in replies(u) and 'GENERAL' not in replies(u)
    (directory / 'developer__engineering.md').unlink()
    u.message.reply_text.reset_mock()
    await h.handle_message(u, None)
    assert 'ROLE' in replies(u) and 'SPECIFIC' not in replies(u)
    (directory / 'developer.md').unlink()
    u.message.reply_text.reset_mock()
    await h.handle_message(u, None)
    assert 'GENERAL' in replies(u) and t('plan.escalation_offer') in replies(u)
    assert h.unanswered_writer.write.call_args.args[0].reason == 'missing_plan'
    (directory / 'default.md').unlink()
    u.message.reply_text.reset_mock()
    await h.handle_message(u, None)
    assert 'GENERAL' not in replies(u) and t('plan.not_configured') in replies(u)


def test_yaml_bundle_added_without_code_changes(tmp_path):
    bundle = tmp_path / 'new_department'
    bundle.mkdir()
    (bundle / 'faq.md').write_text('New FAQ')
    (bundle / 'system_prompt.md').write_text('New system prompt')
    (bundle / 'mode.yaml').write_text(yaml.safe_dump({'name': 'new_department', 'display_name': 'New department', 'description': 'Independent bundle', 'enabled': True, 'files': {'faq': 'faq.md', 'system_prompt': 'system_prompt.md'}, 'timeout_seconds': 30}))
    assert ModeLoader(tmp_path).load_all_modes()['new_department']['display_name'] == 'New department'


@pytest.mark.parametrize('scenario', ['vpn', 'mail'])
def test_diagnostics_all_three_terminal_paths(scenario):
    graph = load_graph(ROOT / 'config/modes/it_support/diagnostics.yaml')
    spec = graph.scenarios[scenario]
    paths = []
    def visit(name, depth):
        node = spec['nodes'][name]
        assert graph.escalate_available(node)
        if node['type'] == 'terminal':
            paths.append(name)
            assert depth <= 3 and node['faq_ref'].startswith('faq.md#')
        else:
            for index, choice in enumerate(node['choices']):
                expected = spec['nodes'][choice['next']]
                assert graph.step(scenario, name, index) == (expected if expected['type'] == 'terminal' else choice['next'])
                visit(choice['next'], depth + 1)
    visit(spec['start'], 0)
    assert len(paths) == 3 and len(set(paths)) == 3
    with pytest.raises(ValueError): graph.step(scenario, spec['start'], 999)


def test_diagnostic_cycle_is_rejected(tmp_path):
    config = tmp_path / 'config'
    shutil.copytree(ROOT / 'config/modes/it_support', config / 'modes/it_support')
    (config / 'i18n').mkdir()
    shutil.copy(ROOT / 'config/i18n/ru.yaml', config / 'i18n/ru.yaml')
    path = config / 'modes/it_support/diagnostics.yaml'
    data = yaml.safe_load(path.read_text())
    spec = data['scenarios']['vpn']
    spec['nodes'][spec['start']]['choices'][0]['next'] = spec['start']
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(InvalidGraph): load_graph(path)


def test_ast_no_ui_cyrillic():
    # The strict replacement is also collected as a standalone artifact test.
    import runpy
    checks = runpy.run_path(str(ROOT / '.agent/artifacts/backend_rest_i18n_checks/test_legacy_and_ui_cyrillic.py'))
    checks['assert_ui_cyrillic_allowed']((SOURCE / 'handlers.py').read_text(), False)
    checks['assert_ui_cyrillic_allowed']((SOURCE / 'mode_loader.py').read_text(), True)


def test_ast_negative_control_rejects_new_ui_even_with_noqa():
    import runpy
    check = runpy.run_path(str(ROOT / '.agent/artifacts/backend_rest_i18n_checks/test_legacy_and_ui_cyrillic.py'))['assert_ui_cyrillic_allowed']
    with pytest.raises(AssertionError): check('text = "Неожиданная строка"  # noqa: i18n\n', False)


@pytest.mark.asyncio
async def test_standalone_legacy_commands_work_without_active_locale(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError('locale not activated')
    monkeypatch.setattr('telegram_rag_bot.i18n.t', unavailable)
    monkeypatch.setattr('telegram_rag_bot.handlers.t', unavailable)
    h = TelegramHandlers(Mock(), SessionManager(),
        {'modes': {'it_support': {'display_name': 'IT Support'}}}, Mock())
    u = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()),
                        effective_user=SimpleNamespace(id=101, username=None))
    await h.cmd_start(u, None)
    assert 'Привет' in u.message.reply_text.call_args.args[0]
    await h.cmd_help(u, None)
    assert 'Помощь' in u.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_hr_commands_do_not_mask_missing_locale(monkeypatch):
    h, u = handler()
    def unavailable(*args, **kwargs):
        raise RuntimeError('locale not activated')
    monkeypatch.setattr('telegram_rag_bot.handlers.t', unavailable)
    with pytest.raises(RuntimeError, match='locale not activated'):
        await h.cmd_start(u, None)
