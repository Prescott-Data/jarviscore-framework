"""
Framework integrations for JarvisCore.

Provides first-class support for popular web frameworks,
reducing boilerplate for production deployments.

Available integrations:
- FastAPI: JarvisLifespan, create_jarvis_app
- Chat: create_chat_router (POST /chat + GET /chat/stream SSE)
"""

try:
    from .fastapi import JarvisLifespan, create_jarvis_app
    from .chat import create_chat_router
    __all__ = ["JarvisLifespan", "create_jarvis_app", "create_chat_router"]
except ImportError:
    # FastAPI not installed - integrations not available
    __all__ = []
