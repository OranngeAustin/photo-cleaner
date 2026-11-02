import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _lines(path):
    return [
        line.strip()
        for line in (PROJECT_ROOT / path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_lock_file_pins_every_requirement_to_an_exact_version():
    """L13: requirements.lock records the versions the tests passed with; the
    pHash values the tests expect depend on ImageHash, NumPy and SciPy."""
    pins = {}
    for line in _lines("requirements.lock"):
        name, separator, version = line.partition("==")
        assert separator and re.fullmatch(r"[0-9][0-9A-Za-z.+!]*", version), line
        pins[_canonical(name)] = version

    requirements = {_canonical(re.split(r"[\s;<>=!~\[]", line)[0]) for line in _lines("requirements.txt")}

    assert requirements <= pins.keys()
    assert {"numpy", "scipy", "pywavelets"} <= pins.keys()
