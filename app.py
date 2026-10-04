"""Test Auto Generator - 데모 서버 (Python 표준 라이브러리만 사용, 설치 불필요)

흐름:
  1. 브라우저에서 테스트 케이스를 보낸다          POST /api/generate
  2. 서버가 `claude -p` 를 실행해 스크립트를 쓰게 한다 (진행 상황은 SSE로 실시간 전송)
  3. (선택) 서버가 생성된 테스트를 pytest로 직접 실행해 PASS/FAIL 을 확인한다

실행:  python app.py   ->  http://localhost:3000
"""
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

# ---------------------------------------------------------------------------
# 설정 (환경 변수로 바꿀 수 있음)
# ---------------------------------------------------------------------------
PORT = int(os.environ.get("PORT", 3000))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
PYTHON_BIN = os.environ.get("PYTHON_BIN", sys.executable)  # 기본: 이 서버를 실행한 python
ALLOWED_TOOLS = os.environ.get("CLAUDE_ALLOWED_TOOLS", "WebFetch Read Write Edit Bash").split()

ROOT = Path(__file__).resolve().parent
GENERATED_DIR = ROOT / "generated"
PUBLIC_DIR = ROOT / "public"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".py": "text/plain; charset=utf-8",
    ".png": "image/png",
}


def has_module(code):
    """PYTHON_BIN 에서 해당 import 가 되는지 확인한다."""
    result = subprocess.run([PYTHON_BIN, "-c", code], capture_output=True)
    return result.returncode == 0


# 서버 시작 시 한 번만 확인: 서버에서 직접 pytest 를 돌릴 수 있는지
ENV = {
    "pytest": has_module("import pytest, playwright, pytest_playwright"),
    "pytestHtml": has_module("import pytest_html"),
}


# ---------------------------------------------------------------------------
# Claude 에게 보낼 지시문 (실무 규칙 = 강의에서 배운 원칙)
# ---------------------------------------------------------------------------
def build_prompt(url, test_case, out_file, pom, verify):
    lines = [
        "You are a senior QA automation engineer. Turn the manual test case below into an automated test.",
        "",
        f"Target site: {url}",
        "Framework: Playwright for Python + pytest (pytest-playwright `page` fixture, sync API)",
        f"Output file: ./{out_file} (relative to the current directory)",
        "",
        "Test case (written by a human QA engineer):",
        test_case,
        "",
        "How to work:",
        # 강의 02 - F12 로 실제 DOM 확인
        "1. Inspect the real site first - the F12 step. Fetch the page, or drive it with a headless browser / "
        "Playwright MCP if available. Every locator must come from the real DOM, never from a guess.",
        # 강의 08 - Locator 우선순위
        "2. Locator priority: test id (data-test / data-testid) > role + accessible name > visible text / placeholder "
        "> CSS (#id, .class) > XPath only as a last resort. For repeated items (e.g. product cards) narrow down "
        "with .filter(has_text=...), not with position/index.",
        # 강의 06 - 기대 결과 = assert
        "3. Every expected result in the test case must become an assertion. Use `expect(...)` from "
        "playwright.sync_api (auto-retrying). Never use time.sleep or page.wait_for_timeout.",
        "4. Keep it readable for a junior QA engineer. Test functions start with `test_` and take the `page` fixture. "
        "Add Korean comments that mirror each test-case step, e.g. `# 1. 로그인 페이지 접속`. "
        "No dead code, no unused imports.",
    ]
    step = 5
    if pom:
        # 강의 09 - Page Object Model
        lines.append(
            f"{step}. Page Object Model: define one small class per page (e.g. LoginPage, InventoryPage, CartPage) "
            "at the top of the same file, holding locators and actions. Tests only call page-object methods and assert."
        )
        step += 1
    if verify:
        lines.append(
            f"{step}. Run it: `python -m pytest {out_file} -v`. If it fails because of the script (wrong locator, "
            "timing), fix the script and run again - at most 3 runs in total. If it fails because the site really "
            "behaves differently from the expected result, keep the assertion as written and report it as a possible defect."
        )
    lines += [
        "",
        f"Write exactly one file: ./{out_file}. Do not create any other file.",
        "Finish with a short summary in Korean (3-5 lines): which locators you chose and why, any assumptions"
        + (", and the result of your last run." if verify else "."),
    ]
    return "\n".join(lines)


def claude_command():
    """CLAUDE_BIN 을 실행 가능한 명령 리스트로 만든다. (Windows 의 claude.cmd 도 찾아줌)"""
    parts = shlex.split(CLAUDE_BIN, posix=os.name != "nt")
    parts[0] = shutil.which(parts[0]) or parts[0]
    return parts


def tool_hint(tool_input):
    """도구 호출에서 화면에 보여줄 핵심 값(URL, 파일, 명령)만 뽑는다."""
    for key in ("url", "file_path", "command", "pattern"):
        if tool_input.get(key):
            return str(tool_input[key])[:200]
    return ""


# ---------------------------------------------------------------------------
# HTTP 핸들러
# ---------------------------------------------------------------------------
class ClientGone(Exception):
    """브라우저가 연결을 끊었다 (중지 버튼 등)."""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 요청마다 찍히는 기본 로그는 생략
        pass

    # ---- 라우팅 ----
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/api/env":
            return self.send_json(ENV)
        if path.startswith("/generated/"):
            return self.send_static(GENERATED_DIR, path[len("/generated/"):])
        return self.send_static(PUBLIC_DIR, "index.html" if path == "/" else path.lstrip("/"))

    def do_POST(self):
        if urlparse(self.path).path != "/api/generate":
            return self.send_error(404)
        length = int(self.headers.get("Content-Length", 0))
        if length > 100_000:
            return self.send_error(413)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self.send_error(400, "bad json")
        self.generate(data)

    # ---- 응답 도우미 ----
    def send_json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, root, rel):
        file = (root / rel).resolve()
        if root not in file.parents or not file.is_file():
            return self.send_error(404)
        body = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(file.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def sse(self, event, data):
        """브라우저로 이벤트 하나를 보낸다 (Server-Sent Events)."""
        try:
            self.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            raise ClientGone

    # ---- 핵심: 스크립트 생성 ----
    def generate(self, data):
        url = str(data.get("url", "")).strip()
        test_case = str(data.get("testCase", "")).strip()
        model = str(data.get("model", "")).strip()
        pom, verify = bool(data.get("pom")), bool(data.get("verify"))
        if not re.match(r"^https?://", url) or not test_case:
            return self.send_error(400, "url and testCase required")
        if model and not re.fullmatch(r"[\w.\-\[\]]+", model):
            return self.send_error(400, "invalid model")

        run_id = secrets.token_hex(4)
        out_file = f"test_{run_id}.py"

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        try:
            ok = self.run_claude(build_prompt(url, test_case, out_file, pom, verify), model)
            if not ok:
                return
            script_path = GENERATED_DIR / out_file
            script = script_path.read_text(encoding="utf-8") if script_path.exists() else None
            self.sse("script", {"file": f"generated/{out_file}" if script else None, "script": script})

            if script and verify and ENV["pytest"]:
                self.run_pytest(run_id, out_file)
                self.sse("done", {"verified": True})
            else:
                self.sse("done", {"verified": False})
        except ClientGone:
            pass

    def run_claude(self, prompt, model):
        """claude -p 를 실행하고 stream-json 출력을 화면용 이벤트로 바꿔 보낸다.

        내 PC에 로그인된 Claude Code 를 그대로 쓰므로 모델/권한/CLAUDE.md/MCP 설정이 적용된다.
        """
        cmd = claude_command() + [
            "-p",
            "--output-format", "stream-json", "--verbose",
            "--permission-mode", "acceptEdits",
            "--allowedTools", *ALLOWED_TOOLS,
        ]
        if model:
            cmd += ["--model", model]

        try:
            proc = subprocess.Popen(
                cmd, cwd=GENERATED_DIR, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
        except OSError as e:
            self.sse("fatal", {"error": f'cannot start "{CLAUDE_BIN}": {e}'})
            return False

        # stderr 는 따로 모아뒀다가 끝나면 보여준다
        stderr_lines = []
        threading.Thread(target=lambda: stderr_lines.extend(proc.stderr), daemon=True).start()

        try:
            proc.stdin.write(prompt)  # 프롬프트는 stdin 으로 (여러 줄도 안전)
            proc.stdin.close()
            for line in proc.stdout:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.forward(msg)
            proc.wait()
        except ClientGone:
            proc.kill()
            raise

        if stderr_lines:
            self.sse("stderr", {"text": "".join(stderr_lines)[-4000:]})
        return True

    def forward(self, msg):
        if msg.get("type") == "assistant":
            for block in msg.get("message", {}).get("content", []):
                if block.get("type") == "text" and block["text"].strip():
                    self.sse("text", {"text": block["text"]})
                elif block.get("type") == "tool_use":
                    self.sse("tool", {"name": block.get("name"), "hint": tool_hint(block.get("input") or {})})
        elif msg.get("type") == "result":
            self.sse("result", {
                "ok": not msg.get("is_error"),
                "cost": msg.get("total_cost_usd"),
                "ms": msg.get("duration_ms"),
                "turns": msg.get("num_turns"),
            })

    def run_pytest(self, run_id, out_file):
        """AI 의 요약을 믿지 않고, 서버가 직접 pytest 를 돌려 결과를 확인한다."""
        report = f"{run_id}.report.html"
        cmd = [PYTHON_BIN, "-m", "pytest", out_file, "-v", "--tb=short", "-p", "no:cacheprovider"]
        if ENV["pytestHtml"]:
            cmd += [f"--html={report}", "--self-contained-html"]
        self.sse("run-start", {"cmd": "python " + " ".join(cmd[1:])})

        proc = subprocess.Popen(
            cmd, cwd=GENERATED_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        counts = {"passed": 0, "failed": 0, "error": 0}
        try:
            for line in proc.stdout:
                line = line.rstrip("\r\n")
                self.sse("run-line", {"text": line})
                # 마지막 요약 줄 예: "==== 2 passed, 1 failed in 3.21s ===="
                if re.match(r"^=+ .* in [\d.]+s", line):
                    for n, kind in re.findall(r"(\d+) (passed|failed|errors?)", line):
                        counts["error" if kind.startswith("error") else kind] = int(n)
            proc.wait()
        except ClientGone:
            proc.kill()
            raise

        has_report = ENV["pytestHtml"] and (GENERATED_DIR / report).exists()
        self.sse("run-done", {"code": proc.returncode, **counts, "report": f"/generated/{report}" if has_report else None})


def main():
    GENERATED_DIR.mkdir(exist_ok=True)
    print(f"test-auto-generator on http://localhost:{PORT}")
    if not ENV["pytest"]:
        print('  (pytest-playwright 미설치: "실행 검증"은 건너뜁니다 -> pip install -r requirements.txt)')
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
