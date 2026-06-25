"""Render — traverse DOM tree and write to Output/Screen.

Walks the DOM tree, applies layout rects, renders text and borders.
"""

from __future__ import annotations

from .dom import DOMElement, DOMNode, NodeType, Rect, TextNode
from .output import Output
from .screen import CharPool, StylePool


def render_tree(
    root: DOMElement,
    output: Output,
    char_pool: CharPool,
    style_pool: StylePool,
) -> None:
    """Render the entire DOM tree into the Output buffer."""
    _render_node(root, output, char_pool, style_pool, offset_x=0, offset_y=0)


def _render_node(
    node: DOMNode,
    output: Output,
    char_pool: CharPool,
    style_pool: StylePool,
    offset_x: int,
    offset_y: int,
) -> None:
    """Recursively render a node and its children."""
    if isinstance(node, TextNode):
        return

    if not isinstance(node, DOMElement):
        return

    if node.is_hidden or node.style.display == "none":
        return

    rect = node.rect
    abs_x = offset_x + rect.x
    abs_y = offset_y + rect.y

    
    if node.style.border_style:
        _render_border(node, output, style_pool, abs_x, abs_y)

    
    border_w = 1 if node.style.border_style else 0
    content_x = abs_x + node.style.padding_left + border_w
    content_y = abs_y + node.style.padding_top + border_w

    
    # 内容可用宽度(始终算):text 软换行行数据此定位下一个 child,必须和 output._apply_write
    # 的软换行、transcript._content_height_rows 的滚动高度用同一算法(wrapped_row_count)。
    content_w = rect.width - 2 * border_w - node.style.padding_left - node.style.padding_right

    clip_pushed = False
    viewport_h: int | None = None
    if node.style.overflow in ("hidden", "scroll"):
        content_h = rect.height - 2 * border_w - node.style.padding_top - node.style.padding_bottom
        output.push_clip(content_x, content_y, content_w, content_h)
        clip_pushed = True
        viewport_h = content_h


    scroll_offset = node.scroll_top if node.style.overflow == "scroll" else 0
    text_y_offset = 0
    for child in node.children:
        if isinstance(child, TextNode):
            # 软换行感知行数(缓存在节点上,大 transcript 不每帧重算 string_width)。
            rows = child.wrapped_rows(content_w)
            # 跳过完全在可视区外的行(仅裁剪容器):省掉屏外 write op + _apply_write 逐字符
            # 裁剪 —— 大 transcript 滚轮翻页才不卡。top = child 相对内容区顶部的起始行。
            top = text_y_offset - scroll_offset
            if viewport_h is None or (top + rows > 0 and top < viewport_h):
                _render_text(child, output, style_pool, content_x, content_y - scroll_offset + text_y_offset)
            text_y_offset += rows
        elif isinstance(child, DOMElement):
            _render_node(child, output, char_pool, style_pool, content_x, content_y - scroll_offset)
            text_y_offset = 0

    if clip_pushed:
        output.pop_clip()


def _render_text(
    node: TextNode,
    output: Output,
    style_pool: StylePool,
    x: int,
    y: int,
) -> None:
    """Render a text node at the given position."""
    if not node.value:
        return
    
    style_id = _resolve_text_style(node, style_pool)
    output.write(x, y, node.value, style_id)


def _resolve_text_style(node: DOMNode, style_pool: StylePool) -> int:
    """Walk up the parent chain to resolve inherited text styles into a style ID."""
    codes: list[str] = []
    current = node.parent
    while current is not None:
        ts = current.text_styles
        if ts.bold:
            codes.append("\x1b[1m")
        if ts.dim:
            codes.append("\x1b[2m")
        if ts.italic:
            codes.append("\x1b[3m")
        if ts.underline:
            codes.append("\x1b[4m")
        if ts.strikethrough:
            codes.append("\x1b[9m")
        if ts.inverse:
            codes.append("\x1b[7m")
        if ts.color:
            color_code = _named_color_to_sgr(ts.color, fg=True)
            if color_code:
                codes.append(color_code)
        if ts.background_color:
            color_code = _named_color_to_sgr(ts.background_color, fg=False)
            if color_code:
                codes.append(color_code)
        current = current.parent
    if not codes:
        return style_pool.none
    return style_pool.intern(codes)


_FG_COLORS = {
    "black": 30, "red": 31, "green": 32, "yellow": 33,
    "blue": 34, "magenta": 35, "cyan": 36, "white": 37,
    "gray": 90, "grey": 90,
}
_BG_COLORS = {
    "black": 40, "red": 41, "green": 42, "yellow": 43,
    "blue": 44, "magenta": 45, "cyan": 46, "white": 47,
}


def _named_color_to_sgr(color: str, *, fg: bool) -> str | None:
    """Convert a named color to an SGR code string."""
    table = _FG_COLORS if fg else _BG_COLORS
    code = table.get(color.lower())
    if code is not None:
        return f"\x1b[{code}m"
    if color.startswith("#") and len(color) == 7:
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        prefix = 38 if fg else 48
        return f"\x1b[{prefix};2;{r};{g};{b}m"
    return None



_BORDERS = {
    "single": ("┌", "┐", "└", "┘", "─", "│"),
    "double": ("╔", "╗", "╚", "╝", "═", "║"),
    "round": ("╭", "╮", "╰", "╯", "─", "│"),
    "bold": ("┏", "┓", "┗", "┛", "━", "┃"),
}


def _render_border(
    node: DOMElement,
    output: Output,
    style_pool: StylePool,
    x: int,
    y: int,
) -> None:
    """Render a box border around the node's rect."""
    bs = node.style.border_style or "single"
    chars = _BORDERS.get(bs, _BORDERS["single"])
    tl, tr, bl, br, h, v = chars
    w = node.rect.width
    ht = node.rect.height

    style_id = style_pool.none
    if node.style.border_color:
        code = _named_color_to_sgr(node.style.border_color, fg=True)
        if code:
            style_id = style_pool.intern([code])

    
    top_line = tl + h * (w - 2) + tr
    output.write(x, y, top_line, style_id)
    
    bottom_line = bl + h * (w - 2) + br
    output.write(x, y + ht - 1, bottom_line, style_id)
    
    for row in range(1, ht - 1):
        output.write(x, y + row, v, style_id)
        output.write(x + w - 1, y + row, v, style_id)
