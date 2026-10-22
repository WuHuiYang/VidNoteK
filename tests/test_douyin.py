"""Pure Douyin parsing. No network and no browser."""

from core.douyin import choose_play_url, extract_video_id, is_douyin_url, parse_render_html


def test_extract_video_id_from_common_urls():
    assert extract_video_id("https://www.douyin.com/video/7694957011309432099") == "7694957011309432099"
    assert extract_video_id("https://www.iesdouyin.com/share/video/7694957011309432099/?from_ssr=1") == "7694957011309432099"
    assert extract_video_id("https://www.douyin.com/jingxuan?modal_id=7694957011309432099") == "7694957011309432099"
    assert extract_video_id("https://v.douyin.com/fnnhAB4lkq8/") == ""


def test_is_douyin_url_does_not_match_lookalikes():
    assert is_douyin_url("https://v.douyin.com/abc/")
    assert is_douyin_url("https://www.iesdouyin.com/share/video/1/")
    assert not is_douyin_url("https://notdouyin.com/video/1")
    assert not is_douyin_url("https://www.youtube.com/watch?v=abcdefg")


def test_choose_play_url_prefers_progressive_h264():
    video = {
        "playAddr": [{"src": "https://cdn.example/h264.mp4"}],
        "playAddrH265": [{"src": "https://cdn.example/h265.mp4"}],
        "bitRateList": [
            {"isH265": True, "dataSize": 100, "playAddr": [{"src": "https://cdn.example/small265.mp4"}]},
        ],
    }
    assert choose_play_url(video) == "https://cdn.example/h264.mp4"


def test_choose_play_url_skips_h265_bitrate_list():
    video = {
        "bitRateList": [
            {"isH265": True, "dataSize": 1_000, "playAddr": [{"src": "https://cdn.example/h265.mp4"}]},
            {"isH265": False, "dataSize": 8_000_000, "playAddr": [{"src": "https://cdn.example/h264-a.mp4"}]},
            {"isH265": False, "dataSize": 20_000_000, "playAddr": [{"src": "https://cdn.example/h264-b.mp4"}]},
            {"isH265": False, "dataSize": 90_000_000, "playAddr": [{"src": "https://cdn.example/huge.mp4"}]},
        ],
    }
    assert choose_play_url(video) == "https://cdn.example/h264-b.mp4"


def test_parse_render_html_reads_the_matching_video():
    html = """
    <html><head><title>示例 - 抖音</title></head><body>
    <script id="RENDER_DATA" type="application/json">
    {"app":{"videoDetail":{
        "awemeId":"7694957011309432099",
        "itemTitle":"做多赚的是空间",
        "desc":"做多赚的是空间 #短线",
        "authorInfo":{"nickname":"熊猫讲技术分析"},
        "video":{
            "duration":181836,
            "cover":"https://cdn.example/cover.jpg",
            "playAddr":[{"src":"https://cdn.example/video.mp4?mime_type=video_mp4"}],
            "bigThumbs":[{"duration":181.8}]
        }
    }}}
    </script>
    </body></html>
    """
    media = parse_render_html(html, "7694957011309432099")
    assert media.video_id == "7694957011309432099"
    assert media.title == "做多赚的是空间"
    assert media.uploader == "熊猫讲技术分析"
    assert media.duration == 181.8
    assert media.play_url.startswith("https://cdn.example/video.mp4")
    assert media.webpage_url == "https://www.douyin.com/video/7694957011309432099"
