"""
Framework integrations for JarvisCore.

Provides first-class support for popular web frameworks,
reducing boilerplate for production deployments.

Available integrations:
- FastAPI: JarvisLifespan, create_jarvis_app
"""

try:
    from .fastapi import JarvisLifespan, create_jarvis_app
    __all__ = ['JarvisLifespan', 'create_jarvis_app']
except ImportError:
    # FastAPI not installed - integrations not available
    __all__ = []
