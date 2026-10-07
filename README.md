# test_auto_generator

**"QA를 위한 테스트 자동화 기초" 강의 첫머리에 보여주는 데모**입니다.

"오늘 배울 것이 현업에서는 이렇게까지 쓰인다"를 먼저 보여줘서 흥미를 끈 다음, 기초(HTML·Locator·pytest)로 들어갑니다.
강의를 마치면 이 화면 속 코드를 직접 읽고, 맞는지 판단할 수 있게 되는 것이 목표입니다.

현업에서는 역할이 이렇게 나뉩니다.

- **사람(QA):** "무엇을 검증할지"를 테스트 케이스로 설계하고, 결과를 리뷰합니다
- **AI(Claude Code):** 사이트를 분석해 스크립트를 쓰고, 직접 실행해서 깨지면 스스로 고칩니다

## 파이프라인과 강의 연결

| 단계 | 누가 | 하는 일 | 강의 |
|---|---|---|---|
| 1. 테스트 케이스 작성 | 👤 사람 | 단계와 기대 결과 정의 | 06 · assert |
| 2. 사이트 분석 | 🤖 AI | 실제 DOM 확인 (F12 대신) | 02 · HTML & DOM |
| 3. 스크립트 작성 | 🤖 AI | test-id > role > text > CSS > XPath 순으로 Locator 선택, 기대 결과마다 `expect` | 08 · Locator |
| 4. 실행 · 자가 수정 | 🤖 AI + pytest | 돌려보고 실패하면 수정 후 재실행 (최대 3회) | 06 · pytest |
| 5. 결과 리뷰 | 👤 사람 | 서버가 **직접** 돌린 PASS/FAIL과 HTML 리포트 확인 | 09 · 실무 |

생성된 코드에서 강의 개념(assert, get_by_role, filter, POM 등)을 찾아 "오늘 이 섹션에서 배웁니다" 뱃지로 보여 줍니다.
화면 아래에는 **손으로 직접 / Codegen / AI 에이전트** 세 방식의 비교가 있습니다 (강의 07의 "Codegen은 초안 생성기"와 연결).

## 시연 방법 (강의 오프닝)

1. `.venv\Scripts\python app.py --wsl`을 실행한 뒤 http://localhost:3000 을 엽니다 (WSL에서 로그인한 경우. Windows의 claude에 로그인했다면 `--wsl` 없이)
2. **예시 테스트 케이스** 카드 중 하나를 클릭합니다. 처음에는 `TC-01 로그인 성공`, 그다음 `TC-05 장바구니 담기`를 추천합니다
3. **모델**을 고릅니다 (빠른 시연은 Sonnet 또는 Haiku). **브라우저 띄워서 실행**은 기본으로 켜져 있습니다
4. **자동화 스크립트 만들기**를 누르면 AI 로그 → 스크립트 → 실제 브라우저 실행 → PASS 순서로 보여집니다

예시 케이스는 [test_cases.json](test_cases.json)에서 추가·수정합니다. 저장하고 새로고침하면 바로 반영됩니다.
모델 목록은 [app.py](app.py)의 `MODELS`에서 바꿉니다.

## 하네스 (Claude에게 무엇을 어떻게 넘기나)

`claude -p`에 넘기는 지시문과 도구는 모두 [harness/](harness/) 폴더에 있고, QA가 직접 읽고 고칠 수 있습니다.
생성할 때 ② 로그에서 **실제로 보낸 지시문 전문과 실행 명령**을 펼쳐볼 수 있습니다.

| 파일 | 역할 |
|---|---|
| [system_prompt.md](harness/system_prompt.md) | 역할, 작업 순서, Locator 우선순위, 검증 규칙, 금지사항, 자가 수정 규칙, 보고 형식 |
| [task.md](harness/task.md) | 이번 작업: 사이트, 결과 파일, 옵션(POM/실행), 테스트 케이스, 사전 분석 결과 |
| [inspect_page.py](harness/inspect_page.py) | 페이지 분석 도구 (F12 대신). 조작 가능한 요소와 추천 Locator를 출력하고, 반복 요소에는 "filter로 좁히기"를 표시 |

생성 한 번의 흐름은 이렇습니다.

1. **사전 분석:** 서버가 `inspect_page.py`로 첫 화면을 분석해 지시문에 넣습니다
2. **지시문 전달:** `system_prompt.md` + `task.md`를 채워 stdin으로 `claude -p`에 넘깁니다 (`--max-turns 40`)
3. **추가 분석 · 작성 · 실행:** Claude가 로그인 이후 화면 등을 분석 도구로 보고, 스크립트를 쓰고, 직접 실행해 고칩니다
4. **하네스 점검:** 서버가 결과를 정적 검사합니다 (문법, test_ 함수, 검증 개수, sleep · XPath · nth 사용 여부)
5. **독립 실행:** 서버가 pytest로 직접 돌려 PASS/FAIL과 HTML 리포트를 만듭니다

분석 도구는 혼자서도 쓸 수 있습니다.

```bash
python harness/inspect_page.py https://www.saucedemo.com --do "fill:#user-name=standard_user" --do "fill:#password=secret_sauce" --do "click:#login-button"
```

## 만든 스크립트 다시 보기 · 다시 실행

- 케이스 카드에 `📄 스크립트 2개 · PASS`처럼 상태가 표시됩니다. 카드를 누르면 ③에 그 케이스의 최신 스크립트가 열리고, 여러 번 만들었다면 버전을 고를 수 있습니다
- **▶ 실행**은 저장된 스크립트를 Claude 없이 다시 돌립니다 (토큰 사용 없음). "브라우저 띄워서 실행"을 켜면 시연용으로 천천히 보여줍니다
- 기록은 `generated/test_xxxx.json`에 남습니다 (케이스, 모델, 점검 결과, 마지막 실행 결과)
- 서버 실행은 매번 **영상**을 녹화하고, 실패하면 **그 순간의 스크린샷**도 남겨 ④에서 바로 보여줍니다 (현업의 "실패 증거 남기기"). "브라우저 띄워서 실행"은 기본으로 켜져 있습니다

## 동작 방식

```
[브라우저 UI] --테스트 케이스--> [app.py] --실행--> claude -p (헤드리스)
      ^                              |                    └─ generated/test_xxxx.py 작성
      |                              └--실행--> python -m pytest  (서버의 독립 검증)
      +-------- SSE로 진행 상황 / 스크립트 / pytest 결과를 실시간 전송 --------+
```

**내 환경 그대로 사용합니다.** API 키 없이, 이 PC에 설치·로그인된 `claude` CLI를 호출합니다.
그래서 내 Claude Code 설정(모델, 권한, CLAUDE.md, MCP 서버 등)이 그대로 적용됩니다.
Playwright MCP를 연결해 두면 Claude가 실제 브라우저로 사이트를 살펴봅니다.

## 실행

요구사항: Python 3.9+, 로그인된 [Claude Code](https://claude.com/claude-code) CLI

```bash
python app.py
```

브라우저에서 http://localhost:3000 을 엽니다. 서버 자체는 표준 라이브러리만 써서 설치할 것이 없습니다.

**WSL(리눅스)에서 Claude Code에 로그인해 쓰는 경우**에는 `--wsl`을 붙입니다. Windows와 WSL의 `claude`는 로그인이 따로라서, 붙이지 않으면 "Not logged in"이 뜹니다.

```bash
python app.py --wsl
```

이 모드에서는 WSL의 `claude`가 스크립트를 쓰고, 테스트는 Windows 쪽 같은 python(venv)으로 돌려서 서버 검증과 결과가 일치합니다.

④ "서버 실행 결과"(pytest로 직접 검증)까지 보려면 다음을 설치합니다.

```bash
pip install -r requirements.txt
```

```bash
playwright install chromium
```

생성된 테스트를 따로 돌릴 수도 있습니다.

```bash
python -m pytest generated/test_xxxx.py -v --headed
```

## 설정 (환경 변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PORT` | `3000` | 서버 포트 |
| `HOST` | `127.0.0.1` | 접속 허용 주소. 기본은 내 PC만. `0.0.0.0`으로 열면 같은 네트워크의 누구나 내 PC에서 명령을 실행시킬 수 있으니 주의 |
| `CLAUDE_BIN` | `claude` | claude 실행 파일 경로 |
| `CLAUDE_WSL` | (없음) | `1`이면 `--wsl`과 같음 |
| `CLAUDE_MAX_TURNS` | `40` | 생성 한 번에 Claude가 쓸 수 있는 최대 턴 |
| `PYTHON_BIN` | app.py를 실행한 python | pytest를 돌릴 python |
| `CLAUDE_ALLOWED_TOOLS` | `WebFetch Read Write Edit Bash` | `claude -p`에 허용할 도구 (공백 구분) |

## 주의

- `claude -p`는 사람이 승인할 수 없는 헤드리스 모드라서, 허용한 도구(`Bash` 포함)는 **자동 실행**됩니다. **로컬 데모 용도로만** 쓰고 외부에 공개하지 마세요.
- 생성된 스크립트와 리포트는 `generated/`에 저장되며 git에는 올라가지 않습니다.
- 내 Claude Code 계정의 사용량을 씁니다. 화면의 "API 환산 $" 금액은 API 단가로 계산한 참고값이며, 구독(Pro/Max) 로그인이면 따로 청구되지 않고 구독 사용량에서 차감됩니다.
