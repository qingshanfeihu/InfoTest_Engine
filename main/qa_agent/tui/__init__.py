"""IST-Core Textual TUI package.

Architecture mapping (React/Ink -> Python/Textual):
  React Component        -> Textual Widget
  React Context          -> Textual reactive
  React state hook       -> Widget reactive field
  Ink event dispatcher   -> Textual Message + post_message
  Ink ModalScreen        -> Textual ModalScreen
  Ink frame buffer       -> Textual native screen render
"""

from main.qa_agent.tui.messages import IstMessage  # re-export for callers

__all__ = ["IstMessage"]
