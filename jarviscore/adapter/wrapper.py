"""
wrap() function - Wrap an existing instance as a JarvisCore agent.

Alternative to @jarvis_agent decorator when you have an existing instance
rather than a class definition.

Example:
    from jarviscore import wrap, Mesh

    # Your existing agent instance
    my_langchain_agent = LangChainAgent(llm=my_llm)

    # Wrap it for JarvisCore
    wrapped = wrap(
        my_langchain_agent,
        role="researcher",
        capabilities=["research", "analysis"],
        execute_method="invoke"
    )

    mesh = Mesh(mode="autonomous")
    mesh.add(wrapped)
    await mesh.start()
"""
from typing import List, Optional, Any
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


def detect_execute_method(instance: Any) -> Optional[str]:
    """
    Auto-detect the execute method on an instance.

    Args:
        instance: Object instance to inspect

    Returns:
        Method name or None if not found
    """
    for method_name in EXECUTE_METHODS:
        if hasattr(instance, method_name):
            attr = getattr(instance, method_name)
            if callable(attr) and method_name != '__call__':
                return method_name
            elif method_name == '__call__':
                # Check if __call__ is defined on the class itself
                for klass in type(instance).__mro__:
                    if klass is object:
                        break
                    if '__call__' in klass.__dict__:
                        return method_name
    return None


def wrap(
    instance: Any,
    role: str,
    capabilities: List[str],
    execute_method: Optional[str] = None
) -> CustomAgent:
    """
    Wrap an existing instance as a JarvisCore agent.

    Use this when you have an already-instantiated object (like a LangChain
    agent or custom class instance) that you want to use with JarvisCore.

    Args:
        instance: The object instance to wrap
        role: Agent role identifier (used for step routing)
        capabilities: List of capabilities (used for step matching)
        execute_method: Method name to call for execution (auto-detected if not provided)

    Returns:
        A CustomAgent instance wrapping the original object

    Example:
        # Wrap a LangChain agent
        from langchain.agents import AgentExecutor

        langchain_agent = AgentExecutor(agent=my_agent, tools=my_tools)

        wrapped = wrap(
            langchain_agent,
            role="assistant",
            capabilities=["chat", "tools"],
            execute_method="invoke"
        )

        mesh.add(wrapped)

        # Wrap a simple Python object
        class MyProcessor:
            def run(self, data):
                return {"processed": data * 2}

        processor = MyProcessor()
        wrapped = wrap(processor, role="processor", capabilities=["processing"])

        # Wrap with context access
        class MyAggregator:
            def run(self, task, ctx: JarvisContext):
                prev = ctx.previous("step1")
                return {"aggregated": prev}

        aggregator = MyAggregator()
        wrapped = wrap(aggregator, role="aggregator", capabilities=["aggregation"])
    """
    # Detect execute method if not provided
    method_name = execute_method or detect_execute_method(instance)
    if not method_name:
        raise ValueError(
            f"Could not detect execute method on {type(instance).__name__}. "
            f"Please specify execute_method parameter or add one of: {EXECUTE_METHODS}"
        )

    # Verify method exists
    if not hasattr(instance, method_name):
        raise ValueError(
            f"{type(instance).__name__} has no method '{method_name}'"
        )

    # Check if method expects context parameter
    method = getattr(instance, method_name)
    sig = inspect.signature(method)
    params = list(sig.parameters.keys())

    # Remove 'self' from params (shouldn't be there for bound methods, but just in case)
    if params and params[0] == 'self':
        params = params[1:]

    expects_context = 'ctx' in params or 'context' in params

    logger.debug(
        f"Wrapping instance {type(instance).__name__}: method={method_name}, "
        f"expects_context={expects_context}, params={params}"
    )

    # Create a CustomAgent subclass dynamically
    class WrappedInstanceAgent(CustomAgent):
        """Agent wrapping an existing instance via wrap()."""
        pass

    # Set class attributes
    WrappedInstanceAgent.role = role
    WrappedInstanceAgent.capabilities = capabilities

    # Store metadata
    WrappedInstanceAgent._wrapped_instance = instance
    WrappedInstanceAgent._execute_method = method_name
    WrappedInstanceAgent._expects_context = expects_context
    WrappedInstanceAgent._original_params = params

    # Create the agent instance
    agent = WrappedInstanceAgent.__new__(WrappedInstanceAgent)

    # Initialize CustomAgent parts
    CustomAgent.__init__(agent)

    # Store the wrapped instance
    agent._instance = instance

    # Override execute_task
    async def execute_task(self, task: dict) -> dict:
        """Execute by calling the wrapped instance's method."""
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

        # Prepare arguments
        args = _prepare_args(task, ctx, params)

        # Call the method
        try:
            result = method(*args)

            # Handle async methods
            if inspect.isawaitable(result):
                result = await result

        except Exception as e:
            logger.error(f"Error in {type(instance).__name__}.{method_name}: {e}")
            return {
                'status': 'failure',
                'error': str(e),
                'agent': self.agent_id
            }

        # Normalize result
        return _normalize_result(self, result)

    # Bind the method to the agent
    import types
    agent.execute_task = types.MethodType(execute_task, agent)

    # Copy class name for better debugging
    WrappedInstanceAgent.__name__ = f"Wrapped_{type(instance).__name__}"
    WrappedInstanceAgent.__qualname__ = f"Wrapped_{type(instance).__name__}"

    logger.debug(f"Created wrapped agent: role={role}, instance={type(instance).__name__}")

    return agent


def _prepare_args(task: dict, ctx: Optional[JarvisContext], param_names: List[str]) -> tuple:
    """Prepare arguments for the wrapped method."""
    args = []

    task_params = task.get('params', {})
    params_is_dict = isinstance(task_params, dict)

    for param in param_names:
        if param in ('ctx', 'context'):
            args.append(ctx)
        elif param == 'task':
            args.append(task.get('task', task))
        elif param == 'data':
            if params_is_dict:
                args.append(task_params.get('data', task_params))
            else:
                args.append(task_params)
        elif param == 'params':
            args.append(task_params)
        elif param in ('input', 'query', 'text', 'message'):
            if params_is_dict:
                args.append(task.get('task', task_params.get(param, '')))
            else:
                args.append(task.get('task', task_params))
        else:
            if params_is_dict and param in task_params:
                args.append(task_params[param])
            elif param in task:
                args.append(task[param])
            else:
                args.append(task_params)
                break

    if not args:
        if 'params' in task:
            args.append(task_params)
        else:
            args.append(task)

    return tuple(args)


def _normalize_result(agent: CustomAgent, result: Any) -> dict:
    """Normalize result to expected format."""
    if isinstance(result, dict):
        if 'status' not in result:
            return {
                'status': 'success',
                'output': result,
                'agent': agent.agent_id
            }
        if 'agent' not in result:
            result['agent'] = agent.agent_id
        return result
    else:
        return {
            'status': 'success',
            'output': result,
            'agent': agent.agent_id
        }
