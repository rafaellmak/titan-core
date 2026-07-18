import os
import tempfile
from pathlib import Path
import pytest

from titan.actions.recipe import RecipeModifier
from titan.actions.modifier import WorkspaceModifier
from titan.recipes.db import RecipeDB
from titan.workspace.models import YoctoWorkspace


@pytest.fixture
def fake_ws(tmp_path):
    """Workspace Yocto sintético: build/conf + 1 layer com 1 .bb"""
    build = tmp_path / "build" / "conf"
    build.mkdir(parents=True)
    layer = tmp_path / "meta-test"
    (build / "bblayers.conf").write_text(
        f'BBLAYERS = "\n  {layer}\n"\n'
    )
    (build / "local.conf").write_text("MACHINE = 'qemu'\n")
    recipes = layer / "recipes-core" / "zlib"
    recipes.mkdir(parents=True)
    (recipes / "zlib_1.2.13.bb").write_text("SUMMARY = 'zlib'\nPV = '1.2.13'\n")
    (layer / "conf").mkdir(parents=True, exist_ok=True)
    (layer / "conf" / "layer.conf").write_text("BBPATH = ''\n")
    return YoctoWorkspace(
        root_dir=tmp_path,
        build_dir=tmp_path / "build",
        init_script=tmp_path / "poky/oe-init-build-env",
        layers=[layer],
    )


class TestPatchRecipeFallback:
    def test_underscore_preserved(self, fake_ws):
        db = RecipeDB(fake_ws.root_dir)
        rm = RecipeModifier(db, workspace=fake_ws)
        ok = rm.append_variable("zlib", "EXTRA_OECONF", "--with-foo")
        assert ok
        text = (fake_ws.layers[0] / "recipes-core" / "zlib" / "zlib_1.2.13.bb").read_text()
        assert 'EXTRA_OECONF += "--with-foo"' in text
        assert "EXTRA:OECONF" not in text

    def test_modern_override_char_kept(self, fake_ws):
        bb = fake_ws.layers[0] / "recipes-core" / "zlib" / "zlib_1.2.13.bb"
        bb.write_text("SUMMARY = 'zlib'\nEXTRA_OECONF:append = 'x'\n")
        db = RecipeDB(fake_ws.root_dir)
        rm = RecipeModifier(db, workspace=fake_ws)
        ok = rm.append_variable("zlib", "EXTRA_OECONF:append", "y")
        assert ok
        assert "EXTRA_OECONF:append" in bb.read_text()

    def test_legacy_override_char_kept(self, fake_ws):
        bb = fake_ws.layers[0] / "recipes-core" / "zlib" / "zlib_1.2.13.bb"
        bb.write_text("SUMMARY = 'zlib'\nEXTRA_OECONF_append = 'x'\n")
        db = RecipeDB(fake_ws.root_dir)
        rm = RecipeModifier(db, workspace=fake_ws)
        ok = rm.append_variable("zlib", "EXTRA_OECONF:append", "y")
        assert ok
        assert "EXTRA_OECONF_append" in bb.read_text()

    def test_recipe_not_in_db_falls_back_to_disk(self, fake_ws):
        db = RecipeDB(fake_ws.root_dir)
        rm = RecipeModifier(db, workspace=fake_ws)
        assert db.get_recipe("zlib") is None
        ok = rm.append_variable("zlib", "PV", "9.9.9")
        assert ok

    def test_missing_recipe_gives_helpful_error(self, fake_ws, capsys):
        db = RecipeDB(fake_ws.root_dir)
        rm = RecipeModifier(db, workspace=fake_ws)
        assert rm.append_variable("nonexistent", "FOO", "bar") is False
        captured = capsys.readouterr()
        assert "não encontrada" in captured.out
        assert "titan index" in captured.out


class TestAddLayer:
    def test_adds_to_bblayers(self, fake_ws):
        new_layer = fake_ws.root_dir / "meta-mine"
        new_layer.mkdir()
        (new_layer / "conf").mkdir()
        (new_layer / "conf" / "layer.conf").write_text("BBPATH = ''\n")
        wm = WorkspaceModifier(fake_ws)
        assert wm.add_layer(str(new_layer)) is True
        bblayers = (fake_ws.build_dir / "conf" / "bblayers.conf").read_text()
        assert str(new_layer.resolve()) in bblayers

    def test_idempotent(self, fake_ws):
        new_layer = fake_ws.root_dir / "meta-mine"
        new_layer.mkdir()
        (new_layer / "conf").mkdir()
        (new_layer / "conf" / "layer.conf").write_text("")
        wm = WorkspaceModifier(fake_ws)
        wm.add_layer(str(new_layer))
        wm.add_layer(str(new_layer))
        bblayers = (fake_ws.build_dir / "conf" / "bblayers.conf").read_text()
        assert bblayers.count(str(new_layer.resolve())) == 1

    def test_missing_layer(self, fake_ws, capsys):
        wm = WorkspaceModifier(fake_ws)
        assert wm.add_layer("/does/not/exist") is False
        captured = capsys.readouterr()
        assert "não encontrada" in captured.out
