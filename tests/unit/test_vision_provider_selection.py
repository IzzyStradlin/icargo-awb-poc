import os
from pathlib import Path

import pytest

from app.interpretation.awb_vision_extractor import AwbVisionExtractor
from app.llm import msc_tech_ai_provider
from app.llm.msc_tech_ai_provider import MscTechAiProvider


class DummyProvider:
    def extract_mawb_with_hawbs_json(self, *args, **kwargs):
        return '{"mawb": null, "hawbs": []}'


class ConsolidatedDummyProvider:
    def extract_mawb_with_hawbs_json(self, *args, **kwargs):
        return (
            '{"document_type": "CONSOLIDATED_MAWB", '
            '"mawb": {"awb_number": "233-10169294"}, '
            '"house_awbs": [{"hawb_number": "MIL0333227"}], '
            '"reconciliation": {"status": "WARNING"}, '
            '"warnings": [{"code": "GROSS_WEIGHT_MISMATCH", "message": "Check weights"}]}'
        )


def test_awb_vision_extractor_can_use_msc_tech_provider(tmp_path):
    extractor = AwbVisionExtractor(provider_name="msc_tech_ai")

    assert isinstance(extractor._provider, MscTechAiProvider)


def test_awb_vision_extractor_forwards_msc_tech_provider(tmp_path):
    extractor = AwbVisionExtractor(
        provider_name="msc_tech_ai",
    )

    assert isinstance(extractor._provider, MscTechAiProvider)


def test_msc_tech_provider_writes_and_collects_payload(tmp_path):
    png_dir = tmp_path / "png-in"
    json_dir = tmp_path / "json-out"
    png_dir.mkdir()
    json_dir.mkdir()

    provider = MscTechAiProvider(png_folder=str(png_dir), json_folder=str(json_dir))
    payload = provider.prepare_payload(
        pdf_bytes=b"PDF",
        start_page=1,
        end_page=1,
        page_rotations=None,
        awb_number="123-45678901",
        group_label="group-a",
    )

    assert payload["awb_number"] == "123-45678901"
    assert payload["group_label"] == "group-a"
    assert payload["png_path"].startswith(str(png_dir))
    assert Path(payload["png_path"]).exists()

    output_path = json_dir / "123-45678901_page_001.png_2026-07-14_02-44.json"
    output_path.write_text('{"mawb": {}, "hawbs": []}', encoding="utf-8")

    result = provider.collect_result(payload)
    assert result["mawb"] == {}
    assert result["hawbs"] == []


def test_msc_tech_provider_does_not_archive_png_files_by_default(tmp_path):
    png_dir = tmp_path / "png-in"
    json_dir = tmp_path / "json-out"
    png_dir.mkdir()
    json_dir.mkdir()

    provider = MscTechAiProvider(png_folder=str(png_dir), json_folder=str(json_dir))
    payload = provider.prepare_payload(
        pdf_bytes=b"PDF",
        start_page=1,
        end_page=1,
        page_rotations=None,
        awb_number="123-45678901",
        group_label="group-a",
    )

    input_png = Path(payload["png_files"][0])
    assert input_png.exists()

    output_path = json_dir / f"{Path(payload['png_files'][0]).stem}.json"
    output_path.write_text('{"mawb": {}, "hawbs": []}', encoding="utf-8")

    _ = provider.collect_result(payload)

    assert input_png.exists()
    archived_png = png_dir / "Processed" / input_png.name
    assert not archived_png.exists()


def test_msc_tech_provider_can_archive_consumed_png_files_when_enabled(monkeypatch, tmp_path):
    png_dir = tmp_path / "png-in"
    json_dir = tmp_path / "json-out"
    png_dir.mkdir()
    json_dir.mkdir()

    monkeypatch.setenv("MSC_TECH_ARCHIVE_PNG_AFTER_SUCCESS", "true")
    provider = MscTechAiProvider(png_folder=str(png_dir), json_folder=str(json_dir))
    payload = provider.prepare_payload(
        pdf_bytes=b"PDF",
        start_page=1,
        end_page=1,
        page_rotations=None,
        awb_number="123-45678901",
        group_label="group-a",
    )

    input_png = Path(payload["png_files"][0])
    assert input_png.exists()

    output_path = json_dir / f"{Path(payload['png_files'][0]).stem}.json"
    output_path.write_text('{"mawb": {}, "hawbs": []}', encoding="utf-8")

    _ = provider.collect_result(payload)

    assert not input_png.exists()
    archived_png = png_dir / "Processed" / input_png.name
    assert archived_png.exists()


def test_msc_tech_provider_preserves_hawbs_with_alternate_number_keys():
    provider = MscTechAiProvider()

    merged = provider._merge_batch_results(
        [
            {
                "mawb": {"awb_number": "233-10300566"},
                "hawbs": [
                    {"houseAirwaybillNumber": "MIL0332355", "pieces": 1},
                    {"hawbNumber": "MIL0332356", "pieces": 2},
                    {"hawb": "MIL0333367", "pieces": 3},
                ],
            }
        ]
    )

    got_numbers = {h.get("hawb_number") for h in merged.get("hawbs", [])}
    assert got_numbers == {"MIL0332355", "MIL0332356", "MIL0333367"}


def test_msc_tech_provider_confirms_hawbs_by_master_reference_when_available():
    provider = MscTechAiProvider()

    merged = provider._merge_batch_results(
        [
            {
                "mawb": {"awb_number": "233-10300566"},
                "hawbs": [
                    {"hawb_number": "MIL0332355", "mawb_number_reference": "233-10300566"},
                    {"hawb_number": "MIL0332356", "mawb_number_reference": "233-10300566"},
                    {"hawb_number": "MIL0333367", "mawb_number_reference": "233-10399999"},
                ],
            }
        ]
    )

    assert merged.get("hawb_assignment_mode") == "confirmed_by_hawb_master_ref"
    got_numbers = {h.get("hawb_number") for h in merged.get("hawbs", [])}
    assert got_numbers == {"MIL0332355", "MIL0332356"}
    assert any("Ignored" in w for w in merged.get("warnings", []))


def test_msc_tech_provider_falls_back_when_hawb_master_reference_not_found():
    provider = MscTechAiProvider()

    merged = provider._merge_batch_results(
        [
            {
                "mawb": {"awb_number": "233-10300566"},
                "hawbs": [
                    {"hawb_number": "MIL0332355"},
                    {"hawb_number": "MIL0332356"},
                ],
            }
        ]
    )

    assert merged.get("hawb_assignment_mode") == "group_fallback"
    got_numbers = {h.get("hawb_number") for h in merged.get("hawbs", [])}
    assert got_numbers == {"MIL0332355", "MIL0332356"}
    assert "MAWB number not found in the HAWB doc; using group assignment fallback." in merged.get("warnings", [])


def test_msc_tech_provider_uses_unique_fallback_prefix_when_awb_number_is_missing(tmp_path):
    png_dir = tmp_path / "png-in"
    json_dir = tmp_path / "json-out"
    png_dir.mkdir()
    json_dir.mkdir()

    provider = MscTechAiProvider(png_folder=str(png_dir), json_folder=str(json_dir))

    payload_1 = provider.prepare_payload(
        pdf_bytes=b"PDF",
        start_page=1,
        end_page=2,
        page_rotations=None,
        awb_number=None,
        group_label="group-a",
    )
    payload_2 = provider.prepare_payload(
        pdf_bytes=b"PDF",
        start_page=3,
        end_page=4,
        page_rotations=None,
        awb_number=None,
        group_label="group-a",
    )

    assert payload_1["png_path"] != payload_2["png_path"]
    assert Path(payload_1["png_path"]).exists()
    assert Path(payload_2["png_path"]).exists()


def test_awb_vision_extractor_normalizes_null_mawb_payload():
    extractor = AwbVisionExtractor(provider_name="msc_tech_ai")
    extractor._provider = DummyProvider()

    result = extractor.extract_mawb_with_hawbs(b"PDF")

    assert isinstance(result, dict)
    assert isinstance(result["mawb"], dict)
    assert result["mawb"] == {}
    assert result["hawbs"] == []


def test_awb_vision_extractor_normalizes_consolidated_house_awbs_payload():
    extractor = AwbVisionExtractor(provider_name="msc_tech_ai")
    extractor._provider = ConsolidatedDummyProvider()

    result = extractor.extract_mawb_with_hawbs(b"PDF")

    assert result["document_type"] == "CONSOLIDATED_MAWB"
    assert result["hawbs"] == [{"hawb_number": "MIL0333227"}]
    assert result["reconciliation"]["status"] == "WARNING"
    assert result["warnings"][0]["code"] == "GROSS_WEIGHT_MISMATCH"


def test_msc_tech_provider_does_not_settle_before_all_expected_json_files_arrive(monkeypatch, tmp_path):
    png_dir = tmp_path / "png-in"
    json_dir = tmp_path / "json-out"
    png_dir.mkdir()
    json_dir.mkdir()

    provider = MscTechAiProvider(
        png_folder=str(png_dir),
        json_folder=str(json_dir),
        poll_interval=0.0,
        timeout=0.01,
    )

    payload = provider.prepare_payload(
        pdf_bytes=b"PDF",
        start_page=1,
        end_page=2,
        page_rotations=None,
        awb_number="233-10166763",
        group_label="group-a",
    )
    payload["png_files"] = [
        str(png_dir / "233-10166763_page_001.png"),
        str(png_dir / "233-10166763_page_002.png"),
    ]
    payload["requested_at"] = 0.0

    matching_result = json_dir / "233-10166763_page_001.png_2026-07-14_02-44.json"
    matching_result.write_text('{"mawb": {"awb_number": "233-10166763"}, "hawbs": []}', encoding="utf-8")

    now = 0.0

    def fake_time():
        nonlocal now
        now += 0.01
        return now

    monkeypatch.setattr(msc_tech_ai_provider.time, "time", fake_time)
    monkeypatch.setattr(msc_tech_ai_provider.time, "sleep", lambda *_args, **_kwargs: None)

    with pytest.raises(TimeoutError):
        provider.collect_result(payload)


def test_msc_tech_provider_ignores_stale_json_files_from_previous_runs(monkeypatch, tmp_path):
    png_dir = tmp_path / "png-in"
    json_dir = tmp_path / "json-out"
    png_dir.mkdir()
    json_dir.mkdir()

    provider = MscTechAiProvider(
        png_folder=str(png_dir),
        json_folder=str(json_dir),
        poll_interval=0.0,
        timeout=0.05,
    )

    payload = provider.prepare_payload(
        pdf_bytes=b"PDF",
        start_page=1,
        end_page=2,
        page_rotations=None,
        awb_number="233-10167566",
        group_label="group-a",
    )

    current_batch_prefix = Path(payload["png_files"][0]).stem.split("_page_")[0]
    payload["png_files"] = [
        str(png_dir / f"{current_batch_prefix}_page_001.png"),
        str(png_dir / f"{current_batch_prefix}_page_002.png"),
    ]

    stale_result_1 = json_dir / "233-10167566_page_001.png_old.json"
    stale_result_1.write_text('{"mawb": {"awb_number": "233-10167566"}, "hawbs": []}', encoding="utf-8")
    stale_result_2 = json_dir / "233-10167566_page_002.png_old.json"
    stale_result_2.write_text('{"mawb": {"awb_number": "233-10167566"}, "hawbs": []}', encoding="utf-8")

    requested_at = 1_000.0
    payload["requested_at"] = requested_at

    os.utime(stale_result_1, (requested_at - 100.0, requested_at - 100.0))
    os.utime(stale_result_2, (requested_at - 100.0, requested_at - 100.0))

    # Only one fresh file arrives for the current request -> still incomplete.
    fresh_result = json_dir / f"{current_batch_prefix}_page_001.png_new.json"
    fresh_result.write_text('{"mawb": {"awb_number": "233-10167566"}, "hawbs": []}', encoding="utf-8")
    os.utime(fresh_result, (requested_at + 1.0, requested_at + 1.0))

    now = requested_at

    def fake_time():
        nonlocal now
        now += 0.01
        return now

    monkeypatch.setattr(msc_tech_ai_provider.time, "time", fake_time)
    monkeypatch.setattr(msc_tech_ai_provider.time, "sleep", lambda *_args, **_kwargs: None)

    with pytest.raises(TimeoutError):
        provider.collect_result(payload)
