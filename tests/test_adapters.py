import threading
from collections import deque

import pytest
import requests

from armchemist.openai_client import DecisionsJudge, OpenAIHTTP, OpenAIPlanner
from armchemist.rail import CentralRail
from armchemist.registry import CAPABILITIES
from armchemist.runtime import DecisionUnavailable, ExecutionError, Frame


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status
        self.ok = 200 <= status < 300
    def json(self):
        return self.body
    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError('error')


class Session:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.calls = []
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        value = self.responses.popleft()
        if isinstance(value, Exception):
            raise value
        return value
    def post(self, url, **kwargs):
        return self.request('POST', url, **kwargs)


@pytest.mark.parametrize('answer,status', [({'type': 'choice', 'choice': 'complete', 'confidence': .97}, 'complete'), ({'type': 'choice', 'choice': 'incomplete', 'confidence': .96}, 'incomplete'), ({'type': 'choice', 'choice': 'complete', 'confidence': .51}, 'unknown'), ({'type': 'refusal'}, 'unknown')])
def test_decisions_official_contract_and_uncertainty(answer, status):
    session = Session([Response({'id': 'd1', 'answers': [{'name': 'completion', **answer}]})])
    judge = DecisionsJudge(OpenAIHTTP('test-key', session=session))
    verdict = judge.check(CAPABILITIES['pickup_bottle1'], [Frame('head', 1, b'image')])
    assert verdict.status == status
    _, url, kwargs = session.calls[0]
    assert url.endswith('/v1/decisions')
    assert kwargs['json']['questions'][0]['name'] == 'completion'
    assert kwargs['json']['input'][0]['content'][-1]['image_url'].startswith('data:image/jpeg;base64,')


@pytest.mark.parametrize('response', [Response({}, 429), Response({}, 503), requests.Timeout()])
def test_transient_decision_errors_are_distinct(response):
    client = OpenAIHTTP('test', session=Session([response]))
    with pytest.raises(DecisionUnavailable):
        client.post('decisions', {})


def test_authentication_failure_not_retried_as_incomplete():
    with pytest.raises(ExecutionError):
        OpenAIHTTP('test', session=Session([Response({}, 401)])).post('decisions', {})


def status(command_id, state='DONE', station='실험존', ts=20):
    return {'devices': {'pi2': {'online': True, 'age_s': .1, 'ts': ts, 'rail': {
        'available': True, 'position_known': True, 'calibrated': True, 'moving': False,
        'stations_stale': False, 'station': station}}}, 'rail_commands': {'pi2': {'id': command_id,
        'status': state, 'updated_at': 10}}}


def test_rail_done_waits_for_fresh_report_after_result(monkeypatch):
    monkeypatch.setattr('armchemist.rail.uuid4', lambda: type('ID', (), {'hex': 'cmd'})())
    session = Session([Response({'id': 'cmd'}), Response(status('cmd', ts=9)), Response(status('cmd'))])
    rail = CentralRail('http://central', session=session)
    assert rail.move('실험존', threading.Event()) == 'cmd'
    assert [c[0] for c in session.calls] == ['POST', 'GET', 'GET']
    assert all('/rail/command?' not in c[1] for c in session.calls)


def test_unknown_rail_result_never_resubmits(monkeypatch):
    monkeypatch.setattr('armchemist.rail.uuid4', lambda: type('ID', (), {'hex': 'cmd'})())
    session = Session([Response({'id': 'cmd'}), Response(status('cmd', state='UNKNOWN'))])
    with pytest.raises(ExecutionError, match='UNKNOWN'):
        CentralRail('http://central', session=session).move('실험존', threading.Event())
    assert len([c for c in session.calls if c[0] == 'POST']) == 1


def test_rail_request_timeout_never_resubmits():
    session = Session([requests.Timeout()])
    with pytest.raises(ExecutionError):
        CentralRail('http://central', session=session).move('실험존', threading.Event())
    assert len(session.calls) == 1


def test_planner_uses_structured_output_and_refuses_missing_output():
    session = Session([Response({'status': 'completed', 'output': [{'content': [{'type': 'refusal'}]}]})])
    planner = OpenAIPlanner(OpenAIHTTP('test', session=session), 'gpt-6-luna')
    with pytest.raises(ExecutionError):
        planner.select([{'role': 'user', 'content': 'test'}], {})
    body = session.calls[0][2]['json']
    assert body['text']['format']['strict'] is True
    assert len(body['text']['format']['schema']['properties']['actions']['items']['enum']) == 9
