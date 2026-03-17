"""Ollama / OpenAI API ?????????"""

from .api_client_openai import _ApiClientOpenAIMixin
from .api_client_ollama import _ApiClientOllamaMixin


class _ApiClientMixin(_ApiClientOpenAIMixin, _ApiClientOllamaMixin):
    """?? API ???????OpenAI ?? + Ollama??"""
