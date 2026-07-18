import subprocess
import shutil
import pytest
from pathlib import Path


WORKSPACE = Path("/home/ubunote/projects/titan-core-v12")


def _run(args, **kwargs):
    return subprocess.run(
        ["titan"] + args,
        cwd=WORKSPACE, capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(WORKSPACE)},
        **kwargs,
    )


@pytest.fixture(autouse=True)
def clean_titan():
    for pattern in (".titan_digital_twin", ".titan_cache", ".titan_recipe_db", ".titan"):
        p = WORKSPACE / pattern
        if p.exists():
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()
    cache = Path.home() / ".cache" / "titan"
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)
    yield
    for pattern in (".titan_digital_twin", ".titan_cache", ".titan_recipe_db", ".titan"):
        p = WORKSPACE / pattern
        if p.exists():
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()


def _indexed():
    _run(["recipe", "index"])


class TestRecipeSearch:
    def test_empty_db_gives_friendly_message(self):
        r = _run(["recipe", "search"])
        assert r.returncode == 1
        assert "Banco vazio" in r.stdout

    def test_after_index_lists_all(self):
        _indexed()
        r = _run(["recipe", "search"])
        assert r.returncode == 0
        assert "openssl" in r.stdout
        assert "example" in r.stdout

    def test_search_finds_existing(self):
        _indexed()
        r = _run(["recipe", "search", "openssl"])
        assert r.returncode == 0
        assert "openssl" in r.stdout

    def test_search_is_case_insensitive(self):
        _indexed()
        r = _run(["recipe", "search", "OPENSSL"])
        assert r.returncode == 0
        assert "openssl" in r.stdout

    def test_search_missing_recipe_gives_helpful_error(self):
        _indexed()
        r = _run(["recipe", "search", "zzz-nonexistent"])
        assert r.returncode == 1
        assert "Nenhuma receita encontrada" in r.stdout
        assert "titan recipe index" in r.stdout

    def test_whitespace_only_target_lists_all_when_db_has_data(self):
        _indexed()
        r = _run(["recipe", "search", "   "])
        assert r.returncode == 0
        assert "openssl" in r.stdout
        assert "example" in r.stdout

    def test_whitespace_only_target_empty_when_db_empty(self):
        r = _run(["recipe", "search", "   "])
        assert r.returncode == 1
        assert "Nenhuma receita encontrada" in r.stdout


class TestRecipeShow:
    def test_show_existing_recipe(self):
        _indexed()
        r = _run(["recipe", "show", "openssl"])
        assert r.returncode == 0
        assert "openssl" in r.stdout
        assert "PV:" in r.stdout
        assert "Arquivo:" in r.stdout

    def test_show_without_target_errors(self):
        r = _run(["recipe", "show"])
        assert r.returncode == 1
        assert "requer o PN" in r.stdout

    def test_show_nonexistent_recipe_errors(self):
        _indexed()
        r = _run(["recipe", "show", "zzz-nonexistent"])
        assert r.returncode == 1
        assert "não encontrada" in r.stdout
        assert "titan recipe index" in r.stdout

    def test_show_unknown_recipe_errors_with_help(self):
        _indexed()
        r = _run(["recipe", "show", "zzz-unknown-recipe"])
        assert r.returncode == 1
        assert "não encontrada" in r.stdout
        assert "titan recipe index" in r.stdout


class TestRecipeDepsImpact:
    def test_deps_without_target_errors(self):
        _indexed()
        r = _run(["recipe", "deps"])
        assert r.returncode == 1
        assert "requer o PN" in r.stdout

    def test_impact_without_target_errors(self):
        _indexed()
        r = _run(["recipe", "impact"])
        assert r.returncode == 1
        assert "requer o PN" in r.stdout

    def test_deps_shows_fallback_from_db(self):
        _indexed()
        r = _run(["recipe", "deps", "openssl"])
        assert r.returncode == 0
        # Deve mostrar algo (fallback ou grafo)
        assert r.stdout.strip()

    def test_impact_shows_fallback_from_db(self):
        _indexed()
        r = _run(["recipe", "impact", "zlib"])
        assert r.returncode == 0
        assert r.stdout.strip()

    def test_deps_nonexistent_recipe_returns_helpful_message(self):
        _indexed()
        r = _run(["recipe", "deps", "zzz-nonexistent"])
        assert "não encontrada" in r.stdout or "Nenhum" in r.stdout


class TestRecipeOutsideWorkspace:
    def test_search_outside_yocto(self, tmp_path):
        r = subprocess.run(
            ["titan", "recipe", "search"],
            cwd=tmp_path, capture_output=True, text=True,
            env={**__import__("os").environ, "PYTHONPATH": str(WORKSPACE)},
        )
        assert r.returncode == 1
        assert "Nenhum workspace" in r.stdout

    def test_index_outside_yocto(self, tmp_path):
        r = subprocess.run(
            ["titan", "recipe", "index"],
            cwd=tmp_path, capture_output=True, text=True,
            env={**__import__("os").environ, "PYTHONPATH": str(WORKSPACE)},
        )
        assert r.returncode == 1
        assert "Nenhum workspace" in r.stdout
