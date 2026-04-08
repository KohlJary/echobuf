"""Tests for the output template parser."""

from datetime import datetime

import pytest

from echobuf.template import render_template, sanitize_filename


class TestSanitizeFilename:
    def test_removes_unsafe_chars(self):
        assert "foo_bar" == sanitize_filename("foo:bar")
        assert "foo_bar" == sanitize_filename("foo|bar")
        assert "a_b_c" == sanitize_filename('a"b*c')

    def test_preserves_path_separators(self):
        assert "dir/file" == sanitize_filename("dir/file")

    def test_collapses_underscores(self):
        assert "a_b" == sanitize_filename("a___b")

    def test_strips_dots_from_components(self):
        result = sanitize_filename("...hidden/..also/file.wav")
        assert "hidden" in result
        assert "file.wav" in result

    def test_empty_string(self):
        assert sanitize_filename("") == ""

    def test_unicode_preserved(self):
        assert "café" in sanitize_filename("café")


class TestRenderTemplate:
    NOW = datetime(2026, 4, 8, 14, 30, 52)

    def test_basic_tokens(self):
        result = render_template(
            "%(date)s/%(time)s.%(ext)s",
            now=self.NOW,
        )
        assert result == "2026-04-08/143052.wav"

    def test_counter_formatting(self):
        result = render_template(
            "%(counter)03d.%(ext)s",
            now=self.NOW, counter=7,
        )
        assert result == "007.wav"

    def test_counter_zero_pad_5(self):
        result = render_template(
            "%(counter)05d.%(ext)s",
            now=self.NOW, counter=42,
        )
        assert result == "00042.wav"

    def test_label(self):
        result = render_template(
            "%(label)s.%(ext)s",
            now=self.NOW, label="drum_fill",
        )
        assert result == "drum_fill.wav"

    def test_default_value(self):
        result = render_template(
            "%(label|untitled)s.%(ext)s",
            now=self.NOW, label="",
        )
        assert result == "untitled.wav"

    def test_default_value_not_used_when_set(self):
        result = render_template(
            "%(label|untitled)s.%(ext)s",
            now=self.NOW, label="my_clip",
        )
        assert result == "my_clip.wav"

    def test_full_template(self):
        result = render_template(
            "%(date)s/%(app)s/%(time)s_%(counter)03d.%(ext)s",
            now=self.NOW, app="spotify", counter=1,
        )
        assert result == "2026-04-08/spotify/143052_001.wav"

    def test_timestamp_token(self):
        result = render_template("%(timestamp)s", now=self.NOW, sanitize=False)
        assert result == str(int(self.NOW.timestamp()))

    def test_iso_token(self):
        result = render_template("%(iso)s", now=self.NOW, sanitize=False)
        assert result == "2026-04-08T14:30:52"

    def test_duration_as_int(self):
        result = render_template("%(duration)d", now=self.NOW, duration=10.5)
        assert result == "10"

    def test_source_token(self):
        result = render_template("%(source)s", now=self.NOW, source="app:firefox")
        assert "firefox" in result

    def test_sanitize_enabled(self):
        result = render_template(
            "%(label)s.%(ext)s",
            now=self.NOW, label='bad:name"here',
        )
        assert ":" not in result
        assert '"' not in result

    def test_sanitize_disabled(self):
        result = render_template(
            "%(label)s.%(ext)s",
            now=self.NOW, label='bad:name"here', sanitize=False,
        )
        assert ":" in result

    def test_unknown_token_left_empty(self):
        result = render_template("%(nonexistent)s.wav", now=self.NOW, sanitize=False)
        assert result == ".wav"

    def test_creates_subdirectories_in_template(self):
        result = render_template(
            "%(date)s/%(app)s/%(time)s.%(ext)s",
            now=self.NOW, app="firefox",
        )
        parts = result.split("/")
        assert len(parts) == 3
