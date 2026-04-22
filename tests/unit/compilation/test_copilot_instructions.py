"""Unit tests for .github/copilot-instructions.md compilation."""

import shutil
from pathlib import Path
from typing import List

import pytest

from apm_cli.compilation.agents_compiler import (
    AgentsCompiler,
    CompilationConfig,
    CompilationResult,
    COPILOT_INSTRUCTIONS_PATH,
)
from apm_cli.compilation.constants import GENERATED_HEADER
from apm_cli.compilation.template_builder import build_root_sections
from apm_cli.primitives.models import Instruction, PrimitiveCollection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_instruction(
    file_path: Path,
    content: str,
    apply_to: str = "",
    name: str = "",
) -> Instruction:
    """Create a minimal Instruction for testing."""
    return Instruction(
        name=name or file_path.stem,
        file_path=file_path,
        description="test instruction",
        apply_to=apply_to,
        content=content,
    )


def _make_primitives(instructions: List[Instruction]) -> PrimitiveCollection:
    """Wrap a list of instructions in a PrimitiveCollection."""
    pc = PrimitiveCollection()
    pc.instructions = list(instructions)
    return pc


def _compiler_and_config(
    tmp_path: Path,
    *,
    dry_run: bool = False,
    target: str = "vscode",
    strategy: str = "single-file",
) -> tuple:
    """Return (AgentsCompiler, CompilationConfig) rooted at *tmp_path*."""
    compiler = AgentsCompiler(str(tmp_path))
    config = CompilationConfig(
        target=target,
        dry_run=dry_run,
        strategy=strategy,
        single_agents=True,
    )
    return compiler, config


# ---------------------------------------------------------------------------
# 1. Mixed fixture — root + pattern-scoped instructions
# ---------------------------------------------------------------------------

class TestCopilotInstructionsMixed:
    """Compile with a mix of root-scoped and pattern-scoped instructions."""

    def test_mixed_instructions(self, tmp_path: Path) -> None:
        root_a = tmp_path / "a.instructions.md"
        root_b = tmp_path / "b.instructions.md"
        scoped_c = tmp_path / "c.instructions.md"
        scoped_d = tmp_path / "d.instructions.md"
        for f in (root_a, root_b, scoped_c, scoped_d):
            f.touch()

        instructions = [
            _make_instruction(root_a, "Root instruction A"),
            _make_instruction(root_b, "Root instruction B"),
            _make_instruction(scoped_c, "Scoped C", apply_to="**/*.py"),
            _make_instruction(scoped_d, "Scoped D", apply_to="**/*.js"),
        ]
        primitives = _make_primitives(instructions)

        compiler, config = _compiler_and_config(tmp_path)
        result = compiler._compile_copilot_instructions(config, primitives)

        assert result is not None
        assert result.output_path.endswith(str(COPILOT_INSTRUCTIONS_PATH))
        assert "Root instruction A" in result.content
        assert "Root instruction B" in result.content
        assert "Scoped C" not in result.content
        assert "Scoped D" not in result.content
        assert GENERATED_HEADER in result.content


# ---------------------------------------------------------------------------
# 2. Empty case — no root-scoped instructions -> None
# ---------------------------------------------------------------------------

class TestCopilotInstructionsEmpty:
    """No root-scoped instructions means no file at all."""

    def test_returns_none_when_no_root_instructions(self, tmp_path: Path) -> None:
        scoped = tmp_path / "scoped.instructions.md"
        scoped.touch()

        instructions = [
            _make_instruction(scoped, "Only scoped", apply_to="**/*.py"),
        ]
        primitives = _make_primitives(instructions)

        compiler, config = _compiler_and_config(tmp_path)
        result = compiler._compile_copilot_instructions(config, primitives)

        assert result is None
        assert not (tmp_path / COPILOT_INSTRUCTIONS_PATH).exists()


# ---------------------------------------------------------------------------
# 3. Deterministic sort — order is base_dir-relative
# ---------------------------------------------------------------------------

class TestCopilotInstructionsDeterministicSort:
    """Root-scoped instructions are sorted by base_dir-relative path."""

    def test_sort_uses_base_dir(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        beta = project / "beta" / "root.instructions.md"
        alpha = project / "alpha" / "root.instructions.md"
        beta.parent.mkdir(parents=True)
        alpha.parent.mkdir(parents=True)
        beta.touch()
        alpha.touch()

        instructions = [
            _make_instruction(beta, "beta content"),
            _make_instruction(alpha, "alpha content"),
        ]
        primitives = _make_primitives(instructions)

        compiler, config = _compiler_and_config(project)
        result = compiler._compile_copilot_instructions(config, primitives)

        assert result is not None
        alpha_pos = result.content.index("alpha content")
        beta_pos = result.content.index("beta content")
        assert alpha_pos < beta_pos, (
            "alpha should appear before beta (sorted by relative path)"
        )


# ---------------------------------------------------------------------------
# 4. Round-trip stability — byte-identical content on repeated compiles
# ---------------------------------------------------------------------------

class TestCopilotInstructionsRoundTrip:
    """Two dry-run compiles with identical input produce identical content."""

    def test_byte_identical(self, tmp_path: Path) -> None:
        root = tmp_path / "root.instructions.md"
        root.touch()
        instructions = [_make_instruction(root, "stable content")]
        primitives = _make_primitives(instructions)

        compiler1, config1 = _compiler_and_config(tmp_path, dry_run=True)
        result1 = compiler1._compile_copilot_instructions(config1, primitives)

        compiler2, config2 = _compiler_and_config(tmp_path, dry_run=True)
        result2 = compiler2._compile_copilot_instructions(config2, primitives)

        assert result1.content == result2.content


# ---------------------------------------------------------------------------
# 5. Header present at very start of content
# ---------------------------------------------------------------------------

class TestCopilotInstructionsHeader:
    """Generated content starts with the standardised header."""

    def test_starts_with_generated_header(self, tmp_path: Path) -> None:
        root = tmp_path / "root.instructions.md"
        root.touch()
        instructions = [_make_instruction(root, "content")]
        primitives = _make_primitives(instructions)

        compiler, config = _compiler_and_config(tmp_path, dry_run=True)
        result = compiler._compile_copilot_instructions(config, primitives)

        assert result.content.startswith(GENERATED_HEADER)


# ---------------------------------------------------------------------------
# 6. Source attribution — <!-- Source: ... --> / <!-- End source: ... -->
# ---------------------------------------------------------------------------

class TestCopilotInstructionsSourceAttribution:
    """Each root instruction is wrapped in source-attribution comments."""

    def test_source_markers_surround_content(self, tmp_path: Path) -> None:
        root = tmp_path / "coding.instructions.md"
        root.touch()
        instructions = [_make_instruction(root, "Use type hints.")]
        primitives = _make_primitives(instructions)

        compiler, config = _compiler_and_config(tmp_path, dry_run=True)
        result = compiler._compile_copilot_instructions(config, primitives)

        assert "<!-- Source: coding.instructions.md -->" in result.content
        assert "<!-- End source: coding.instructions.md -->" in result.content

        # Content must be between the markers
        src_start = result.content.index("<!-- Source: coding.instructions.md -->")
        body_pos = result.content.index("Use type hints.")
        src_end = result.content.index("<!-- End source: coding.instructions.md -->")
        assert src_start < body_pos < src_end


# ---------------------------------------------------------------------------
# 7. Dry-run mode — result returned but file NOT written
# ---------------------------------------------------------------------------

class TestCopilotInstructionsDryRun:
    """In dry-run mode the file must not be created on disk."""

    def test_dry_run_no_file(self, tmp_path: Path) -> None:
        root = tmp_path / "root.instructions.md"
        root.touch()
        instructions = [_make_instruction(root, "dry-run body")]
        primitives = _make_primitives(instructions)

        compiler, config = _compiler_and_config(tmp_path, dry_run=True)
        result = compiler._compile_copilot_instructions(config, primitives)

        assert result is not None
        assert result.success is True
        assert result.content  # non-empty
        assert not (tmp_path / COPILOT_INSTRUCTIONS_PATH).exists()
        assert result.stats["copilot_instructions_written"] == 0

    def test_non_dry_run_writes_file(self, tmp_path: Path) -> None:
        root = tmp_path / "root.instructions.md"
        root.touch()
        instructions = [_make_instruction(root, "written body")]
        primitives = _make_primitives(instructions)

        compiler, config = _compiler_and_config(tmp_path, dry_run=False)
        result = compiler._compile_copilot_instructions(config, primitives)

        assert result is not None
        assert result.success is True
        assert (tmp_path / COPILOT_INSTRUCTIONS_PATH).exists()
        disk_content = (tmp_path / COPILOT_INSTRUCTIONS_PATH).read_text(encoding="utf-8")
        assert disk_content == result.content
        assert result.stats["copilot_instructions_written"] == 1


# ---------------------------------------------------------------------------
# 9. Integration — compile() produces both AGENTS.md and copilot-instructions
# ---------------------------------------------------------------------------

class TestCopilotInstructionsIntegration:
    """Full compile() with target=vscode should produce both outputs."""

    def test_vscode_target_produces_both(self, tmp_path: Path) -> None:
        root = tmp_path / "root.instructions.md"
        scoped = tmp_path / "scoped.instructions.md"
        root.touch()
        scoped.touch()

        instructions = [
            _make_instruction(root, "Root-scoped global rule"),
            _make_instruction(scoped, "Python rule", apply_to="**/*.py"),
        ]
        primitives = _make_primitives(instructions)

        compiler = AgentsCompiler(str(tmp_path))
        config = CompilationConfig(
            target="vscode",
            dry_run=False,
            strategy="single-file",
            single_agents=True,
        )
        result = compiler.compile(config, primitives)

        assert result.success

        # AGENTS.md should exist and contain scoped content
        agents_path = tmp_path / "AGENTS.md"
        assert agents_path.exists()
        agents_content = agents_path.read_text(encoding="utf-8")
        assert "Python rule" in agents_content

        # copilot-instructions.md should exist with root content
        copilot_path = tmp_path / COPILOT_INSTRUCTIONS_PATH
        assert copilot_path.exists()
        copilot_content = copilot_path.read_text(encoding="utf-8")
        assert "Root-scoped global rule" in copilot_content
        assert "Python rule" not in copilot_content


# ---------------------------------------------------------------------------
# build_root_sections unit tests (template_builder layer)
# ---------------------------------------------------------------------------

class TestBuildRootSections:
    """Direct tests for the build_root_sections helper."""

    def test_filters_to_empty_apply_to_only(self, tmp_path: Path) -> None:
        root = tmp_path / "root.md"
        scoped = tmp_path / "scoped.md"
        root.touch()
        scoped.touch()

        result = build_root_sections(
            [
                _make_instruction(root, "root body"),
                _make_instruction(scoped, "scoped body", apply_to="*.py"),
            ],
            tmp_path,
        )

        assert "root body" in result
        assert "scoped body" not in result

    def test_returns_empty_string_when_none_match(self, tmp_path: Path) -> None:
        scoped = tmp_path / "scoped.md"
        scoped.touch()

        result = build_root_sections(
            [_make_instruction(scoped, "x", apply_to="*.ts")],
            tmp_path,
        )
        assert result == ""

    def test_empty_input_list(self, tmp_path: Path) -> None:
        assert build_root_sections([], tmp_path) == ""
