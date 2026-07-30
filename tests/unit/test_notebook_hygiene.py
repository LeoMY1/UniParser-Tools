"""Regression checks for customer-facing playground notebooks."""

from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_TOKEN_PATTERN = re.compile(
    r"(?i)(?<![0-9a-f])(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})(?![0-9a-f])"
)


def test_playground_notebooks_have_no_saved_outputs_or_real_task_tokens() -> None:
    notebooks = sorted((REPO_ROOT / "playground").glob("*.ipynb"))
    assert notebooks

    for notebook_path in notebooks:
        notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
        for cell_index, cell in enumerate(notebook.get("cells", [])):
            if cell.get("cell_type") == "code":
                assert cell.get("outputs", []) == [], f"{notebook_path}: cell {cell_index} has saved output"
                assert cell.get("execution_count") is None, f"{notebook_path}: cell {cell_index} has an execution count"

            serialized_cell = json.dumps(cell, ensure_ascii=False)
            assert TASK_TOKEN_PATTERN.search(serialized_cell) is None, (
                f"{notebook_path}: cell {cell_index} contains a task-token-shaped value"
            )
