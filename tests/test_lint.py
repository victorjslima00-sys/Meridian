from flake8.api import legacy as flake8

def test_flake8_lint():
    style_guide = flake8.get_style_guide(select=['E9', 'F63', 'F7', 'F82'])
    report = style_guide.check_files(['trading_bot', 'tests'])
    assert report.total_errors == 0, f"Flake8 found {report.total_errors} errors"
