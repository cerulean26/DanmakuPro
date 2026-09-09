from danmakupro.utils.helpers import extract_emoji_names, ensure_qt_app, EMOJI_PATTERN


class TestExtractEmojiNames:

    def test_single_emoji(self):
        assert extract_emoji_names("你好[微笑]") == ["微笑"]

    def test_multiple_emojis(self):
        assert extract_emoji_names("[大笑][大哭]hhh[微笑]") == ["大笑", "大哭", "微笑"]

    def test_no_emoji(self):
        assert extract_emoji_names("普通文本") == []

    def test_empty_string(self):
        assert extract_emoji_names("") == []

    def test_empty_brackets(self):
        assert extract_emoji_names("[]") == []

    def test_nested_brackets(self):
        assert extract_emoji_names("[[a]b]") == ["[a"]

    def test_unclosed_bracket(self):
        assert extract_emoji_names("你好[微笑") == []


class TestEmojiPattern:

    def test_pattern_findall(self):
        result = EMOJI_PATTERN.findall("a[微笑]b[大笑]c")
        assert result == ["微笑", "大笑"]

    def test_pattern_no_match(self):
        assert EMOJI_PATTERN.findall("abc") == []


# =============================================================================
# ensure_qt_app
# =============================================================================

class TestEnsureQtApp:

    def test_returns_existing_qapp(self, qapp):
        app = ensure_qt_app()
        assert app is not None