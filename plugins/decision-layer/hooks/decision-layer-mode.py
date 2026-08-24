"""Keeps the decision-layer boundary switched on for one session. See skills/decision-layer/SKILL.md.

The rules themselves are NOT here and are not injected. They live in the output style
output-styles/decision-layer.md, which sits in the system prompt permanently and is written
conditionally: it applies only to a turn carrying the marker. All this hook does is decide,
per turn, whether to send that marker. That is why the injected text is a few dozen tokens
rather than the whole rulebook.

Three hook events, because Claude Code splits them:

  SessionStart         fires once when a session opens. Used only to check that the output
                       style this plugin ships was actually selected. If it was not, the
                       whole plugin is inert - arming writes its flag, the marker goes out,
                       and nothing happens, because the rules live in the style. That failure
                       is invisible, so say so on screen rather than let it pass.
  UserPromptExpansion  fires for a TYPED slash command and carries command_name and
                       command_args. "/decision-layer" arms the session, "/decision-layer
                       off" disarms it. Deterministic - no model involvement.
  UserPromptSubmit     fires for ordinary text. While the session is armed, send the marker
                       so the style engages for that turn. "--impl" suppresses the marker
                       for one turn (the escape hatch); "--impl-off" disarms the session
                       outright. Both are handled here, so neither depends on the model
                       reading anything.

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


def check_style_selected():
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
    if ours in chosen:
        return
    if chosen:
        warn_user("decision-layer is installed, but your output style is \"" + chosen[0]
                  + "\", so the boundary will never appear. Pick \"" + ours
                  + "\" in /config -> Output style.")
    else:
        warn_user("decision-layer is installed, but no output style is selected, so arming "
                  "it does nothing. Pick \"" + ours + "\" in /config -> Output style.")


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
        check_style_selected()
        return

    session_id = str(payload.get("session_id") or "")
    if not SESSION_RE.match(session_id):
        return

    if payload.get("hook_event_name") == "UserPromptExpansion":
        if not is_our_command(payload.get("command_name")):
            return
        words = str(payload.get("command_args") or "").strip().lower().split()
        if words and words[0] in OFF_WORDS:
            disarm(session_id)
            # The skill body still loads and describes the boundary. Say plainly that it no
            # longer applies, so the turn does not act on it.
            emit("The decision-layer boundary is now OFF for this session. Ignore the "
                 "decision-layer skill instructions and write normally, with full "
                 "implementation detail.", "UserPromptExpansion")
        else:
            arm(session_id)
        return

    prompt = str(payload.get("prompt") or "")

    # Kill-switch first: --impl-off contains --impl, so testing the escape word first would
    # swallow it and the session would never disarm.
    if KILL_WORD in prompt:
        disarm(session_id)
        return

    if not flag_path(session_id).exists():
        return

    # One-turn escape. Send no marker, so the style simply does not engage this turn.
    if ESCAPE_WORD in prompt:
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
