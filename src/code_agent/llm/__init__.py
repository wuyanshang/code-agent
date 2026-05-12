from code_agent.config import ModelConfig
from code_agent.llm.base import BaseLLMClient
from code_agent.llm.mock import MockLLMClient
from code_agent.llm.openai_compatible import OpenAICompatibleClient
from code_agent.llm.tongyi import TongyiClient


def create_llm_client(config: ModelConfig) -> BaseLLMClient:
    if config.provider == "mock":
        return MockLLMClient()
    if config.provider == "tongyi":
        return TongyiClient(config)
    return OpenAICompatibleClient(config)
