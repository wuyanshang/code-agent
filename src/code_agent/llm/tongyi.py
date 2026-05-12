from __future__ import annotations

from code_agent.config import ModelConfig
from code_agent.llm.openai_compatible import OpenAICompatibleClient


class TongyiClient(OpenAICompatibleClient):
    def __init__(self, config: ModelConfig) -> None:
        super().__init__(config)
