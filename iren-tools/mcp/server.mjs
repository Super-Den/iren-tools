#!/usr/bin/env node
// iren-mcp — MCP-сервер для работы с тестами «Айрен» (.itx).
// Инструменты: iren_test_info, iren_validate_itx, iren_pack_itx, iren_unpack_itx, iren_check_formula.
// Транспорт: stdio (JSON-RPC 2.0, newline-delimited). Зависимостей от npm нет.
// Формулы проверяются тем же рендерером (MathJax 2.7.3), что использует сама программа Айрен.

import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import { fileURLToPath } from 'node:url';
import { checkFormulas } from './assets/formula-engine.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCRIPTS = path.join(__dirname, 'scripts');
const SERVER_NAME = 'iren-mcp';
const SERVER_VERSION = '1.1.0';

process.stderr.write(`[${SERVER_NAME}] запущен\n`);

// ------------------------------------------------------------------- Python

function capture(cmd, args) {
  return new Promise((resolve) => {
    const p = spawn(cmd, args, { windowsHide: true });
    let out = '';
    p.stdout.on('data', (d) => { out += d.toString('utf8'); });
    p.stderr.on('data', (d) => { out += d.toString('utf8'); });
    p.on('error', () => resolve(''));
    p.on('close', () => resolve(out.trim()));
  });
}

let pythonPromise = null;

function detectPython() {
  if (!pythonPromise) pythonPromise = (async () => {
    for (const c of ['py', 'python']) {
      const v = await capture(c, ['--version']);
      if (/^Python 3\./.test(v)) {
        process.stderr.write(`[${SERVER_NAME}] интерпретатор: ${c} (${v})\n`);
        return c;
      }
    }
    const candidates = [];
    const local = process.env.LOCALAPPDATA;
    if (local) {
      const base = path.join(local, 'Programs', 'Python');
      try {
        for (const d of readdirSync(base)) candidates.push(path.join(base, d, 'python.exe'));
      } catch { /* нет папки */ }
    }
    try {
      for (const d of readdirSync('C:/Program Files')) {
        if (/^Python\d+/.test(d)) candidates.push(path.join('C:/Program Files', d, 'python.exe'));
      }
    } catch { /* нет папки */ }
    let best = null;
    for (const c of candidates) {
      if (!existsSync(c)) continue;
      const v = await capture(c, ['--version']);
      const m = v.match(/^Python (\d+)\.(\d+)/);
      if (m && +m[1] >= 3 && (!best || +`${m[1]}.${m[2]}` > best.v)) {
        best = { c, v: +`${m[1]}.${m[2]}` };
      }
    }
    if (!best) throw new Error('Python 3 не найден. Установите Python 3 (галочки «Add to PATH» и «py launcher») или укажите путь в PATH.');
    process.stderr.write(`[${SERVER_NAME}] интерпретатор: ${best.c}\n`);
    return best.c;
  })();
  return pythonPromise;
}

async function runPy(args) {
  const py = await detectPython();
  return new Promise((resolve, reject) => {
    const p = spawn(py, [path.join(SCRIPTS, 'iren_tools.py'), ...args], { windowsHide: true });
    let out = '';
    let err = '';
    p.stdout.on('data', (d) => { out += d.toString('utf8'); });
    p.stderr.on('data', (d) => { err += d.toString('utf8'); });
    p.on('error', reject);
    p.on('close', (code) => resolve({ code, out: out.trim(), err: err.trim() }));
  });
}

// ------------------------------------------------------------------- Инструменты

const TOOLS = [
  {
    name: 'iren_test_info',
    description: 'Сводка по тесту Айрен (.itx или папка с test.xml): дерево секций, число вопросов по типам, профили (время, перемешивание, шкала оценок), теги, число сценариев и формул, картинки (ссылки/на месте/битые). Возвращает JSON.',
    inputSchema: {
      type: 'object',
      properties: { source: { type: 'string', description: 'Путь к .itx или к папке с test.xml' } },
      required: ['source'],
    },
  },
  {
    name: 'iren_validate_itx',
    description: 'Проверка теста Айрен: XML, дубликаты тегов, lastGeneratedTag, существование картинок, select-вопросы без верного ответа, дубликаты вариантов, объявления переменных против подстановок $(var) в сценариях. Принимает .itx или папку. Возвращает список ошибок и предупреждений.',
    inputSchema: {
      type: 'object',
      properties: { source: { type: 'string', description: 'Путь к .itx или к папке с test.xml' } },
      required: ['source'],
    },
  },
  {
    name: 'iren_pack_itx',
    description: 'Собрать .itx из папки (test.xml + images/). Сначала выполняет все проверки валидатора, потом упаковывает ZIP с корректными путями (test.xml, images/...). Код результата отражает наличие ошибок.',
    inputSchema: {
      type: 'object',
      properties: {
        source: { type: 'string', description: 'Папка с test.xml и images/' },
        output: { type: 'string', description: 'Путь итогового .itx (по умолчанию: рядом с папкой, имя папки + .itx)' },
      },
      required: ['source'],
    },
  },
  {
    name: 'iren_unpack_itx',
    description: 'Распаковать .itx в папку (для правки test.xml и картинок).',
    inputSchema: {
      type: 'object',
      properties: {
        source: { type: 'string', description: 'Путь к .itx' },
        dest: { type: 'string', description: 'Папка назначения (по умолчанию: рядом с архивом, по имени файла)' },
      },
      required: ['source'],
    },
  },
  {
    name: 'iren_check_formula',
    description: 'Проверить TeX-формулы через тот же движок, что использует Айрен (MathJax 2.7.3 + AMSmath/AMSsymbols). Для каждой формулы сообщает: ok (отрисуется), размеры или причину отказа (неизвестный символ/макрос, ошибка разметки). Использовать ДО сдачи теста для каждой <formula source="..."/>.',
    inputSchema: {
      type: 'object',
      properties: {
        formulas: {
          type: 'array',
          items: { type: 'string' },
          description: 'TeX-разметка формул без $-разделителей, как в <formula source="..."/>',
        },
      },
      required: ['formulas'],
    },
  },
];

async function callTool(name, args) {
  switch (name) {
    case 'iren_test_info': {
      const { code, out } = await runPy(['info', '--source', args.source]);
      return text(out, code !== 0);
    }
    case 'iren_validate_itx': {
      const isItx = /\.itx$/i.test(args.source);
      if (!isItx) {
        const { code, out } = await runPy(['build', '--source', args.source, '--no-pack']);
        return text(out, code !== 0);
      }
      const tmpRoot = mkdtempSync(path.join(tmpdir(), 'iren-mcp-'));
      const dest = path.join(tmpRoot, 'test');
      try {
        const up = await runPy(['unpack', '--source', args.source, '--dest', dest]);
        if (up.code !== 0) return text(up.out, true);
        const { code, out } = await runPy(['build', '--source', dest, '--no-pack']);
        return text(out, code !== 0);
      } finally {
        rmSync(tmpRoot, { recursive: true, force: true });
      }
    }
    case 'iren_pack_itx': {
      const argsPy = ['build', '--source', args.source];
      if (args.output) argsPy.push('--output', args.output);
      const { code, out } = await runPy(argsPy);
      return text(out, code !== 0);
    }
    case 'iren_unpack_itx': {
      const argsPy = ['unpack', '--source', args.source];
      if (args.dest) argsPy.push('--dest', args.dest);
      const { code, out } = await runPy(argsPy);
      return text(out, code !== 0);
    }
    case 'iren_check_formula': {
      const list = Array.isArray(args.formulas) ? args.formulas : [args.formulas];
      if (!list.length || list.length > 100) {
        return text('Ошибка: передайте массив formulas от 1 до 100 строк.', true);
      }
      const results = checkFormulas(list);
      const bad = results.filter((r) => !r.ok).length;
      const summary = `Формул: ${results.length}, отрисуется: ${results.length - bad}, сломано: ${bad}`;
      return text(JSON.stringify({ summary, results }, null, 2), false);
    }
    default:
      throw new Error(`Неизвестный инструмент: ${name}`);
  }
}

function text(t, isError = false) {
  return { content: [{ type: 'text', text: t }], ...(isError ? { isError: true } : {}) };
}

// --------------------------------------------------------------- Протокол MCP

async function handle(msg) {
  const { id, method, params } = msg;
  if (typeof method !== 'string') return;
  if (method.startsWith('notifications/')) return; // на уведомления не отвечаем

  let result;
  let error = null;
  try {
    switch (method) {
      case 'initialize':
        result = {
          protocolVersion: (params && params.protocolVersion) || '2024-11-05',
          capabilities: { tools: { listChanged: false } },
          serverInfo: { name: SERVER_NAME, version: SERVER_VERSION },
        };
        break;
      case 'ping':
        result = {};
        break;
      case 'tools/list':
        result = { tools: TOOLS };
        break;
      case 'tools/call': {
        const tool = params && params.toolName !== undefined ? params.toolName : params.name;
        result = await callTool(tool, (params && params.arguments) || {});
        break;
      }
      default:
        error = { code: -32601, message: `Метод не найден: ${method}` };
    }
  } catch (e) {
    error = { code: -32603, message: String((e && e.message) || e) };
  }
  if (id === undefined) return;
  const response = error ? { jsonrpc: '2.0', id, error } : { jsonrpc: '2.0', id, result };
  process.stdout.write(JSON.stringify(response) + '\n');
}

const rl = readline.createInterface({ input: process.stdin, terminal: false });
let inFlight = 0;
let stdinClosed = false;
const maybeExit = () => { if (stdinClosed && inFlight === 0) process.exit(0); };
rl.on('line', (line) => {
  const s = line.trim();
  if (!s) return;
  let msg;
  try { msg = JSON.parse(s); } catch { return; }
  inFlight++;
  handle(msg)
    .catch((e) => process.stderr.write(`[${SERVER_NAME}] ${e}\n`))
    .finally(() => { inFlight--; maybeExit(); });
});
rl.on('close', () => { stdinClosed = true; maybeExit(); });
