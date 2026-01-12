"""
Execution Engine - Complete code generation and execution pipeline

Zero-config components:
- UnifiedLLMClient: Multi-provider LLM (vLLM, Azure, Gemini, Claude)
- InternetSearch: Web search and content extraction (DuckDuckGo)
- CodeGenerator: Natural language → Python code
- SandboxExecutor: Safe code execution with limits
- AutonomousRepair: Automatic error fixing

Everything works out of the box - just pass config dict.
"""

# LLM Client
from .llm import (
    UnifiedLLMClient,
    LLMProvider,
    TOKEN_PRICING,
    create_llm_client
)

# Internet Search
from .search import (
    InternetSearch,
    create_search_client
)

# Code Generator
from .generator import (
    CodeGenerator,
    create_code_generator
)

# Sandbox Executor
from .sandbox import (
    SandboxExecutor,
    ExecutionTimeout,
    create_sandbox_executor
)

# Autonomous Repair
from .repair import (
    AutonomousRepair,
    create_autonomous_repair
)

# Result Handler
from .result_handler import (
    ResultHandler,
    ResultStatus,
    ErrorCategory,
    create_result_handler
)

# Code Registry
from .code_registry import (
    CodeRegistry,
    create_code_registry
)

__all__ = [
    # LLM
    'UnifiedLLMClient',
    'LLMProvider',
    'TOKEN_PRICING',
    'create_llm_client',

    # Search
    'InternetSearch',
    'create_search_client',

    # Generator
    'CodeGenerator',
    'create_code_generator',

    # Sandbox
    'SandboxExecutor',
    'ExecutionTimeout',
    'create_sandbox_executor',

    # Repair
    'AutonomousRepair',
    'create_autonomous_repair',

    # Result Handler
    'ResultHandler',
    'ResultStatus',
    'ErrorCategory',
    'create_result_handler',

    # Code Registry
    'CodeRegistry',
    'create_code_registry',
]
