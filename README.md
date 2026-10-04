# test_auto_generator

UI 자동화 스크립트를 **Claude Code가 알아서 만들어 주는** 데모 사이트입니다.

자동화 테스트 연습에는 보통 [saucedemo](https://www.saucedemo.com) 같은 사이트를 씁니다. 이 프로젝트는 거기에 한 단계를 더합니다. 사람이 짧은 **테스트 케이스**만 적으면, Claude가 대상 사이트를 직접 확인하고 **실행 가능한 자동화 스크립트**를 작성합니다.

## 동작 방식

```
[브라우저 UI] --테스트 케이스--> [Node 서버] --spawn--> claude -p (headless)
      ^                                                    |
      |<------ SSE로 진행 상황/최종 스크립트 스트리밍 --------+
```

1. UI에서 대상 URL과 테스트 케이스(샘플 4개 제공: 로그인, 잠긴 계정, 장바구니, 주문)를 입력합니다.
2. 서버가 `claude -p "<프롬프트>" --output-format stream-json`을 실행합니다.
3. Claude가 사이트를 확인해 실제 셀렉터를 파악하고, `generated/` 아래에 스크립트 파일을 씁니다.
4. 진행 로그(도구 호출 등)와 완성된 스크립트가 화면에 실시간으로 표시됩니다.

**내 환경 그대로 사용합니다.** 서버는 별도 API 키를 쓰지 않고, 이 머신에 설치·로그인된 `claude` CLI를 호출합니다. 그래서 내 Claude Code 설정(모델, 권한, CLAUDE.md, MCP 서버, 스킬 등)이 그대로 적용됩니다.

## 실행

요구사항: Node 18+, 로그인된 [Claude Code](https://claude.com/claude-code) CLI. (의존성 없음, `npm install` 불필요)

```bash
npm start
# http://localhost:3000
```

생성된 Playwright 스크립트를 돌리려면 별도로 설치하세요.

```bash
npm i -D @playwright/test && npx playwright install chromium
npx playwright test generated/<파일명>.test.js
```

## 설정 (환경 변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PORT` | `3000` | 서버 포트 |
| `CLAUDE_BIN` | `claude` | claude 실행 파일 경로 |
| `CLAUDE_ALLOWED_TOOLS` | `WebFetch Read Write Bash` | `claude -p`에 허용할 도구 (공백 구분) |

## 주의

- `claude -p`는 사람이 승인할 수 없는 헤드리스 모드라 `--allowedTools`로 허용한 도구는 **자동 실행**됩니다. 기본값에 `Bash`가 포함되어 있으니 **로컬 데모 용도로만** 쓰고, 외부에 공개하지 마세요.
- 생성 결과는 `generated/`에 저장되며 git에는 올라가지 않습니다.
- 토큰/비용은 내 Claude Code 계정에서 소모됩니다. 완료 시 UI에 소요 시간과 비용이 표시됩니다.
