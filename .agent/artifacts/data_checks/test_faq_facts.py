from pathlib import Path
import json
import re
import pytest

ROOT = Path(__file__).resolve().parents[3]
# AC-owned control questions and required facts, independent of generated graph layout.
PAIRS = [
    ('it_support', 'Как подключиться к VPN?', ('клиент VPN', 'контакт IT')),
    ('it_support', 'Не приходит письмо на корпоративную почту', ('квот', 'Спам', 'контакт IT')),
    ('it_support', 'Как получить доступ к Git?', ('заявк', 'согласование руководителя')),
    ('benefits', 'Какие льготы по ДМС?', ('полис', 'HR-контакт')),
    ('benefits', 'Сколько дней отпуска?', (r'\d+ календарных дней',)),
    ('benefits', 'Как оформить больничный?', ('шаги', 'HR-контакт')),
    ('learning', 'Какие курсы доступны?', (r'https://[^\s]+', 'каталог')),
    ('learning', 'Как согласовать обучение?', ('шаги согласования',)),
    ('learning', 'Есть ли бюджет на обучение?', ('лимит', 'правило')),
    ('culture', 'Какой график работы?', ('гибкий график', 'час')),
    ('culture', 'Есть ли дресс-код?', ('правило', 'дресс-код')),
    ('culture', 'Как оформить командировку?', ('шаги', 'HR-контакт')),
]

@pytest.mark.parametrize('mode,question,patterns', PAIRS)
def test_control_pair(mode, question, patterns):
    faq = (ROOT / 'config/modes' / mode / 'faq.md').read_text()
    question_block = faq.split('## ' + question + '\n')[1].split('\n<a id=')[0]
    assert all(re.search(pattern, question_block, re.I) for pattern in patterns)
    assert 'не реальные политики' in faq


def test_it_faq_append_only_exactly_three_facts():
    snap = json.loads((ROOT / '.agent/artifacts/data_scope_snapshot.json').read_text())
    before = snap['before']['config/modes/it_support/faq.md']
    after = (ROOT / 'config/modes/it_support/faq.md').read_text()
    assert after.startswith(before)
    assert len(re.findall(r'^## ', after[len(before):], re.M)) == 3
    assert len(re.findall(r'<a id="[a-z0-9-]+"></a>', after[len(before):])) == 3
    prompt_before = snap['before']['config/modes/it_support/system_prompt.md']
    assert (ROOT / 'config/modes/it_support/system_prompt.md').read_text().startswith(prompt_before)


def test_new_faqs_and_plan_fixtures():
    for mode in ('benefits', 'learning', 'culture', 'onboarding_plan'):
        faq = (ROOT / 'config/modes' / mode / 'faq.md').read_text()
        assert len(re.findall(r'^## ', faq, re.M)) == 3
    faq = (ROOT / 'config/modes/onboarding_plan/faq.md').read_text()
    for term in ('роль', 'отдел', '24 часа', 'default.md', 'эскалацию'):
        assert term in faq
    for path in (ROOT / 'config/modes').rglob('*.md'):
        for url in re.findall(r'https?://([^/\s]+)', path.read_text()):
            assert url.endswith('.example.invalid'), path
