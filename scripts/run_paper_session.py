#!/usr/bin/env python3
"""Paper CLI suspended until approved data and isolated session storage are wired.

The previous entry point supplied invented market signals to the default
portfolio database. Its original bytes are preserved for audit in
reports/paper-session-cli-before-review-20260914.txt. The session library remains
available to isolated tests; this CLI must not import or start its runner.
"""
from __future__ import annotations

import sys
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    print(
        "unverified_paper_session_inputs: sessao bloqueada; integrar sinais "
        "com fonte, timestamp e aprovacao verificaveis, em banco paper isolado. "
        "Nenhum ciclo iniciado.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())