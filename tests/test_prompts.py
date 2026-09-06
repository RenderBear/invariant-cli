from invariant.cli.commands.initialize import _option_lines, _radio_select


OPTIONS = (
    ("first", "First choice", "The default choice."),
    ("second", "Second choice", "The alternate choice."),
)


def test_radio_options_are_unumbered_and_mark_only_the_selection() -> None:
    lines = _option_lines(OPTIONS, 1, "first")
    assert lines[0].startswith("  ○ First choice")
    assert lines[1].startswith("  ● Second choice")
    assert not any("1." in line or "2." in line for line in lines)


def test_radio_selection_uses_a_green_marker_and_underlined_plain_text(monkeypatch) -> None:
    monkeypatch.setattr(
        "invariant.cli.commands.initialize._color",
        lambda code, text: f"<{code}>{text}</{code}>",
    )
    lines = _option_lines(OPTIONS, 1, "first")
    assert "<32>●</32> <4>Second choice</4>" in lines[1]
    assert "1;36" not in lines[1]


def test_radio_selector_uses_arrows_and_enter(capsys) -> None:
    keys = iter(("\x1b[B", "\r"))
    selected = _radio_select(OPTIONS, "first", key_reader=lambda: next(keys))
    assert selected == "second"
    output = capsys.readouterr().out
    assert "↑/↓ navigate • enter select" in output
    assert "\033[?25l" in output
    assert output.endswith("\033[?25h")
