"""페이지 분석 도구 - 화면의 조작 가능한 요소와 Locator 후보를 뽑아준다. (F12 대신)

사용법:
  python inspect_page.py https://www.saucedemo.com
  python inspect_page.py https://www.saucedemo.com \
      --do "fill:[data-test='username']=standard_user" \
      --do "fill:[data-test='password']=secret_sauce" \
      --do "click:[data-test='login-button']"

--do 동작은 순서대로 실행되고, 마지막 화면의 요소 목록을 출력한다.
  fill:<셀렉터>=<값>   입력
  click:<셀렉터>       클릭
  goto:<URL>          이동
"""
import argparse
import sys

from playwright.sync_api import Error, sync_playwright

# 화면에서 보이는 요소의 단서(태그, id, data-test, role, 텍스트...)를 모은다
COLLECT_JS = r"""
() => {
  const sel = 'input, button, a, select, textarea, [role], [data-test], [data-testid], h1, h2, h3, [class*="title"], [class*="error"]';
  const seen = new Set();
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (!r.width || !r.height || style.visibility === 'hidden' || style.display === 'none') continue;
    const item = {
      tag: el.tagName.toLowerCase(),
      id: el.id || '',
      dataTest: el.getAttribute('data-test') || '',
      dataTestid: el.getAttribute('data-testid') || '',
      role: el.getAttribute('role') || '',
      type: el.getAttribute('type') || '',
      name: el.getAttribute('name') || '',
      placeholder: el.getAttribute('placeholder') || '',
      cls: (el.getAttribute('class') || '').split(/\s+/).filter(Boolean).slice(0, 2).join('.'),
      text: (el.innerText || el.value || '').trim().replace(/\s+/g, ' ').slice(0, 50),
    };
    const key = JSON.stringify(item);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
}
"""

IMPLICIT_ROLE = {"button": "button", "a": "link", "select": "combobox", "textarea": "textbox",
                 "h1": "heading", "h2": "heading", "h3": "heading"}


def best_locator(e):
    """강의 08 의 우선순위대로 가장 좋은 Locator 후보 하나를 고른다."""
    if e["dataTestid"]:
        return f'get_by_test_id("{e["dataTestid"]}")'
    if e["dataTest"]:
        return f"locator(\"[data-test='{e['dataTest']}']\")"
    role = e["role"] or IMPLICIT_ROLE.get(e["tag"])
    if e["tag"] == "input" and e["type"] in ("submit", "button"):
        role = "button"
    if role and e["text"]:
        return f'get_by_role("{role}", name="{e["text"]}")'
    if e["placeholder"]:
        return f'get_by_placeholder("{e["placeholder"]}")'
    if e["id"]:
        return f'locator("#{e["id"]}")'
    if e["text"] and e["tag"] not in ("input", "select"):
        return f'get_by_text("{e["text"]}")'
    if e["cls"]:
        return f'locator(".{e["cls"]}")'
    return f'locator("{e["tag"]}")'


def describe(e):
    parts = [e["tag"]]
    for key, label in (("type", "type"), ("id", "id"), ("placeholder", "placeholder"), ("cls", "class")):
        if e[key]:
            parts.append(f'{label}="{e[key]}"')
    if e["text"]:
        parts.append(f'text="{e["text"]}"')
    return " ".join(parts)


def run_action(page, action):
    kind, _, rest = action.partition(":")
    if kind == "fill":
        selector, _, value = rest.rpartition("=")  # 셀렉터 안에도 = 가 있으므로 마지막 = 기준
        page.locator(selector).first.fill(value, timeout=5000)
    elif kind == "click":
        page.locator(rest).first.click(timeout=5000)
    elif kind == "goto":
        page.goto(rest)
    else:
        raise ValueError(f"알 수 없는 동작: {action}")
    # SPA 는 주소가 바뀐 뒤에 화면을 다시 그리므로, 네트워크가 잠잠해지고 조금 더 기다린다
    # (분석 도구라서 괜찮다. 테스트 코드에서는 sleep 금지!)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="페이지 요소와 Locator 후보 출력")
    parser.add_argument("url")
    parser.add_argument("--do", action="append", default=[], help='예: "click:#login-button"')
    parser.add_argument("--limit", type=int, default=60, help="최대 출력 요소 수")
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(args.url)
        for action in args.do:
            try:
                run_action(page, action)
                print(f"[ok]   {action}")
            except (Error, ValueError) as e:
                print(f"[fail] {action} -> {str(e).splitlines()[0]}")

        # 같은 Locator 가 여러 번 나오면 한 줄로 묶는다 (예: 상품 카드 6개 -> filter 로 좁혀야 함)
        groups = {}
        for e in page.evaluate(COLLECT_JS):
            groups.setdefault(best_locator(e), []).append(e)

        print(f"\nURL:   {page.url}")
        print(f"TITLE: {page.title()}")
        print(f"Locator {len(groups)}종 (최대 {args.limit}개 표시) — 왼쪽: 추천 Locator, 오른쪽: 실제 HTML 단서\n")
        for locator, items in list(groups.items())[: args.limit]:
            repeat = f"  [x{len(items)} 반복 -> .filter(has_text=...) 로 좁히기]" if len(items) > 1 else ""
            print(f"  page.{locator:<55} # {describe(items[0])}{repeat}")
        browser.close()


if __name__ == "__main__":
    main()
