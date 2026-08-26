"""Tests for the decision-layer arming hook.

Run the whole suite:
    python -m pytest tests/test_decision_layer_mode.py -v

The hook derives every path it touches from a module-level CLAUDE_DIR, and reads
those constants at call time rather than at import. So each test redirects
STATE_DIR / LOG_PATH / SKILL_PATH at a pytest tmp_path and nothing ever writes
into the real config tree. No production code carries a test-only switch.

The tests at the end deliberately read the REAL files instead: they guard the
wiring between the hook, the skill, the output style and the documentation, which
is the part that breaks silently.
"""

import importlib.util
import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

# The plugin as it sits in this repository, not as installed on any machine.
PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugins" / "decision-layer"
HOOK_PATH = PLUGIN_DIR / "hooks" / "decision-layer-mode.py"
REAL_STYLE_PATH = PLUGIN_DIR / "output-styles" / "decision-layer.md"

SESSION = "11111111-2222-3333-4444-555555555555"


def _load_hook():
    """The filename has hyphens, so it cannot be imported by name."""
    spec = importlib.util.spec_from_file_location("decision_layer_mode", HOOK_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {HOOK_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook(tmp_path, monkeypatch):
    """A fresh copy of the hook with every path pointed at tmp_path."""
    module = _load_hook()
    state = tmp_path / "state"
    state.mkdir()
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "preamble\n<!-- INJECT:BEGIN -->\nDECISION-LAYER:ARMED\n\nbody text\n"
        "<!-- INJECT:END -->\ntrailer\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "STATE_DIR", state)
    monkeypatch.setattr(module, "SKILL_PATH", skill)
    monkeypatch.setattr(module, "LOG_PATH", tmp_path / "hook.log")

    # A stand-in plugin and config dir, so the session-start check never reads the real ones.
    config = tmp_path / "claude"
    config.mkdir()
    plugin = tmp_path / "plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "demo-plugin"}', encoding="utf-8")
    (plugin / "output-styles").mkdir()
    (plugin / "output-styles" / "whatever.md").write_text(
        "---\nname: Demo\n---\nbody\n", encoding="utf-8")
    monkeypatch.setattr(module, "CLAUDE_DIR", config)
    monkeypatch.setattr(module, "PLUGIN_DIR", plugin)
    monkeypatch.setattr(module, "MANIFEST_PATH", plugin / ".claude-plugin" / "plugin.json")
    monkeypatch.setattr(module, "STYLE_DIR", plugin / "output-styles")
    return module


def feed(hook, monkeypatch, payload):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    hook.run_hook()


def submit(prompt, session_id=SESSION):
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": session_id,
        "prompt": prompt,
    }


def expand(command_args, command_name="decision-layer", session_id=SESSION):
    return {
        "hook_event_name": "UserPromptExpansion",
        "session_id": session_id,
        "command_name": command_name,
        "command_args": command_args,
    }


def emitted(capsys):
    """The additionalContext the hook printed, or None if it printed nothing."""
    out = capsys.readouterr().out.strip()
    if not out:
        return None
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def start(session_id=SESSION):
    return {"hook_event_name": "SessionStart", "session_id": session_id}


def system_message(capsys):
    """The line the hook asked Claude Code to show the user, or None if it stayed quiet."""
    out = capsys.readouterr().out.strip()
    if not out:
        return None
    return json.loads(out).get("systemMessage")


def select_style(hook, name, scope="user"):
    """Write an output style choice into one of the settings files the check reads."""
    if scope == "user":
        path = hook.CLAUDE_DIR / "settings.json"
    else:
        path = Path.cwd() / ".claude" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"outputStyle": name}), encoding="utf-8")


def emitted_text(capsys) -> str:
    """Same as emitted(), but for the cases where printing nothing is itself a failure."""
    text = emitted(capsys)
    assert text is not None, "the hook printed nothing"
    return text


# --------------------------------------------------------------------------
# arming state
# --------------------------------------------------------------------------

def test_arm_creates_the_flag(hook):
    hook.arm(SESSION)
    assert hook.flag_path(SESSION).exists()


def test_disarm_removes_the_flag(hook):
    hook.arm(SESSION)
    hook.disarm(SESSION)
    assert not hook.flag_path(SESSION).exists()


def test_disarm_without_a_flag_is_silent(hook):
    hook.disarm(SESSION)
    assert not hook.flag_path(SESSION).exists()


def test_flags_are_per_session(hook):
    other = "99999999-8888-7777-6666-555555555555"
    hook.arm(SESSION)
    assert not hook.flag_path(other).exists()


# --------------------------------------------------------------------------
# UserPromptSubmit: the per-turn decision
# --------------------------------------------------------------------------

def test_armed_turn_gets_the_marker(hook, monkeypatch, capsys):
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit("what should we do about the failing build?"))
    assert "DECISION-LAYER:ARMED" in emitted_text(capsys)


def test_unarmed_turn_gets_nothing(hook, monkeypatch, capsys):
    feed(hook, monkeypatch, submit("what should we do about the failing build?"))
    assert emitted(capsys) is None


def test_impl_suppresses_the_marker_for_one_turn(hook, monkeypatch, capsys):
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit("--impl show me the function"))
    assert emitted(capsys) is None


def test_impl_leaves_the_session_armed(hook, monkeypatch):
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit("--impl show me the function"))
    assert hook.flag_path(SESSION).exists(), "the one-turn escape must not disarm"


def test_impl_off_disarms_the_session(hook, monkeypatch, capsys):
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit("--impl-off just talk normally now"))
    assert not hook.flag_path(SESSION).exists()
    assert emitted(capsys) is None


def test_impl_off_is_tested_before_impl(hook, monkeypatch):
    """--impl-off contains --impl. Wrong order and the kill switch never fires."""
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit("--impl-off"))
    assert not hook.flag_path(SESSION).exists(), "--impl-off was swallowed by --impl"


def test_impl_off_when_not_armed_does_not_crash(hook, monkeypatch, capsys):
    feed(hook, monkeypatch, submit("--impl-off"))
    assert emitted(capsys) is None


def test_a_prompt_merely_mentioning_implementation_still_gets_the_marker(hook, monkeypatch, capsys):
    """Prose that happens to share the letters is not a switch."""
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit("does the implementation look right?"))
    assert "DECISION-LAYER:ARMED" in emitted_text(capsys)


# --------------------------------------------------------------------------
# where a switch counts: first line, last line, nowhere else
# --------------------------------------------------------------------------

def quoted(word):
    """A message that quotes a switch in passing, the way pasted documentation does."""
    return ("here is the bit of the readme I do not follow:\n\n"
            "| `" + word + "` | off for that one reply |\n\n"
            "what does that actually mean?")


def test_the_escape_works_on_the_first_line(hook, monkeypatch, capsys):
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit(hook.ESCAPE_WORD + "\nshow me the function"))
    assert emitted(capsys) is None
    assert hook.flag_path(SESSION).exists(), "the one-turn escape must not disarm"


def test_the_escape_works_on_the_last_line(hook, monkeypatch, capsys):
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit("show me the function\n\n" + hook.ESCAPE_WORD))
    assert emitted(capsys) is None


def test_the_kill_switch_works_on_the_first_line(hook, monkeypatch):
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit(hook.KILL_WORD + "\njust talk normally from now on"))
    assert not hook.flag_path(SESSION).exists()


def test_the_kill_switch_works_on_the_last_line(hook, monkeypatch):
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit("just talk normally from now on\n" + hook.KILL_WORD))
    assert not hook.flag_path(SESSION).exists()


def test_an_escape_buried_mid_message_is_ignored(hook, monkeypatch, capsys):
    """Quoting a switch is not typing one, and a paste is nearly always a quote."""
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit(quoted(hook.ESCAPE_WORD)))
    assert "DECISION-LAYER:ARMED" in emitted_text(capsys)


def test_a_kill_switch_buried_mid_message_is_ignored(hook, monkeypatch, capsys):
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit(quoted(hook.KILL_WORD)))
    assert hook.flag_path(SESSION).exists(), "a quoted switch disarmed the session"
    assert "DECISION-LAYER:ARMED" in emitted_text(capsys)


def test_a_switch_glued_to_other_text_is_ignored(hook, monkeypatch, capsys):
    """On a line that counts, but not standing alone on it, so it is prose."""
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit("mind the `" + hook.ESCAPE_WORD + "`-shaped hole"))
    assert "DECISION-LAYER:ARMED" in emitted_text(capsys)


def test_the_kill_switch_still_wins_over_the_escape(hook, monkeypatch):
    """One string contains the other, so the kill switch is still tested first. Type both
    and the session ends, rather than merely skipping a turn."""
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit(hook.ESCAPE_WORD + "\nand also\n" + hook.KILL_WORD))
    assert not hook.flag_path(SESSION).exists()


# --------------------------------------------------------------------------
# UserPromptExpansion: the typed command
# --------------------------------------------------------------------------

def test_bare_command_arms(hook, monkeypatch):
    feed(hook, monkeypatch, expand(""))
    assert hook.flag_path(SESSION).exists()


def test_off_disarms_and_says_so(hook, monkeypatch, capsys):
    hook.arm(SESSION)
    feed(hook, monkeypatch, expand("off"))
    assert not hook.flag_path(SESSION).exists()
    assert "OFF" in emitted_text(capsys)


def test_off_reply_is_tagged_with_the_event_that_fired(hook, monkeypatch, capsys):
    """hookSpecificOutput is a union keyed on hookEventName; a wrong name is dropped."""
    hook.arm(SESSION)
    feed(hook, monkeypatch, expand("off"))
    out = json.loads(capsys.readouterr().out.strip())
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptExpansion"


@pytest.mark.parametrize("word", ["off", "stop", "no", "disable", "OFF", " off "])
def test_every_off_word_disarms(hook, monkeypatch, word):
    hook.arm(SESSION)
    feed(hook, monkeypatch, expand(word))
    assert not hook.flag_path(SESSION).exists()


def test_off_with_trailing_words_still_disarms(hook, monkeypatch):
    hook.arm(SESSION)
    feed(hook, monkeypatch, expand("off please"))
    assert not hook.flag_path(SESSION).exists()


@pytest.mark.parametrize("word", ["now", "notes", "nothing", "stopwatch", "offset"])
def test_words_that_merely_start_like_an_off_word_still_arm(hook, monkeypatch, word):
    """A prefix match would read /decision-layer now as 'no' and silently disarm."""
    feed(hook, monkeypatch, expand(word))
    assert hook.flag_path(SESSION).exists(), f"{word} was misread as an off word"


def test_a_different_command_is_ignored(hook, monkeypatch, capsys):
    feed(hook, monkeypatch, expand("", command_name="orchestrate"))
    assert not hook.flag_path(SESSION).exists()
    assert emitted(capsys) is None


# --------------------------------------------------------------------------
# input validation and failure modes
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["", "../../evil", "a/b", "x" * 65, "has space"])
def test_a_bad_session_id_is_refused(hook, monkeypatch, capsys, bad):
    feed(hook, monkeypatch, submit("anything", session_id=bad))
    assert emitted(capsys) is None
    assert list(hook.STATE_DIR.iterdir()) == []


def test_a_missing_inject_block_emits_nothing_and_logs(hook, monkeypatch, capsys):
    hook.SKILL_PATH.write_text("no markers here at all\n", encoding="utf-8")
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit("anything"))
    assert emitted(capsys) is None
    assert "ERROR" in hook.LOG_PATH.read_text(encoding="utf-8")


def test_marker_strips_surrounding_whitespace(hook):
    assert hook.marker().startswith("DECISION-LAYER:ARMED")
    assert hook.marker().endswith("body text")


def test_the_log_truncates_itself(hook, monkeypatch):
    monkeypatch.setattr(hook, "LOG_MAX_BYTES", 100)
    hook.LOG_PATH.write_text("x" * 200, encoding="utf-8")
    hook.log("fresh line")
    assert hook.LOG_PATH.read_text(encoding="utf-8") == "fresh line\n"


def test_sweep_drops_stale_flags_and_keeps_live_ones(hook):
    hook.arm(SESSION)
    stale = hook.STATE_DIR / "decision-layer-old-session"
    stale.write_text("", encoding="utf-8")
    stale_time = time.time() - 30 * 86400
    os.utime(stale, (stale_time, stale_time))
    hook.sweep_old_flags()
    assert not stale.exists()
    assert hook.flag_path(SESSION).exists()


def test_emit_shape_is_what_the_engine_expects(hook, capsys):
    hook.emit("hello", "UserPromptSubmit")
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "hello",
        }
    }


# --------------------------------------------------------------------------
# SessionStart: is the output style selected at all?
# --------------------------------------------------------------------------

def test_style_name_is_prefixed_with_the_plugin(hook):
    """Claude Code registers a plugin style as <plugin>:<style>, never the bare name."""
    assert hook.style_name() == "demo-plugin:Demo"


def test_style_name_falls_back_to_the_filename(hook):
    (hook.STYLE_DIR / "whatever.md").write_text("no frontmatter here\n", encoding="utf-8")
    assert hook.style_name() == "demo-plugin:whatever"


def test_style_name_ignores_a_name_field_in_the_body(hook):
    """A "name:" line in ordinary prose must not beat the one in the frontmatter."""
    (hook.STYLE_DIR / "whatever.md").write_text(
        "---\nname: Demo\n---\nname: NotThis\n", encoding="utf-8")
    assert hook.style_name() == "demo-plugin:Demo"


def test_session_start_warns_when_no_style_is_selected(hook, monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    feed(hook, monkeypatch, start())
    message = system_message(capsys)
    assert message is not None, "the quietest failure went unreported"
    assert "demo-plugin:Demo" in message


def test_session_start_warns_when_another_style_is_selected(hook, monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    select_style(hook, "Concise")
    message = None
    feed(hook, monkeypatch, start())
    message = system_message(capsys)
    assert message is not None
    assert "Concise" in message, "the user is not told what is overriding it"
    assert "demo-plugin:Demo" in message


def test_session_start_is_silent_when_our_style_is_selected(hook, monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    select_style(hook, "demo-plugin:Demo")
    feed(hook, monkeypatch, start())
    assert system_message(capsys) is None


def test_a_project_settings_selection_counts(hook, monkeypatch, capsys, tmp_path):
    """Crying wolf at someone who selected it in a place we did not look is the worse bug."""
    monkeypatch.chdir(tmp_path)
    select_style(hook, "demo-plugin:Demo", scope="project")
    feed(hook, monkeypatch, start())
    assert system_message(capsys) is None


def test_session_start_does_not_need_a_session_id(hook, monkeypatch, capsys, tmp_path):
    """The check touches no session state, so it must run before the id is validated."""
    monkeypatch.chdir(tmp_path)
    feed(hook, monkeypatch, {"hook_event_name": "SessionStart"})
    assert system_message(capsys) is not None


def test_an_unreadable_settings_file_does_not_crash(hook, monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    (hook.CLAUDE_DIR / "settings.json").write_text("{ not json", encoding="utf-8")
    feed(hook, monkeypatch, start())
    assert system_message(capsys) is not None


def test_session_start_sends_no_marker(hook, monkeypatch, capsys, tmp_path):
    """It talks to the user, not the model. An additionalContext here would be a leak."""
    monkeypatch.chdir(tmp_path)
    hook.arm(SESSION)
    feed(hook, monkeypatch, start())
    assert "hookSpecificOutput" not in capsys.readouterr().out


# --------------------------------------------------------------------------
# "/decision-layer setup" - selecting the style for every project
# --------------------------------------------------------------------------

USER_SETTINGS_LABEL = "~/.claude/settings.json"


def user_settings(hook):
    return hook.CLAUDE_DIR / "settings.json"


def emitted_text_for_setup(hook, monkeypatch, capsys):
    feed(hook, monkeypatch, expand("setup"))
    return emitted_text(capsys).lower()


def test_setup_selects_the_style_in_user_settings(hook, monkeypatch, capsys):
    """The whole point: the terminal picker writes the project, this writes the user."""
    feed(hook, monkeypatch, expand("setup"))
    capsys.readouterr()
    written = json.loads(user_settings(hook).read_text(encoding="utf-8"))
    assert written["outputStyle"] == "demo-plugin:Demo"


@pytest.mark.parametrize("word", ["setup", "install", "select"])
def test_every_setup_word_selects_the_style(hook, monkeypatch, capsys, word):
    feed(hook, monkeypatch, expand(word))
    capsys.readouterr()
    assert json.loads(user_settings(hook).read_text(encoding="utf-8"))["outputStyle"]


def test_setup_leaves_the_rest_of_the_settings_alone(hook, monkeypatch, capsys):
    """Someone's whole configuration lives in this file. Touch one key and nothing else."""
    user_settings(hook).write_text(
        json.dumps({"model": "opus", "permissions": {"allow": ["Bash(ls)"]}}),
        encoding="utf-8")
    feed(hook, monkeypatch, expand("setup"))
    capsys.readouterr()
    written = json.loads(user_settings(hook).read_text(encoding="utf-8"))
    assert written["model"] == "opus"
    assert written["permissions"] == {"allow": ["Bash(ls)"]}
    assert written["outputStyle"] == "demo-plugin:Demo"


def test_setup_says_what_it_replaced(hook, monkeypatch, capsys):
    """Replacing a style the person chose is the only part they cannot see for themselves."""
    select_style(hook, "Concise")
    feed(hook, monkeypatch, expand("setup"))
    report = emitted_text(capsys)
    assert "Concise" in report, "the report never names the style it replaced"


def test_setup_stays_quiet_about_a_replacement_when_there_was_none(hook, monkeypatch, capsys):
    feed(hook, monkeypatch, expand("setup"))
    assert "took over from" not in emitted_text(capsys)


def test_setup_run_twice_reports_no_replacement(hook, monkeypatch, capsys):
    """Running it again is not a change, so it must not read like one."""
    feed(hook, monkeypatch, expand("setup"))
    capsys.readouterr()
    feed(hook, monkeypatch, expand("setup"))
    assert "took over from" not in emitted_text(capsys)


def test_setup_does_not_arm_the_session(hook, monkeypatch, capsys):
    """The style is read when a session opens, so it is not loaded in this one. Arming here
    would switch on nothing and leave the person waiting for a boundary that cannot come."""
    feed(hook, monkeypatch, expand("setup"))
    capsys.readouterr()
    assert not (hook.STATE_DIR / ("decision-layer-" + SESSION)).exists()


def test_setup_report_confirms_it_worked_before_anything_else(hook, monkeypatch, capsys):
    """This opened with "nothing is switched on" once, and a tester read it as a failed
    install. After a command someone chose to run, the first words have to say it worked. The
    off state belongs second, as the next step rather than a disclaimer."""
    report = emitted_text_for_setup(hook, monkeypatch, capsys)
    assert "setup is done" in report
    assert "stays off until they ask" in report
    assert report.index("setup is done") < report.index("stays off"), (
        "the report puts what did not happen before what did, which reads as a failure")


def test_setup_report_warns_against_opening_with_a_negation(hook, monkeypatch, capsys):
    """The reason travels with the rule, so the opener cannot quietly drift back."""
    assert "did not happen" in emitted_text_for_setup(hook, monkeypatch, capsys)


def test_setup_report_tells_the_model_not_to_reassure(hook, monkeypatch, capsys):
    """The instruction is the fix, not a style note. A report that piles on reassurance reads
    as though there were something to be reassured about, which is the failure it prevents."""
    assert "do not reassure" in emitted_text_for_setup(hook, monkeypatch, capsys)


def test_setup_report_caps_its_own_length(hook, monkeypatch, capsys):
    """Length is the other half of the tone. Left uncapped the model explains what an output
    style is, and the explanation is what makes a one-line edit sound big."""
    assert "three short sentences" in emitted_text_for_setup(hook, monkeypatch, capsys)


def test_setup_report_says_this_session_cannot_switch_it_on(hook, monkeypatch, capsys):
    """Told only to use a new session, people try the arming command where they are standing.
    It is accepted and does nothing, because the style is not loaded here - the single most
    likely way a working install still looks broken."""
    report = emitted_text_for_setup(hook, monkeypatch, capsys)
    assert "this session cannot switch it on" in report
    assert "/clear" in report


def test_setup_refuses_to_overwrite_a_settings_file_it_cannot_parse(hook, monkeypatch, capsys):
    """A file we cannot read is someone's whole setup. Report it; never rewrite it."""
    broken = "{ this is not json"
    user_settings(hook).write_text(broken, encoding="utf-8")
    feed(hook, monkeypatch, expand("setup"))
    report = emitted_text(capsys)
    assert user_settings(hook).read_text(encoding="utf-8") == broken, "it clobbered the file"
    assert "could not" in report


def test_setup_leaves_no_temporary_file_behind(hook, monkeypatch, capsys):
    feed(hook, monkeypatch, expand("setup"))
    capsys.readouterr()
    leftovers = list(hook.CLAUDE_DIR.glob("*decision-layer-tmp*"))
    assert leftovers == [], leftovers


def test_the_warning_offers_the_setup_command(hook, monkeypatch, capsys, tmp_path):
    """The session-start warning is where someone meets this problem, so it is where the
    one-step fix belongs."""
    monkeypatch.chdir(tmp_path)
    feed(hook, monkeypatch, start())
    shown = system_message(capsys)
    assert shown is not None, "the hook said nothing at all"
    assert "setup" in shown


# --------------------------------------------------------------------------
# arming when the style cannot possibly apply
# --------------------------------------------------------------------------

def open_session(hook, monkeypatch, capsys, tmp_path, with_style):
    """Open a session the way a real one opens, and swallow the start-up warning."""
    monkeypatch.chdir(tmp_path)
    if with_style:
        select_style(hook, "demo-plugin:Demo")
    feed(hook, monkeypatch, start())
    capsys.readouterr()


def test_arming_a_session_that_opened_without_the_style_says_it_cannot_apply(
        hook, monkeypatch, capsys, tmp_path):
    """The model has no way to see this for itself. Arming looks identical whether the rules
    exist or not, so left alone it announces a boundary that was never there - and a confident
    false claim is worse than no boundary, because the reader trusts the prose."""
    open_session(hook, monkeypatch, capsys, tmp_path, with_style=False)
    feed(hook, monkeypatch, expand(""))
    report = emitted_text(capsys)
    assert "CANNOT apply" in report
    assert "Do NOT say the boundary is on" in report


def test_arming_a_session_that_opened_with_the_style_stays_quiet(
        hook, monkeypatch, capsys, tmp_path):
    """The ordinary path must not grow a new message."""
    open_session(hook, monkeypatch, capsys, tmp_path, with_style=True)
    feed(hook, monkeypatch, expand(""))
    assert emitted(capsys) is None


def test_setup_then_arming_in_the_same_session_still_says_it_cannot_apply(
        hook, monkeypatch, capsys, tmp_path):
    """The reported sequence, end to end: a fresh install, setup, then arming straight away.
    The style is selected by then, so a settings check would call this fine; the session still
    opened without it, which is what decides."""
    open_session(hook, monkeypatch, capsys, tmp_path, with_style=False)
    feed(hook, monkeypatch, expand("setup"))
    capsys.readouterr()
    feed(hook, monkeypatch, expand(""))
    report = emitted_text(capsys)
    assert "CANNOT apply" in report
    assert "this session opened before it" in report, "it blames the wrong cause"


def test_arming_before_setup_points_at_setup(hook, monkeypatch, capsys, tmp_path):
    open_session(hook, monkeypatch, capsys, tmp_path, with_style=False)
    feed(hook, monkeypatch, expand(""))
    assert "setup" in emitted_text(capsys)


def test_arming_still_sets_the_flag_when_the_style_is_missing(
        hook, monkeypatch, capsys, tmp_path):
    """Refusing to arm would strand anyone whose session state we failed to record, and the
    flag costs nothing. Only what the model is told changes."""
    open_session(hook, monkeypatch, capsys, tmp_path, with_style=False)
    feed(hook, monkeypatch, expand(""))
    capsys.readouterr()
    assert hook.flag_path(SESSION).exists()


def test_arming_is_silent_when_the_session_state_was_never_recorded(hook, monkeypatch, capsys):
    """No SessionStart, no verdict. Guessing here would announce a broken boundary to sessions
    that are working, so silence is the safe answer."""
    feed(hook, monkeypatch, expand(""))
    assert emitted(capsys) is None


# --------------------------------------------------------------------------
# live wiring - these read the REAL files on purpose
# --------------------------------------------------------------------------

def test_the_real_skill_still_carries_an_inject_block():
    assert "DECISION-LAYER:ARMED" in _load_hook().marker(), "the hook would inject nothing"


def test_the_real_style_looks_for_the_marker_the_hook_sends():
    """The two files are edited independently. This is the seam that rots."""
    marker_line = _load_hook().marker().splitlines()[0].strip()
    style = REAL_STYLE_PATH.read_text(encoding="utf-8")
    assert marker_line in style, f"the style never mentions {marker_line}"


def test_the_real_style_keeps_the_coding_instructions():
    """Dropping this flag degrades engineering work with no error and no warning."""
    frontmatter = REAL_STYLE_PATH.read_text(encoding="utf-8").split("---")[1]
    assert "keep-coding-instructions: true" in frontmatter


DOCS = [
    PLUGIN_DIR.parent.parent / "README.md",
    PLUGIN_DIR / "README.md",
    PLUGIN_DIR / "skills" / "decision-layer" / "SKILL.md",
]


def test_no_document_still_tells_people_to_run_output_style():
    """/output-style was removed from Claude Code; the docs sent people to a dead command."""
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        assert "/output-style" not in text, (
            path.name + " still points at the removed /output-style command")


def test_every_document_names_the_style_exactly_as_it_registers():
    """The name people are told to pick and the name the plugin registers must not drift."""
    registered = _load_hook().style_name()
    assert registered == "decision-layer:Plain", registered
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        assert registered in text, path.name + " never names " + registered


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_pasting_our_own_documentation_leaves_the_session_armed(hook, monkeypatch, capsys, path):
    """The reproduction. Every one of these documents names both switches, so while a switch
    counted anywhere in a message, quoting one back at an armed session disarmed it - and
    nothing on screen said so."""
    hook.arm(SESSION)
    feed(hook, monkeypatch, submit(path.read_text(encoding="utf-8")))
    assert hook.flag_path(SESSION).exists(), path.name + " disarmed the session"
    assert "DECISION-LAYER:ARMED" in emitted_text(capsys)


INSTALL_DOCS = [PLUGIN_DIR.parent.parent / "README.md", PLUGIN_DIR / "README.md"]


def test_both_guides_warn_that_the_current_session_cannot_see_the_style():
    """Selecting the style and then arming in the same session looks like a working install
    and does nothing whatever. Both pages have to send the reader to a fresh session.

    This pins the fact, not the sentence. Nobody reads the two pages together, and each says
    it in its own shape: the landing page warns while you are installing, the plugin page
    carries it as the first thing to check when nothing happens. Forcing them to match would
    cost whichever page had to give up its own wording.
    """
    for path in INSTALL_DOCS:
        text = path.read_text(encoding="utf-8")
        assert "/clear" in text, path.name + " never sends the reader to a fresh session"


def test_every_document_names_the_setup_command():
    """The one-command install is the whole answer to the picker's project scope. A document
    that never mentions it sends the reader back to hand-editing JSON."""
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        assert "decision-layer setup" in text, path.name + " never names the setup command"


def test_the_hand_edit_route_survives_where_it_is_described():
    """Only the terminal has an Output style picker. The VS Code extension lists the entry but
    sends you to a terminal, and the desktop app's /config opens its own settings screen, so a
    document that names only the picker strands both of them.
    """
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        assert "~/.claude/settings.json" in text, (
            path.name + " names no route for surfaces without the /config picker")


def test_the_warning_offers_a_route_without_the_picker(hook, monkeypatch, capsys, tmp_path):
    """The session-start warning reaches the surfaces that have no picker too."""
    monkeypatch.setattr(hook, "CLAUDE_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    feed(hook, monkeypatch, start())
    assert "~/.claude/settings.json" in capsys.readouterr().out
