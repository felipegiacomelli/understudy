from types import SimpleNamespace

import pytest

from understudy.llm import CompletionError, Completer


class Client:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def response(text='hello', finish='stop', usage=None, refusal=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=text, refusal=refusal),
            finish_reason=finish,
        )],
        usage=usage,
        model='provider-resolved-model',
    )


def test_completion_records_actual_usage_and_provider_specific_request():
    usage = SimpleNamespace(prompt_tokens=25, completion_tokens=8,
                            prompt_cache_hit_tokens=10, prompt_tokens_details=None)
    client = Client(response(usage=usage))
    complete = Completer('customer', 'deepseek-flash', 'https://api.deepseek.com',
                        client=client)
    assert complete([{'role': 'user', 'content': 'Hello'}]) == 'hello'
    request = client.requests[0]
    assert request['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert request['max_tokens'] == 800
    assert 'seed' not in request
    assert complete.calls[0]['input_tokens'] == 25
    assert complete.calls[0]['output_tokens'] == 8
    assert complete.calls[0]['cached_input_tokens'] == 10
    assert complete.calls[0]['resolved_model'] == 'provider-resolved-model'


def test_openai_request_omits_deepseek_parameters_and_unknown_usage_is_null():
    client = Client(response())
    complete = Completer('target', 'gpt-4.1-mini-2025-04-14',
                        'https://api.openai.com/v1', client=client)
    complete([{'role': 'user', 'content': 'JSON please'}], json_output=True)
    assert 'extra_body' not in client.requests[0]
    assert client.requests[0]['response_format'] == {'type': 'json_object'}
    assert complete.calls[0]['input_tokens'] is None


@pytest.mark.parametrize('answer', [response('', 'stop'), response('partial', 'length'),
                                   response('blocked', refusal='refused'),
                                   TimeoutError('SECRET provider body')])
def test_failures_are_bounded_sanitized_and_accounted(answer):
    client = Client(answer)
    complete = Completer('judge', 'model', 'https://api.openai.com/v1', client=client)
    with pytest.raises(CompletionError) as caught:
        complete([{'role': 'user', 'content': 'Evaluate'}])
    assert 'SECRET' not in str(caught.value)
    assert len(client.requests) == 1
    assert len(complete.calls) == 1
    assert complete.calls[0]['status'] == 'error'


def test_client_is_created_only_on_call_with_no_hidden_retries(monkeypatch):
    import openai
    constructed = []
    client = Client(response())
    monkeypatch.setattr(openai, 'OpenAI', lambda **kwargs: constructed.append(kwargs) or client)
    complete = Completer('target', 'model', 'https://api.openai.com/v1', api_key='fake')
    assert constructed == []
    complete([{'role': 'user', 'content': 'Hello'}])
    assert constructed[0]['max_retries'] == 0
    assert constructed[0]['timeout'] == 30.0


def test_real_sdk_decodes_response_without_network():
    import httpx
    from openai import OpenAI

    def respond(request):
        assert request.url.path == '/v1/chat/completions'
        return httpx.Response(200, json={
            'id': 'synthetic', 'object': 'chat.completion', 'created': 1,
            'model': 'gpt-4.1-mini-2025-04-14',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'hello'},
                         'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 5, 'total_tokens': 25,
                      'prompt_tokens_details': {'cached_tokens': 4}},
        })

    client = OpenAI(api_key='test-only', max_retries=0,
                    http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    complete = Completer('target', 'gpt-4.1-mini-2025-04-14',
                        'https://api.openai.com/v1', client=client)
    try:
        assert complete([{'role': 'user', 'content': 'Hello'}]) == 'hello'
        assert complete.calls[0]['cached_input_tokens'] == 4
    finally:
        complete.close()
