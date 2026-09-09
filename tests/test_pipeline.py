"""RenderPipeline 单元测试"""

from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from danmakupro.core.pipeline import RenderPipeline, PipelineResult
from danmakupro.config.models import DEFAULT_CONFIG
from danmakupro.layout.engine import LayoutContext


@pytest.fixture
def pipeline():
    encoder = MagicMock()
    assets = MagicMock()
    return RenderPipeline(encoder, DEFAULT_CONFIG, assets)


# =============================================================================
# PipelineResult
# =============================================================================

class TestPipelineResult:

    def test_dataclass_fields(self):
        ctx = LayoutContext()
        result = PipelineResult(
            text_spawned=10, gift_spawned=5,
            layout_ctx=ctx, t_start=1.0,
            total_text_danmaku=100, total_gift_danmaku=50,
        )
        assert result.text_spawned == 10
        assert result.gift_spawned == 5
        assert result.layout_ctx is ctx
        assert result.t_start == 1.0
        assert result.total_text_danmaku == 100
        assert result.total_gift_danmaku == 50


# =============================================================================
# RenderPipeline
# =============================================================================

class TestRenderPipeline:

    def test_init(self, pipeline):
        assert pipeline._config is DEFAULT_CONFIG

    def test_run_enumerates_all_frames(self, pipeline):
        events = []
        layout_builder = MagicMock()
        layout_params = MagicMock()
        layout_params.bottom = 1080
        layout_params.text_top = 200
        layout_params.gift_top = 0
        layout_params.gap = 4
        layout_params.text_w = 800
        layer_params = MagicMock()

        type(pipeline._frame_encoder).current_speed = PropertyMock(return_value=0.0)

        with patch("danmakupro.core.pipeline.LayoutEngine") as mock_engine, \
             patch("danmakupro.core.pipeline.DanmakuRenderer") as mock_renderer_cls, \
             patch("danmakupro.core.pipeline.tqdm") as mock_tqdm:

            mock_renderer = MagicMock()
            mock_renderer.get_frame_data.return_value = memoryview(b"data")
            mock_renderer_cls.return_value = mock_renderer

            mock_engine.spawn_new_danmakus.return_value = (False, False, 0, 0)
            mock_engine.update_danmaku_layer = MagicMock()

            mock_pbar = MagicMock()
            mock_tqdm.return_value = mock_pbar
            mock_tqdm.return_value.__enter__ = MagicMock(return_value=mock_pbar)
            mock_tqdm.return_value.__exit__ = MagicMock(return_value=False)

            pipeline._encode_frame = MagicMock()

            result = pipeline.run(
                30, 10, events, layout_builder,
                layout_params, layer_params,
            )

            assert isinstance(result, PipelineResult)
            assert result.total_text_danmaku == 0
            assert result.total_gift_danmaku == 0

    def test_encode_frame_success(self, pipeline):
        mock_renderer = MagicMock()
        mock_renderer.get_frame_data.return_value = memoryview(b"data")
        mock_pbar = MagicMock()

        pipeline._encode_frame(mock_renderer, mock_pbar, 0, 100)
        pipeline._frame_encoder.submit_frame.assert_called_once()
        mock_pbar.update.assert_called_once_with(1)

    def test_encode_frame_broken_pipe(self, pipeline):
        from danmakupro.errors import EncodeError

        pipeline._frame_encoder.submit_frame.side_effect = BrokenPipeError
        mock_renderer = MagicMock()
        mock_renderer.get_frame_data.return_value = memoryview(b"data")
        mock_pbar = MagicMock()

        with pytest.raises(EncodeError):
            pipeline._encode_frame(mock_renderer, mock_pbar, 0, 100)

    def test_run_with_events(self, pipeline):
        events = [
            MagicMock(is_gift=False),
            MagicMock(is_gift=False),
            MagicMock(is_gift=True),
        ]
        layout_builder = MagicMock()
        layout_params = MagicMock()
        layout_params.bottom = 1080
        layout_params.text_top = 200
        layout_params.gift_top = 0
        layout_params.gap = 4
        layout_params.text_w = 800
        layer_params = MagicMock()

        type(pipeline._frame_encoder).current_speed = PropertyMock(return_value=0.0)

        with patch("danmakupro.core.pipeline.LayoutEngine") as mock_engine, \
             patch("danmakupro.core.pipeline.DanmakuRenderer") as mock_renderer_cls, \
             patch("danmakupro.core.pipeline.tqdm") as mock_tqdm:

            mock_renderer = MagicMock()
            mock_renderer.get_frame_data.return_value = memoryview(b"data")
            mock_renderer_cls.return_value = mock_renderer

            mock_engine.spawn_new_danmakus.return_value = (True, True, 1, 1)
            mock_engine.update_danmaku_layer = MagicMock()

            mock_pbar = MagicMock()
            mock_tqdm.return_value = mock_pbar
            mock_tqdm.return_value.__enter__ = MagicMock(return_value=mock_pbar)
            mock_tqdm.return_value.__exit__ = MagicMock(return_value=False)

            pipeline._encode_frame = MagicMock()

            result = pipeline.run(
                30, 5, events, layout_builder,
                layout_params, layer_params,
            )

            assert result.total_text_danmaku == 2
            assert result.total_gift_danmaku == 1
            assert result.text_spawned == 5
            assert result.gift_spawned == 5