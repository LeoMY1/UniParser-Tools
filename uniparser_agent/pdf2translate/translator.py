"""OpenAI-compatible LLM translator with formula placeholder protection."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from uniparser_agent.llm import LLMConfig, OpenAICompatLLM
from uniparser_agent.pdf2translate.glossary import (
    GlossaryEntry,
    extract_glossary_with_llm,
    hit_glossary_entries,
    load_glossary_csv,
    merge_glossaries,
    save_glossary,
)
from uniparser_agent.pdf2translate.models import TranslateUnit
from uniparser_agent.pdf2translate.prompts import (
    DEFAULT_TARGET_LANG,
    build_context_fields,
    build_translate_system_prompt,
    build_translate_user_content,
)

DEFAULT_BATCH_SIZE = 12
DEFAULT_MAX_WORKERS = 4

# Match $...$, $$...$$, \(...\), \[...\]
_FORMULA_RE = re.compile(
    r"(\$\$.*?\$\$|\$[^$]+\$|\\\(.*?\\\)|\\\[.*?\\\])",
    re.DOTALL,
)
_PLACEHOLDER_RE = re.compile(r"<<EQ(\d+)>>")


@dataclass
class TranslateStats:
    empty_rejected: int = 0
    item_retries: int = 0
    schema_failures: int = 0
    glossary_manual: int = 0
    glossary_auto: int = 0
    glossary_total: int = 0
    auto_glossary_enabled: bool = True
    paths: dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, *, empty_rejected: int = 0, item_retries: int = 0, schema_failures: int = 0) -> None:
        with self._lock:
            self.empty_rejected += empty_rejected
            self.item_retries += item_retries
            self.schema_failures += schema_failures





def get_translate_batch_size() -> int:
    raw = (os.environ.get("PDF_TRANSLATE_BATCH_SIZE") or "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_BATCH_SIZE


def get_translate_max_workers() -> int:
    raw = (os.environ.get("PDF_TRANSLATE_MAX_WORKERS") or "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_MAX_WORKERS


def protect_formulas(text: str) -> tuple[str, dict[str, str]]:
    placeholders: dict[str, str] = {}
    counter = 0

    def _repl(match: re.Match[str]) -> str:
        nonlocal counter
        key = f"<<EQ{counter}>>"
        placeholders[key] = match.group(0)
        counter += 1
        return key

    protected = _FORMULA_RE.sub(_repl, text)
    return protected, placeholders


def restore_formulas(text: str, placeholders: dict[str, str]) -> str:
    restored = text
    # Tolerate models rewriting brackets around EQ tokens.
    restored = re.sub(
        r"【EQ(\d+)】|\[\[EQ(\d+)\]\]|⟦EQ(\d+)⟧",
        lambda m: f"<<EQ{next(g for g in m.groups() if g)}>>",
        restored,
    )
    for key, value in placeholders.items():
        if key not in restored:
            raise ValueError(f"Missing placeholder {key} in translated text")
        restored = restored.replace(key, value)
    leftovers = _PLACEHOLDER_RE.findall(restored)
    if leftovers:
        raise ValueError(f"Unexpected placeholders in translation: {leftovers}")
    return restored


def _extract_json_array(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, list):
        raise ValueError("Translator response is not a JSON array")
    return [item for item in data if isinstance(item, dict)]


def _normalize_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one response object; return None if invalid."""
    unit_id = item.get("unit_id")
    if unit_id is None:
        return None
    translated = item.get("translated_text")
    if translated is None or (isinstance(translated, str) and not translated.strip()):
        for alt in ("translation", "text"):
            alt_val = item.get(alt)
            if isinstance(alt_val, str) and alt_val.strip():
                translated = alt_val
                break
    if not isinstance(translated, str) or not translated.strip():
        return None
    return {"unit_id": str(unit_id), "translated_text": translated.strip()}


def parse_and_validate_batch(
    raw: str,
    *,
    expected_ids: set[str],
) -> tuple[dict[str, str], dict[str, Any]]:
    """Parse LLM JSON and return accepted map + validation meta."""
    items = _extract_json_array(raw)
    accepted: dict[str, str] = {}
    empty_ids: list[str] = []
    bad_schema = 0
    seen_extra: list[str] = []

    for item in items:
        normalized = _normalize_item(item)
        if normalized is None:
            uid = item.get("unit_id")
            if uid is not None:
                empty_ids.append(str(uid))
            else:
                bad_schema += 1
            continue
        uid = normalized["unit_id"]
        if uid not in expected_ids:
            seen_extra.append(uid)
            continue
        accepted[uid] = normalized["translated_text"]

    missing = sorted(expected_ids - set(accepted.keys()))
    meta = {
        "parse_ok": True,
        "accepted": sorted(accepted.keys()),
        "empty_or_missing": missing,
        "empty_rejected_ids": empty_ids,
        "schema_failures": bad_schema,
        "extra_ids": seen_extra,
        "valid_count": len(accepted),
        "expected_count": len(expected_ids),
        "complete": len(accepted) == len(expected_ids),
    }
    return accepted, meta


class TranslateLLMClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        max_tokens: int | None = None,
        batch_size: int | None = None,
        max_workers: int | None = None,
        enable_thinking: bool = False,
        extra_body: dict[str, Any] | None = None,
        config: LLMConfig | None = None,
        chat_fn: Callable[..., str] | None = None,
    ) -> None:
        self.batch_size = max(1, batch_size or get_translate_batch_size())
        self.max_workers = max(1, max_workers or get_translate_max_workers())
        self._chat_fn = chat_fn
        self._llm: OpenAICompatLLM | None = None
        if chat_fn is None:
            self._llm = OpenAICompatLLM(
                config=config,
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout=timeout,
                max_tokens=max_tokens,
                enable_thinking=enable_thinking,
                extra_body=extra_body,
            )

    @property
    def api_key(self) -> str:
        if self._llm is None:
            return ""
        return self._llm.api_key

    @property
    def base_url(self) -> str:
        if self._llm is None:
            return ""
        return self._llm.base_url

    @property
    def model(self) -> str:
        if self._llm is None:
            return ""
        return self._llm.model

    @property
    def timeout(self) -> float:
        if self._llm is None:
            return 3600.0
        return self._llm.timeout

    @property
    def max_tokens(self) -> int:
        if self._llm is None:
            return 81920
        return self._llm.max_tokens

    @property
    def enable_thinking(self) -> bool:
        if self._llm is None:
            return False
        return self._llm.enable_thinking

    def chat(self, *, system_prompt: str, user_content: str) -> str:
        if self._chat_fn is not None:
            return self._chat_fn(system_prompt=system_prompt, user_content=user_content)
        assert self._llm is not None
        return self._llm.chat(system_prompt=system_prompt, user_content=user_content)

    def meta(self) -> dict[str, Any]:
        base = (
            self._llm.meta()
            if self._llm is not None
            else {
                "base_url": "",
                "model": "",
                "timeout": 3600.0,
                "max_tokens": 81920,
                "enable_thinking": False,
                "extra_body": None,
            }
        )
        return {
            **base,
            "batch_size": self.batch_size,
            "max_workers": self.max_workers,
        }


class _RawSink:
    def __init__(self, root: Path | None) -> None:
        self.root = root
        if root is not None:
            root.mkdir(parents=True, exist_ok=True)

    def write(self, stem: str, raw: str, meta: dict[str, Any]) -> None:
        if self.root is None:
            return
        (self.root / f"{stem}.txt").write_text(raw, encoding="utf-8")
        (self.root / f"{stem}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _unit_payload(
    unit: TranslateUnit,
    *,
    contexts: dict[str, dict[str, str]],
) -> dict[str, str]:
    protected, placeholders = protect_formulas(unit.text)
    unit.placeholders = placeholders
    item: dict[str, str] = {"unit_id": unit.unit_id, "text": protected}
    ctx = contexts.get(unit.unit_id) or {}
    if ctx.get("context_title"):
        item["context_title"] = ctx["context_title"]
    if ctx.get("context_prev"):
        item["context_prev"] = ctx["context_prev"]
    return item


def _glossary_hits_for_units(
    units: list[TranslateUnit],
    glossary: list[GlossaryEntry],
) -> list[GlossaryEntry]:
    hits: dict[str, GlossaryEntry] = {}
    for unit in units:
        for entry in hit_glossary_entries(unit.text, glossary):
            hits[entry.source] = entry
    return sorted(hits.values(), key=lambda e: len(e.source), reverse=True)


def _apply_translation(unit: TranslateUnit, translated: str) -> None:
    unit.translated_text = restore_formulas(translated, unit.placeholders)
    unit.status = "translated"
    unit.error = None


def _mark_failed(unit: TranslateUnit, error: str) -> None:
    unit.status = "failed"
    unit.error = error
    unit.translated_text = None


def _retry_single_unit(
    unit: TranslateUnit,
    *,
    llm: TranslateLLMClient,
    target_lang: str,
    source_lang: str | None,
    glossary: list[GlossaryEntry],
    contexts: dict[str, dict[str, str]],
    raw_sink: _RawSink,
    stats: TranslateStats,
    max_retries: int,
) -> None:
    hits = _glossary_hits_for_units([unit], glossary)
    system_prompt = build_translate_system_prompt(
        target_lang=target_lang,
        source_lang=source_lang,
        glossary_entries=hits,
    )
    payload = [_unit_payload(unit, contexts=contexts)]
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        stats.add(item_retries=1)
        started = time.time()
        try:
            raw = llm.chat(
                system_prompt=system_prompt,
                user_content=build_translate_user_content(payload),
            )
            accepted, vmeta = parse_and_validate_batch(raw, expected_ids={unit.unit_id})
            raw_sink.write(
                f"unit_{unit.unit_id}_attempt_{attempt}",
                raw,
                {
                    "unit_ids": [unit.unit_id],
                    "elapsed_sec": round(time.time() - started, 3),
                    **vmeta,
                },
            )
            if unit.unit_id not in accepted:
                stats.add(empty_rejected=1)
                raise ValueError("empty or missing translated_text after retry")
            _apply_translation(unit, accepted[unit.unit_id])
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            stats.add(schema_failures=1)
    _mark_failed(unit, f"item_retry_failed: {last_error}")


def _translate_one_batch(
    batch: list[TranslateUnit],
    *,
    batch_idx: int,
    llm: TranslateLLMClient,
    target_lang: str,
    source_lang: str | None,
    glossary: list[GlossaryEntry],
    contexts: dict[str, dict[str, str]],
    raw_sink: _RawSink,
    stats: TranslateStats,
    max_retries: int,
) -> None:
    hits = _glossary_hits_for_units(batch, glossary)
    system_prompt = build_translate_system_prompt(
        target_lang=target_lang,
        source_lang=source_lang,
        glossary_entries=hits,
    )
    payload = [_unit_payload(u, contexts=contexts) for u in batch]
    expected = {u.unit_id for u in batch}
    accepted: dict[str, str] = {}
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        started = time.time()
        try:
            raw = llm.chat(
                system_prompt=system_prompt,
                user_content=build_translate_user_content(payload),
            )
            accepted, vmeta = parse_and_validate_batch(raw, expected_ids=expected)
            raw_sink.write(
                f"batch_{batch_idx:03d}_attempt_{attempt}",
                raw,
                {
                    "unit_ids": [u.unit_id for u in batch],
                    "elapsed_sec": round(time.time() - started, 3),
                    **vmeta,
                },
            )
            if vmeta["empty_or_missing"]:
                stats.add(empty_rejected=len(vmeta["empty_or_missing"]))
            if vmeta["schema_failures"]:
                stats.add(schema_failures=int(vmeta["schema_failures"]))
            # Keep whatever was accepted; incomplete units go to per-item retry.
            last_error = None
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            raw_sink.write(
                f"batch_{batch_idx:03d}_attempt_{attempt}",
                str(exc),
                {
                    "unit_ids": [u.unit_id for u in batch],
                    "elapsed_sec": round(time.time() - started, 3),
                    "parse_ok": False,
                    "error": str(exc),
                },
            )

    # Apply accepted translations; retry the rest per-unit.
    pending_retry: list[TranslateUnit] = []
    for unit in batch:
        text = accepted.get(unit.unit_id)
        if not text:
            pending_retry.append(unit)
            continue
        try:
            _apply_translation(unit, text)
        except Exception as exc:  # noqa: BLE001
            unit.error = f"restore_failed: {exc}"
            pending_retry.append(unit)

    for unit in pending_retry:
        _retry_single_unit(
            unit,
            llm=llm,
            target_lang=target_lang,
            source_lang=source_lang,
            glossary=glossary,
            contexts=contexts,
            raw_sink=raw_sink,
            stats=stats,
            max_retries=max_retries,
        )

    # If the whole batch never produced anything and retries failed, ensure failed marks.
    if last_error is not None:
        for unit in batch:
            if unit.status == "pending":
                _mark_failed(unit, f"translate_batch_failed: {last_error}")


def prepare_glossary(
    units: list[TranslateUnit],
    *,
    target_lang: str,
    glossary_path: str | Path | None,
    auto_glossary: bool,
    client: TranslateLLMClient,
    output_dir: Path | None,
) -> tuple[list[GlossaryEntry], TranslateStats]:
    stats = TranslateStats(auto_glossary_enabled=auto_glossary)
    manual: list[GlossaryEntry] = []
    if glossary_path:
        manual = load_glossary_csv(glossary_path, target_lang=target_lang)
        stats.glossary_manual = len(manual)

    auto: list[GlossaryEntry] = []
    if auto_glossary:
        auto = extract_glossary_with_llm(
            units,
            chat_fn=client.chat,
            target_lang=target_lang,
        )
        stats.glossary_auto = len(auto)
        if output_dir is not None and auto:
            json_path = output_dir / "glossary_auto.json"
            csv_path = output_dir / "glossary_auto.csv"
            save_glossary(auto, json_path=json_path, csv_path=csv_path)
            stats.paths["glossary_auto_json"] = str(json_path)
            stats.paths["glossary_auto_csv"] = str(csv_path)

    merged = merge_glossaries(auto, manual)
    stats.glossary_total = len(merged)
    return merged, stats


def translate_units(
    units: list[TranslateUnit],
    *,
    target_lang: str = DEFAULT_TARGET_LANG,
    source_lang: str | None = None,
    client: TranslateLLMClient | None = None,
    max_retries: int = 2,
    glossary_path: str | Path | None = None,
    auto_glossary: bool = True,
    output_dir: str | Path | None = None,
    stats_out: TranslateStats | None = None,
) -> list[TranslateUnit]:
    """Translate eligible units in-place and return the same list."""
    llm = client or TranslateLLMClient()
    out_dir = Path(output_dir).expanduser().resolve() if output_dir else None
    llm_raw_dir = out_dir / "llm_raw" if out_dir else None
    raw_sink = _RawSink(llm_raw_dir)

    glossary, gloss_stats = prepare_glossary(
        units,
        target_lang=target_lang,
        glossary_path=glossary_path,
        auto_glossary=auto_glossary,
        client=llm,
        output_dir=out_dir,
    )
    stats = stats_out or gloss_stats
    if stats_out is not None:
        stats.glossary_manual = gloss_stats.glossary_manual
        stats.glossary_auto = gloss_stats.glossary_auto
        stats.glossary_total = gloss_stats.glossary_total
        stats.auto_glossary_enabled = gloss_stats.auto_glossary_enabled
        stats.paths.update(gloss_stats.paths)
    if llm_raw_dir is not None:
        stats.paths["llm_raw"] = str(llm_raw_dir)

    todo = [u for u in units if u.translate and u.status == "pending"]
    if not todo:
        return units

    contexts = build_context_fields(units)
    batches = [
        todo[start : start + llm.batch_size]
        for start in range(0, len(todo), llm.batch_size)
    ]

    def _run_batch(batch_idx: int, batch: list[TranslateUnit]) -> None:
        _translate_one_batch(
            batch,
            batch_idx=batch_idx,
            llm=llm,
            target_lang=target_lang,
            source_lang=source_lang,
            glossary=glossary,
            contexts=contexts,
            raw_sink=raw_sink,
            stats=stats,
            max_retries=max_retries,
        )

    if llm.max_workers == 1 or len(batches) == 1 or llm._chat_fn is not None:
        for idx, batch in enumerate(batches):
            _run_batch(idx, batch)
        return units

    with ThreadPoolExecutor(max_workers=min(llm.max_workers, len(batches))) as pool:
        futures = [
            pool.submit(_run_batch, idx, batch)
            for idx, batch in enumerate(batches)
        ]
        for future in as_completed(futures):
            future.result()

    return units
