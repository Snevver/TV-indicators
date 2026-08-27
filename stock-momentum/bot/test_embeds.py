"""Discord embed helpers. `python test_embeds.py`.

_nd() is the no-em-dash filter every user-facing string goes through. clip()
keeps a field under Discord's 1024-char limit. _embed() assembles the dict the
API wants -- if its shape drifts, every autotrade message silently fails to post.
"""
import sys
sys.argv = ["x"]
import momentum_bot as bot            # noqa: E402


def test_nd_replaces_em_dashes_only():
    assert bot._nd("sold A — bought B") == "sold A - bought B"
    assert bot._nd("a—b") == "a-b"
    assert bot._nd("hyphen-word stays") == "hyphen-word stays"
    assert bot._nd(42) == "42"                        # coerces non-strings


def test_block_wraps_in_a_code_fence():
    out = bot._block(["line one", "line two"])
    assert out.startswith("```\n") and out.endswith("\n```")
    assert "line one\nline two" in out


def test_clip_leaves_short_values_alone():
    assert bot.clip("short") == "short"


def test_clip_truncates_and_recloses_the_fence():
    big = "```\n" + "\n".join(f"row {i}" for i in range(400)) + "\n```"
    out = bot.clip(big)
    assert len(out) <= 1024
    assert out.endswith("```")                        # fence still closed
    assert "truncated" in out


def test_embed_has_the_fields_the_api_needs():
    e = bot._embed("Rebalance placed — Sep", bot.GREEN,
                   desc="2 sell — 3 buy",
                   fields=[{"name": "Sold — 2", "value": "A, B", "inline": True}],
                   footer="react — soon")
    assert e["title"] == "Rebalance placed - Sep"     # _nd applied
    assert e["color"] == bot.GREEN
    assert "timestamp" in e
    assert e["description"] == "2 sell - 3 buy"
    assert e["fields"][0] == {"name": "Sold - 2", "value": "A, B", "inline": True}
    assert e["footer"]["text"] == "react - soon"


def test_embed_omits_empty_optionals():
    e = bot._embed("Title", bot.RED)
    assert "description" not in e and "fields" not in e and "footer" not in e


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    print("all passed" if not fails else f"{fails} failed")
    sys.exit(1 if fails else 0)
