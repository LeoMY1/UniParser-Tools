"""Run molecule enrich while dumping each LLM call to disk.

Dev-only. Not part of the product CLI. Safe to delete this package after debugging.

Example:
  uv run python -m uniparser_agent.chemistry.llm_io_debug.run_dump \\
    /root/code/test/chemistry/pages_tree.json --doc-id CN106380440B
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from uniparser_agent.chemistry.enrich import enrich_compounds
from uniparser_agent.chemistry.jobspec import JobSpec
from uniparser_agent.chemistry.join import build_logical_compounds
from uniparser_agent.chemistry.llm_io_debug.dump_chat import DEFAULT_OUT_DIR, make_dumping_chat_fn
from uniparser_agent.chemistry.store import ChemistryStore
from uniparser_agent.llm import OpenAICompatLLM, resolve_llm_config
from uniparser_agent.parse.service import load_pages_tree


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dump activity+link+summarize LLM I/O.",
    )
    parser.add_argument("pages_tree", type=str, help="Path to pages_tree.json")
    parser.add_argument("--doc-id", required=True, help="Document id, e.g. CN106380440B")
    parser.add_argument(
        "--out",
        type=str,
        default=str(DEFAULT_OUT_DIR),
        help=f"Output root (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Optional SQLite path; if set, write enriched compounds after dump.",
    )
    args = parser.parse_args(argv)

    pages_path = Path(args.pages_tree).expanduser().resolve()
    if not pages_path.is_file():
        print(f"pages_tree not found: {pages_path}", file=sys.stderr)
        return 1

    doc_id = args.doc_id.strip()
    out_root = Path(args.out).expanduser().resolve()
    pages_tree_doc = load_pages_tree(pages_path)
    compounds = build_logical_compounds(pages_tree_doc, doc_id)
    print(f"logical compounds: {len(compounds)}")

    llm_config = resolve_llm_config()
    client = OpenAICompatLLM(config=llm_config)

    def base_chat(system_prompt: str, user_content: str) -> str:
        return client.chat(system_prompt=system_prompt, user_content=user_content)

    dumping = make_dumping_chat_fn(
        base_chat,
        out_dir=out_root,
        doc_id=doc_id,
        model=client.model,
    )
    compounds = enrich_compounds(
        doc_id,
        compounds,
        pages_tree_doc=pages_tree_doc,
        llm_config=llm_config,
        chat_fn=dumping,
        skip_enrich=False,
    )

    dump_dir = out_root / doc_id
    print(f"LLM IO dir: {dump_dir}")
    print(
        f"act files: {dumping.act_count} "
        f"link files: {dumping.link_count} sum files: {dumping.sum_count}"
    )

    n_summary = sum(1 for c in compounds if c.semantic_summary)
    print(f"enriched with summary: {n_summary}/{len(compounds)}")
    preview = [
        {
            "label": c.label,
            "role": c.role,
            "summary": (c.semantic_summary or "")[:120],
        }
        for c in compounds[:8]
    ]
    print(json.dumps(preview, ensure_ascii=False, indent=2))

    if args.db:
        db_path = Path(args.db).expanduser().resolve()
        jobspec = JobSpec.from_profile("molecules_only", db_path=db_path)
        with ChemistryStore(db_path) as store:
            summary = store.ingest_compounds(
                doc_id=doc_id,
                source=str(pages_path),
                pages_tree_path=str(pages_path),
                markdown_path=None,
                output_dir=None,
                token="",
                jobspec=jobspec,
                compounds=compounds,
            )
        print(f"wrote db: {db_path} compounds={summary.n_compounds}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
