"""Provider request and response types, tool calling contracts, and token usage."""

from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field


class ToolParameter(BaseModel):
    type: str
    description: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    required: Optional[List[str]] = None


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: ToolParameter


class ToolCall(BaseModel):
    id: str
    function_name: str
    arguments_json: str


class ChatMessage(BaseModel):
    role: str  # 'system', 'user', 'assistant', 'tool'
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None


class CompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    tools: Optional[List[ToolDefinition]] = None
    temperature: float = 0.2
    max_tokens: Optional[int] = None
    stream: bool = False


class ModelUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class CompletionResponse(BaseModel):
    id: str
    model: str
    message: ChatMessage
    usage: ModelUsage
    finish_reason: str


class CompletionChunk(BaseModel):
    delta_content: Optional[str] = None
    delta_tool_calls: Optional[List[ToolCall]] = None
    finish_reason: Optional[str] = None


class EncryptedCredentials(BaseModel):
    provider_id: str
    ciphertext: str
    iv: str
    tag: str
