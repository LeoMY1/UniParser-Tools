"""Reusable sample payloads for tests.

Kept deliberately small and deterministic so assertions don't drift when
the underlying pandas / tabulate version changes formatting whitespace
slightly.
"""
from __future__ import annotations


SIMPLE_HTML = """
<table>
  <thead>
    <tr><th>name</th><th>value</th></tr>
  </thead>
  <tbody>
    <tr><td>alpha</td><td>1</td></tr>
    <tr><td>beta</td><td>2</td></tr>
  </tbody>
</table>
"""

MULTIHEADER_HTML = """
<table>
  <thead>
    <tr><th>group-A</th><th>group-A</th><th>group-B</th></tr>
    <tr><th>x</th><th>y</th><th>z</th></tr>
  </thead>
  <tbody>
    <tr><td>1</td><td>2</td><td>3</td></tr>
    <tr><td>4</td><td>5</td><td>6</td></tr>
  </tbody>
</table>
"""

ROWSPAN_HTML = """
<table>
  <thead>
    <tr><th>col1</th><th>col2</th></tr>
  </thead>
  <tbody>
    <tr><td rowspan="2">merged</td><td>a</td></tr>
    <tr><td>b</td></tr>
  </tbody>
</table>
"""

MALFORMED_HTML = "<not a table at all>"


def make_reaction_dict(reactants=("A",), products=("B",), conditions=("cat",)):
    """Return a dict shaped like the ``Reaction`` payload used by the parser."""
    bbox = [0.0, 0.0, 0.1, 0.1]

    def _components(texts, category="[Mol]", category_id=1):
        return [
            {"bbox": bbox, "category": category, "category_id": category_id, "text": t}
            for t in texts
        ]

    return {
        "reactants": _components(reactants, "[Mol]", 1),
        "products": _components(products, "[Mol]", 1),
        "conditions": _components(conditions, "[Txt]", 2),
    }


def make_tabular_payload(structure: str, placeholders, contents):
    """Build kwargs for TabularResult with the minimal required shape."""
    assert len(placeholders) == len(contents)
    return dict(
        token="t",
        page=0,
        block=0,
        conf=1.0,
        bbox=[0.0, 0.0, 1.0, 1.0],
        page_size=(100, 100),
        type="table",
        bboxes=[[0.0, 0.0, 1.0, 1.0] for _ in placeholders],
        labels=[0 for _ in placeholders],
        placeholders=list(placeholders),
        contents=list(contents),
        structure=structure,
    )


def make_chart_data(rows):
    """Convert list of rows (list of strings) into the ``|`` separated chart string."""
    return "\n".join("|".join(str(c) for c in row) for row in rows)
