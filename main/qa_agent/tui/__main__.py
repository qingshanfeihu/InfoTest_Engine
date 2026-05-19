"""兼容入口：``python -m main.qa_agent.tui``。

Real entry is ``cli.main()``. infotest console_script 也指向同一函数。
"""

from main.qa_agent.tui.cli import main


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
