"""兼容入口：``python -m main.ist_core.tui``。

Real entry is ``cli.main()``. infotest console_script 也指向同一函数。
"""

from main.ist_core.tui.cli import main


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
