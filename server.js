// Zero-dependency demo server.
// POST /api/generate  -> spawns `claude -p` in headless mode and streams progress as SSE.
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawn } = require('child_process');

const PORT = process.env.PORT || 3000;
const CLAUDE_BIN = process.env.CLAUDE_BIN || 'claude';
const ALLOWED_TOOLS = process.env.CLAUDE_ALLOWED_TOOLS || 'WebFetch Read Write Bash';
const GENERATED_DIR = path.join(__dirname, 'generated');
const PUBLIC_DIR = path.join(__dirname, 'public');

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css' };

function buildPrompt({ url, testCase, framework, outFile }) {
  return [
    `You are a UI test automation engineer. Write an automated test script for the test case below.`,
    ``,
    `Target site: ${url}`,
    `Framework: ${framework}`,
    ``,
    `Test case:`,
    testCase,
    ``,
    `Rules:`,
    `1. Actually inspect the target site first (fetch the page, or drive it with a headless browser if available) so selectors come from the real DOM, not guesses. Prefer data-test / id / role selectors.`,
    `2. Write exactly one script file to ./${outFile} (relative to the current directory). Do not create other files.`,
    `3. The script must include assertions for every expected result in the test case.`,
    `4. Finish with a 3-5 line summary: which selectors you used and any assumptions you made.`,
  ].join('\n');
}

function sse(res, event, data) {
  res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

// Turn one stream-json line from claude into a UI-friendly event.
function forward(res, msg) {
  if (msg.type === 'assistant') {
    for (const block of msg.message?.content || []) {
      if (block.type === 'text' && block.text.trim()) sse(res, 'text', { text: block.text });
      if (block.type === 'tool_use') {
        const input = block.input || {};
        const hint = input.url || input.file_path || input.command || '';
        sse(res, 'tool', { name: block.name, hint: String(hint).slice(0, 200) });
      }
    }
  } else if (msg.type === 'result') {
    sse(res, 'result', { ok: !msg.is_error, cost: msg.total_cost_usd, ms: msg.duration_ms });
  }
}

function handleGenerate(req, res) {
  let body = '';
  req.on('data', (c) => { body += c; if (body.length > 1e5) req.destroy(); });
  req.on('end', () => {
    let input;
    try { input = JSON.parse(body); } catch { res.writeHead(400).end('bad json'); return; }

    const url = String(input.url || '').trim();
    const testCase = String(input.testCase || '').trim();
    const framework = input.framework === 'playwright-python' ? 'Playwright (Python, pytest)' : 'Playwright (JavaScript, @playwright/test)';
    const ext = input.framework === 'playwright-python' ? 'py' : 'js';
    if (!/^https?:\/\//.test(url) || !testCase) { res.writeHead(400).end('url and testCase required'); return; }

    const outFile = `${crypto.randomBytes(4).toString('hex')}.test.${ext}`;
    const args = [
      '-p', buildPrompt({ url, testCase, framework, outFile }),
      '--output-format', 'stream-json', '--verbose',
      '--permission-mode', 'acceptEdits',
      '--allowedTools', ...ALLOWED_TOOLS.split(/\s+/),
    ];
    if (input.model) args.push('--model', String(input.model));

    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
    // Runs with the user's own environment and Claude Code settings (cwd = generated/).
    const child = spawn(CLAUDE_BIN, args, { cwd: GENERATED_DIR, stdio: ['ignore', 'pipe', 'pipe'] });

    let buf = '';
    child.stdout.on('data', (chunk) => {
      buf += chunk;
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (!line) continue;
        try { forward(res, JSON.parse(line)); } catch { /* ignore non-JSON noise */ }
      }
    });
    child.stderr.on('data', (c) => sse(res, 'stderr', { text: String(c) }));
    child.on('error', (e) => { sse(res, 'fatal', { error: `cannot start "${CLAUDE_BIN}": ${e.message}` }); res.end(); });
    child.on('close', (code) => {
      const file = path.join(GENERATED_DIR, outFile);
      const script = fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : null;
      sse(res, 'done', { code, file: script ? `generated/${outFile}` : null, script });
      res.end();
    });
    res.on('close', () => child.kill());
  });
}

http.createServer((req, res) => {
  if (req.method === 'POST' && req.url === '/api/generate') return handleGenerate(req, res);
  const rel = req.url === '/' ? 'index.html' : decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '');
  const file = path.join(PUBLIC_DIR, rel);
  if (!file.startsWith(PUBLIC_DIR) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404).end('not found');
    return;
  }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
}).listen(PORT, () => console.log(`test-auto-generator on http://localhost:${PORT}`));
