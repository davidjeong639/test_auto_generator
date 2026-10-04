# test_auto_generator

**"QA를 위한 테스트 자동화 기초" 강의의 다음 단계를 보여주는 실무 심화 데모**입니다.

강의에서는 F12로 단서를 찾고, `page.fill()` · `assert`를 한 줄씩 직접 쳤습니다.
현업에서는 같은 원리 위에서 역할이 이렇게 나뉩니다.

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

생성된 코드에서 강의 개념(assert, get_by_role, filter, POM 등)을 찾아 뱃지로 보여 줍니다.
화면 아래에는 **손으로 직접 / Codegen / AI 에이전트** 세 방식의 비교가 있습니다 (강의 07의 "Codegen은 초안 생성기"와 연결).

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
| `CLAUDE_BIN` | `claude` | claude 실행 파일 경로 |
| `PYTHON_BIN` | app.py를 실행한 python | pytest를 돌릴 python |
| `CLAUDE_ALLOWED_TOOLS` | `WebFetch Read Write Edit Bash` | `claude -p`에 허용할 도구 (공백 구분) |

## 주의

- `claude -p`는 사람이 승인할 수 없는 헤드리스 모드라서, 허용한 도구(`Bash` 포함)는 **자동 실행**됩니다. **로컬 데모 용도로만** 쓰고 외부에 공개하지 마세요.
- 생성된 스크립트와 리포트는 `generated/`에 저장되며 git에는 올라가지 않습니다.
- 토큰과 비용은 내 Claude Code 계정에서 나갑니다. 완료되면 소요 시간, 턴 수, 비용이 화면에 표시됩니다.
