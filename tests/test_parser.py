"""URL and local-path parsing."""

import os

from core.parser import LinkType, Platform, _clean_url, parse_link


def test_absolute_local_path_is_not_rewritten_into_a_url(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not-a-real-video")
    parsed = parse_link(str(video))
    assert parsed.platform == Platform.LOCAL
    assert parsed.link_type == LinkType.LOCAL_FILE
    assert parsed.url == os.path.abspath(video)
    assert not parsed.url.startswith("://")


def test_relative_and_file_url_local_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    relative = parse_link("./clip.mp4")
    assert relative.platform == Platform.LOCAL
    assert relative.url == os.path.abspath(video)

    from_uri = parse_link(video.as_uri())
    assert from_uri.platform == Platform.LOCAL
    assert from_uri.url == os.path.abspath(video)


def test_missing_absolute_path_stays_a_local_file():
    parsed = parse_link("/tmp/vidnotek-does-not-exist-ba9b.mp4")
    assert parsed.platform == Platform.LOCAL
    assert parsed.url.endswith("vidnotek-does-not-exist-ba9b.mp4")
    assert "://" not in parsed.url


def test_clean_url_keeps_episode_and_drops_tracker():
    cleaned = _clean_url("https://www.bilibili.com/video/BV1xx?vd_source=abc&p=2")
    assert cleaned.startswith("https://www.bilibili.com/video/BV1xx?")
    assert "p=2" in cleaned
    assert "vd_source" not in cleaned


def test_clean_url_leaves_local_paths_alone():
    assert _clean_url("/workspace/video.mp4") == "/workspace/video.mp4"


def test_douyin_ids_are_parsed_without_network():
    canonical = parse_link("https://www.douyin.com/video/7694957011309432099")
    assert canonical.platform == Platform.DOUYIN
    assert canonical.video_id == "7694957011309432099"

    modal = parse_link("https://www.douyin.com/jingxuan?modal_id=7694957011309432099")
    assert modal.platform == Platform.DOUYIN
    assert modal.video_id == "7694957011309432099"

    share = parse_link("https://www.iesdouyin.com/share/video/7694957011309432099/")
    assert share.platform == Platform.DOUYIN
    assert share.video_id == "7694957011309432099"

    short = parse_link("https://v.douyin.com/fnnhAB4lkq8/")
    assert short.platform == Platform.DOUYIN
    assert short.video_id == ""
