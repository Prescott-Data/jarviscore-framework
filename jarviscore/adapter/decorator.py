"""
@jarvis_agent decorator - Convert any class into a JarvisCore agent.

Wraps existing classes (LangChain, CrewAI, raw Python) to work with
JarvisCore orchestration without requiring them to inherit from CustomAgent.
"""
from typing import List, Optional, Type, Any
import inspect
import logging

from jarviscore.profiles.customagent import CustomAgent
from jarviscore.context import JarvisContext, create_context

logger = logging.getLogger(__name__)


# Common method names to auto-detect
EXECUTE_METHODS = [
    "run",           # Most common
    "invoke",        # LangChain
    "execute",       # Generic
    "call",          # Callable pattern
    "__call__",      # Callable objects
    "process",       # Processing agents
    "handle",        # Handler pattern
]


def detect_execute_method(cls: Type) -> Optional[str]:
    """
    Auto-detect the execute method on a class.

    Checks for common method names in order of preference.
    Only detects methods defined on the class itself, not inherited
    from object (like __call__ from type).

    Args:
        cls: Class to inspect

    Returns:
        Method name or None if not found
    """
    for method_name in EXECUTE_METHODS:
        # Check if method is defined on the class itself (not inherited from object)
        # We walk the MRO but stop before 'object'
        for klass in cls.__mro__:
            if klass is object:
                break
            if method_name in klass.__dict__:
                attr = getattr(cls, method_name)
                if callable(attr):
                    return method_name
                break
    return None


def jarvis_agent(
    role: str,
    capabilities: List[str],
    execute_method: Optional[str] = None
):
    """
    Decorator to convert any class into a JarvisCore agent.

    The decorated class can use any framework (LangChain, CrewAI, raw Python).
    JarvisCore provides orchestration (data handoff, dependencies, memory).

    Args:
        role: Agent role identifier (used for step routing)
        capabilities: List of capabilities (used for step matching)
        execute_method: Method name to call for execution (auto-detected if not provided)

    Returns:
        Wrapped class that extends CustomAgent

    Example:
        # Simple agent
        @jarvis_agent(role="processor", capabilities=["data_processing"])
        class DataProcessor:
            def run(self, data):
                return {"processed": data * 2}

        # Agent with context access
        @jarvis_agent(role="aggregator", capabilities=["aggregation"])
        class Aggregator:
            def run(self, task, ctx: JarvisContext):
                prev = ctx.previous("step1")
                return {"result": prev}

        # Agent with custom method name
        @jarvis_agent(role="researcher", capabilities=["research"], execute_method="invoke")
        class Researcher:
            def invoke(self, query):
                return {"findings": search(query)}

    Usage:
        mesh = Mesh(mode="autonomous")
        mesh.add(DataProcessor)
        await mesh.start()
        results = await mesh.workflow("pipeline", [...])
    """
    def decorator(cls: Type) -> Type:
        # Detect execute method if not provided
        method_name = execute_method or detect_execute_method(cls)
        if not method_name:
            raise ValueError(
                f"Could not detect execute method on {cls.__name__}. "
                f"Please specify execute_method parameter or add one of: {EXECUTE_METHODS}"
            )

        # Verify method exists
        if not hasattr(cls, method_name):
            raise ValueError(
                f"{cls.__name__} has no method '{method_name}'"
            )

        # Check if method expects context parameter
        method = getattr(cls, method_name)
        sig = inspect.signature(method)
        params = list(sig.parameters.keys())

        # Remove 'self' from params
        if params and params[0] == 'self':
            params = params[1:]

        expects_context = 'ctx' in params or 'context' in params

        logger.debug(
            f"Wrapping {cls.__name__}: method={method_name}, "
            f"expects_context={expects_context}, params={params}"
        )

        # Create wrapped CustomAgent subclass
        class WrappedAgent(CustomAgent):
            """Wrapped agent created by @jarvis_agent decorator."""

            # Override class attributes from decorator
            # (Can't use nonlocal role/capabilities directly due to scoping)
            pass

        # Set class attributes (must do this after class creation)
        WrappedAgent.role = role
        WrappedAgent.capabilities = capabilities

        # Store metadata for introspection
        WrappedAgent._wrapped_class = cls
        WrappedAgent._execute_method = method_name
        WrappedAgent._expects_context = expects_context
        WrappedAgent._original_params = params

        # Override __init__
        original_init = WrappedAgent.__init__

        def new_init(self, agent_id=None, **kwargs):
            # Call CustomAgent init
            CustomAgent.__init__(self, agent_id)

            # Instantiate the wrapped class
            try:
                self._instance = cls(**kwargs) if kwargs else cls()
            except TypeError:
                # Class might not accept kwargs
                self._instance = cls()

            self._logger.debug(f"Created wrapped instance of {cls.__name__}")

        WrappedAgent.__init__ = new_init

        # Override setup
        async def new_setup(self):
            await CustomAgent.setup(self)

            # Call wrapped class setup if it exists
            if hasattr(self._instance, 'setup'):
                setup_fn = self._instance.setup
                if inspect.iscoroutinefunction(setup_fn):
                    await setup_fn()
                else:
                    setup_fn()

            self._logger.debug(f"Setup complete for wrapped {cls.__name__}")

        WrappedAgent.setup = new_setup

        # Override execute_task
        async def new_execute_task(self, task: dict) -> dict:
            """Execute by calling the wrapped class's method."""
            # Get the execute method from instance
            method = getattr(self._instance, method_name)

            # Get context if method expects it
            ctx = None
            if expects_context:
                # Use pre-injected context from WorkflowEngine if available
                ctx = task.get('_jarvis_context')

                # Fallback: build context manually (for standalone usage)
                if ctx is None:
                    memory_dict = {}
                    dep_manager = None

                    if self._mesh:
                        engine = getattr(self._mesh, '_workflow_engine', None)
                        if engine:
                            memory_dict = engine.memory
                            dep_manager = getattr(engine, 'dependency_manager', None)

                    ctx = create_context(
                        workflow_id=task.get('context', {}).get('workflow_id', 'unknown'),
                        step_id=task.get('context', {}).get('step_id', task.get('id', 'unknown')),
                        task=task.get('task', ''),
                        params=task.get('params', {}),
                        memory_dict=memory_dict,
                        dependency_manager=dep_manager
                    )

            # Prepare arguments based on method signature
            args = self._prepare_args(task, ctx, params)

            # Call the method
            try:
                result = method(*args)

                # Handle async methods
                if inspect.isawaitable(result):
                    result = await result

            except Exception as e:
                self._logger.error(f"Error in {cls.__name__}.{method_name}: {e}")
                return {
                    'status': 'failure',
                    'error': str(e),
                    'agent': self.agent_id
                }

            # Normalize result to expected format
            return self._normalize_result(result)

        WrappedAgent.execute_task = new_execute_task

        # Helper to prepare arguments
        def prepare_args(self, task: dict, ctx: Optional[JarvisContext], param_names: List[str]) -> tuple:
            """Prepare arguments for the wrapped method."""
            args = []

            # Get params, handling both dict and non-dict cases
            task_params = task.get('params', {})
            params_is_dict = isinstance(task_params, dict)

            for param in param_names:
                if param in ('ctx', 'context'):
                    args.append(ctx)
                elif param == 'task':
                    args.append(task.get('task', task))
                elif param == 'data':
                    # Try to get data from params or context
                    if params_is_dict:
                        args.append(task_params.get('data', task_params))
                    else:
                        args.append(task_params)
                elif param == 'params':
                    args.append(task_params)
                elif param in ('input', 'query', 'text', 'message'):
                    # Common input parameter names
                    if params_is_dict:
                        args.append(task.get('task', task_params.get(param, '')))
                    else:
                        args.append(task.get('task', task_params))
                else:
                    # Try to get from params, fall back to task dict
                    if params_is_dict and param in task_params:
                        args.append(task_params[param])
                    elif param in task:
                        args.append(task[param])
                    else:
                        # Pass whole params as fallback
                        args.append(task_params)
                        break  # Only do this once

            # If no args were determined, pass the task/params
            if not args:
                if 'params' in task:
                    args.append(task_params)
                else:
                    args.append(task)

            return tuple(args)

        WrappedAgent._prepare_args = prepare_args

        # Helper to normalize result
        def normalize_result(self, result: Any) -> dict:
            """Normalize result to expected format."""
            if isinstance(result, dict):
                if 'status' not in result:
                    return {
                        'status': 'success',
                        'output': result,
                        'agent': self.agent_id
                    }
                if 'agent' not in result:
                    result['agent'] = self.agent_id
                return result
            else:
                return {
                    'status': 'success',
                    'output': result,
                    'agent': self.agent_id
                }

        WrappedAgent._normalize_result = normalize_result

        # Override teardown
        async def new_teardown(self):
            # Call wrapped class teardown if it exists
            if hasattr(self._instance, 'teardown'):
                teardown_fn = self._instance.teardown
                if inspect.iscoroutinefunction(teardown_fn):
                    await teardown_fn()
                else:
                    teardown_fn()

            await CustomAgent.teardown(self)
            self._logger.debug(f"Teardown complete for wrapped {cls.__name__}")

        WrappedAgent.teardown = new_teardown

        # Copy class metadata
        WrappedAgent.__name__ = cls.__name__
        WrappedAgent.__qualname__ = cls.__qualname__
        WrappedAgent.__doc__ = cls.__doc__ or f"Wrapped agent from {cls.__name__}"
        WrappedAgent.__module__ = cls.__module__

        return WrappedAgent

    return decorator
