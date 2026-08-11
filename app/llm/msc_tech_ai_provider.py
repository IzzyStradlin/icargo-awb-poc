from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

import fitz

from app.interpretation.awb_llm_parser import parse_llm_json

logger = logging.getLogger(__name__)


_MINIMAL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAACklEQVR4nGMAAA3UDAh6xQAAAABJRU5ErkJggg=="
)


class MscTechAiProvider:
    """File-based provider for MSC Tech AI OCR handoff.

    Instead of calling an API directly, this provider writes rendered PNG pages
    to an inbox folder and then waits for a JSON result in an output folder.
    This keeps the user flow transparent while allowing a downstream MSC Tech AI
    worker to process the images and return structured AWB JSON.
    """

    def __init__(
        self,
        png_folder: Optional[str] = None,
        json_folder: Optional[str] = None,
        group_label: Optional[str] = None,
        poll_interval: float = 2.0,
        timeout: float = 1800.0,  # 30 minutes by default so the last JSON can arrive after a slow OCR run
    ) -> None:
        self.png_folder = png_folder or os.getenv("MSC_TECH_PNG_FOLDER", "")
        self.json_folder = json_folder or os.getenv("MSC_TECH_JSON_FOLDER", "")
        self.poll_interval = float(os.getenv("MSC_TECH_POLL_INTERVAL_SEC", str(poll_interval)))
        self.timeout = float(os.getenv("MSC_TECH_TIMEOUT_SEC", str(timeout)))
        self.group_label = group_label or os.getenv("MSC_TECH_GROUP_LABEL", "default")
        self.archive_png_after_success = os.getenv("MSC_TECH_ARCHIVE_PNG_AFTER_SUCCESS", "false").strip().lower() in {
            "1", "true", "yes", "on"
        }
        self.png_folder_path: Optional[Path] = None
        self.json_folder_path: Optional[Path] = None

    def _is_browser_url(self, input_path: str) -> bool:
        return bool(
            input_path
            and input_path.lower().startswith(
                ("http://", "https://", "http:\\", "https:\\")
            )
        )

    def _list_local_one_drive_roots(self) -> list[Path]:
        candidates: set[Path] = set()
        for env_name in (
            "OneDrive",
            "ONEDRIVE",
            "OneDriveCommercial",
            "OneDriveConsumer",
            "ONEDRIVE_COMMERCIAL",
            "ONEDRIVE_CONSUMER",
        ):
            candidate = os.getenv(env_name)
            if candidate:
                candidates.add(Path(candidate))

        home = Path.home()
        for child in home.glob("OneDrive*"):
            if child.is_dir():
                candidates.add(child)

        return [path for path in candidates if path.exists()]

    def _extract_sharepoint_relative_path(self, url: str) -> str:
        parsed = urlparse(url)
        share_path = unquote(parsed.path or "")
        for marker in ("/Shared Documents/", "/Documents/"):
            index = share_path.find(marker)
            if index >= 0:
                return share_path[index + len(marker) :].lstrip("/")

        if parsed.query:
            query = parse_qs(parsed.query)
            for key in ("path", "id"):
                values = query.get(key)
                if values:
                    candidate = unquote(values[0])
                    for marker in ("/Shared Documents/", "/Documents/"):
                        index = candidate.find(marker)
                        if index >= 0:
                            return candidate[index + len(marker) :].lstrip("/")
                    return candidate.lstrip("/")

        raise ValueError(
            "Impossibile interpretare l'URL di SharePoint. Usa un percorso locale sincronizzato con OneDrive o un URL valido di SharePoint/OneDrive."
        )

    def _resolve_sharepoint_url_to_local_path(self, url: str) -> Path:
        relative_path = self._extract_sharepoint_relative_path(url)
        roots = self._list_local_one_drive_roots()
        if not roots:
            raise ValueError(
                "Impossibile trovare una cartella OneDrive locale. Assicurati che la libreria SharePoint sia sincronizzata con OneDrive."
            )

        candidates = []
        for root in roots:
            candidates.extend(
                [
                    root / relative_path,
                    root / "Shared Documents" / relative_path,
                    root / "Documents" / relative_path,
                ]
            )

        for candidate in candidates:
            if candidate.exists():
                return candidate

        visible_roots = ", ".join(str(root) for root in roots)
        raise ValueError(
            "SharePoint URL non risolto in un percorso locale. Assicurati che la cartella sia sincronizzata e prova con un percorso locale esistente. "
            f"Percorsi OneDrive trovati: {visible_roots}"
        )

    def _validate_folder_target(self, input_path: str, label: str) -> Path:
        if not input_path:
            raise ValueError(f"{label} is required for MSC Tech AI mode.")
        if self._is_browser_url(input_path):
            return self._resolve_sharepoint_url_to_local_path(input_path)
        return Path(input_path)

    def _safe_name(self, value: Optional[str]) -> str:
        value = (value or "default").strip()
        return re.sub(r"[^A-Za-z0-9._-]+", "_", value) or "default"

    def _make_png_prefix(
        self,
        awb_number: Optional[str] = None,
        group_label: Optional[str] = None,
        start_page: int = 0,
        end_page: int = 0,
    ) -> str:
        run_id = int(time.time() * 1000)
        if awb_number:
            safe_awb = self._safe_name(awb_number)
            safe_group = self._safe_name(group_label or self.group_label)
            if safe_group and safe_group != self._safe_name(self.group_label):
                return f"{safe_group}_{safe_awb}_{run_id}"
            return f"{safe_awb}_{run_id}"

        safe_group = self._safe_name(group_label or self.group_label)
        if start_page and end_page and start_page != end_page:
            return f"{safe_group}_{start_page:03d}_{end_page:03d}_{run_id}"
        if start_page:
            return f"{safe_group}_{start_page:03d}_{run_id}"
        return f"{safe_group}_{run_id}"

    def _render_pngs(
        self,
        pdf_bytes: bytes,
        start_page: int,
        end_page: int,
        page_rotations: Optional[dict] = None,
        awb_number: Optional[str] = None,
        group_label: Optional[str] = None,
    ) -> list[Path]:
        self.png_folder_path.mkdir(parents=True, exist_ok=True)
        base_name = self._make_png_prefix(
            awb_number=awb_number,
            group_label=group_label,
            start_page=start_page,
            end_page=end_page,
        )

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            total = len(doc)
            fitz_start = max(0, start_page - 1) if start_page > 0 else 0
            fitz_end = max(0, end_page - 1) if end_page > 0 else fitz_start
            written: list[Path] = []
            for idx, p in enumerate(range(fitz_start, min(fitz_end + 1, total)), start=1):
                page = doc[p]
                page_num = p + 1
                page_path = self.png_folder_path / f"{base_name}_page_{page_num:03d}.png"
                page_path.write_bytes(page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).tobytes("png"))
                written.append(page_path)
            doc.close()
            return written or [self.png_folder_path / f"{base_name}_page_001.png"]
        except Exception:
            fallback_path = self.png_folder_path / f"{base_name}_page_001.png"
            fallback_path.write_bytes(_MINIMAL_PNG)
            return [fallback_path]

    def prepare_payload(
        self,
        pdf_bytes: bytes,
        start_page: int = 0,
        end_page: int = 0,
        page_rotations: Optional[dict] = None,
        awb_number: Optional[str] = None,
        group_label: Optional[str] = None,
    ) -> dict:
        self.png_folder_path = self._validate_folder_target(
            self.png_folder,
            "PNG inbox folder",
        )
        self.json_folder_path = self._validate_folder_target(
            self.json_folder,
            "JSON output folder",
        )
        rendered_files = self._render_pngs(
            pdf_bytes,
            start_page=start_page,
            end_page=end_page,
            page_rotations=page_rotations,
            awb_number=awb_number,
            group_label=group_label,
        )
        payload = {
            "awb_number": awb_number or "",
            "group_label": group_label or self.group_label,
            "png_path": str(rendered_files[0]),
            "png_files": [str(path) for path in rendered_files],
            "requested_at": time.time(),
        }
        return payload

    @staticmethod
    def _score_result_data(data: dict) -> int:
        """Score a parsed JSON by data completeness. Higher = better quality."""
        if not isinstance(data, dict):
            return -1
        # Nested mawb+hawbs format is the most complete output
        if "mawb" in data and "hawbs" in data:
            base = 100
            mawb = data.get("mawb") or {}
            mawb_fields = sum(
                1 for v in (mawb.values() if isinstance(mawb, dict) else [])
                if v is not None and v != ""
            )
            hawb_count = len(data["hawbs"]) if isinstance(data.get("hawbs"), list) else 0
            return base + mawb_fields + hawb_count * 20
        # Flat format: score by number of non-null fields
        return sum(1 for v in data.values() if v is not None and v != "")

    @staticmethod
    def _extract_hawb_number_from_record(hawb: dict) -> str:
        if not isinstance(hawb, dict):
            return ""
        return str(
            hawb.get("hawb_number")
            or hawb.get("hawbNumber")
            or hawb.get("hawb")
            or hawb.get("houseAirwaybillNumber")
            or hawb.get("hawbNo")
            or ""
        ).strip()

    @staticmethod
    def _normalize_hawb_dedupe_key(hawb_number: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", (hawb_number or "").upper())

    @staticmethod
    def _extract_hawb_master_awb_ref(hawb: dict) -> str:
        if not isinstance(hawb, dict):
            return ""
        return str(
            hawb.get("mawb_number_reference")
            or hawb.get("mawb_number")
            or hawb.get("mawb")
            or hawb.get("master_awb")
            or hawb.get("master_awb_number")
            or hawb.get("master_awb_no")
            or hawb.get("masterAirwaybillNumber")
            or hawb.get("masterAwb")
            or hawb.get("masterAwbNumber")
            or hawb.get("parent_awb")
            or hawb.get("parentAwb")
            or ""
        ).strip()

    @staticmethod
    def _normalize_awb_ref(value: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", (value or "").upper())

    def _is_same_master_awb(self, left: str, right: str) -> bool:
        l = self._normalize_awb_ref(left)
        r = self._normalize_awb_ref(right)
        if not l or not r:
            return False
        if l == r:
            return True

        l_digits = "".join(ch for ch in l if ch.isdigit())
        r_digits = "".join(ch for ch in r if ch.isdigit())
        if len(l_digits) >= 11 and len(r_digits) >= 11:
            return l_digits[-11:] == r_digits[-11:]
        return False

    def _merge_batch_results(self, results: list) -> dict:
        """
        Merge multiple per-page JSON results into one comprehensive AWB record.

        Strategy:
        - MAWB fields: use the result with the most non-null fields across all pages.
        - HAWBs: collect all unique HAWBs from every result in the batch.

        This handles the common case where the AWB form page (rich MAWB data, no
        HAWBs) and the cargo manifest page (mawb: null, multiple HAWBs) are two
        separate JSONs from the same document block.
        """
        best_mawb: dict = {}
        best_mawb_score: int = -1
        all_hawbs: list = []
        seen_hawb_numbers: set = set()
        warnings: list[str] = []
        assignment_mode = "group_fallback"

        for data in results:
            if not isinstance(data, dict):
                continue

            # Normalise to mawb / hawbs
            if "mawb" in data and "hawbs" in data:
                mawb = data.get("mawb") or {}
                hawbs = data.get("hawbs") or []
            else:
                # Flat AWB format — treat as MAWB data, no HAWBs
                mawb = data
                hawbs = []

            # Pick the MAWB with the most non-null fields
            if isinstance(mawb, dict):
                score = sum(1 for v in mawb.values() if v is not None and v != "")
                if score > best_mawb_score:
                    best_mawb_score = score
                    best_mawb = mawb

            # Collect unique HAWBs
            for hawb in (hawbs if isinstance(hawbs, list) else []):
                if not isinstance(hawb, dict):
                    continue
                hawb_num = self._extract_hawb_number_from_record(hawb)
                dedupe_key = self._normalize_hawb_dedupe_key(hawb_num)
                if dedupe_key and dedupe_key not in seen_hawb_numbers:
                    # Canonicalize the identifier key for downstream UI/diff code.
                    hawb_canonical = dict(hawb)
                    hawb_canonical["hawb_number"] = hawb_num
                    all_hawbs.append(hawb_canonical)
                    seen_hawb_numbers.add(dedupe_key)

        mawb_number = str((best_mawb or {}).get("awb_number") or "").strip()
        if mawb_number and all_hawbs:
            with_ref: list[dict] = []
            without_ref: list[dict] = []
            matched_with_ref: list[dict] = []

            for hawb in all_hawbs:
                ref = self._extract_hawb_master_awb_ref(hawb)
                if ref:
                    with_ref.append(hawb)
                    if self._is_same_master_awb(ref, mawb_number):
                        matched_with_ref.append(hawb)
                else:
                    without_ref.append(hawb)

            if with_ref and matched_with_ref:
                # Confirmed assignment by HAWB master reference when available.
                # Keep no-ref records as group fallback; drop explicit mismatches.
                all_hawbs = matched_with_ref + without_ref
                assignment_mode = "confirmed_by_hawb_master_ref"
                dropped = len(with_ref) - len(matched_with_ref)
                if dropped > 0:
                    warnings.append(
                        f"Ignored {dropped} HAWB(s) with explicit MAWB reference not matching {mawb_number}."
                    )
            elif not with_ref:
                # Requested behavior: if HAWB docs do not expose the MAWB number,
                # keep group-based assignment and signal it to the UI.
                assignment_mode = "group_fallback"
                warnings.append("MAWB number not found in the HAWB doc; using group assignment fallback.")
            else:
                # A MAWB ref exists in HAWB records but none matched the selected MAWB.
                # Keep fallback behavior but surface a stronger warning.
                assignment_mode = "group_fallback"
                warnings.append(
                    f"HAWB docs contain MAWB reference(s), but none matches {mawb_number}; using group assignment fallback."
                )

        merged = {
            "mawb": best_mawb,
            "hawbs": all_hawbs,
            "hawb_assignment_mode": assignment_mode,
        }
        if warnings:
            merged["warnings"] = warnings
        return merged

    def _extract_batch_prefix_from_png_files(self, png_files: list) -> Optional[str]:
        """
        Extract the batch prefix from PNG filenames.
        
        MSC Tech AI renders PDFs with names like:
          - "233-10167566_page_0000.png"    → prefix: "233-10167566"
          - "default_001_page_0000.png"     → prefix: "default_001"
        
        The same prefix appears in the output JSON filenames, so we can use it
        to match JSON files even if we don't know the MAWB number.
        """
        if not png_files:
            return None
        
        # Get the first PNG file's stem and extract the prefix before "_page_"
        try:
            first_png = Path(png_files[0])
            stem = first_png.stem  # e.g. "233-10167566_page_0000" or "default_001_page_0000"
            
            # Split on "_page_" and take the first part
            parts = stem.split("_page_")
            if len(parts) >= 1:
                prefix = parts[0].lower()
                logger.debug(f"[MSC Tech AI] Extracted batch prefix from PNG: {prefix}")
                return prefix
        except Exception as e:
            logger.warning(f"[MSC Tech AI] Failed to extract batch prefix from PNG files: {e}")
        
        return None

    def _find_all_result_files(self, payload: dict) -> list:
        """Return all unarchived JSON files for this AWB batch.
        
        MSC Tech AI names output files starting with the MAWB number:
        e.g. "233-10167566_page_0123.png_timestamp.json"
        
        Simple strategy: collect all unarchived files that start with the MAWB.
        Falls back to batch prefix extracted from PNG files if MAWB is not available.
        """
        awb_number = (payload.get("awb_number") or "").strip()
        results: list[Path] = []
        
        if self.json_folder_path is None:
            return results

        # Intentionally scan only the configured output root folder.
        # Subfolders (for example "Copied") are ignored by design.
        all_json_files = sorted(
            path
            for path in self.json_folder_path.glob("*.json")
            if path.is_file()
        )

        # PRIORITY: exact batch-prefix match from the current rendered PNG names.
        # This is the most reliable strategy and avoids cross-run collisions.
        png_files = payload.get("png_files", [])
        batch_prefix = self._extract_batch_prefix_from_png_files(png_files)
        if batch_prefix:
            logger.debug(
                "[MSC Tech AI] PRIORITY search: looking for files starting with batch prefix '%s'",
                batch_prefix,
            )
            for path in all_json_files:
                name_lower = path.name.lower()
                if name_lower.startswith(f"{batch_prefix}_") or name_lower.startswith(f"{batch_prefix}."):
                    results.append(path)
                    logger.debug(f"[MSC Tech AI] PRIORITY found: {path.name}")
            if results:
                logger.info(
                    "[MSC Tech AI] PRIORITY strategy successful: found %d files by batch prefix",
                    len(results),
                )
                return results
        
        # PRIMARY: Search by MAWB number if available
        if awb_number:
            safe_awb = self._safe_name(awb_number).lower()
            logger.debug(f"[MSC Tech AI] PRIMARY search: looking for files starting with '{safe_awb}'")
            for path in all_json_files:
                name_lower = path.name.lower()
                if name_lower.startswith(f"{safe_awb}_") or name_lower.startswith(f"{safe_awb}."):
                    results.append(path)
                    logger.debug(f"[MSC Tech AI] PRIMARY found: {path.name}")
            if results:
                logger.info(f"[MSC Tech AI] PRIMARY strategy successful: found {len(results)} files")
                return results
            logger.debug(f"[MSC Tech AI] PRIMARY strategy failed: no files found with prefix '{safe_awb}'")
        
        # FALLBACK: Search by batch prefix extracted from PNG filenames
        # This handles the case where presplitter failed to extract MAWB,
        # so files were saved with batch prefix (e.g. "default_001_page_0123.json")
        
        if batch_prefix:
            logger.debug(f"[MSC Tech AI] FALLBACK search: looking for files starting with batch prefix '{batch_prefix}'")
            for path in all_json_files:
                name_lower = path.name.lower()
                if name_lower.startswith(f"{batch_prefix}_") or name_lower.startswith(f"{batch_prefix}."):
                    results.append(path)
                    logger.debug(f"[MSC Tech AI] FALLBACK found: {path.name}")
            if results:
                logger.info(f"[MSC Tech AI] FALLBACK strategy successful: found {len(results)} files by batch prefix")
                return results
            logger.debug(f"[MSC Tech AI] FALLBACK strategy failed: no files found with batch prefix '{batch_prefix}'")

        # SECOND FALLBACK: match JSON names that contain one of the rendered PNG stems.
        # Example: "result_233-10167566_page_001.png_2026-07-14_02-44.json"
        png_stems = []
        for png_path_str in payload.get("png_files", []):
            try:
                png_stems.append(Path(png_path_str).stem.lower())
            except Exception:
                continue
        if png_stems:
            for path in all_json_files:
                name_lower = path.name.lower()
                if any(stem and stem in name_lower for stem in png_stems):
                    results.append(path)
            if results:
                # De-duplicate while preserving order.
                unique_results = list(dict.fromkeys(results))
                logger.info(
                    "[MSC Tech AI] PNG-stem strategy successful: found %d files",
                    len(unique_results),
                )
                return unique_results

        # LAST FALLBACK: use request timestamp window when naming is completely custom.
        requested_at = float(payload.get("requested_at") or 0.0)
        if requested_at > 0:
            for path in all_json_files:
                try:
                    # Include files created after the request started.
                    if path.stat().st_mtime >= (requested_at - 2.0):
                        results.append(path)
                except Exception:
                    continue
            if results:
                unique_results = list(dict.fromkeys(results))
                logger.info(
                    "[MSC Tech AI] Timestamp fallback successful: found %d candidate files",
                    len(unique_results),
                )
                return unique_results
        
        logger.warning(f"[MSC Tech AI] No JSON files found for AWB {awb_number or '(unknown)'} - will retry or timeout")
        return results

    def _archive_result_file(self, result_file: Path) -> Path:
        if self.json_folder_path is None:
            return result_file

        processed_dir = self.json_folder_path / "Processed"
        processed_dir.mkdir(parents=True, exist_ok=True)

        destination = processed_dir / result_file.name
        if destination.exists():
            unique_suffix = int(time.time() * 1000)
            destination = processed_dir / f"{result_file.stem}_{unique_suffix}{result_file.suffix}"

        result_file.replace(destination)
        return destination

    def _archive_png_file(self, png_file: Path) -> Path:
        if self.png_folder_path is None:
            return png_file

        processed_dir = self.png_folder_path / "Processed"
        processed_dir.mkdir(parents=True, exist_ok=True)

        destination = processed_dir / png_file.name
        if destination.exists():
            unique_suffix = int(time.time() * 1000)
            destination = processed_dir / f"{png_file.stem}_{unique_suffix}{png_file.suffix}"

        png_file.replace(destination)
        return destination

    def _archive_batch_png_files(self, payload: dict) -> None:
        png_files = payload.get("png_files", [])
        if not isinstance(png_files, list):
            return

        for png_path_str in png_files:
            try:
                png_path = Path(png_path_str)
                if not png_path.exists():
                    logger.debug("[MSC Tech AI] PNG already moved/removed: %s", png_path)
                    continue
                archived = self._archive_png_file(png_path)
                logger.info(
                    "[MSC Tech AI] Archived PNG %s → %s/%s",
                    png_path.name,
                    archived.parent.name,
                    archived.name,
                )
            except Exception as e:
                logger.warning("[MSC Tech AI] Failed to archive PNG %s: %s", png_path_str, e)

    def _filter_files_for_current_request(self, files: list[Path], requested_at: float) -> list[Path]:
        """Keep only files created for the current request window."""
        if requested_at <= 0:
            # Backward-compatible behavior for tests/legacy payloads.
            return list(dict.fromkeys(files))

        filtered: list[Path] = []
        for path in files:
            try:
                # Allow a small clock skew window.
                if path.stat().st_mtime >= (requested_at - 2.0):
                    filtered.append(path)
            except Exception:
                continue
        return list(dict.fromkeys(filtered))

    def _count_matched_png_stems(self, files: list[Path], png_files: list[str]) -> int:
        """Count how many expected PNG stems appear in result filenames."""
        expected_stems = []
        for png_path in png_files:
            try:
                expected_stems.append(Path(png_path).stem.lower())
            except Exception:
                continue

        if not expected_stems:
            return 0

        matched: set[str] = set()
        for result_file in files:
            name = result_file.name.lower()
            for stem in expected_stems:
                if stem and stem in name:
                    matched.add(stem)

        return len(matched)

    def _collect_files_matching_expected_pngs(self, files: list[Path], png_files: list[str]) -> list[Path]:
        """Return at most one JSON file per expected PNG stem.

        If multiple candidates match the same PNG stem, keep the newest one.
        """
        expected_stems: list[str] = []
        for png_path in png_files:
            try:
                stem = Path(png_path).stem.lower()
                if stem:
                    expected_stems.append(stem)
            except Exception:
                continue

        if not expected_stems:
            return []

        best_by_stem: dict[str, Path] = {}
        best_mtime: dict[str, float] = {}

        for result_file in files:
            name = result_file.name.lower()
            for stem in expected_stems:
                if stem and stem in name:
                    try:
                        mtime = result_file.stat().st_mtime
                    except Exception:
                        mtime = -1.0
                    prev = best_mtime.get(stem, -1.0)
                    if mtime >= prev:
                        best_mtime[stem] = mtime
                        best_by_stem[stem] = result_file

        # Preserve expected order for easier debug logs/comparison.
        ordered_unique: list[Path] = []
        seen_paths: set[Path] = set()
        for stem in expected_stems:
            path = best_by_stem.get(stem)
            if path is not None and path not in seen_paths:
                ordered_unique.append(path)
                seen_paths.add(path)

        return ordered_unique

    def collect_result(self, payload: dict) -> dict:
        """Poll for JSON results until ALL expected files appear (based on PNG count)."""
        # Expected number of JSON files = number of PNG files rendered for this batch
        # MSC Tech AI produces one JSON per PNG, so we wait until we have them all
        png_files = payload.get("png_files", [])
        expected_count = len(png_files)
        awb_number = payload.get("awb_number", "?")
        requested_at = float(payload.get("requested_at") or 0.0)
        
        if expected_count == 0:
            raise ValueError("No PNG files in payload - cannot determine expected JSON count")
        
        logger.info(
            f"[MSC Tech AI] AWB {awb_number}: Polling for {expected_count} JSON files (matching {expected_count} PNG files)"
        )
        logger.info(
            f"[MSC Tech AI] AWB {awb_number}: waiting up to {self.timeout:.0f}s for the last JSON file to arrive"
        )

        no_progress_count = 0
        max_no_progress = max(30, int(self.timeout / max(self.poll_interval, 1.0)))
        last_file_count = 0
        deadline = time.time() + self.timeout
        
        while time.time() < deadline:
            all_batch_files = self._find_all_result_files(payload)
            fresh_batch_files = self._filter_files_for_current_request(all_batch_files, requested_at)

            # Strict rule: we count only JSON files that match expected PNG stems.
            strict_fresh_files = self._collect_files_matching_expected_pngs(fresh_batch_files, png_files)
            strict_all_files = self._collect_files_matching_expected_pngs(all_batch_files, png_files)

            # If mtimes are unreliable (cloud sync), allow fallback to all files,
            # but still only for JSON files matching expected PNG stems.
            if requested_at > 0 and len(strict_fresh_files) < expected_count and len(strict_all_files) >= expected_count:
                logger.warning(
                    "[MSC Tech AI] AWB %s: timestamp drift suspected (fresh-matched=%d, all-matched=%d). Using stem-matched files.",
                    awb_number,
                    len(strict_fresh_files),
                    len(strict_all_files),
                )
                batch_files = strict_all_files
            elif requested_at > 0:
                batch_files = strict_fresh_files
            else:
                batch_files = strict_all_files
            
            # LAST RESORT: If still no files found, search by broad timestamp window.
            # Keep this conservative to avoid picking up historical JSONs from prior batches.
            if not batch_files and self.json_folder_path:
                if requested_at > 0:
                    for path in sorted(self.json_folder_path.glob("*.json")):
                        try:
                            if path.is_file() and path.stat().st_mtime >= (requested_at - 2.0):
                                batch_files.append(path)
                        except Exception:
                            continue
                    if batch_files:
                        batch_files = list(dict.fromkeys(batch_files))
            
            matched_stems_count = len(batch_files)

            # Settle only when we have one matched JSON per expected PNG.
            if matched_stems_count >= expected_count:
                logger.info(
                    "[MSC Tech AI] AWB %s: Found all %d JSON files (stem-matched=%d)",
                    awb_number,
                    expected_count,
                    matched_stems_count,
                )
                # Parse and merge them
                parsed: list = []
                for path in batch_files:
                    try:
                        raw = path.read_text(encoding="utf-8")
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            data = parse_llm_json(raw).data
                        if isinstance(data, dict):
                            parsed.append((data, path))
                            logger.debug(f"[MSC Tech AI] Parsed {path.name}: {len(data)} fields")
                    except Exception as e:
                        logger.warning(f"[MSC Tech AI] Failed to parse {path.name}: {e}")
                        continue

                if parsed:
                    merged = self._merge_batch_results([d for d, _ in parsed])
                    mawb_fields = len(merged.get("mawb") or {})
                    hawb_count = len(merged.get("hawbs") or [])
                    logger.info(f"[MSC Tech AI] AWB {awb_number}: Merged into MAWB({mawb_fields} fields) + {hawb_count} HAWBs")
                    
                    # Archive ALL consumed files
                    processed_dir = (self.json_folder_path / "Processed").resolve()
                    for _, path in parsed:
                        if path.parent.resolve() != processed_dir:
                            try:
                                archived = self._archive_result_file(path)
                                logger.info(f"[MSC Tech AI] Archived {path.name} → {archived.parent.name}/{archived.name}")
                            except Exception as e:
                                logger.error(f"[MSC Tech AI] Failed to archive {path.name}: {e}")
                        else:
                            logger.debug(f"[MSC Tech AI] {path.name} is already in Processed, skipping archive")

                    # Optional: archive consumed PNG inputs. Disabled by default
                    # because some deployments let the external AI service manage
                    # PNG lifecycle directly.
                    if self.archive_png_after_success:
                        self._archive_batch_png_files(payload)
                    return merged
            
            # Track progress: if we got more files, reset the counter
            if matched_stems_count > last_file_count:
                logger.info(f"[MSC Tech AI] AWB {awb_number}: Progress {matched_stems_count}/{expected_count} files found")
                no_progress_count = 0
                last_file_count = matched_stems_count
            else:
                no_progress_count += 1
                if no_progress_count <= 3:
                    logger.debug(f"[MSC Tech AI] AWB {awb_number}: Waiting ({matched_stems_count}/{expected_count})...")
                elif no_progress_count % min(30, max_no_progress) == 0:
                    logger.info(
                        f"[MSC Tech AI] AWB {awb_number}: still waiting after {no_progress_count} polls ({matched_stems_count}/{expected_count} files found)"
                    )

            time.sleep(self.poll_interval)
        
        raise TimeoutError(
            f"MSC Tech AI timeout: expected {expected_count} JSON files for AWB {awb_number}, "
            f"but only found {len(self._collect_files_matching_expected_pngs(self._find_all_result_files(payload), png_files))} stem-matched files after {self.timeout:.0f} seconds. "
            f"JSON folder: {self.json_folder_path}"
        )

    def extract_awb_json(
        self,
        pdf_bytes: bytes,
        start_page: int = 0,
        end_page: int = 0,
        page_rotations: Optional[dict] = None,
        awb_number: Optional[str] = None,
        group_label: Optional[str] = None,
    ) -> str:
        payload = self.prepare_payload(
            pdf_bytes,
            start_page=start_page,
            end_page=end_page,
            page_rotations=page_rotations,
            awb_number=awb_number,
            group_label=group_label or self.group_label,
        )
        result = self.collect_result(payload)
        return json.dumps(result)

    def extract_mawb_with_hawbs_json(
        self,
        pdf_bytes: bytes,
        start_page: int = 0,
        end_page: int = 0,
        page_rotations: Optional[dict] = None,
        awb_number: Optional[str] = None,
        group_label: Optional[str] = None,
    ) -> str:
        payload = self.prepare_payload(
            pdf_bytes,
            start_page=start_page,
            end_page=end_page,
            page_rotations=page_rotations,
            awb_number=awb_number,
            group_label=group_label or self.group_label,
        )
        result = self.collect_result(payload)
        return json.dumps(result)

    def extract_from_text(self, ocr_text: str, awb_number: Optional[str] = None, group_label: Optional[str] = None) -> str:
        payload = {
            "awb_number": awb_number or "",
            "group_label": group_label or self.group_label,
            "png_path": "",
            "png_files": [],
            "requested_at": time.time(),
        }
        result = self.collect_result(payload)
        return json.dumps(result)
