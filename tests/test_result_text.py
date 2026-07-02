from __future__ import annotations

from types import SimpleNamespace

from throughline.memory import _result_text


def test_result_text_uses_content_attribute() -> None:
    result = SimpleNamespace(content="clean graph answer", text=None)

    assert _result_text(result) == "clean graph answer"
