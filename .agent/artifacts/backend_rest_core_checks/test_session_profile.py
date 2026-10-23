import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
from telegram_rag_bot.utils.session_manager import SessionManager


def run(awaitable):
    return asyncio.run(awaitable)


def clock(monkeypatch, manager):
    now = [datetime(2026,1,1,tzinfo=timezone.utc)]
    monkeypatch.setattr(manager,'_now',lambda:now[0])
    return now


def test_profile_last_explicit_input_survives_session_window(monkeypatch):
    manager = SessionManager()
    now = clock(monkeypatch, manager)
    run(manager.set_session(101, {'mode':'onboarding_plan'}))
    now[0] += timedelta(hours=23)
    run(manager.set_profile(101, 'developer','engineering'))
    entered = now[0]
    now[0] += timedelta(hours=2)
    assert run(manager.get_session(101))['profile']['role'] == 'developer'
    assert run(manager.get_session(101))['profile']['role'] == 'developer'
    now[0] = entered + timedelta(seconds=86399)
    assert run(manager.get_session(101))['profile']['role'] == 'developer'
    now[0] = entered + timedelta(seconds=86400)
    expired = run(manager.get_session(101))
    assert expired['profile'] == {} and expired['rag_fallback_streak'] == 0


def test_redis_sliding_write_never_refreshes_profile(monkeypatch):
    client = MagicMock()
    storage = {}
    client.get.side_effect=lambda key:storage.get(key)
    client.setex.side_effect=lambda key, ttl, data:storage.update({key:data})
    with patch('redis.from_url',return_value=client) as connect:
        manager=SessionManager('redis://example.invalid')
    assert connect.call_args.kwargs == {'socket_connect_timeout':5,'socket_timeout':5}
    now=clock(monkeypatch,manager)
    run(manager.set_profile(101,'developer','engineering'))
    initial=run(manager.get_session(101))['profile']['set_at_iso']
    now[0]+=timedelta(hours=23)
    session=run(manager.get_session(101))
    session['diagnostics_state']={'scenario':'vpn','node':'q1','started_at':now[0].isoformat()}
    run(manager.set_session(101,session))
    assert run(manager.get_session(101))['profile']['set_at_iso']==initial
    now[0]+=timedelta(hours=1)
    assert run(manager.get_session(101))['profile']=={}
    assert client.setex.call_count == 2


def test_only_rag_events_change_streak_and_ticket_state(monkeypatch):
    manager=SessionManager()
    clock(monkeypatch,manager)
    run(manager.record_rag_fallback(101))
    session=run(manager.get_session(101))
    session['diagnostics_state']={'scenario':'mail','node':'q1','started_at':manager._now().isoformat()}
    session['active_ticket_uuid']='00000000-0000-4000-8000-000000000001'
    run(manager.set_session(101,session))
    assert run(manager.get_session(101))['rag_fallback_streak']==1
    assert run(manager.get_session(101))['active_ticket_uuid']==session['active_ticket_uuid']
    assert run(manager.record_rag_fallback(101))['rag_fallback_streak']==2
    assert run(manager.record_ticket_created(101))['rag_fallback_streak']==0
    assert run(manager.get_session(101))['active_ticket_uuid'] is None
    run(manager.record_rag_fallback(101))
    assert run(manager.record_rag_success(101))['rag_fallback_streak']==0


def test_ttl_zero_never_uses_invalid_setex(monkeypatch):
    client=MagicMock()
    client.get.return_value=None
    with patch('redis.from_url',return_value=client):
        manager=SessionManager('redis://example.invalid',ttl_seconds=0)
    clock(monkeypatch,manager)
    run(manager.set_profile(101,'developer','engineering'))
    assert run(manager.get_session(101))['profile']=={}
    client.setex.assert_not_called()


@pytest.mark.parametrize('timestamp', ['malformed','2026-01-02T00:00:00+00:00',None])
def test_bad_or_future_profile_time_fails_closed(monkeypatch,timestamp):
    manager=SessionManager()
    clock(monkeypatch,manager)
    session=manager._default_session(101)
    session.update(profile={'role':'developer','department':'engineering','set_at_iso':timestamp},rag_fallback_streak=2)
    run(manager.set_session(101,session))
    assert run(manager.get_session(101))['profile']=={}
    assert run(manager.get_session(101))['rag_fallback_streak']==0


def test_legacy_naive_profile_treated_as_utc(monkeypatch):
    manager=SessionManager()
    now=clock(monkeypatch,manager)
    session=manager._default_session(101)
    session['profile']={'role':'developer','department':'engineering','set_at_iso':'2026-01-01T00:00:00'}
    run(manager.set_session(101,session))
    now[0]+=timedelta(hours=23)
    assert run(manager.get_session(101))['profile']['role']=='developer'


def test_memory_fallback_honest_and_logs_redacted(monkeypatch,caplog):
    assert 'process-local' in SessionManager.__doc__ and 'cross-pod' in SessionManager.__doc__
    with patch('redis.from_url',side_effect=RuntimeError('synthetic-private-url-value')):
        manager=SessionManager('redis://example.invalid')
    assert not manager.use_redis
    assert 'synthetic-private-url-value' not in caplog.text


def test_events_serialize_even_when_storage_yields(monkeypatch):
    manager=SessionManager()
    clock(monkeypatch,manager)
    original_get=manager.get_session
    async def delayed_get(user):
        session=await original_get(user)
        await asyncio.sleep(0)
        return session
    monkeypatch.setattr(manager,'get_session',delayed_get)
    async def concurrent():
        await asyncio.gather(*(manager.record_rag_fallback(101) for _ in range(20)))
        assert (await manager.get_session(101))['rag_fallback_streak']==20
    run(concurrent())


def test_expired_session_keeps_recent_profile_but_resets_other_state(monkeypatch):
    manager=SessionManager()
    now=clock(monkeypatch,manager)
    session=manager._default_session(101)
    session.update(profile={'role':'developer','department':'engineering','set_at_iso':(now[0]+timedelta(hours=23)).isoformat()},
                   rag_fallback_streak=1,diagnostics_state={'scenario':'vpn','node':'q1'},active_ticket_uuid='pending')
    run(manager.set_session(101,session))
    now[0]+=timedelta(hours=24)
    result=run(manager.get_session(101))
    assert result['profile']['role']=='developer'
    assert result['rag_fallback_streak']==0
    assert result['diagnostics_state']=={}
    assert result['active_ticket_uuid'] is None


def test_baseline_local_created_at_is_compatible(monkeypatch):
    manager=SessionManager()
    # Baseline wrote naive local datetime.now(); only this legacy field is local.
    local_now=datetime.now()
    monkeypatch.setattr(manager,'_now',lambda:local_now.astimezone(timezone.utc))
    manager.memory_store[101]={'created_at':local_now.isoformat(),'mode':'it_support'}
    assert run(manager.get_session(101))['mode']=='it_support'
    manager.memory_store[102]={'created_at':(local_now-timedelta(hours=25)).isoformat(),'mode':'it_support'}
    assert 'mode' not in run(manager.get_session(102))


def test_set_session_accepts_legacy_naive_local_datetime_object(monkeypatch):
    manager=SessionManager()
    local_now=datetime.now()
    now=[local_now.astimezone(timezone.utc)]
    monkeypatch.setattr(manager,'_now',lambda:now[0])
    run(manager.set_session(101,{'created_at':local_now,'mode':'it_support'}))
    result=run(manager.get_session(101))
    assert result['mode']=='it_support'
    assert datetime.fromisoformat(result['created_at'])==now[0]
    now[0]+=timedelta(hours=24)
    assert 'mode' not in run(manager.get_session(101))
