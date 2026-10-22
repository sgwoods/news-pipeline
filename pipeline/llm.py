"""LLM backends behind one tiny interface: complete(system, user, json=True) -> str.

local        Ollama native API (default; lets us set the context window) or any
             OpenAI-compatible server (LM Studio, mlx_lm.server) with api: openai.
claude_code  headless Claude Code (`claude -p`), runs on your subscription, tools disabled.
claude_api   Anthropic API, needs ANTHROPIC_API_KEY.

Pick per stage in config.yaml: llm.backend, optionally llm.stages.<stage>.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time


class LLMError(RuntimeError):
    pass


_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def parse_json(text: str):
    """Parse a JSON object out of model output (tolerates code fences / think blocks / chatter)."""
    t = _THINK_RE.sub("", text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = t.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(t)):
            if t[i] == "{":
                depth += 1
            elif t[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = t.find("{", start + 1)
    raise LLMError(f"model did not return JSON: {t[:200]!r}")


class Backend:
    name = "base"
    model = ""

    def complete(self, system: str, user: str, json_mode: bool = True, max_tokens=None) -> str:
        raise NotImplementedError

    def complete_json(self, system: str, user: str, retries: int = 1, max_tokens=None):
        last = None
        for attempt in range(retries + 1):
            out = self.complete(system, user if attempt == 0 else
                                user + "\n\nReturn ONLY a valid JSON object, nothing else.", json_mode=True,
                                max_tokens=max_tokens)
            try:
                return parse_json(out)
            except LLMError as e:
                last = e
        raise last

    def check(self) -> str:
        """Raise LLMError with a helpful message if the backend can't be used."""
        return "ok"

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model or 'default'}"


class Local(Backend):
    name = "local"

    def __init__(self, c: dict):
        self.api = c.get("api", "ollama")
        self.base = c.get("base_url", "http://localhost:11434").rstrip("/")
        self.model = c.get("model", "")
        self.timeout = c.get("timeout_seconds", 300)
        self.num_ctx = c.get("num_ctx", 16384)
        self.temperature = c.get("temperature", 0.2)
        self.think = c.get("think", None)
        self.repeat_penalty = c.get("repeat_penalty", 1.1)

    def _client(self):
        import httpx
        return httpx.Client(timeout=self.timeout)

    def check(self) -> str:
        if not self.model:
            raise LLMError("llm.local.model is empty in config.yaml (e.g. qwen3:30b)")
        try:
            with self._client() as c:
                if self.api == "ollama":
                    r = c.get(f"{self.base}/api/tags")
                    names = {m.get("name") for m in r.json().get("models", [])}
                    if self.model not in names and f"{self.model}:latest" not in names:
                        raise LLMError(f"model {self.model!r} not pulled. Run: ollama pull {self.model}"
                                       f" (installed: {', '.join(sorted(n for n in names if n)) or 'none'})")
                else:
                    c.get(f"{self.base}/models").raise_for_status()
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"local LLM server not reachable at {self.base} ({type(e).__name__}). "
                           "Is Ollama / LM Studio running?") from e
        return "ok"

    def complete(self, system, user, json_mode=True, max_tokens=None):
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        with self._client() as c:
            if self.api == "ollama":
                body = {"model": self.model, "messages": msgs, "stream": False,
                        "options": {"temperature": self.temperature, "num_ctx": self.num_ctx,
                                    "repeat_penalty": self.repeat_penalty}}
                if max_tokens:
                    body["options"]["num_predict"] = int(max_tokens)
                if json_mode:
                    body["format"] = "json"
                if self.think is not None:
                    body["think"] = bool(self.think)
                r = c.post(f"{self.base}/api/chat", json=body)
                if r.status_code == 400 and "think" in body and "think" in r.text.lower():
                    body.pop("think")                       # model doesn't support the flag
                    r = c.post(f"{self.base}/api/chat", json=body)
                if r.status_code == 500 and "repeat" in r.text.lower():
                    # model got stuck repeating itself: one retry with a stronger penalty and more variety
                    body["options"].update({"repeat_penalty": 1.3, "temperature": 0.5})
                    r = c.post(f"{self.base}/api/chat", json=body)
                if r.status_code != 200:
                    raise LLMError(f"ollama HTTP {r.status_code}: {r.text[:200]}")
                return r.json().get("message", {}).get("content", "")
            body = {"model": self.model, "messages": msgs, "temperature": self.temperature}
            if max_tokens:
                body["max_tokens"] = int(max_tokens)
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            r = c.post(f"{self.base}/chat/completions", json=body)
            if r.status_code != 200:
                raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
            return r.json()["choices"][0]["message"]["content"]


class ClaudeCode(Backend):
    name = "claude_code"
    # Fetched content goes into these prompts, so the CLI gets no tools at all.
    DISALLOWED = ("Bash,Edit,Write,MultiEdit,NotebookEdit,NotebookRead,Read,Glob,Grep,LS,WebFetch,WebSearch,Task,Agent,"
                  "TodoWrite,Skill,SlashCommand,BashOutput,KillShell,KillBash,ExitPlanMode,mcp__*")

    def __init__(self, c: dict):
        self.cmd = c.get("command", "claude")
        self.model = c.get("model", "")
        self.timeout = c.get("timeout_seconds", 600)
        # Only the source-suggestion stage turns this on: it may search the web for feed URLs.
        # Still no shell/file tools, and every URL it returns is verified by our own code.
        self.web = False

    def check(self):
        if not shutil.which(self.cmd):
            raise LLMError(f"`{self.cmd}` not found on PATH (install Claude Code and log in)")
        if os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMError("ANTHROPIC_API_KEY is set; claude_code would bill the API. Unset it or use claude_api.")
        return "ok"

    # Only these variables reach the CLI: never the Gmail password, Slack token or Apps Script key.
    ENV_KEEP = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TERM",
                "__CF_USER_TEXT_ENCODING", "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR")
    _help = None

    def _flags(self) -> str:
        if ClaudeCode._help is None:
            try:
                ClaudeCode._help = subprocess.run([self.cmd, "--help"], capture_output=True, text=True, timeout=30,
                                                  env=self.safe_env()).stdout
            except Exception:  # noqa: BLE001
                ClaudeCode._help = ""
        return ClaudeCode._help

    @classmethod
    def safe_env(cls) -> dict:
        return {k: v for k, v in os.environ.items() if k in cls.ENV_KEEP}

    def build_args(self, system: str) -> list:
        """No tools at all (web stages: WebSearch and WebFetch only); no MCP servers; deny-list as a second layer."""
        disallowed = self.DISALLOWED
        args = [self.cmd, "-p", "--output-format", "json"]
        flags = self._flags()
        if "--strict-mcp-config" in flags:                 # ignore every MCP server in the user's settings
            args += ["--strict-mcp-config", "--mcp-config", '{"mcpServers": {}}']
        if "--tools" in flags:                             # allow-list of built-in tools (newer CLIs)
            args += ["--tools", "WebSearch,WebFetch" if self.web else ""]
        if self.web:
            disallowed = ",".join(t for t in disallowed.split(",") if t not in ("WebSearch", "WebFetch"))
            args += ["--allowedTools", "WebSearch,WebFetch"]
        args += ["--disallowedTools", disallowed, "--append-system-prompt", system]
        if self.model:
            args += ["--model", self.model]
        return args

    def complete(self, system, user, json_mode=True, max_tokens=None):
        args = self.build_args(system)
        # Run outside the project folder so the CLI doesn't load this repo's CLAUDE.md as context.
        import tempfile
        r = subprocess.run(args, input=user, capture_output=True, text=True, timeout=self.timeout,
                           cwd=tempfile.gettempdir(), env=self.safe_env())
        if r.returncode != 0:
            raise LLMError(f"claude -p failed ({r.returncode}): {(r.stderr or r.stdout)[:300]}")
        try:
            return json.loads(r.stdout).get("result", "")
        except json.JSONDecodeError:
            return r.stdout


class ClaudeAPI(Backend):
    name = "claude_api"

    def __init__(self, c: dict):
        self.model = c.get("model", "")
        self.max_tokens = c.get("max_tokens", 4096)

    def check(self):
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMError("ANTHROPIC_API_KEY not set (put it in .env)")
        return "ok"

    def complete(self, system, user, json_mode=True, max_tokens=None):
        import anthropic
        client = anthropic.Anthropic()
        for attempt in range(3):
            try:
                m = client.messages.create(model=self.model, max_tokens=self.max_tokens, system=system,
                                           messages=[{"role": "user", "content": user}])
                return "".join(b.text for b in m.content if getattr(b, "type", "") == "text")
            except anthropic.RateLimitError:
                time.sleep(5 * (attempt + 1))
        raise LLMError("rate limited")


BACKENDS = {"local": Local, "claude_code": ClaudeCode, "claude_api": ClaudeAPI}


def for_stage(cfg: dict, stage: str) -> Backend:
    llm = cfg.get("llm", {})
    name = (llm.get("stages") or {}).get(stage) or llm.get("backend", "local")
    if name not in BACKENDS:
        raise LLMError(f"unknown llm backend {name!r} for stage {stage}")
    return BACKENDS[name](llm.get(name) or {})
