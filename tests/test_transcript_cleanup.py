"""Masked-word restoration, caption-bleed dedupe, and transcript line count."""

from core.config import AppConfig
from core.finance_unmask import parse_unmask_extra, restore_masked_terms
from core.ocr_subtitle import dedupe_overlapping_captions, merge_ocr_samples, rows_from_ocr_output
from core.subtitle import SubtitleResult, SubtitleSegment


def _segs(*texts: str) -> list[SubtitleSegment]:
    return [
        SubtitleSegment(start=float(index), end=float(index) + 1, text=text)
        for index, text in enumerate(texts)
    ]


def test_restore_user_examples_and_leave_real_latin_words():
    raw = "做空总爆C，建C要慢，一轮N市，准备C底，一半L润，别把Q亏加仓"
    text = restore_masked_terms(raw)
    assert text == "做空总爆仓，建仓要慢，一轮牛市，准备抄底，一半利润，别把全亏加仓"
    untouched = restore_masked_terms("A股、CEO、C位出道、空CPU、OCR识别")
    assert untouched == "A股、CEO、C位出道、空CPU、OCR识别"


def test_unmask_extra_overrides_and_can_be_disabled():
    assert restore_masked_terms("爆C", {"爆C": "爆仓库"}) == "爆仓库"
    parsed = parse_unmask_extra("Q亏=全亏, 建C=建仓")
    assert parsed["Q亏"] == "全亏"
    config = AppConfig()
    config.asr.unmask_finance = False
    from core.ocr_subtitle import _restore_finance_masks
    kept = _restore_finance_masks(_segs("爆C"), config)
    assert kept[0].text == "爆C"


def test_merge_prefers_caption_without_one_letter_bleed():
    samples = [
        (0.0, "主力建C"),
        (0.5, "C主力建C"),
        (1.0, "主力建C"),
    ]
    segments = merge_ocr_samples(samples, interval=0.5, duration=2.0)
    assert [segment.text for segment in segments] == ["主力建C"]


def test_dedupe_strips_letter_bleed_and_glued_neighbor():
    bleed = dedupe_overlapping_captions(_segs("你上一次爆C", "C主力建C"))
    assert [segment.text for segment in bleed] == ["你上一次爆C", "主力建C"]

    glued = dedupe_overlapping_captions(_segs("你上一次爆C主力建C", "主力建C"))
    assert [segment.text for segment in glued] == ["你上一次爆C", "主力建C"]

    short = dedupe_overlapping_captions(_segs("爆C主力建C", "主力建C"))
    assert [segment.text for segment in short] == ["爆C", "主力建C"]

    both = dedupe_overlapping_captions(_segs("你上一次爆C", "C主力建C", "主力建C"))
    assert [segment.text for segment in both] == ["你上一次爆C", "主力建C"]


def test_cleanup_then_unmask_reads_naturally():
    cleaned = dedupe_overlapping_captions(
        _segs("你上一次爆C", "C主力建C", "一轮N市下来", "准备C底", "一半L润", "Q亏停手")
    )
    texts = [restore_masked_terms(segment.text) for segment in cleaned]
    assert texts == [
        "你上一次爆仓",
        "主力建仓",
        "一轮牛市下来",
        "准备抄底",
        "一半利润",
        "全亏停手",
    ]


def test_save_txt_trailing_newline_matches_line_count(tmp_path):
    segments = _segs("爆仓", "建仓", "牛市")
    result = SubtitleResult(segments=segments, source="ocr")
    path = tmp_path / "transcript.txt"
    result.save_txt(path)
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    assert raw.count(b"\n") == len(path.read_text(encoding="utf-8").splitlines()) == 3


def test_rapidocr_v3_output_shape():
    class Output:
        boxes = [[[1, 180], [20, 180], [20, 200], [1, 200]]]
        txts = ("这个不对称藏着第二条铁律",)
        scores = (0.99,)

    from core.ocr_subtitle import pick_ocr_text
    assert pick_ocr_text(rows_from_ocr_output(Output())) == "这个不对称藏着第二条铁律"
    legacy = [([[[1, 10]]], "归零就是归零", 0.9)]
    assert pick_ocr_text(rows_from_ocr_output((legacy, 0.2))) == "归零就是归零"
