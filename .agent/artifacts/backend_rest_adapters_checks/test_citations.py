from pathlib import Path
import pytest
from langchain_core.documents import Document
from telegram_rag_bot.citations import extract_citation

PAIRS = [
 ('it_support', 'клиент VPN; контакт IT'), ('it_support', 'квота и спам; контакт IT'),
 ('it_support', 'заявка и согласование руководителя'), ('benefits', 'полис ДМС; HR-контакт'),
 ('benefits', 'отпуск 28 дней'), ('benefits', 'больничный: шаги и HR-контакт'),
 ('learning', 'каталог курсов https://example.test/catalog'), ('learning', 'шаги согласования обучения'),
 ('learning', 'лимит бюджета на обучение'), ('culture', 'гибкий график 10–19'),
 ('culture', 'правило дресс-кода'), ('culture', 'шаги командировки и HR-контакт'),
]
@pytest.mark.parametrize('mode,fact', PAIRS)
def test_exact_manual_control_fact(mode, fact):
    source = f'{mode}/faq.md'
    document = Document(page_content='Вопрос\n' + fact + '\nКонец', metadata={'source': source})
    citation = extract_citation([document], {source: 'Проверенный источник'})
    assert citation.source_display == 'Проверенный источник'
    assert fact in citation.quote
    assert citation.quote == document.page_content

@pytest.mark.parametrize('content,metadata,titles', [('', {'source':'known'}, {'known':'FAQ'}), ('irrelevant',{}, {'known':'FAQ'}), ('text',{'source':'other'},{'known':'FAQ'}), ('   ',{'source':'known'},{'known':'FAQ'})])
def test_no_provenance_match(content, metadata, titles):
    assert extract_citation([Document(page_content=content, metadata=metadata)], titles) is None

def test_locale_source_title():
    from telegram_rag_bot.i18n import load_locale
    load_locale(Path('config/i18n/ru.yaml'))
    citation = extract_citation([Document(page_content='exact', metadata={'source':'faq.md'})], {'faq.md':'mode.it_support'})
    assert citation.source_display != 'mode.it_support'
