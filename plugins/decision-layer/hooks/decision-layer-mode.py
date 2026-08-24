"""Keeps the decision-layer boundary switched on for one session. See skills/decision-layer/SKILL.md.

The rules themselves are NOT here and are not injected. They live in the output style
output-styles/decision-layer.md, which sits in the system prompt permanently and is written
conditionally: it applies only to a turn carrying the marker. All this hook does is decide,
per turn, whether to send that marker. That is why the injected text is a few dozen tokens
rather than the whole rulebook.

Three hook events, because Claude Code splits them:

  SessionStart         fires once when a session opens. Checks that the output style this
                       plugin ships was actually selected, and remembers the answer for this
                       session. If it was not, the whole plugin is inert - arming writes its
                       flag, the marker goes out, and nothing happens, because the rules live
                       in the style. That failure is invisible, so say so on screen rather
                       than let it pass. The remembered answer is what arming consults later:
                       the style is loaded when a session opens, so selecting it afterwards
                       cannot help this one, and only the verdict taken at the start knows.
  UserPromptExpansion  fires for a TYPED slash command and carries command_name and
                       command_args. "/decision-layer" arms the session, "/decision-layer
                       off" disarms it, and "/decision-layer setup" selects the output style
                       in the user's own settings file, which is the one scope that covers
                       every project. Deterministic - no model involvement.
  UserPromptSubmit     fires for ordinary text. While the session is armed, send the marker
                       so the style engages for that turn. "--impl" suppresses the marker
                       for one turn (the escape hatch); "--impl-off" disarms the session
                       outright. Either counts only as a word of its own on the first or
                       last line of the message, so quoting one does not throw it. Both are
                       handled here, so neither depends on the model reading anything.

Armed state is one file per session, under the user's config directory:
state/decision-layer-<session_id>. Keyed by session id because several sessions can run on one
machine at once, and because a new session must start OFF - that is the whole reason this hook
exists rather than just setting the output style and leaving it on. State lives in the config
directory rather than the plugin directory, which is versioned and replaced on update.

The marker text lives in skills/decision-layer/SKILL.md between INJECT markers and is read at
run time, so changing it is an edit to that one file.

Also runnable by hand, for when the skill was invoked in plain words rather than typed as a
command, so no UserPromptExpansion event ever fired:

    bash decision-layer-mode.sh --arm
    bash decision-layer-mode.sh --disarm

Any failure is silent when running as a hook. A hook that breaks must not break the session,
and failing silently here fails safe: no marker means no boundary, which is ordinary output.
"""

import glob
import json
import os
import re
import sys
import time
from pathlib import Path

SKILL_NAME = "decision-layer"


def config_dir():
    """Where Claude Code keeps sessions, transcripts and our state file.

    CLAUDE_CONFIG_DIR moves that whole directory, so honour it before falling back to
    ~/.claude.
    """
    override = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if override:
        return Path(os.path.expanduser(override))
    return Path(os.path.expanduser("~")) / ".claude"


def plugin_root():
    """The installed plugin directory.

    Set for us when we run as a plugin hook. When run by hand it is absent, so fall back to
    this file's own location - hooks/ sits one level below the plugin root.
    """
    root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if root:
        return Path(root)
    return Path(__file__).resolve().parent.parent


CLAUDE_DIR = config_dir()
STATE_DIR = CLAUDE_DIR / "state"
PLUGIN_DIR = plugin_root()
SKILL_PATH = PLUGIN_DIR / "skills" / SKILL_NAME / "SKILL.md"
STYLE_DIR = PLUGIN_DIR / "output-styles"
MANIFEST_PATH = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
LOG_PATH = STATE_DIR / (SKILL_NAME + "-mode.log")

# Session ids are uuids. Validate before using one in a path.
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
INJECT_RE = re.compile(r"<!--\s*INJECT:BEGIN\s*-->(.*?)<!--\s*INJECT:END\s*-->", re.S)

# Run only against a frontmatter block, never a whole file: "name:" appears in ordinary prose
# too, and the first match anywhere would quietly win.
FRONTMATTER_NAME_RE = re.compile(r"^name:\s*(\S.*?)\s*$", re.M)

# Matched against the FIRST WORD of the argument, exactly. A prefix match would read
# "/decision-layer now" as "no" and silently switch the boundary off, which is the worst
# possible failure: the user sees an ordinary reply and no sign anything was disabled.
OFF_WORDS = ("off", "stop", "no", "disable")

# "/decision-layer setup" selects the style for every project at once. It exists because the
# only picker Claude Code offers is the terminal's, and that one saves to the project you
# happen to be standing in, so a pick made in one repository leaves every other one without
# the style. The words people reach for vary; accept the obvious ones.
SETUP_WORDS = ("setup", "install", "select")

# What was true about the style when this session opened, remembered per session. The style
# is loaded once, at that moment, so a selection made later - by /decision-layer setup, or by
# hand - is real everywhere except here. Recording it at the start is the only honest way to
# know later: reading the settings file at arming time answers a different question.
STYLE_LOADED = "loaded"
STYLE_MISSING = "missing"

# The user's own settings file, named the way the documentation names it. The real path goes
# through CLAUDE_DIR, but a home-relative spelling is what a person can act on.
USER_SETTINGS_LABEL = "~/.claude/settings.json"

# Order matters: --impl-off contains --impl, so the session kill-switch has to be tested
# first or it would only ever read as a one-turn escape.
KILL_WORD = "--impl-off"
ESCAPE_WORD = "--impl"

LOG_MAX_BYTES = 256 * 1024


def log(message):
    """One line per state change or error. Truncates itself so it cannot grow unbounded."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES:
            LOG_PATH.unlink()
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except Exception:
        pass


def flag_path(session_id):
    return STATE_DIR / (SKILL_NAME + "-" + session_id)


def sweep_old_flags(max_age_days=14):
    """Arming is rare, so it is the cheap moment to drop flags from long-dead sessions."""
    cutoff = time.time() - max_age_days * 86400
    for path in glob.glob(str(STATE_DIR / (SKILL_NAME + "-*"))):
        if os.path.normcase(path) == os.path.normcase(str(LOG_PATH)):
            continue
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except Exception:
            pass


def arm(session_id):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    sweep_old_flags()
    flag_path(session_id).write_text("", encoding="utf-8")
    log(session_id + " armed")


def disarm(session_id):
    try:
        flag_path(session_id).unlink()
        log(session_id + " disarmed")
    except FileNotFoundError:
        pass


def switch_typed(prompt, switch):
    """Was this switch typed, or merely quoted in passing?

    It counts as typed only as a word of its own on the first or last line. That is where a
    switch actually gets thrown: at the top or the bottom of whatever is being written,
    mid-run, without stopping to read. Everywhere else it is nearly always a paste - and
    this plugin's own documentation names both switches, so honouring them anywhere in a
    message meant quoting the help text switched the plugin off, with nothing on screen to
    say it had.
    """
    lines = prompt.strip().splitlines()
    return bool(lines) and (switch in lines[0].split() or switch in lines[-1].split())


def marker():
    """The text between the INJECT markers in the skill."""
    match = INJECT_RE.search(SKILL_PATH.read_text(encoding="utf-8"))
    return match.group(1).strip() if match else ""


def emit(text, event="UserPromptSubmit"):
    """Hook output. Anything else printed would be injected verbatim, so print only this.

    hookSpecificOutput is validated as a union keyed on hookEventName, and each event has
    its own variant, so the name here has to be the event that actually fired.
    """
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": text,
        }
    }))


def warn_user(text):
    """A line shown to the user in the terminal, not to the model.

    emit() talks to the model; this one talks to the person. Both print JSON on stdout, so
    only ever call one of them per run.
    """
    print(json.dumps({"systemMessage": text}))


def plugin_name():
    """The name Claude Code registers this plugin under."""
    try:
        name = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("name")
        if name:
            return str(name)
    except Exception:
        pass
    return PLUGIN_DIR.name


def frontmatter_name(path):
    """The name: field of a markdown file's frontmatter, or its filename if it has none."""
    text = Path(path).read_text(encoding="utf-8")
    if text.startswith("---"):
        match = FRONTMATTER_NAME_RE.search(text.split("---")[1])
        if match:
            return match.group(1)
    return Path(path).stem


def style_name():
    """The style's full name, spelled the way the picker spells it.

    A style shipped inside a plugin is registered as "<plugin>:<style>", never as the bare
    name in its frontmatter. Derive both halves rather than hard-coding the result: a copy
    of a name in a second place is exactly what goes stale without anyone noticing.
    """
    for path in sorted(glob.glob(str(STYLE_DIR / "*.md"))):
        return plugin_name() + ":" + frontmatter_name(path)
    return ""


def selected_styles():
    """Every output style named by a settings file that could apply here.

    Claude Code merges several settings files and the precedence is its business, not ours.
    Collecting them all and treating any match as good keeps this from crying wolf at
    someone who selected the style in a place we did not think to look.
    """
    here = Path(os.getcwd())
    paths = [
        CLAUDE_DIR / "settings.json",
        here / ".claude" / "settings.json",
        here / ".claude" / "settings.local.json",
    ]
    found = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get("outputStyle")
        except Exception:
            continue
        if value:
            found.append(str(value))
    return found


def style_state_path(session_id):
    return STATE_DIR / (SKILL_NAME + "-style-" + session_id)


def record_style_state(session_id, loaded):
    """Remember, at session start, whether the style was there to be loaded."""
    if not SESSION_RE.match(session_id or ""):
        return
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        style_state_path(session_id).write_text(
            STYLE_LOADED if loaded else STYLE_MISSING, encoding="utf-8")
    except Exception:
        pass


def style_was_loaded(session_id):
    """Did this session open with the style? Empty when we never got to record it."""
    try:
        return style_state_path(session_id).read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def arm_report(selected_now):
    """What to say when arming cannot do anything, which the model has no way to notice.

    Arming writes its flag and sends its marker whatever the style is doing, and the rules the
    marker points at live in the style. With the style absent the marker points at nothing, so
    the reply comes back ordinary - and the model, going by the marker alone, announces that
    the boundary is on. A confident false claim is worse than no boundary: the reader trusts
    prose that was never written under one.
    """
    head = ("The decision-layer boundary CANNOT apply to this session: its output style was "
            "not loaded when this session opened, so none of its rules are in your prompt. "
            "Do NOT say the boundary is on, and do not write its footer. ")
    if selected_now:
        return head + ("Tell the user the style is selected but this session opened before it "
                       "was, so it cannot see it - starting a new session, or running /clear, "
                       "picks it up, and arming there works. Then answer their message "
                       "normally, with full implementation detail.")
    return head + ("Tell the user no output style is selected yet, so there is nothing to "
                   "switch on - running /" + SKILL_NAME + " setup selects it, and it takes "
                   "effect in a new session or after /clear. Then answer their message "
                   "normally, with full implementation detail.")


def check_style_selected(session_id=""):
    """Say so when the plugin is installed but its output style was never picked.

    This is the plugin's quietest way to fail. The rules live in the style, so without it
    selected everything else still works and produces nothing: the command is accepted, the
    flag file is written, the marker goes out, and the reply comes back in ordinary prose
    with no footer and no error. Nothing on screen separates that from the boundary simply
    having little to say, so the user has no way to tell.
    """
    ours = style_name()
    if not ours:
        return
    chosen = selected_styles()
    record_style_state(session_id, ours in chosen)
    if ours in chosen:
        return
    # Offer the command rather than the picker. Only the terminal has a picker, and the pick
    # it saves covers one project; the command works on every surface and every project. Name
    # the file as well, for anyone who would rather see the edit than run something.
    fix = ("Run \"/" + SKILL_NAME + " setup\" to select it for every project, or add "
           "\"outputStyle\": \"" + ours + "\" to " + USER_SETTINGS_LABEL + " by hand.")
    if chosen:
        warn_user("decision-layer is installed, but your output style is \"" + chosen[0]
                  + "\", so the boundary will never appear. " + fix)
    else:
        warn_user("decision-layer is installed, but no output style is selected, so arming "
                  "it does nothing. " + fix)


def select_style_globally():
    """Put this plugin's output style into the user's own settings file.

    This is the same one-line edit a person would otherwise make by hand, and the user file
    is the only scope that covers every project: the terminal picker writes the project-local
    file, and neither the VS Code extension nor the desktop app offers a picker at all.

    Never overwrite a settings file we could not parse - a half-understood config is someone's
    whole setup. Write through a temporary file so a crash mid-write cannot truncate it.

    Returns (ok, replaced, reason). "replaced" is whatever outputStyle was set before, and is
    empty when there was none.
    """
    ours = style_name()
    if not ours:
        return False, "", "this plugin ships no output style"
    path = CLAUDE_DIR / "settings.json"
    settings = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            return False, "", "could not read " + USER_SETTINGS_LABEL + " as JSON: " + str(error)
        if not isinstance(settings, dict):
            return False, "", USER_SETTINGS_LABEL + " does not hold a JSON object"
    replaced = str(settings.get("outputStyle") or "")
    if replaced == ours:
        return True, replaced, ""
    settings["outputStyle"] = ours
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.parent / (path.name + ".decision-layer-tmp")
        temp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        os.replace(str(temp), str(path))
    except Exception as error:
        return False, replaced, "could not write " + USER_SETTINGS_LABEL + ": " + str(error)
    return True, replaced, ""


def setup_report(ok, replaced, reason):
    """What to tell the person after a setup run.

    Two traps, pulling opposite ways. Pile on reassurance and a one-line edit reads as though
    it were dangerous - the more lines spent saying nothing changed, the harder the reader
    looks for what did. But lead with what did NOT happen and it reads as a failure report:
    "nothing is switched on" is the first thing someone sees after running a command they
    chose, and it lands as "it did not work".

    So: confirm it worked, then say it stays off until asked - forward-looking, the next step
    rather than a disclaimer. The instructions about ordering and reassurance are not style
    notes; they are the fix.

    The last sentence earns its place by saving a confusing minute. Someone told to run the
    arming command will try it where they are standing, and the style is not loaded in the
    session that selected it, so it accepts the command and does nothing. Saying which session
    to use is not enough; the reason has to come with it.

    The one fact that earns a sentence of its own is what the write took over from, if it
    took over anything, because that is the only part the person cannot see for themselves.
    """
    ours = style_name()
    if not ok:
        return ("The decision-layer setup could not finish: " + reason + ". Tell the user, "
                "and tell them they can add \"outputStyle\": \"" + ours + "\" to "
                + USER_SETTINGS_LABEL + " themselves. Do not edit the file for them.")
    lines = [
        "The decision-layer setup succeeded. Tell the user, in at most three short sentences, "
        "and in this order: setup is done and decision-layer is ready in every project; it "
        "stays off until they ask for it; and this session cannot switch it on, because "
        "Claude Code loads the output style when a session opens - so they start a new "
        "session or run /clear, and run /" + SKILL_NAME + " there.",
    ]
    if replaced and replaced != ours:
        lines.append("Add one more sentence, no longer: it took over from \"" + replaced
                     + "\", and setting \"outputStyle\": \"" + replaced + "\" in "
                     + USER_SETTINGS_LABEL + " puts it back.")
    lines.append("Open by confirming it worked. A message that opens with what did NOT happen "
                 "reads as a failure report however it ends, and this one follows a command "
                 "the user chose to run.")
    lines.append("Then say it as routine. Do not explain what an output style is, do not list "
                 "what is unaffected, and do not reassure them - this is a small thing, and "
                 "dwelling on it is what makes it read as a large one.")
    lines.append("Do not arm the boundary and do not write the decision-layer footer: the "
                 "style is not loaded in this session yet.")
    return "\n".join(lines)


def is_our_command(command_name):
    """Match the skill whether or not the host namespaced the command.

    A skill shipped inside a plugin can surface as "decision-layer" or as
    "<plugin>:decision-layer", so compare the last segment rather than the whole string.
    """
    return str(command_name or "").lower().rsplit(":", 1)[-1] == SKILL_NAME


def same_dir(left, right):
    """Path comparison: case and separators both vary between sources on Windows."""
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def resolve_session_id():
    """Which session is a hand-run command sitting inside?

    sessions/<pid>.json holds pid, sessionId and cwd for each running CLI. Filter by the
    working directory; if several sessions share it, take the one whose transcript was
    written most recently, which is the one that just prompted.
    """
    here = os.getcwd()
    candidates = []
    for path in glob.glob(str(CLAUDE_DIR / "sessions" / "*.json")):
        try:
            entry = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            continue
        session_id = str(entry.get("sessionId") or "")
        if not SESSION_RE.match(session_id) or not same_dir(entry.get("cwd") or "", here):
            continue
        transcripts = glob.glob(str(CLAUDE_DIR / "projects" / "*" / (session_id + ".jsonl")))
        newest = max((os.path.getmtime(t) for t in transcripts), default=0)
        candidates.append((newest, session_id))
    if not candidates:
        return ""
    return max(candidates)[1]


def run_cli(argument):
    """Hand-run mode. Prints a plain sentence: this output goes to a tool result, not context."""
    session_id = resolve_session_id()
    if not session_id:
        print("Could not work out which session this is. No session in "
              + str(CLAUDE_DIR / "sessions") + " has cwd " + os.getcwd() + ".")
        return
    if argument == "--arm":
        arm(session_id)
        print("Decision-layer boundary armed for session " + session_id + ".")
    else:
        disarm(session_id)
        print("Decision-layer boundary off for session " + session_id + ".")


def run_hook():
    payload = json.loads(sys.stdin.read())

    # Needs no session id, so it runs before that check rather than after it.
    if payload.get("hook_event_name") == "SessionStart":
        check_style_selected(str(payload.get("session_id") or ""))
        return

    session_id = str(payload.get("session_id") or "")
    if not SESSION_RE.match(session_id):
        return

    if payload.get("hook_event_name") == "UserPromptExpansion":
        if not is_our_command(payload.get("command_name")):
            return
        words = str(payload.get("command_args") or "").strip().lower().split()
        if words and words[0] in SETUP_WORDS:
            ok, replaced, reason = select_style_globally()
            # Deliberately does not arm. The style is read once when a session opens, so it
            # is not loaded in this one, and arming now would switch on nothing.
            emit(setup_report(ok, replaced, reason), "UserPromptExpansion")
        elif words and words[0] in OFF_WORDS:
            disarm(session_id)
            # The skill body still loads and describes the boundary. Say plainly that it no
            # longer applies, so the turn does not act on it.
            emit("The decision-layer boundary is now OFF for this session. Ignore the "
                 "decision-layer skill instructions and write normally, with full "
                 "implementation detail.", "UserPromptExpansion")
        else:
            # Arm either way: the flag is harmless, and refusing it would strand anyone whose
            # session state we failed to record. What changes is what the model is told.
            arm(session_id)
            if style_was_loaded(session_id) == STYLE_MISSING:
                emit(arm_report(style_name() in selected_styles()), "UserPromptExpansion")
        return

    prompt = str(payload.get("prompt") or "")

    # Kill-switch first: --impl-off contains --impl, so testing the escape word first would
    # swallow it and the session would never disarm.
    if switch_typed(prompt, KILL_WORD):
        disarm(session_id)
        return

    if not flag_path(session_id).exists():
        return

    # One-turn escape. Send no marker, so the style simply does not engage this turn.
    if switch_typed(prompt, ESCAPE_WORD):
        return

    text = marker()
    if not text:
        log(session_id + " ERROR: no INJECT block in " + str(SKILL_PATH))
        return
    emit(text)


if __name__ == "__main__":
    argument = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if argument in ("--arm", "--disarm"):
            run_cli(argument)
        else:
            run_hook()
    except Exception as error:
        if argument:
            print("Failed: " + type(error).__name__ + ": " + str(error))
        log("ERROR " + type(error).__name__ + ": " + str(error))
    sys.exit(0)
