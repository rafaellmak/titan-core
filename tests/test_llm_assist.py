import io
import json
import sys

from titan.llm_assist.engine import DeterministicLLMMock, _extract_name


def test_classifier_distinguishes_intents():
    mock = DeterministicLLMMock()
    cases = {
        "scan for security vulnerabilities": ("security", "security"),
        "what depends on openssl": ("recipe", "recipe impact openssl"),
        "show me the deps of zlib": ("recipe", "recipe deps zlib"),
        "tree of openssl": ("recipe", "recipe deps openssl"),
        "search openssl": ("recipe", "recipe search openssl"),
        "find recipe curl": ("recipe", "recipe search curl"),
        "dependências do zlib": ("recipe", "recipe deps zlib"),
        "buscar receita openssl": ("recipe", "recipe search openssl"),
        "fix my build": ("fix", "fix build.log"),
        "rebuild everything": ("fix", "fix build.log"),
        "fix this nothing provides error in openssl": ("fix", "fix build.log"),
        "explain openssl": ("explain", "explain openssl"),
        "add layer poky": ("action", "action add-layer /path/to/layer"),
        "show workspace info": ("info", "info"),
        "analisa esse dts": ("hardware", "hardware board.dts"),
    }
    for prompt, (want_intent, want_cmd) in cases.items():
        r = json.loads(mock.generate_response(prompt))
        assert r["intent"] == want_intent, f"{prompt!r}: intent={r['intent']}, want {want_intent}"
        assert r["command"] == want_cmd, f"{prompt!r}: command={r['command']!r}, want {want_cmd!r}"


def test_classifier_returns_none_for_unknown():
    mock = DeterministicLLMMock()
    for prompt in ["olá, tudo bem?", "asdfghjkl nonsense", "", " "]:
        r = json.loads(mock.generate_response(prompt))
        assert r["intent"] == "unknown", f"{prompt!r}: intent={r['intent']}"
        assert r["command"] is None, f"{prompt!r}: command={r['command']!r}"


def test_extract_name_strips_stop_words():
    assert _extract_name("on openssl") == "openssl"
    assert _extract_name("of zlib") == "zlib"
    assert _extract_name("recipe curl") == "curl"
    assert _extract_name("do openssl") == "openssl"
    assert _extract_name("") == "RECIPE"
    assert _extract_name(None) == "RECIPE"
    assert _extract_name("for the openssl") == "openssl"
    assert _extract_name("openssl.") == "openssl"


def test_cli_handles_eof_gracefully(monkeypatch, capsys):
    from titan.cli import main

    class _FakeArgs:
        prompt = "scan for security vulnerabilities"
        provider = "offline"
        model = None
        url = None
        key = None
        yes = False

    monkeypatch.setattr(sys, "argv", ["titan", "llm-assist", "scan for security vulnerabilities"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    try:
        main()
    except SystemExit as e:
        assert e.code in (0, 1)

    out = capsys.readouterr().out
    assert "Stdin não é TTY" in out or "Nenhum comando Titan pôde ser mapeado" in out or "titan security" in out or "cancelado" in out.lower()


def test_cli_handles_unknown_intent(monkeypatch, capsys):
    from titan.cli import main

    monkeypatch.setattr(sys, "argv", ["titan", "llm-assist", "olá tudo bem"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    try:
        main()
    except SystemExit as e:
        assert e.code == 0

    out = capsys.readouterr().out
    assert "Nenhum comando Titan pôde ser mapeado" in out


if __name__ == "__main__":
    test_classifier_distinguishes_intents()
    test_classifier_returns_none_for_unknown()
    test_extract_name_strips_stop_words()
    print("OK: classifier + extract_name + cli edges")
