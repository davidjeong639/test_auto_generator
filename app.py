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
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

# ---------------------------------------------------------------------------
# 설정 (환경 변수로 바꿀 수 있음)
# ---------------------------------------------------------------------------
PORT = int(os.environ.get("PORT", 3000))
# 기본은 내 PC 에서만 접속 가능. Claude 가 Bash 를 자동 실행하므로 강의장 와이파이 등에 열면 위험하다.
HOST = os.environ.get("HOST", "127.0.0.1")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
PYTHON_BIN = os.environ.get("PYTHON_BIN", sys.executable)  # 기본: 이 서버를 실행한 python
ALLOWED_TOOLS = os.environ.get("CLAUDE_ALLOWED_TOOLS", "WebFetch Read Write Edit Bash").split()
# WSL(리눅스)에 로그인된 claude 를 쓰려면:  python app.py --wsl
USE_WSL = "--wsl" in sys.argv or os.environ.get("CLAUDE_WSL") == "1"

ROOT = Path(__file__).resolve().parent
GENERATED_DIR = ROOT / "generated"
PUBLIC_DIR = ROOT / "public"
TEST_CASES_FILE = ROOT / "test_cases.json"  # 화면의 예시 케이스 목록 (자유롭게 추가/수정)

# 화면에서 고를 수 있는 모델. id 는 `claude --model` 에 그대로 전달된다. ("" = 내 Claude Code 기본값)
MODELS = [
    {"id": "", "label": "기본값 (내 Claude Code 설정)"},
    {"id": "claude-sonnet-5-5", "label": "Sonnet 5.5 · 속도와 품질 균형 (추천)"},
    {"id": "claude-opus-5-5", "label": "Opus 5.5 · 가장 꼼꼼함, 느림"},
    {"id": "claude-haiku-4-5-20251001", "label": "Haiku 4.5 · 가장 빠르고 저렴"},
    {"id": "claude-fable-5-1", "label": "Fable 5.1"},
]

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".py": "text/plain; charset=utf-8",
    ".png": "image/png",
    ".webm": "video/webm",
}


ANSI_COLOR = re.compile(r"\x1b\[[0-9;]*m")  # 터미널 색상 코드 (FORCE_COLOR 환경 등에서 섞여 들어옴)


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
# 하네스: Claude 에게 넘기는 지시문과 도구 (harness/ 폴더)
#   system_prompt.md  역할 · 작업 순서 · Locator/검증 규칙 · 금지사항 · 보고 형식
#   task.md           이번 작업 (사이트, 케이스, 옵션, 사전 분석 결과)
#   inspect_page.py   페이지 요소와 Locator 후보를 뽑아주는 분석 도구 (F12 대신)
# ---------------------------------------------------------------------------
HARNESS_DIR = ROOT / "harness"
MAX_TURNS = int(os.environ.get("CLAUDE_MAX_TURNS", 40))  # 무한 반복 방지


def load_test_cases():
    """test_cases.json 을 읽는다. 요청마다 읽으므로 파일을 고치고 새로고침하면 바로 반영된다."""
    try:
        return json.loads(TEST_CASES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"  test_cases.json 을 읽지 못했습니다: {e}")
        return []


def wsl_path(windows_path):
    """E:\\a\\b.exe -> /mnt/e/a/b.exe (WSL 안에서 Windows 파일을 부를 때)"""
    p = Path(windows_path).resolve()
    return f"/mnt/{p.drive[0].lower()}{p.as_posix()[2:]}"


def claude_python():
    """Claude 가 Bash 로 부를 python. 서버와 같은 python(venv)을 써서 결과가 일치하게 한다."""
    return wsl_path(PYTHON_BIN) if USE_WSL else f'"{Path(PYTHON_BIN).as_posix()}"'


def pytest_command(out_file):
    return f"{claude_python()} -m pytest {out_file} -v"


def inspect_command():
    # 작업 폴더가 generated/ 이므로 상대 경로는 WSL / Windows 양쪽에서 똑같이 동작한다
    return f"{claude_python()} ../harness/inspect_page.py"


def pre_inspect(url):
    """Claude 를 부르기 전에 첫 화면을 미리 분석한다. (Claude 의 탐색 턴을 줄이고, 화면에도 보여준다)"""
    if not ENV["pytest"]:
        return "(분석 도구를 쓸 수 없음: pytest-playwright 미설치. 직접 페이지를 확인할 것)"
    try:
        result = subprocess.run(
            [PYTHON_BIN, str(HARNESS_DIR / "inspect_page.py"), url],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        return (result.stdout + result.stderr).strip() or "(출력 없음)"
    except subprocess.TimeoutExpired:
        return "(사전 분석 시간 초과. 분석 도구로 직접 확인할 것)"


def build_prompt(url, test_case, out_file, pom, verify, inspection):
    """하네스 파일을 채워 Claude 에게 보낼 지시문 전체를 만든다."""
    options = ["- 구조: " + (
        "Page Object Model — 페이지마다 작은 클래스(LoginPage, InventoryPage 등)를 같은 파일 위쪽에 두고, "
        "테스트 함수는 페이지 객체 메서드 호출과 검증만 한다"
        if pom else "단순 테스트 함수 (클래스 없이)"
    )]
    if verify:
        options.append(f"- 실행 명령: `{pytest_command(out_file)}` — 작성 후 직접 실행, 최대 3번")
    else:
        options.append("- 실행: 하지 않음 (작성만). 보고의 실행 결과는 \"실행 안 함\"")

    system = (HARNESS_DIR / "system_prompt.md").read_text(encoding="utf-8")
    system = system.replace("{inspect_command}", inspect_command())
    task = (HARNESS_DIR / "task.md").read_text(encoding="utf-8")
    for key, value in {"url": url, "out_file": out_file, "options": "\n".join(options),
                       "test_case": test_case, "inspection": inspection}.items():
        task = task.replace("{" + key + "}", value)
    return f"{system.strip()}\n\n---\n\n{task.strip()}\n"


def check_script(path):
    """생성된 스크립트를 실행 전에 점검한다. (하네스의 마지막 안전장치)"""
    text = path.read_text(encoding="utf-8")
    checks = []

    def add(ok, msg, level="error"):
        checks.append({"ok": ok, "level": "ok" if ok else level, "msg": msg})

    try:
        compile(text, path.name, "exec")
        add(True, "파이썬 문법 OK")
    except SyntaxError as e:
        add(False, f"문법 오류: {e.msg} (줄 {e.lineno})")
    tests = re.findall(r"^\s*def (test_\w+)", text, re.M)
    add(bool(tests), f"테스트 함수 {len(tests)}개: {', '.join(tests)}" if tests else "test_ 함수가 없음 (pytest 가 못 찾음)")
    asserts = len(re.findall(r"\bexpect\(|^\s*assert\b", text, re.M))
    add(asserts > 0, f"검증(expect/assert) {asserts}개" if asserts else "검증이 0개 — 테스트가 아님")
    sleeps = re.findall(r"time\.sleep|wait_for_timeout", text)
    add(not sleeps, "sleep 없음 (자동 대기 사용)" if not sleeps else f"고정 대기 {len(sleeps)}곳 — 느리고 불안정", "warn")
    xpaths = len(re.findall(r"xpath=|[\"']//", text))
    add(not xpaths, "XPath 없음" if not xpaths else f"XPath {xpaths}곳 — 더 안정적인 Locator 가 있는지 확인", "warn")
    nths = len(re.findall(r"\.nth\(", text))
    add(not nths, "위치 기반(nth) 없음" if not nths else f"nth() {nths}곳 — 순서가 바뀌면 깨질 수 있음", "warn")
    return checks


def claude_command():
    """CLAUDE_BIN 을 실행 가능한 명령 리스트로 만든다. (Windows 의 claude.cmd 도 찾아줌)"""
    if USE_WSL:
        # 로그인 셸(-l)로 실행해야 ~/.local/bin 등 평소 PATH 에서 claude 를 찾는다
        return ["wsl", "-e", "bash", "-lc", 'exec claude "$@"', "claude"]
    parts = shlex.split(CLAUDE_BIN, posix=os.name != "nt")
    found = shutil.which(parts[0])
    if not found and os.name == "nt" and parts[0] == "claude":
        # PATH 에 없을 때: npm 전역 설치 기본 위치
        npm_claude = Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd"
        found = str(npm_claude) if npm_claude.exists() else None
    parts[0] = found or parts[0]
    return parts


def tool_hint(tool_input):
    """도구 호출에서 화면에 보여줄 핵심 값(URL, 파일, 명령)만 뽑는다."""
    for key in ("url", "file_path", "command", "pattern"):
        if tool_input.get(key):
            return str(tool_input[key])[:200]
    return ""


# ---------------------------------------------------------------------------
# 생성된 스크립트 기록 (generated/test_xxxx.json)
#   어떤 케이스로 만들었는지, 마지막 실행 결과는 어땠는지 저장해 두고 화면에서 다시 보여준다.
# ---------------------------------------------------------------------------
def meta_path(run_id):
    return GENERATED_DIR / f"test_{run_id}.json"


def save_meta(run_id, **fields):
    path = meta_path(run_id)
    meta = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"id": run_id}
    meta.update(fields)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def list_scripts():
    """최신순 목록. 스크립트 파일이 지워진 기록은 뺀다."""
    metas = []
    for path in GENERATED_DIR.glob("test_*.json"):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (GENERATED_DIR / meta.get("file", "")).is_file():
            metas.append(meta)
    return sorted(metas, key=lambda m: m.get("createdAt", ""), reverse=True)


def now():
    return datetime.now().isoformat(timespec="seconds")


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
        if path == "/api/config":
            return self.send_json({"env": ENV, "models": MODELS, "examples": load_test_cases()})
        if path == "/api/scripts":
            return self.send_json(list_scripts())
        if path.startswith("/generated/"):
            return self.send_static(GENERATED_DIR, path[len("/generated/"):])
        return self.send_static(PUBLIC_DIR, "index.html" if path == "/" else path.lstrip("/"))

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/generate", "/api/run"):
            return self.send_error(404)
        length = int(self.headers.get("Content-Length", 0))
        if length > 100_000:
            return self.send_error(413)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self.send_error(400, "bad json")
        if path == "/api/generate":
            self.generate(data)
        else:
            self.rerun(data)

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

    def start_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

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
        pom, verify, headed = bool(data.get("pom")), bool(data.get("verify")), bool(data.get("headed"))
        case_id = str(data.get("caseId") or "NEW")[:40]
        if not re.match(r"^https?://", url) or not test_case:
            return self.send_error(400, "url and testCase required")
        if model and not re.fullmatch(r"[\w.\-\[\]]+", model):
            return self.send_error(400, "invalid model")

        run_id = secrets.token_hex(4)
        out_file = f"test_{run_id}.py"

        self.start_sse()
        try:
            self.sse("inspect-start", {"url": url})
            inspection = pre_inspect(url)
            self.sse("inspect", {"output": inspection})

            ok = self.run_claude(build_prompt(url, test_case, out_file, pom, verify, inspection), model)
            if not ok:
                return
            script_path = GENERATED_DIR / out_file
            script = script_path.read_text(encoding="utf-8") if script_path.exists() else None
            checks = check_script(script_path) if script else []
            if checks:
                self.sse("check", {"items": checks})
            self.sse("script", {"id": run_id if script else None, "file": f"generated/{out_file}" if script else None, "script": script})
            if script:
                save_meta(
                    run_id, file=out_file, caseId=case_id, title=test_case.splitlines()[0][:80], testCase=test_case,
                    url=url, model=model or "default", pom=pom, createdAt=now(), checks=checks, lastRun=None,
                )

            if script and verify and ENV["pytest"]:
                save_meta(run_id, lastRun=self.run_pytest(run_id, out_file, headed))
                self.sse("done", {"verified": True})
            else:
                self.sse("done", {"verified": False})
        except ClientGone:
            pass

    def rerun(self, data):
        """이미 만들어진 스크립트를 Claude 없이 다시 실행한다 (토큰 사용 없음)."""
        run_id = str(data.get("id", ""))
        if not re.fullmatch(r"[0-9a-f]{8}", run_id) or not (GENERATED_DIR / f"test_{run_id}.py").is_file():
            return self.send_error(404, "script not found")
        if not ENV["pytest"]:
            return self.send_error(400, "pytest-playwright not installed")
        self.start_sse()
        try:
            save_meta(run_id, lastRun=self.run_pytest(run_id, f"test_{run_id}.py", bool(data.get("headed"))))
            self.sse("done", {"verified": True})
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
            "--max-turns", str(MAX_TURNS),
        ]
        if model:
            cmd += ["--model", model]
        # 무엇을 어떻게 넘기는지 그대로 화면에 보여준다 (지시문은 stdin 으로 전달)
        self.sse("harness", {"command": " ".join(shlex.quote(c) for c in cmd) + " < 지시문", "prompt": prompt})

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
        stderr_reader = threading.Thread(target=lambda: stderr_lines.extend(proc.stderr), daemon=True)
        stderr_reader.start()

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
            stderr_reader.join(timeout=5)  # 마지막 에러 메시지까지 다 읽고 보여준다
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
                "reason": msg.get("subtype"),  # success / error_max_turns / error_during_execution ...
            })

    def run_pytest(self, run_id, out_file, headed):
        """AI 의 요약을 믿지 않고, 서버가 직접 pytest 를 돌려 결과를 확인한다."""
        report = f"{run_id}.report.html"
        artifacts = f"{run_id}.artifacts"  # 실행 영상 · 실패 스크린샷 (화면에서 재생)
        shutil.rmtree(GENERATED_DIR / artifacts, ignore_errors=True)
        cmd = [PYTHON_BIN, "-m", "pytest", out_file, "-v", "--tb=short", "--color=no", "-p", "no:cacheprovider",
               "--video", "on", "--screenshot", "only-on-failure", "--output", artifacts]
        if headed:  # 시연용: 브라우저 창을 띄우고 사람이 볼 수 있는 속도로 실행
            cmd += ["--headed", "--slowmo", "700"]
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
                line = ANSI_COLOR.sub("", line.rstrip("\r\n"))
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
        result = {
            "code": proc.returncode, **counts, "ok": proc.returncode == 0 and counts["passed"] > 0,
            "report": f"/generated/{report}" if has_report else None, "at": now(),
            "videos": [f"/generated/{f.relative_to(GENERATED_DIR).as_posix()}" for f in sorted((GENERATED_DIR / artifacts).rglob("*.webm"))],
            "screenshots": [f"/generated/{f.relative_to(GENERATED_DIR).as_posix()}" for f in sorted((GENERATED_DIR / artifacts).rglob("*.png"))],
        }
        self.sse("run-done", result)
        return result


def main():
    GENERATED_DIR.mkdir(exist_ok=True)
    print(f"test-auto-generator on http://localhost:{PORT}")
    print(f"  claude: {'WSL' if USE_WSL else 'Windows'} -> {' '.join(claude_command())}")
    if not ENV["pytest"]:
        print('  (pytest-playwright 미설치: "실행 검증"은 건너뜁니다 -> pip install -r requirements.txt)')
    # Windows 에서는 SO_REUSEADDR 때문에 같은 포트에 서버가 두 개 뜰 수 있다 -> 겹치면 바로 에러가 나게 한다
    ThreadingHTTPServer.allow_reuse_address = os.name != "nt"
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        sys.exit(f"포트 {PORT} 가 이미 사용 중입니다. 이미 켜 둔 서버를 끄거나 PORT=3001 처럼 다른 포트를 쓰세요.")
    server.serve_forever()


if __name__ == "__main__":
    main()
