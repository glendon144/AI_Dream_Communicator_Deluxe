# ... existing imports ...
import json, typing as t, requests

# ... existing code ...

class AIInterface:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        default_temperature: float | None = None,
        max_tokens_default: int | None = None,
    ):
        # ... existing initialization ...
        self._tool_functions: t.Dict[str, t.Callable[..., t.Any]] = {}
        # ... rest of initialization ...

    def register_tool(self, function_name: str, function: t.Callable[..., t.Any]) -> None:
        """Register a callable function for tool execution."""
        self._tool_functions[function_name] = function

    def unregister_tool(self, function_name: str) -> None:
        """Remove a registered tool function."""
        if function_name in self._tool_functions:
            del self._tool_functions[function_name]

    def tool_fn(self, function_name: str, arguments: dict) -> str:
        """
        Execute a registered tool function with arguments.
        
        Args:
            function_name: Name of registered function
            arguments: Keyword arguments for the function
            
        Returns:
            String result (JSON-encoded if non-string)
        """
        if function_name not in self._tool_functions:
            raise ValueError(f"Tool '{function_name}' not registered")

        try:
            result = self._tool_functions[function_name](**arguments)
        except Exception as e:
            return f"Error: {str(e)}"
        
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False)
        except TypeError:
            return str(result)

    # ... existing methods ...
