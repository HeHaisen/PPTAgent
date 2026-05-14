"""PPTAgent: Generating and Evaluating Presentations Beyond Text-to-Slides.

This package provides tools to automatically generate presentations from documents,
following a two-phase approach of Analysis and Generation.

For more information, visit: https://github.com/icip-cas/PPTAgent
"""

__version__ = "1.0.2"
__author__ = "Hao Zheng"
__email__ = "wszh712811@gmail.com"


_LAZY_EXPORTS = {
    "PPTAgent": (".pptgen", "PPTAgent"),
    "PPTAgentServer": (".mcp_server", "PPTAgentServer"),
    "Document": (".document", "Document"),
    "Presentation": (".presentation", "Presentation"),
    "Config": (".utils", "Config"),
    "Language": (".utils", "Language"),
    "ModelManager": (".model_utils", "ModelManager"),
    "ImageLabler": (".multimodal", "ImageLabler"),
    "LLM": (".llms", "LLM"),
    "AsyncLLM": (".llms", "AsyncLLM"),
}


def __getattr__(name):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module_name, attr_name = _LAZY_EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value

__all__ = [
    "__version__",
    "__author__",
    "__email__",
    "PPTAgent",
    "PPTAgentServer",
    "Document",
    "Presentation",
    "Config",
    "Language",
    "ModelManager",
    "ImageLabler",
    "LLM",
    "AsyncLLM",
]
