"""Component — declarative component base class for the Python Ink renderer.

Replaces React reconciler with a simple Python component model.
Components have render() returning child nodes, and reactive state.
"""

from __future__ import annotations

from typing import Any, Callable

from .dom import DOMElement, DOMNode, NodeType, TextNode, create_element, create_text


class Component:
    """Base class for declarative UI components.

    Subclass and implement render() to return a DOM subtree.
    Call set_state() to trigger re-render.
    """

    def __init__(self) -> None:
        self._node: DOMElement = create_element(NodeType.BOX)
        self._mounted = False
        self._app: "InkApp | None" = None
        self._children: list[Component] = []

    @property
    def node(self) -> DOMElement:
        return self._node

    def render(self) -> list[DOMNode]:
        """Override to return child DOM nodes for this component."""
        return []

    def mount(self, app: "InkApp") -> None:
        """Called when component is added to the tree."""
        self._app = app
        self._mounted = True
        self._reconcile()

    def unmount(self) -> None:
        """Called when component is removed from the tree."""
        self._mounted = False
        self._app = None

    def set_state(self, **kwargs: Any) -> None:
        """Update component state and trigger re-render."""
        for k, v in kwargs.items():
            setattr(self, k, v)
        if self._mounted and self._app:
            self._reconcile()
            self._app.schedule_render()

    def _reconcile(self) -> None:
        """Rebuild the DOM subtree from render()."""
        self._node.clear_children()
        children = self.render()
        for child in children:
            self._node.append_child(child)


# TYPE_CHECKING import to avoid circular deps at runtime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import InkApp
