"""Burned-in subtitle OCR helpers that do not need a model."""

from core.ffmpeg_util import choose_subtitle_crop
from core.ocr_subtitle import drop_watermark_lines, merge_ocr_samples, pick_ocr_text


def test_merge_dedupes_consecutive_lines_and_tolerates_one_miss():
    samples = [
        (0.0, "归零就是归零"),
        (0.5, "归零就是归零"),
        (1.0, ""),
        (1.5, "归零就是归零"),
        (2.0, "这个不对称藏着第二条铁律"),
        (2.5, "这个不对称藏着第二条铁律"),
        (3.0, ""),
        (3.5, ""),
    ]
    segments = merge_ocr_samples(samples, interval=0.5, duration=4.0)
    assert [segment.text for segment in segments] == [
        "归零就是归零",
        "这个不对称藏着第二条铁律",
    ]
    assert segments[0].start == 0.0
    assert segments[0].end == 2.0
    assert segments[1].start == 2.0


def test_merge_keeps_the_longer_ocr_variant():
    samples = [
        (0.0, "你左侧冲进"),
        (0.5, "你左侧冲进去"),
        (1.0, "你左侧冲进去"),
    ]
    segments = merge_ocr_samples(samples, interval=0.5, duration=2.0)
    assert len(segments) == 1
    assert segments[0].text == "你左侧冲进去"


def test_drop_watermark_lines():
    samples = [(index * 0.5, "理财有风险") for index in range(9)]
    samples.append((4.5, "你左侧冲进去"))
    cleaned = drop_watermark_lines(samples)
    texts = [text for _, text in cleaned if text]
    assert texts == ["你左侧冲进去"]


def test_pick_ocr_text_uses_the_lowest_caption():
    result = [
        [[[10, 10], [200, 10], [200, 30], [10, 30]], "理财有风险投资需谨慎", 0.99],
        [[[40, 180], [300, 180], [300, 220], [40, 220]], "你左侧冲进去", 0.97],
    ]
    assert pick_ocr_text(result) == "你左侧冲进去"


def test_subtitle_crop_depends_on_aspect():
    landscape = choose_subtitle_crop(1920, 1080, 0)
    assert landscape.y_ratio == 0.82
    portrait = choose_subtitle_crop(1080, 1920, 0)
    assert portrait.y_ratio == 0.62
    forced = choose_subtitle_crop(1920, 1080, 0.2)
    assert abs(forced.h_ratio - 0.2) < 1e-6
    assert abs(forced.y_ratio - 0.8) < 1e-6
