from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda
from langchain_classic.chains.retrieval import create_retrieval_chain
from telegram_rag_bot.hr_adapter import HRFAISSProvider, IndexCoordinator, LowScoreFallback, _Facade
from telegram_rag_bot.vectorstore.local_faiss import LocalFAISSProvider

class FakeStore:
    def __init__(self, pairs, metric=1):
        self.pairs=pairs;self.index=SimpleNamespace(metric_type=metric)
        self.similarity_search_with_score=Mock(return_value=pairs)

@pytest.mark.parametrize('similarity', [.7,.5])
def test_gate_calls_once_and_does_not_mutate(similarity):
    doc=Document(page_content='original FAQ fact',metadata={'source':'faq.md','nested':{'a':1}})
    before=deepcopy(doc)
    store=FakeStore([(doc,1/similarity-1)])
    retriever=_Facade(store,.65).as_retriever({'k':3})
    document_chain=Mock(return_value='answered')
    chain=create_retrieval_chain(retriever,RunnableLambda(document_chain))
    if similarity < .65:
        with pytest.raises(LowScoreFallback) as exc:chain.invoke({'input':'question'})
        assert exc.value.candidates==[]
        assert exc.value.top_score==pytest.approx(.5)
        document_chain.assert_not_called()
    else:
        result=chain.invoke({'input':'question'})
        output=result['context'][0]
        assert output.page_content==doc.page_content
        assert output.metadata['source']=='faq.md'
        assert output.metadata['score']==pytest.approx(similarity)
        output.metadata['nested']['a']=2
    assert doc==before
    store.similarity_search_with_score.assert_called_once_with('question',k=3)

@pytest.mark.parametrize('pairs,metric', [([],1),([(Document(page_content='x'),float('nan'))],1),([(Document(page_content='x'),0)],0),([(Document(page_content='x'),-1)],1)])
def test_invalid_scores_fail_closed(pairs,metric):
    store=FakeStore(pairs,metric)
    with pytest.raises(LowScoreFallback) as exc:_Facade(store,.65).as_retriever().invoke('q')
    assert exc.value.top_score==0 and exc.value.candidates==[]
    assert store.similarity_search_with_score.call_count==1

class DiskStore:
    def __init__(self,text,fail=False):self.text=text;self.fail=fail
    def save_local(self,path):
        path=Path(path);path.mkdir(exist_ok=True)
        (path/'content').write_text(self.text)
        if self.fail:raise RuntimeError('fake failed build')

@pytest.mark.asyncio
async def test_cache_freshness_and_both_cache_layers(tmp_path,monkeypatch):
    factory=SimpleNamespace(chains={'it_support':object()})
    provider=HRFAISSProvider({'indices_dir':str(tmp_path)},SimpleNamespace(dimension=3),rag_factory=factory)
    assert isinstance(provider,LocalFAISSProvider)
    from functools import lru_cache
    @lru_cache(maxsize=10)
    def load(self,mode):return FakeStore([(Document(page_content=(self.indices_dir/mode/'content').read_text(),metadata={'source':'faq.md'}),0)])
    monkeypatch.setattr(LocalFAISSProvider,'load_index',load)
    provider.save_index(DiskStore('old'),'it_support')
    assert provider.load_index('it_support').as_retriever().invoke('x')[0].page_content=='old'
    provider.save_index(DiskStore('new'),'it_support')
    assert provider.load_index('it_support').as_retriever().invoke('x')[0].page_content=='new'
    assert not factory.chains
    provider.load_index.cache_clear()
    await provider.delete_index('it_support')
    assert not (tmp_path/'it_support').exists()

@pytest.mark.asyncio
async def test_coordinator_traversal_symlink_isolation_and_rollback(tmp_path,monkeypatch):
    root=tmp_path/'config/modes';root.mkdir(parents=True)
    for mode in ['it_support','benefits']:
        (root/mode).mkdir();(root/mode/'faq.md').write_text(mode)
    provider=HRFAISSProvider({'indices_dir':str(tmp_path/'indices')},SimpleNamespace(model=SimpleNamespace(embed_documents=lambda x:None)))
    coordinator=IndexCoordinator(provider,root)
    for mapping in [{root/'it_support/../benefits/faq.md':'it_support'},{root/'benefits/faq.md':'it_support'}]:
        with pytest.raises(ValueError):await coordinator.ingest(mapping)
    external=tmp_path/'outside.md';external.write_text('outside')
    (root/'it_support/escape.md').symlink_to(external)
    with pytest.raises(ValueError):await coordinator.ingest({root/'it_support/escape.md':'it_support'})
    captured=[]
    def build(docs,embeddings):
        captured.append(docs)
        return DiskStore(docs[0].page_content)
    monkeypatch.setattr('telegram_rag_bot.hr_adapter.FAISS.from_documents',build)
    await coordinator.ingest({root/'it_support/faq.md':'it_support',root/'benefits/faq.md':'benefits'})
    assert len(captured)==2
    assert all(len({d.metadata['mode'] for d in group})==1 for group in captured)
    assert (provider.indices_dir/'it_support/content').read_text()=='it_support'
    provider.save_index(DiskStore('OLD-IT'),'it_support')
    provider.save_index(DiskStore('OLD-HR'),'benefits')
    def fail_second(docs,embeddings):return DiskStore('new',fail=docs[0].metadata['mode']=='benefits')
    monkeypatch.setattr('telegram_rag_bot.hr_adapter.FAISS.from_documents',fail_second)
    with pytest.raises(RuntimeError):await coordinator.ingest({root/'it_support/faq.md':'it_support',root/'benefits/faq.md':'benefits'})
    assert (provider.indices_dir/'it_support/content').read_text()=='OLD-IT'
    assert (provider.indices_dir/'benefits/content').read_text()=='OLD-HR'
