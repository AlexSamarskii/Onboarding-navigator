import importlib
import pytest
from prometheus_client import CollectorRegistry, generate_latest, REGISTRY
from telegram_rag_bot.utils import metrics


def test_new_and_old_series_share_supplied_registry():
    registry=CollectorRegistry()
    collectors=metrics.register_metrics(registry)
    collectors['QUERY_LATENCY'].labels(mode='it_support').observe(.1)
    collectors['ACTIVE_USERS'].set(1)
    collectors['ERROR_COUNT'].labels(error_type='test').inc()
    collectors['LLM_REQUESTS'].labels(provider='gigachat',status='success').inc()
    collectors['RAG_SCORE'].observe(.65)
    collectors['FALLBACK_TOTAL'].labels(type='rag').inc()
    collectors['TICKETS_CREATED'].inc()
    collectors['TICKETS_FAILED'].inc()
    exported=generate_latest(registry).decode()
    for name in ['bot_query_latency_seconds','bot_active_users','bot_errors_total',
                 'llm_requests_total','rag_score_bucket','fallback_total',
                 'tickets_created_total','tickets_failed_total']:
        assert name in exported
    bounds=[sample.labels['le'] for sample in collectors['RAG_SCORE'].collect()[0].samples if sample.name=='rag_score_bucket']
    assert bounds==['0.0','0.2','0.4','0.6','0.65','0.7','0.8','0.9','1.0','+Inf']


def test_isolated_registration_and_reload_reuse_global_collectors():
    original=metrics.QUERY_LATENCY
    isolated=CollectorRegistry()
    first=metrics.register_metrics(isolated)
    assert metrics.QUERY_LATENCY is original and metrics.REGISTRY is REGISTRY
    assert first['QUERY_LATENCY'] is not original
    assert metrics.register_metrics(isolated)['RAG_SCORE'] is first['RAG_SCORE']
    before=metrics.LLM_REQUESTS
    importlib.reload(metrics)
    assert metrics.LLM_REQUESTS is before and metrics.QUERY_LATENCY is original
    assert metrics.register_metrics(isolated)['LLM_REQUESTS'] is first['LLM_REQUESTS']


@pytest.mark.parametrize('values', [{'provider':'user-123','status':'success'},
                                   {'provider':'gigachat','status':'arbitrary'},
                                   {'source':'faq','status':'success'}, {'user_id':'101'}])
def test_bounded_labels_reject_unapproved_values(values):
    collector=metrics.register_metrics(CollectorRegistry())['LLM_REQUESTS']
    with pytest.raises(ValueError):
        collector.labels(**values)


def test_fallback_type_bounded():
    collector=metrics.register_metrics(CollectorRegistry())['FALLBACK_TOTAL']
    with pytest.raises(ValueError):
        collector.labels(type='diagnostics')
    assert collector._labelnames==('type',)
