"""Bounded session navigation from descriptor-backed listings, never model text."""
from dataclasses import dataclass
import json
from pathlib import Path
import re

from friday.tools.locations import command_text, instructional_question, LocationResolutionError
from friday.tools.models import DirectoryIdentity, DirectoryGuard, ToolRequest

MAX_HISTORY = 16
MAX_CHILDREN = 100


@dataclass(frozen=True)
class NavigationPlan:
    request: ToolRequest | None = None
    message: str | None = None
    transition: str = "visit"
    explanation: str | None = None


class NavigationManager:
    def __init__(self, home):
        self.home = str(Path(home).absolute())
        self.clear()

    def clear(self):
        self.current = None
        self.children = {}
        self.history = []

    def plan(self, message, locations):
        text = command_text(message).strip().rstrip(".?!")
        if instructional_question(text) and not text.casefold().startswith("explain "):
            return None
        text = re.sub(r"^(?:please |can you |could you )", "", text, flags=re.I)
        if text.lower() in {"go home", "return home"}:
            return NavigationPlan(ToolRequest("list_directory", {"path": self.home}), transition="home")
        if text.lower() in {"go back", "back", "return to the previous directory"}:
            if not self.history:
                return NavigationPlan(message="No previous directory is available in this session.")
            target = self.history[-1]
            return NavigationPlan(ToolRequest("list_directory", {"path": target.path},
                directory_guard=DirectoryGuard(target)), transition="back")
        match = re.fullmatch(
            r"(open|enter|go into|read|show(?: me)?|what(?:'s| is) in|what have in|"
            r"explain(?: what's inside)?|summarize)\s+(.+)", text, re.I)
        if not match:
            return None
        action, name = match.group(1).casefold(), match.group(2).strip()
        if action.startswith("show") and name.casefold().startswith("files in "):
            return None  # Existing deterministic list syntax retains priority.
        if name.lower() in {"this file", "that file"}:
            return None  # Preserve the existing bounded file-reference workflow.
        try:
            semantic = locations.fast_location(message)
        except LocationResolutionError:
            return None
        if semantic is not None or name.startswith(("/", "~/")) or "/" in name:
            return None  # Preserve explicit paths and standard-directory precedence.
        if re.search(r"(?<![\w.-])(application|app|viewer|player)(?![\w.-])", name, re.I):
            return None
        if self.current is None:
            if action.startswith(("what", "explain", "summarize")) and Path(name).suffix:
                return NavigationPlan(message="Please list a folder first or provide an explicit file path to read.")
            return None
        quoted = len(name) > 1 and name[0] == name[-1] == '"'
        variants = {name[1:-1]} if quoted else {name}
        file_hint = not quoted and bool(re.search(r"\s+file$", name, re.I))
        folder_hint = not quoted and bool(re.search(r"\s+(?:folder|directory)$", name, re.I))
        if not quoted:
            variants.add(re.sub(r"^(?:my|the)\s+", "", name, flags=re.I))
            variants |= {re.sub(r"\s+(?:folder|directory|file)$", "", item, flags=re.I) for item in tuple(variants)}
        matches = []
        for key, (kind, _) in self.children.items():
            candidates = {key}
            if file_hint and kind == "file":
                candidates.add(Path(key).stem)
                if Path(key).suffix:
                    candidates.add(Path(key).suffix)
            if any(candidate == item if quoted else candidate.casefold() == item.casefold()
                   for candidate in candidates for item in variants):
                matches.append(key)
        if not matches and action.startswith(("explain", "summarize")) and not file_hint and not Path(name).suffix:
            return None  # General explanatory questions remain conversation.
        if len(matches) != 1:
            return NavigationPlan(message="Please name one listed file or folder, or provide an explicit path; the reference is unknown or ambiguous.")
        name = matches[0]
        kind, identity = self.children[name]
        if kind not in {"directory", "file"} or identity is None:
            return NavigationPlan(message="That entry is not supported; symlinks and special files are not followed.")
        if kind == "file":
            if action in {"enter", "go into"} or folder_hint:
                return NavigationPlan(message="That entry is a file, not a directory. Use read or open to display supported text.")
            if Path(name).suffix.casefold() == ".zip":
                return NavigationPlan(message="Archive browsing is not supported. ZIP files are not read, extracted, executed, or launched.")
            explanation = ("summarize that file" if action == "summarize" else
                           "explain that file" if action.startswith("explain") else None)
            return NavigationPlan(ToolRequest("read_file", {"path": identity.path},
                directory_guard=DirectoryGuard(identity, self.current, operation="read_file")), explanation=explanation)
        if file_hint or action.startswith(("read", "explain", "summarize", "what")):
            return NavigationPlan(message="That entry is a directory. Use open or enter to list its contents.")
        return NavigationPlan(ToolRequest("list_directory", {"path": identity.path},
            directory_guard=DirectoryGuard(identity, self.current)))

    def translated_plan(self, request, locations):
        # Validated model basenames still cannot construct relative paths.
        path = request.arguments.get("path")
        if (request.tool_name in {"list_directory", "read_file"} and
                isinstance(path, str) and not path.startswith("~") and "/" not in path):
            if self.current is None:
                if request.tool_name == "read_file":
                    return None  # Preserve existing explicit project-relative reads.
                return NavigationPlan(message="Please list a folder first or provide an explicit folder path.")
            action = "enter " if request.tool_name == "list_directory" else "read "
            return self.plan(action + json.dumps(path, ensure_ascii=False), locations)
        return None

    def remember(self, request, result, transition="visit"):
        if request.tool_name != "list_directory" or not result.success or result.tool_name != request.tool_name or result.request_id != request.request_id:
            return
        try:
            data = result.data
            path = data["path"]
            metadata = data["directory_identity"]
            current = DirectoryIdentity(path, metadata["device"], metadata["inode"])
            children = {}
            for entry in data["entries"][:MAX_CHILDREN]:
                name = json.loads('"' + entry["name"] + '"')
                if (not isinstance(name, str) or not name or name in {".", ".."} or
                        "/" in name or len(name.encode("utf-8")) > 255 or
                        any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in name)):
                    continue
                kind = entry["type"]
                identity = None
                if kind in {"directory", "file"}:
                    info = entry.get("identity")
                    if info is not None:
                        identity = DirectoryIdentity(str(Path(path) / name), info["device"], info["inode"])
                children[name] = (kind, identity)
        except (KeyError, TypeError, ValueError, UnicodeError):
            return
        if transition == "home":
            self.history.clear()
        elif transition == "back":
            if self.history:
                self.history.pop()
        elif self.current is not None and self.current.path != current.path:
            self.history.append(self.current)
            self.history = self.history[-MAX_HISTORY:]
        self.current, self.children = current, children
