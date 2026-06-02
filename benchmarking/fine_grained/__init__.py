"""Fine-grained PPT corruption benchmark generation."""

from .common import save_yaml


def __getattr__(name: str):
    """Lazily import heavier generation entrypoints."""
    if name == "build_corruption":
        from .mutations import build_corruption

        return build_corruption
    if name in {"main", "write_corruption_outputs"}:
        from .runner import main, write_corruption_outputs

        return {"main": main, "write_corruption_outputs": write_corruption_outputs}[name]
    raise AttributeError(name)

__all__ = [
    "build_corruption",
    "main",
    "save_yaml",
    "write_corruption_outputs",
]
