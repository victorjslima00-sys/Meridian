"""Blocked: the received demo mislabeled synthetic values as live financial data."""


def run_live_demonstration():
    raise RuntimeError('unverified_live_demonstration: see docs/AUDITORIA_DASHBOARD_20260913.md')


if __name__ == '__main__':
    try:
        run_live_demonstration()
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(2)