try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

import azayaka


def test_version_is_exposed_and_matches_pyproject():
    assert isinstance(azayaka.__version__, str)
    assert azayaka.__version__.strip()

    with open("pyproject.toml", "rb") as f:
        pyproject = tomllib.load(f)

    assert azayaka.__version__ == pyproject["project"]["version"]
