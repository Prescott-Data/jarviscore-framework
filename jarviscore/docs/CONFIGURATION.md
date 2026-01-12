# JarvisCore Configuration Guide

Complete guide to configuring JarvisCore framework.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Environment Variables](#environment-variables)
3. [LLM Configuration](#llm-configuration)
4. [Sandbox Configuration](#sandbox-configuration)
5. [Storage Configuration](#storage-configuration)
6. [P2P Configuration](#p2p-configuration)
7. [Execution Settings](#execution-settings)
8. [Logging Configuration](#logging-configuration)
9. [Configuration Examples](#configuration-examples)
10. [Troubleshooting](#troubleshooting)

---

## Quick Start

JarvisCore uses environment variables for configuration with sensible defaults.

### Zero-Config Mode

No configuration required! Just install and run:

```python
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

mesh = Mesh()
# Uses default settings, tries to detect LLM providers
```

### Basic Configuration

Create a `.env` file in your project root:

```bash
# Minimal configuration
CLAUDE_API_KEY=your-anthropic-api-key
```

That's it! The framework handles the rest.

---

## Environment Variables

### Configuration File

Create `.env` file:

```bash
cp .env.example .env
# Edit .env with your values
```

### Standard Names (No Prefix)

JarvisCore uses standard environment variable names without prefixes:

```bash
# Good
CLAUDE_API_KEY=...
AZURE_API_KEY=...

# Not used (old format)
JARVISCORE_CLAUDE_API_KEY=...
```

---

## LLM Configuration

Configure language model providers. The framework tries them in order:
**Claude → vLLM → Azure → Gemini**

### Anthropic Claude (Recommended)

```bash
# Standard Anthropic API
CLAUDE_API_KEY=sk-ant-...

# Optional: Custom endpoint (Azure Claude, etc.)
CLAUDE_ENDPOINT=https://api.anthropic.com 

# Optional: Model selection
CLAUDE_MODEL=claude-model  # or claude-opus-4, claude-haiku-3.5
```

**Get API Key:** https://console.anthropic.com/

### vLLM (Self-Hosted)

Recommended for cost-effective production:

```bash
# vLLM server endpoint
LLM_ENDPOINT=http://localhost:8000

# Model name
LLM_MODEL=LLM-model
```

**Setup vLLM:**
```bash
# Install vLLM
pip install vllm

# Start server
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-Coder-32B-Instruct \
    --port 8000
```

### Azure OpenAI

```bash
AZURE_API_KEY=your-azure-key
AZURE_ENDPOINT=https://your-resource.openai.azure.com
AZURE_DEPLOYMENT=gpt-4o
AZURE_API_VERSION=2025-01-01-preview
```

**Get Started:** 

### Google Gemini

```bash
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-2.0-flash
GEMINI_TEMPERATURE=0.1
GEMINI_TIMEOUT=30.0
```

**Get API Key:** https://ai.google.dev/

### Common LLM Settings

```bash
# Request timeout (seconds)
LLM_TIMEOUT=120.0

# Sampling temperature (0.0 - 1.0)
LLM_TEMPERATURE=0.7
```

### Provider Selection

The framework automatically selects providers:

1. **Tries Claude first** (if CLAUDE_API_KEY set)
2. **Falls back to vLLM** (if LLM_ENDPOINT set)
3. **Falls back to Azure** (if AZURE_API_KEY set)
4. **Falls back to Gemini** (if GEMINI_API_KEY set)

You only need to configure ONE provider.

---

## Sandbox Configuration

Configure code execution environment.

### Local Mode (Default)

In-process execution, fast, for development:

```bash
SANDBOX_MODE=local
```

No additional configuration needed.

### Remote Mode (Production)

Azure Container Apps sandbox service:

```bash
SANDBOX_MODE=remote
SANDBOX_SERVICE_URL=https://browser-task-executor.bravesea-3f5f7e75.eastus.azurecontainerapps.io
```

**Features:**
- Full process isolation
- Better security
- Hosted by JarvisCore (no setup required)
- Automatic fallback to local

**When to use:**
- Production deployments
- Untrusted code execution
- Multi-tenant systems
- High security requirements

### Sandbox Timeout

```bash
# Maximum execution time (seconds)
EXECUTION_TIMEOUT=300  # 5 minutes (default)
```

---

## Storage Configuration

Configure result storage and code registry.

### Storage Directory

```bash
# Base directory for logs and results
LOG_DIRECTORY=./logs
```

### Storage Structure

```
logs/
├── {agent_id}/           # Agent results
│   └── {result_id}.json
└── code_registry/        # Registered functions
    ├── index.json
    └── functions/
        └── {function_id}.py
```

### Result Storage

Results are automatically stored:
- **File storage**: Persistent JSON files
- **In-memory cache**: LRU cache (1000 results)
- **Zero dependencies**: No Redis, no database

### Code Registry

Generated code is automatically registered:
- **Searchable**: Find functions by keywords/capabilities
- **Reusable**: Share code between agents
- **Auditable**: Track all generated code

---

## P2P Configuration

Configure distributed mesh networking (optional).

### Enable P2P

```bash
# Enable P2P mesh
P2P_ENABLED=true

# Node identification
NODE_NAME=jarviscore-node-1
```

### Network Settings

```bash
# Bind address and port
BIND_HOST=0.0.0.0      # Listen on all interfaces
BIND_PORT=7946         # SWIM protocol port

# Seed nodes (comma-separated)
SEED_NODES=192.168.1.100:7946,192.168.1.101:7946
```

### Transport Configuration

```bash
# ZeroMQ port offset
ZMQ_PORT_OFFSET=1000   # ZMQ will use BIND_PORT + 1000

# Transport type
TRANSPORT_TYPE=hybrid  # udp, tcp, or hybrid
```

### Keepalive Settings

```bash
# Enable smart keepalive
KEEPALIVE_ENABLED=true

# Keepalive interval (seconds)
KEEPALIVE_INTERVAL=90

# Keepalive timeout (seconds)
KEEPALIVE_TIMEOUT=10

# Activity suppression window (seconds)
ACTIVITY_SUPPRESS_WINDOW=60
```

### When to Use P2P

**Use P2P (distributed mode) when:**
- Running agents across multiple machines
- Need high availability
- Load balancing required
- Geographic distribution

**Don't use P2P (autonomous mode) when:**
- Single machine deployment
- Development/testing
- Simple workflows
- Getting started

---

## Execution Settings

### Repair Attempts

```bash
# Maximum autonomous repair attempts
MAX_REPAIR_ATTEMPTS=3  # Default
```

When code execution fails, AutoAgent attempts to fix it automatically.

### Retry Settings

```bash
# Maximum retries for failed operations
MAX_RETRIES=3  # Default
```

Applies to LLM calls, HTTP requests, etc.

### Timeout Configuration

```bash
# Code execution timeout
EXECUTION_TIMEOUT=300  # 5 minutes (default)

# LLM request timeout
LLM_TIMEOUT=120  # 2 minutes (default)
```

---

## Logging Configuration

### Log Level

```bash
# Log verbosity
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

### Log Formats

**Development:**
```bash
LOG_LEVEL=DEBUG
```

**Production:**
```bash
LOG_LEVEL=INFO
```

### Python Logging

```python
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Get logger
logger = logging.getLogger('jarviscore')
logger.setLevel(logging.DEBUG)
```

---

## Configuration Examples

### Example 1: Local Development

```bash
# .env
CLAUDE_API_KEY=sk-ant-...
SANDBOX_MODE=local
LOG_LEVEL=DEBUG
P2P_ENABLED=false
```

**Use case:** Rapid prototyping, testing

### Example 2: vLLM Production

```bash
# .env
LLM_ENDPOINT=http://localhost:8000
LLM_MODEL=Qwen/Qwen2.5-Coder-32B-Instruct
SANDBOX_MODE=remote
SANDBOX_SERVICE_URL=https://browser-task-executor...
LOG_LEVEL=INFO
LOG_DIRECTORY=/var/log/jarviscore
P2P_ENABLED=false
```

**Use case:** Cost-effective single-node production

### Example 3: Azure OpenAI with P2P

```bash
# .env
AZURE_API_KEY=...
AZURE_ENDPOINT=https://my-resource.openai.azure.com
AZURE_DEPLOYMENT=gpt-4o
AZURE_API_VERSION=2025-01-01-preview

SANDBOX_MODE=remote
SANDBOX_SERVICE_URL=https://browser-task-executor...

P2P_ENABLED=true
BIND_HOST=0.0.0.0
BIND_PORT=7946
SEED_NODES=192.168.1.100:7946,192.168.1.101:7946

LOG_LEVEL=INFO
LOG_DIRECTORY=/var/log/jarviscore
```

**Use case:** Enterprise distributed deployment

### Example 4: Multi-Provider Fallback

```bash
# .env
# Primary: Claude
CLAUDE_API_KEY=sk-ant-...

# Fallback 1: Azure
AZURE_API_KEY=...
AZURE_ENDPOINT=https://...
AZURE_DEPLOYMENT=gpt-4o

# Fallback 2: Gemini
GEMINI_API_KEY=...

SANDBOX_MODE=local
LOG_LEVEL=INFO
```

**Use case:** High availability with provider redundancy

### Example 5: Zero-Config

```bash
# .env
# Empty file or just:
CLAUDE_API_KEY=sk-ant-...
```

Everything else uses defaults. Perfect for getting started!

---

## Environment-Specific Configuration

### Development

```bash
# .env.development
CLAUDE_API_KEY=...
SANDBOX_MODE=local
LOG_LEVEL=DEBUG
P2P_ENABLED=false
EXECUTION_TIMEOUT=60
MAX_REPAIR_ATTEMPTS=1
```

### Staging

```bash
# .env.staging
AZURE_API_KEY=...
AZURE_ENDPOINT=...
SANDBOX_MODE=remote
SANDBOX_SERVICE_URL=https://...
LOG_LEVEL=INFO
P2P_ENABLED=true
EXECUTION_TIMEOUT=300
```

### Production

```bash
# .env.production
LLM_ENDPOINT=http://vllm-service:8000
SANDBOX_MODE=remote
SANDBOX_SERVICE_URL=https://...
LOG_LEVEL=WARNING
LOG_DIRECTORY=/var/log/jarviscore
P2P_ENABLED=true
BIND_HOST=0.0.0.0
EXECUTION_TIMEOUT=600
MAX_REPAIR_ATTEMPTS=3
```

### Load Configuration

```python
import os
from jarviscore import Mesh

# Set environment
env = os.getenv('ENVIRONMENT', 'development')

# Load config file
from dotenv import load_dotenv
load_dotenv(f'.env.{env}')

# Create mesh
mesh = Mesh()
```

---

## Programmatic Configuration

Override environment variables in code:

```python
from jarviscore import Mesh

config = {
    'sandbox_mode': 'remote',
    'sandbox_service_url': 'https://...',
    'execution_timeout': 600,
    'log_level': 'DEBUG'
}

mesh = Mesh(mode="autonomous", config=config)
```

**Note:** Programmatic config overrides environment variables.

---

## Validation

### Check Configuration

```python
from jarviscore.config import settings

# Print current settings
print(f"Sandbox Mode: {settings.sandbox_mode}")
print(f"Log Directory: {settings.log_directory}")
print(f"Claude Key: {'Set' if settings.claude_api_key else 'Not set'}")
```

### Verify LLM Providers

```python
from jarviscore.execution import create_llm_client

llm = create_llm_client()

# Test generation
response = await llm.generate("Hello")
print(f"Provider: {response['provider']}")
print(f"Model: {response['model']}")
```

---

## Security Best Practices

### 1. Never Commit .env Files

```bash
# .gitignore
.env
.env.*
!.env.example
```

### 2. Use Secret Management

**Development:**
```bash
# .env file (gitignored)
CLAUDE_API_KEY=...
```

**Production:**
```bash
# AWS Secrets Manager
aws secretsmanager get-secret-value --secret-id jarviscore/claude-key

# Azure Key Vault
az keyvault secret show --vault-name myvault --name claude-key

# Kubernetes Secrets
kubectl create secret generic jarviscore-secrets \
    --from-literal=CLAUDE_API_KEY=...
```

### 3. Restrict File Permissions

```bash
chmod 600 .env
```

### 4. Use Remote Sandbox in Production

```bash
# Production
SANDBOX_MODE=remote  # Better isolation

# Development
SANDBOX_MODE=local   # Faster iteration
```

### 5. Rotate API Keys Regularly

Set up key rotation every 90 days.

---

## Troubleshooting

### Issue: Configuration not loading

**Solution:**
```python
# Ensure .env is in correct location
import os
print(os.getcwd())  # Should contain .env

# Manual load
from dotenv import load_dotenv
load_dotenv('.env')
```

### Issue: LLM provider not found

**Solution:**
```bash
# Check at least one provider is configured
echo $CLAUDE_API_KEY
echo $LLM_ENDPOINT
echo $AZURE_API_KEY
echo $GEMINI_API_KEY
```

### Issue: Sandbox connection failed

**Solution:**
```bash
# Test remote sandbox URL
curl -X POST https://browser-task-executor... \
    -H "Content-Type: application/json" \
    -d '{"STEP_DATA": {...}, "TASK_CODE_B64": "..."}'

# Fallback to local
SANDBOX_MODE=local
```

### Issue: P2P connection failed

**Solution:**
```bash
# Check firewall
sudo ufw allow 7946/tcp
sudo ufw allow 7946/udp
sudo ufw allow 8946/tcp  # ZMQ (BIND_PORT + 1000)

# Check seed nodes are reachable
nc -zv 192.168.1.100 7946
```

### Issue: Storage directory not writable

**Solution:**
```bash
# Create directory
mkdir -p ./logs

# Fix permissions
chmod 755 ./logs

# Or change location
LOG_DIRECTORY=/tmp/jarviscore-logs
```

---

## Configuration Reference

### All Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_API_KEY` | None | Anthropic API key |
| `CLAUDE_ENDPOINT` | https://api.anthropic.com | Claude API endpoint |
| `CLAUDE_MODEL` | claude-sonnet-4 | Claude model |
| `LLM_ENDPOINT` | None | vLLM server URL |
| `LLM_MODEL` | default | vLLM model name |
| `AZURE_API_KEY` | None | Azure OpenAI key |
| `AZURE_ENDPOINT` | None | Azure OpenAI endpoint |
| `AZURE_DEPLOYMENT` | None | Azure deployment name |
| `AZURE_API_VERSION` | 2024-02-15-preview | Azure API version |
| `GEMINI_API_KEY` | None | Google Gemini key |
| `GEMINI_MODEL` | gemini-1.5-flash | Gemini model |
| `LLM_TIMEOUT` | 120.0 | LLM timeout (seconds) |
| `LLM_TEMPERATURE` | 0.7 | Sampling temperature |
| `SANDBOX_MODE` | local | Execution mode |
| `SANDBOX_SERVICE_URL` | None | Remote sandbox URL |
| `EXECUTION_TIMEOUT` | 300 | Code timeout (seconds) |
| `MAX_REPAIR_ATTEMPTS` | 3 | Max repair attempts |
| `MAX_RETRIES` | 3 | Max retry attempts |
| `LOG_DIRECTORY` | ./logs | Storage directory |
| `LOG_LEVEL` | INFO | Log verbosity |
| `P2P_ENABLED` | false | Enable P2P mesh |
| `NODE_NAME` | jarviscore-node | Node identifier |
| `BIND_HOST` | 127.0.0.1 | P2P bind address |
| `BIND_PORT` | 7946 | P2P bind port |
| `SEED_NODES` | None | Seed nodes (CSV) |
| `ZMQ_PORT_OFFSET` | 1000 | ZMQ port offset |
| `TRANSPORT_TYPE` | hybrid | Transport type |
| `KEEPALIVE_ENABLED` | true | Enable keepalive |
| `KEEPALIVE_INTERVAL` | 90 | Keepalive interval |

---

## Next Steps

1. **Read the [User Guide](USER_GUIDE.md)** for practical examples
2. **Check the [API Reference](API_REFERENCE.md)** for detailed documentation
3. **Explore .env.example** for complete configuration template

---

## Version

Configuration Guide for JarvisCore v0.1.0

Last Updated: 2026-01-12
