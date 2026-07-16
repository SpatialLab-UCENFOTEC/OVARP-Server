"""
Open Virtual Agent Research Platform (OVARP) — Provider Base Classes

Defines abstract base classes for the three AI provider roles:
``BaseSTTProvider`` (speech-to-text), ``BaseLLMProvider`` (language model),
and ``BaseTTSProvider`` (text-to-speech). All concrete providers must
implement their respective interfaces.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any, Optional

class BaseSTTProvider(ABC):
    """
    Abstract Base Class for Speech-To-Text Providers.
    Takes binary audio data from the client and returns a transcribed string.
    """
    @abstractmethod
    async def transcribe(self, audio_data: bytes) -> str:
        """Process binary audio into text."""
        pass

class BaseLLMProvider(ABC):
    """
    Abstract Base Class for Large Language Models.
    Takes user prompt + system context (including dynamic spatial tools) 
    and streams responses back.
    """
    @abstractmethod
    async def generate_response(self, prompt: str, system_prompt: Optional[str] = None) -> AsyncGenerator[str, None]:
        """Generate a streaming text response from the model."""
        pass
        
    @abstractmethod
    async def generate_response_with_actions(self, prompt: str, system_prompt: Optional[str] = None, history: Optional[list] = None) -> tuple[str, Dict[str, Any]]:
        """
        Generate a text response alongside strict JSON tool calls (actions/emotions) 
        mapped from the dynamic configuration.
        Returns: (spoken_text, actions_dict)
        """
        pass

class BaseTTSProvider(ABC):
    """
    Abstract Base Class for Text-To-Speech Providers.
    Takes text and returns a stream of audio chunks to be piped into the XR client via ZMQ.
    """
    @abstractmethod
    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """Convert text into an asynchronous stream of binary audio chunks."""
        pass
