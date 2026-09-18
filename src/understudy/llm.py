"""One bounded SDK call; ordinary imports and reports never construct clients."""

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


TARGET_MODEL = 'gpt-4.1-mini-2025-04-14'
SIMULATION_MODEL = 'deepseek-flash'


class CompletionError(RuntimeError):
    """A deliberately sanitized provider or completion error."""


class Completer:
    def __init__(self, role: str, model: str, base_url: str, *,
                 api_key: str | None = None, client: Any = None):
        self.role = role
        self.model = model
        self.base_url = base_url
        self._api_key = api_key
        self._client = client
        self.calls: list[dict[str, Any]] = []

    def __call__(self, messages: list[dict[str, str]], *,
                 json_output: bool = False) -> str:
        entry: dict[str, Any] = {
            'role': self.role, 'model': self.model, 'resolved_model': None,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'input_tokens': None, 'output_tokens': None,
            'cached_input_tokens': None, 'finish_reason': None, 'status': 'error',
        }
        self.calls.append(entry)
        try:
            if self._client is None:
                from openai import OpenAI
                self._client = OpenAI(api_key=self._api_key, base_url=self.base_url,
                                      timeout=30.0, max_retries=0)
            options: dict[str, Any] = {
                'model': self.model, 'messages': messages, 'max_tokens': 800,
            }
            if json_output:
                options['response_format'] = {'type': 'json_object'}
            if urlparse(self.base_url).hostname == 'api.deepseek.com':
                options['extra_body'] = {'thinking': {'type': 'disabled'}}
            result = self._client.chat.completions.create(**options)
            entry['resolved_model'] = result.model
            usage = result.usage
            if usage is not None:
                entry['input_tokens'] = usage.prompt_tokens
                entry['output_tokens'] = usage.completion_tokens
                details = getattr(usage, 'prompt_tokens_details', None)
                entry['cached_input_tokens'] = (
                    getattr(details, 'cached_tokens', None) if details is not None
                    else getattr(usage, 'prompt_cache_hit_tokens', None)
                )
            choice = result.choices[0]
            entry['finish_reason'] = choice.finish_reason
            if (choice.finish_reason != 'stop' or getattr(choice.message, 'refusal', None)
                    or not isinstance(choice.message.content, str)
                    or not choice.message.content.strip()):
                raise CompletionError('Completion was empty, refused, or truncated.')
            entry['status'] = 'complete'
            return choice.message.content
        except CompletionError:
            raise
        except Exception:
            raise CompletionError('Provider request failed; no automatic retry.') from None

    def close(self) -> None:
        if self._client is not None and hasattr(self._client, 'close'):
            self._client.close()
