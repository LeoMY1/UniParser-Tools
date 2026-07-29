"""Safe output directory resolution and replacement."""

from __future__ import annotations

import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def default_parse_output_dir(source_stem: str) -> Path:
    """Return a contained parse output directory for ``source_stem``."""
    if (
        not source_stem
        or source_stem in {".", ".."}
        or "/" in source_stem
        or "\\" in source_stem
        or Path(source_stem).name != source_stem
    ):
        raise ValueError(f"Unsafe source name for output directory: {source_stem!r}")

    base = (Path.home() / "Uni-Parser-Skill").resolve()
    candidate = (base / source_stem).resolve()
    if candidate == base or not candidate.is_relative_to(base):
        raise ValueError(f"Output directory escapes the managed root: {candidate}")
    return candidate


def resolve_output_dir(output_dir: str | Path | None, *, default: Path) -> Path:
    """Resolve an explicit output path or use the supplied safe default."""
    return Path(output_dir).expanduser().resolve() if output_dir else default.resolve()


def _validate_replacement_target(target: Path) -> None:
    protected = {
        Path(target.anchor).resolve(),
        Path.home().resolve(),
        Path.cwd().resolve(),
    }
    if target in protected:
        raise ValueError(f"Refusing to replace protected directory: {target}")
    if target.exists() and not target.is_dir():
        raise NotADirectoryError(f"Output path exists and is not a directory: {target}")


@contextmanager
def replace_output_dir(target: str | Path, *, overwrite: bool) -> Iterator[Path]:
    """Create ``target``, deleting its previous contents when overwriting."""
    out = Path(target).expanduser().resolve()
    _validate_replacement_target(out)

    if out.exists() and not overwrite:
        raise FileExistsError(f"Output directory exists: {out}. Use --overwrite to replace.")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=False)
    yield out
