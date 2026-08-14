"""Configuration for the Streamlit testing environment."""

from dataclasses import dataclass, field


@dataclass
class TestingConfig:
    """Holds all sidebar configuration state."""
    provider: str = "gemini"                  # LLM provider name
    prompt_path: str = "prompt.md"            # path to prompt file
    user_registered: bool = True              # simulate registered user
    phone: str = "5491112345678"              # simulated phone number
    user_name: str = "Test User"              # simulated user name
    debug_json: bool = True                   # show raw LLM JSON
    debug_latency: bool = True                # show latency metrics
    debug_redis: bool = True                  # show Redis state
    debug_logs: bool = True                   # show dispatcher logs


@dataclass
class ChatMessage:
    """A single message in the chat history."""
    role: str                                 # "user" | "assistant"
    content: str                              # visible text
    debug: dict = field(default_factory=dict) # debug metadata (assistant only)
