"""Coverage for Config coercion helpers and from_env/from_sources branches."""
from __future__ import annotations

from pathlib import Path

import pytest

from reviewforge.config import Config, ConfigError, _coerce_bool, env


class TestCoerceBool:
    def test_string_value_parsed(self):
        assert _coerce_bool("1", False) is True
        assert _coerce_bool("0", True) is False

    def test_env_value_fallback(self):
        assert _coerce_bool(None, False, env_value="true") is True

    def test_default_fallback(self):
        assert _coerce_bool(None, True) is True
        assert _coerce_bool(None, False) is False


class TestEnvHelper:
    def test_missing_required_raises(self, monkeypatch):
        monkeypatch.delenv("REVIEWFORGE_MISSING", raising=False)
        with pytest.raises(ConfigError, match="REVIEWFORGE_MISSING required"):
            env("REVIEWFORGE_MISSING")


class TestFromEnvBranches:
    @pytest.fixture
    def base_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ADO_AUTH_TOKEN", "tok")
        monkeypatch.setenv("WORKSPACE", str(tmp_path))
        monkeypatch.setenv("CLONE_ROOT", str(tmp_path))
        return monkeypatch

    def test_invalid_numeric_overrides_fall_back(self, base_env):
        base_env.setenv("MAX_FINDINGS", "not-a-number")
        base_env.setenv("CONTEXT_FILE_MAX_LINES", "bogus")
        base_env.setenv("CONTEXT_SEARCH_MAX_MATCHES", "bogus")
        base_env.setenv("COLLECT_CONTEXT_WORKERS", "bogus")

        cfg = Config.from_env()

        assert cfg.max_findings is None
        assert cfg.context_file_max_lines == 260
        assert cfg.context_search_max_matches == 40
        assert cfg.collect_context_workers == 8

    def test_invalid_anchor_policy_raises(self, base_env):
        base_env.setenv("ANCHOR_POLICY", "bogus")
        with pytest.raises(ConfigError, match="ANCHOR_POLICY"):
            Config.from_env()

    def test_from_env_does_not_mutate_chunk_trigger_env(self, base_env):
        base_env.setenv("MAX_DIFF_BYTES", "123")
        base_env.delenv("CHUNK_TRIGGER_DIFF_BYTES", raising=False)
        cfg = Config.from_env()
        assert cfg.chunk_trigger_diff_bytes == 123
        assert "CHUNK_TRIGGER_DIFF_BYTES" not in __import__("os").environ


class TestFromSourcesBranches:
    def test_invalid_anchor_policy_raises(self):
        with pytest.raises(ConfigError, match="ANCHOR_POLICY"):
            Config.from_sources(env={"ANCHOR_POLICY": "bogus", "ADO_AUTH_TOKEN": "tok"})

    def test_non_pi_backend_raises(self):
        with pytest.raises(ConfigError, match="MODEL_BACKEND"):
            Config.from_sources(env={"MODEL_BACKEND": "openai", "ADO_AUTH_TOKEN": "tok"})

    def test_pi_session_fields_read_from_injected_env(self):
        cfg = Config.from_sources(
            env={
                "ADO_AUTH_TOKEN": "tok",
                "PI_SESSION_ID": "sid-1",
                "PI_SESSION_ENABLED": "0",
                "PI_SESSION_CLEAR": "1",
            }
        )
        assert cfg.pi_session_id == "sid-1"
        assert cfg.pi_session_enabled is False
        assert cfg.pi_session_clear is True


class TestFromEnvFile:
    def test_default_path_reads_dotenv_in_cwd(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("ADO_AUTH_TOKEN=tok\nPR_ID=77\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("PR_ID", raising=False)

        cfg = Config.from_env_file()

        assert cfg.pr_id == "77"


class TestValidateFiles:
    def test_ac_coverage_prompt_required_when_enabled(self, tmp_path):
        prompt = tmp_path / "ac.md"
        prompt.write_text("prompt", encoding="utf-8")
        cfg = Config.from_sources(
            cli={
                "standards_path": str(prompt),
                "fast_review_prompt_path": str(prompt),
                "ac_coverage_llm": True,
                "ac_coverage_prompt_path": str(prompt),
            },
            env={"ADO_AUTH_TOKEN": "tok"},
        )

        cfg.validate_files()  # must not raise

    def test_missing_standards_raises(self, tmp_path):
        cfg = Config.from_sources(
            cli={"standards_path": str(tmp_path / "absent.md")},
            env={"ADO_AUTH_TOKEN": "tok"},
        )
        with pytest.raises(ConfigError, match="Required file not found"):
            cfg.validate_files()


class TestCrgConfig:
    """CRG cache-dir and prompt-cap configuration resolution."""

    def test_defaults(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ADO_AUTH_TOKEN", "tok")
        monkeypatch.setenv("WORKSPACE", str(tmp_path))
        monkeypatch.setenv("CLONE_ROOT", str(tmp_path))
        monkeypatch.delenv("CRG_CACHE_DIR", raising=False)
        monkeypatch.delenv("CRG_CONTEXT_MAX_BYTES", raising=False)
        cfg = Config.from_env()
        assert cfg.crg_enabled is False
        assert cfg.crg_cache_dir is None
        assert cfg.crg_context_max_bytes == 8192

    def test_from_env_resolves_crg_vars(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ADO_AUTH_TOKEN", "tok")
        monkeypatch.setenv("WORKSPACE", str(tmp_path))
        monkeypatch.setenv("CLONE_ROOT", str(tmp_path))
        monkeypatch.setenv("CRG_ENABLED", "1")
        monkeypatch.setenv("CRG_CACHE_DIR", str(tmp_path / "crg-vol"))
        monkeypatch.setenv("CRG_CONTEXT_MAX_BYTES", "4096")
        cfg = Config.from_env()
        assert cfg.crg_enabled is True
        assert cfg.crg_cache_dir == tmp_path / "crg-vol"
        assert cfg.crg_context_max_bytes == 4096

    def test_from_env_resolves_graph_wave_two_vars(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ADO_AUTH_TOKEN", "tok")
        monkeypatch.setenv("WORKSPACE", str(tmp_path))
        monkeypatch.setenv("CLONE_ROOT", str(tmp_path))
        monkeypatch.setenv("GRAPH_API_DIFF", "1")
        monkeypatch.setenv("GRAPH_FLOWS", "yes")
        monkeypatch.setenv("GRAPH_ARCH", "on")
        monkeypatch.setenv("GRAPH_CONTEXT_MAX_BYTES", "4096")
        cfg = Config.from_env()
        assert cfg.graph_api_diff is True
        assert cfg.graph_flows is True
        assert cfg.graph_arch is True
        assert cfg.graph_context_max_bytes == 4096

    def test_from_sources_resolves_crg_vars(self, tmp_path):
        cfg = Config.from_sources(
            env={
                "ADO_AUTH_TOKEN": "tok",
                "CRG_ENABLED": "1",
                "CRG_CACHE_DIR": str(tmp_path / "crg-vol"),
                "CRG_CONTEXT_MAX_BYTES": "2048",
            }
        )
        assert cfg.crg_enabled is True
        assert cfg.crg_cache_dir == tmp_path / "crg-vol"
        assert cfg.crg_context_max_bytes == 2048

    def test_from_sources_defaults_without_crg_vars(self):
        cfg = Config.from_sources(env={"ADO_AUTH_TOKEN": "tok"})
        assert cfg.crg_cache_dir is None
        assert cfg.crg_context_max_bytes == 8192

    def test_from_env_rejects_non_numeric_crg_cap(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ADO_AUTH_TOKEN", "tok")
        monkeypatch.setenv("WORKSPACE", str(tmp_path))
        monkeypatch.setenv("CLONE_ROOT", str(tmp_path))
        monkeypatch.setenv("CRG_CONTEXT_MAX_BYTES", "lots")
        with pytest.raises(ConfigError, match="CRG_CONTEXT_MAX_BYTES"):
            Config.from_env()

    def test_from_sources_rejects_non_numeric_crg_cap(self):
        with pytest.raises(ConfigError, match="CRG_CONTEXT_MAX_BYTES"):
            Config.from_sources(env={"ADO_AUTH_TOKEN": "tok", "CRG_CONTEXT_MAX_BYTES": "-1"})
