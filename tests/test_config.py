# VERIDEX v0.3.0 - reference validation and provenance auditing.
# Copyright (c) 2026 Madeesh P. Nissanka
# MIT License - see LICENSE file.
"""Tests for user configuration file support."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from veridex.config import (
    CONFIG_FILENAMES,
    find_config_file,
    load_config_file,
    load_user_config,
    merge_config,
)


class TestFindConfigFile:
    def test_finds_yaml_in_cwd(self, tmp_path: Path):
        cfg = tmp_path / "veridex.yaml"
        cfg.write_text("sources: [crossref]\n")
        found = find_config_file(str(tmp_path))
        assert found == str(cfg)

    def test_finds_dotveridexrc(self, tmp_path: Path):
        cfg = tmp_path / ".veridexrc"
        cfg.write_text("workers: 4\n")
        found = find_config_file(str(tmp_path))
        assert found == str(cfg)

    def test_finds_json(self, tmp_path: Path):
        cfg = tmp_path / ".veridexrc.json"
        cfg.write_text('{"cache_dir": "/tmp/cache"}')
        found = find_config_file(str(tmp_path))
        assert found == str(cfg)

    def test_walks_up_parents(self, tmp_path: Path):
        sub = tmp_path / "sub" / "dir"
        sub.mkdir(parents=True)
        cfg = tmp_path / "veridex.yaml"
        cfg.write_text("sources: [crossref]\n")
        found = find_config_file(str(sub))
        assert found == str(cfg)

    def test_returns_none_when_not_found(self, tmp_path: Path):
        found = find_config_file(str(tmp_path))
        assert found is None

    def test_prefers_first_in_list(self, tmp_path: Path):
        # veridex.yaml should be found before .veridexrc
        (tmp_path / "veridex.yaml").write_text("sources: [crossref]\n")
        (tmp_path / ".veridexrc").write_text("workers: 2\n")
        found = find_config_file(str(tmp_path))
        assert found.endswith("veridex.yaml")


class TestLoadConfigFile:
    def test_loads_yaml(self, tmp_path: Path):
        cfg = tmp_path / "veridex.yaml"
        cfg.write_text("sources:\n  - crossref\n  - openalex\nworkers: 4\n")
        data = load_config_file(str(cfg))
        assert data["sources"] == ["crossref", "openalex"]
        assert data["workers"] == 4

    def test_loads_json(self, tmp_path: Path):
        cfg = tmp_path / ".veridexrc.json"
        cfg.write_text(json.dumps({"cache_dir": "/tmp/cache", "semantic": True}))
        data = load_config_file(str(cfg))
        assert data["cache_dir"] == "/tmp/cache"
        assert data["semantic"] is True

    def test_loads_dotveridexrc_as_yaml(self, tmp_path: Path):
        cfg = tmp_path / ".veridexrc"
        cfg.write_text("policy: ./policy.yaml\n")
        data = load_config_file(str(cfg))
        assert data["policy"] == "./policy.yaml"

    def test_empty_file_returns_empty_dict(self, tmp_path: Path):
        cfg = tmp_path / "veridex.yaml"
        cfg.write_text("")
        data = load_config_file(str(cfg))
        assert data == {}


class TestLoadUserConfig:
    def test_loads_from_cwd(self, tmp_path: Path, monkeypatch):
        cfg = tmp_path / "veridex.yaml"
        cfg.write_text("workers: 8\n")
        monkeypatch.chdir(tmp_path)
        config = load_user_config()
        assert config["workers"] == 8

    def test_returns_empty_when_no_config(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config = load_user_config()
        assert config == {}


class TestMergeConfig:
    def test_merges_bool_flags(self):
        class Ctx:
            json = False
            verbose = False

        ctx = Ctx()
        user_config = {"json": True, "verbose": True}
        merge_config(ctx, user_config, {"json", "verbose"}, set())
        assert ctx.json is True
        assert ctx.verbose is True

    def test_cli_takes_precedence_over_config_for_bool(self):
        class Ctx:
            json = True  # CLI already set
            verbose = False

        ctx = Ctx()
        user_config = {"json": False, "verbose": True}
        merge_config(ctx, user_config, {"json", "verbose"}, set())
        # CLI True should not be overridden by config False
        assert ctx.json is True
        # But config can set unset values
        assert ctx.verbose is True

    def test_merges_value_flags(self):
        class Ctx:
            sources = []
            cache_dir = None
            workers = None

        ctx = Ctx()
        user_config = {"sources": ["crossref"], "cache_dir": "/tmp/cache", "workers": 4}
        merge_config(ctx, user_config, set(), {"sources", "cache_dir", "workers"})
        assert ctx.sources == ["crossref"]
        assert ctx.cache_dir == "/tmp/cache"
        assert ctx.workers == 4

    def test_cli_takes_precedence_over_config_for_value(self):
        class Ctx:
            sources = ["pubmed"]  # CLI already set
            cache_dir = None

        ctx = Ctx()
        user_config = {"sources": ["crossref"], "cache_dir": "/tmp/cache"}
        merge_config(ctx, user_config, set(), {"sources", "cache_dir"})
        # CLI value should not be overridden
        assert ctx.sources == ["pubmed"]
        assert ctx.cache_dir == "/tmp/cache"

    def test_empty_list_treated_as_unset(self):
        class Ctx:
            sources = []  # Empty list = not set by CLI

        ctx = Ctx()
        user_config = {"sources": ["crossref"]}
        merge_config(ctx, user_config, set(), {"sources"})
        assert ctx.sources == ["crossref"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])