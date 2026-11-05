"""Review A2/A5/A7/A8/A11 and B2 regressions; all state and HTTP are fixtures."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from threading import Event

import pytest

from scripts.lib.anthropic_credit import CreditBook, CreditDenied
from scripts.lib.anthropic_transport import AnthropicError, AnthropicTransport, price_usage
from scripts.anthropic_credit_reset import confirmation, main, run


NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
HAIKU, SONNET, OPUS = 'claude-haiku-5-5', 'claude-sonnet-5-5', 'claude-opus-5-5'


def policy(**updates):
    base = {
        'enabled': True, 'promotion_id': 'fixture-promotion', 'credit_usd': '200',
        'total_cap_usd': '190', 'daily_cap_usd': '10',
        'starts_at': '2026-10-25T00:00:00Z', 'expires_at': '2026-11-16T00:00:00Z',
        'per_call_caps_usd': {'bulk': '0.10', 'standard': '0.25', 'high': '0.50', 'highest': '0.50'},
        'models': {'bulk': HAIKU, 'standard': OPUS, 'high': OPUS, 'highest': OPUS},
        'retry': {'max_attempts': 2, 'max_delay_seconds': 0}, 'input_framing_margin_tokens': 4096,
        'pricing': {
            HAIKU: {'input': '0.10', 'output': '0.50', 'cache_read': '0.01',
                    'cache_write_5m': '0.125', 'cache_write_1h': '0.20', 'batch_multiplier': '0.5'},
            SONNET: {'input': '2', 'output': '10', 'cache_read': '0.10',
                     'cache_write_5m': '2.5', 'cache_write_1h': '4', 'batch_multiplier': '0.5'},
            OPUS: {'input': '4', 'output': '20', 'cache_read': '0.20',
                   'cache_write_5m': '5', 'cache_write_1h': '8', 'batch_multiplier': '0.5'},
        },
    }
    return dict(base, **updates)


def message(model=HAIKU):
    return {'id': 'msg_fixture', 'model': model, 'content': [{'type': 'text', 'text': 'fixture answer'}],
            'stop_reason': 'end_turn', 'usage': {'input_tokens': 10, 'output_tokens': 5}}


def adapter(tmp_path, responses=None, *, p=None, reserve=None, meter=None, clock=None):
    book = CreditBook(tmp_path, p or policy())
    calls, events, attempts, settled = [], [], [], []
    queue = list(responses or [])
    def request(method, path, payload, **kwargs):
        calls.append((method, path, payload))
        if path.endswith('count_tokens'):
            return 200, {'input_tokens': 10}, {}
        reply = queue.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply
    def record(*args):
        events.append(args)
        return True if meter is None else meter(*args)
    client = AnthropicTransport(book=book, env={'ANTHROPIC_API_KEY': 'synthetic-fixture'},
        request=request, now=clock or (lambda: NOW), sleep=lambda _: None,
        record_usage=record, record_attempt=lambda *args: attempts.append(args) or True,
        reserve_process=reserve or (lambda *args: None), settle_process=settled.append)
    return client, book, calls, events, attempts, settled


def generate(client, request_id='fixture-call', **kwargs):
    return client.generate([{'role': 'user', 'content': 'synthetic fixture'}], HAIKU,
        client_request_id=request_id, process_id='fixture-process', max_tokens=10, **kwargs)


@pytest.mark.parametrize('updates', [
    {'promotion_id': None}, {'promotion_id': ''}, {'starts_at': 'invalid-clock'},
    {'expires_at': None}, {'total_cap_usd': 'NaN'}, {'per_call_caps_usd': []},
    {'per_call_caps_usd': {'bulk': 'NaN'}},
])
def test_credit_constructor_configuration_failures_are_typed(tmp_path, updates):
    with pytest.raises(CreditDenied, match='CREDIT_CONFIGURATION_INVALID'):
        CreditBook(tmp_path, policy(**updates))


def test_missing_required_configuration_is_typed(tmp_path):
    p = policy()
    del p['promotion_id']
    with pytest.raises(CreditDenied, match='CREDIT_CONFIGURATION_INVALID'):
        CreditBook(tmp_path, p)


@pytest.mark.parametrize('row', [None, [], 'invalid', {'checksum': 'wrong'}])
def test_snapshot_nonobject_or_corrupt_journal_is_typed(tmp_path, row):
    book = CreditBook(tmp_path, policy())
    book.reserve('first', 'fixture-process', Decimal('.01'), tier='bulk', now=NOW)
    with book.path.open('a') as handle:
        handle.write(json.dumps(row) + '\n')
    with pytest.raises(CreditDenied, match='CREDIT_UNAVAILABLE'):
        book.snapshot(now=NOW)


def test_snapshot_refusal_is_provider_typed_before_http(tmp_path, monkeypatch):
    client, _, calls, *_ = adapter(tmp_path)
    def denied(**kwargs):
        raise CreditDenied('CREDIT_UNAVAILABLE')
    monkeypatch.setattr(client.book, 'snapshot', denied)
    with pytest.raises(AnthropicError) as error:
        generate(client)
    assert error.value.code == 'CREDIT_UNAVAILABLE'
    assert calls == []


@pytest.mark.parametrize('refusal', [
    CreditDenied('CREDIT_UNAVAILABLE'), RuntimeError('CREDIT_PAUSED_TODAY: fixture'),
    RuntimeError('CREDIT_EXHAUSTED: fixture'), RuntimeError('CREDIT_EXPIRED: fixture'),
    RuntimeError('COST_CAP_EXCEEDED: fixture'), RuntimeError('COST_CONFIGURATION_INVALID: fixture'),
    RuntimeError('persistence failed with sensitive arbitrary text'),
])
def test_native_db_refusal_is_provider_typed_and_releases_unsent_hold(tmp_path, refusal):
    def reserve(*args):
        raise refusal
    client, book, calls, events, _, settled = adapter(tmp_path, reserve=reserve)
    with pytest.raises(AnthropicError) as error:
        generate(client)
    assert error.value.code == ('GOVERNANCE_UNAVAILABLE' if str(refusal).startswith('persistence') else str(refusal).split(':')[0])
    assert [path for _, path, _ in calls] == ['/v1/messages/count_tokens']
    assert book.snapshot(now=NOW)['reserved_usd'] == '0.00'
    assert not events and settled == [Decimal(0)]


@pytest.mark.parametrize('status,body', [
    (429, {'error': {'type': 'rate_limit_error'}}),
    (529, {'error': {'type': 'overloaded_error'}}), (529, []),
    (429, {'error': {'type': 'billing_error'}}), (529, {'error': {'type': 'billing_error'}}),
    (500, {'error': {'type': 'overloaded_error'}}),
])
def test_explicit_rate_and_overload_refusals_do_not_keep_holds(tmp_path, status, body):
    failure = (status, body, {})
    clock = [NOW]
    client, book, _, events, attempts, _ = adapter(tmp_path, [failure] * 8,
        p=policy(daily_cap_usd='.01'), clock=lambda: clock[0])
    for index in range(4):
        if index == 2:
            clock[0] += timedelta(days=1)
        with pytest.raises(AnthropicError):
            generate(client, f'fixture-{index}')
        snapshot = book.snapshot(now=clock[0])
        assert snapshot['status'] == 'OK'
        assert Decimal(snapshot['reserved_usd']) == Decimal(snapshot['today_used_usd']) == 0
    assert not events and not attempts


@pytest.mark.parametrize('tail', [
    (500, {'error': {'type': 'api_error'}}, {}),
    (429, {'error': {'type': 'rate_limit_error'}}, {}),
    (529, {'error': {'type': 'overloaded_error'}}, {}),
    AnthropicError('TIMEOUT', request_sent=True, possibly_billable=True),
    AnthropicError('TIMEOUT', request_sent=False, possibly_billable=False),
])
def test_ambiguous_500_is_retained_even_when_last_attempt_is_refused(tmp_path, tail):
    client, book, _, events, attempts, _ = adapter(tmp_path,
        [(500, {'error': {'type': 'api_error'}}, {}), tail])
    with pytest.raises(AnthropicError):
        generate(client)
    assert Decimal(book.snapshot(now=NOW)['reserved_usd']) > 0
    assert not events and attempts


def test_timeout_retains_total_authorization(tmp_path):
    client, book, *_ = adapter(tmp_path,
        [AnthropicError('TIMEOUT', request_sent=True, possibly_billable=True)])
    with pytest.raises(AnthropicError):
        generate(client)
    assert Decimal(book.snapshot(now=NOW)['reserved_usd']) > 0


@pytest.mark.parametrize('uncertain', [False, True])
def test_daily_hold_never_ttl_expires_but_leaves_daily_pace_at_utc_midnight(tmp_path, uncertain):
    book = CreditBook(tmp_path, policy(daily_cap_usd='.10', reservation_daily_ttl_minutes=1))
    book.reserve('held', 'fixture-process', Decimal('.10'), tier='bulk', now=NOW,
                 process_cap=Decimal('.10'))
    if uncertain:
        book.settle('held', None, now=NOW)
    assert book.snapshot(now=NOW + timedelta(hours=11))['status'] == 'PAUSED_TODAY'
    with pytest.raises(CreditDenied, match='PAUSED_TODAY'):
        book.reserve('same-day', 'fixture-process', Decimal('.01'), tier='bulk', now=NOW + timedelta(hours=11))
    tomorrow = NOW + timedelta(days=1)
    snapshot = book.snapshot(now=tomorrow)
    assert snapshot['status'] == 'OK' and snapshot['reserved_today_usd'] == '0.00'
    assert snapshot['reserved_usd'] == snapshot['expired_unsettled_usd'] == '0.10'
    book.reserve('next-day', 'fixture-process', Decimal('.10'), tier='bulk', now=tomorrow,
                 process_cap=Decimal('.10'))
    assert book.snapshot(now=tomorrow)['reserved_usd'] == '0.20'


def test_old_uncertain_hold_remains_against_total_cap(tmp_path):
    book = CreditBook(tmp_path, policy(total_cap_usd='.10', daily_cap_usd='.10'))
    book.reserve('held', 'fixture-process', Decimal('.10'), tier='bulk', now=NOW)
    book.settle('held', None, now=NOW)
    assert book.snapshot(now=NOW + timedelta(days=1))['status'] == 'EXHAUSTED'


@pytest.mark.parametrize('model,mode', [(HAIKU, 'disabled'), (SONNET, 'between_tools'), (OPUS, 'adaptive')])
@pytest.mark.parametrize('thinking', ['enabled', 'disabled'])
def test_current_model_thinking_controls_are_explicit(tmp_path, model, mode, thinking):
    client, *_ = adapter(tmp_path)
    payload = client._payload([{'role': 'user', 'content': 'fixture'}], model, 16, thinking)
    assert payload['thinking'] == {'type': 'adaptive' if thinking == 'enabled' else mode}
    assert payload['output_config'] == {'effort': 'high' if thinking == 'enabled' else 'low'}


def test_policy_thinking_controls_are_used_and_cannot_disable_opus(tmp_path):
    controls = {OPUS: {'disabled': {'thinking': {'type': 'disabled'}, 'output_config': {'effort': 'low'}}},
                HAIKU: {'enabled': {'thinking': {'type': 'adaptive'}, 'output_config': {'effort': 'medium'}}}}
    original = deepcopy(controls)
    client, *_ = adapter(tmp_path, p=policy(thinking_controls=controls))
    assert client._payload([{'role': 'user', 'content': 'fixture'}], OPUS, 16, 'disabled')['thinking']['type'] == 'adaptive'
    assert client._payload([{'role': 'user', 'content': 'fixture'}], HAIKU, 16, 'enabled')['output_config']['effort'] == 'medium'
    assert controls == original


@pytest.mark.parametrize('stop_reason', ['max_tokens', 'refusal'])
def test_empty_paid_response_is_output_invalid_after_exact_settlement(tmp_path, stop_reason):
    body = message()
    body.update(content=[], stop_reason=stop_reason)
    client, book, _, events, *_ = adapter(tmp_path, [(200, body, {})])
    with pytest.raises(AnthropicError, match='OUTPUT_INVALID'):
        generate(client)
    assert len(events) == 1
    assert Decimal(book.snapshot(now=NOW)['credit_used_usd']) == events[0][2]
    assert Decimal(book.snapshot(now=NOW)['reserved_usd']) == 0


@pytest.mark.parametrize('reason', ['accounting_unavailable', 'over_reservation'])
def test_accounting_pause_is_bounded_and_preserves_total_holds(tmp_path, reason):
    book = CreditBook(tmp_path, policy(unavailable_cooldown_minutes=30))
    book.reserve('held', 'fixture-process', Decimal('.10'), tier='bulk', now=NOW)
    book.settle('held', None, now=NOW)
    book.record_failure(reason, now=NOW)
    assert book.snapshot(now=NOW)['status'] == 'UNAVAILABLE'
    assert book.snapshot(now=NOW + timedelta(minutes=30))['status'] == 'OK'
    assert book.snapshot(now=NOW + timedelta(minutes=30))['reserved_usd'] == '0.10'


@pytest.mark.parametrize('minutes', ['Infinity', 'NaN', 'invalid', 10**20])
def test_unavailable_configuration_cannot_make_pause_permanent(tmp_path, minutes):
    book = CreditBook(tmp_path, policy(unavailable_cooldown_minutes=minutes))
    book.record_failure('accounting_unavailable', now=NOW)
    assert book.snapshot(now=NOW + timedelta(days=1))['status'] == 'OK'


def test_operator_reset_appends_without_erasing_spend_or_holds_and_uses_sequence(tmp_path):
    book = CreditBook(tmp_path, policy())
    book.reserve('spent', 'fixture-process', Decimal('.10'), tier='bulk', now=NOW)
    book.settle('spent', Decimal('.03'), now=NOW)
    book.reserve('held', 'fixture-process', Decimal('.10'), tier='bulk', now=NOW)
    book.settle('held', None, now=NOW)
    book.record_failure('billing_error', now=NOW)
    book.record_failure('accounting_unavailable', now=NOW)
    prefix = book.path.read_bytes()
    before = book.snapshot(now=NOW)
    dry = run(book, scope='all', now=NOW)
    assert dry['dry_run'] is True and book.path.read_bytes() == prefix
    with pytest.raises(CreditDenied, match='CONFIRMATION_REQUIRED'):
        run(book, scope='all', apply=True, now=NOW)
    reset = run(book, scope='all', apply=True, confirm=confirmation(book.promotion, 'all'), now=NOW)
    assert reset['after']['status'] == 'OK' and book.path.read_bytes().startswith(prefix)
    assert reset['after']['credit_used_usd'] == before['credit_used_usd'] == '0.03'
    assert reset['after']['reserved_usd'] == before['reserved_usd'] == '0.10'
    book.record_failure('billing_error', now=NOW)  # Identical clock still follows the reset in the chain.
    assert book.snapshot(now=NOW)['status'] == 'EXHAUSTED'


def test_operator_reset_does_not_clear_total_exhaustion(tmp_path):
    book = CreditBook(tmp_path, policy(total_cap_usd='.10'))
    book.reserve('held', 'fixture-process', Decimal('.10'), tier='bulk', now=NOW)
    book.record_failure('billing_error', now=NOW)
    assert book.operator_reset('all', now=NOW)['status'] == 'EXHAUSTED'


def test_promotion_change_verifies_older_chain_and_isolates_totals(tmp_path):
    old = CreditBook(tmp_path, policy())
    old.reserve('fixture-id', 'fixture-process', Decimal('.10'), tier='bulk', now=NOW)
    old.record_failure('billing_error', now=NOW)
    newer = CreditBook(tmp_path, policy(promotion_id='fixture-next-promotion'))
    assert newer.snapshot(now=NOW)['status'] == 'OK'
    newer.reserve('fixture-id', 'fixture-process', Decimal('.02'), tier='bulk', now=NOW)
    assert newer.snapshot(now=NOW)['reserved_usd'] == '0.02'
    assert old.snapshot(now=NOW)['reserved_usd'] == '0.10'
    rows = old.path.read_text().splitlines()
    row = json.loads(rows[0]); row['projected'] = '0.01'
    rows[0] = json.dumps(row)
    old.path.write_text('\n'.join(rows) + '\n')
    with pytest.raises(CreditDenied, match='CREDIT_UNAVAILABLE'):
        newer.snapshot(now=NOW)


def test_reset_cli_is_dry_by_default_and_uses_explicit_temp_roots(tmp_path, capsys):
    code_root, state_root = tmp_path / 'code', tmp_path / 'state'
    (code_root / 'config').mkdir(parents=True)
    (code_root / 'config/anthropic_credit_policy.json').write_text(json.dumps(policy()))
    (code_root / 'config/llm_model_registry.json').write_text(json.dumps({'providers': {'anthropic': {'enabled': True}}}))
    args = ['--project-root', str(code_root), '--state-root', str(state_root), '--scope', 'all']
    assert main(args) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry['dry_run'] and not state_root.exists()
    assert main(args + ['--apply', '--confirm', dry['required_confirmation']]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert not applied['dry_run'] and applied['after']['reset_sequence'] == 1


def batch_adapter(tmp_path, *, ambiguous=False, meter=None):
    p = policy()
    book = CreditBook(tmp_path, p)
    calls, events, settled = [], [], []
    request_id, batch_id = 'fixture-batch', 'msgbatch_fixture'
    key = book.reserve(request_id, 'fixture-process', Decimal('.05'), tier='bulk', now=NOW)
    with book._locked():
        book._append(book._read(), 'batch', NOW, request=key, batch_id=batch_id,
                     model=HAIKU, process_id='fixture-process', ambiguous=ambiguous)
    def request(method, path, payload, **kwargs):
        calls.append(path)
        if path.endswith('/results'):
            return 200, {'results': [{'custom_id': key, 'result': {'type': 'succeeded', 'message': message()}}]}, {}
        return 200, {'processing_status': 'ended'}, {}
    def record(*args):
        events.append(args)
        return True if meter is None else meter(*args)
    client = AnthropicTransport(book=book, env={'ANTHROPIC_API_KEY': 'synthetic-fixture'},
        request=request, now=lambda: NOW, record_usage=record, record_attempt=lambda *args: True,
        reserve_process=lambda *args: None, settle_process=settled.append)
    return client, book, calls, events, settled


def collect(client):
    return client.collect_batch('msgbatch_fixture', client_request_id='fixture-batch', process_id='fixture-process')


@pytest.mark.parametrize('ambiguous', [False, True])
def test_batch_collection_is_idempotent_even_when_original_submission_was_ambiguous(tmp_path, ambiguous):
    client, book, calls, events, settled = batch_adapter(tmp_path, ambiguous=ambiguous)
    first = collect(client)
    size = book.path.stat().st_size
    restarted = AnthropicTransport(book=CreditBook(tmp_path, policy()), env={'ANTHROPIC_API_KEY': 'synthetic-fixture'},
        request=lambda *args, **kwargs: pytest.fail('duplicate collect made HTTP request'), now=lambda: NOW,
        record_usage=lambda *args: pytest.fail('duplicate collect emitted spend'),
        record_attempt=lambda *args: True, reserve_process=lambda *args: None)
    second = collect(restarted)
    assert first['status'] == 'SUCCEEDED' and second['status'] == 'ALREADY_COLLECTED'
    assert book.path.stat().st_size == size
    assert len(events) == len(settled) == 1 and len(calls) == 2
    assert (Decimal(book.snapshot(now=NOW)['reserved_usd']) > 0) is ambiguous


def test_concurrent_batch_collectors_emit_once(tmp_path):
    entered, release = Event(), Event()
    def meter(*args):
        entered.set()
        assert release.wait(5)
        return True
    client, _, _, events, _ = batch_adapter(tmp_path, meter=meter)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(collect, client)
        assert entered.wait(5)
        second = pool.submit(collect, client)
        try:
            with pytest.raises(AnthropicError, match='BATCH_COLLECTION_UNCERTAIN'):
                second.result(timeout=5)
        finally:
            release.set()
        assert first.result(timeout=5)['status'] == 'SUCCEEDED'
    assert len(events) == 1


def test_uncertain_batch_meter_write_is_not_retried_or_released(tmp_path):
    def meter(*args):
        raise OSError('fixture write failed after an unknown write boundary')
    client, book, _, events, _ = batch_adapter(tmp_path, meter=meter)
    with pytest.raises(AnthropicError, match='ACCOUNTING_UNAVAILABLE'):
        collect(client)
    with pytest.raises(AnthropicError, match='BATCH_COLLECTION_UNCERTAIN'):
        collect(client)
    assert len(events) == 1 and Decimal(book.snapshot(now=NOW)['reserved_usd']) == Decimal('.05')


@pytest.mark.parametrize('status', [429, 529])
def test_refused_batch_submission_releases_hold(tmp_path, status):
    error = (status, {'error': {'type': 'rate_limit_error' if status == 429 else 'overloaded_error'}}, {})
    client, book, _, events, attempts, settled = adapter(tmp_path, [error, error])
    with pytest.raises(AnthropicError):
        client.submit_batch([{'role': 'user', 'content': 'fixture'}], HAIKU,
            caller_allows_async=True, client_request_id='fixture-batch', process_id='fixture-process',
            max_tokens=10, max_input_tokens=1000, process_cap=Decimal(1))
    assert Decimal(book.snapshot(now=NOW)['reserved_usd']) == 0
    assert not events and not attempts and settled == [Decimal(0)]


def test_overload_then_success_settles_exact_usage_without_ambiguity(tmp_path):
    client, book, _, events, attempts, settled = adapter(tmp_path,
        [(529, {'error': {'type': 'overloaded_error'}}, {}), (200, message(), {})])
    generate(client)
    assert len(events) == 1 and not attempts and settled == [events[0][2]]
    assert Decimal(book.snapshot(now=NOW)['reserved_usd']) == 0


def test_batch_snapshot_refusal_is_provider_typed_before_http(tmp_path, monkeypatch):
    client, _, calls, *_ = adapter(tmp_path)
    def denied(**kwargs):
        raise CreditDenied('CREDIT_UNAVAILABLE')
    monkeypatch.setattr(client.book, 'snapshot', denied)
    with pytest.raises(AnthropicError, match='CREDIT_UNAVAILABLE'):
        client.submit_batch([{'role': 'user', 'content': 'fixture'}], HAIKU,
            caller_allows_async=True, client_request_id='fixture-batch', process_id='fixture-process',
            max_tokens=10, max_input_tokens=1000, process_cap=Decimal(1))
    assert calls == []
