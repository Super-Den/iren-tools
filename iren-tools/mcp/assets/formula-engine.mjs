// formula-engine.mjs — проверка TeX-формул движком Айрен (MathJax 2.7.3, SVG).
// Использует штатный headless-рендерер Айрен (formulaRenderer.js) поверх jsdom:
// в браузере он получает полноценный document.implementation.createHTMLDocument,
// jsdom даёт ровно такую же среду, поэтому поведение совпадает с программой.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let renderFn = null;

function init() {
  if (renderFn) return renderFn;
  const src = readFileSync(path.join(__dirname, 'formulaRenderer.js'), 'utf8');
  const dom = new JSDOM('<!DOCTYPE html><html><head></head><body></body></html>');
  globalThis.window = {};
  globalThis.document = dom.window.document;
  (0, eval)(src); // задаёт globalThis.window.irenRenderFormula = render(tex)
  const fn = globalThis.window.irenRenderFormula;
  if (typeof fn !== 'function') throw new Error('Рендерер не инициализировался: window.irenRenderFormula не функция');
  renderFn = fn;
  return renderFn;
}

export function checkOneFormula(tex) {
  try {
    const render = init();
    const result = render(String(tex));
    const svg = Array.isArray(result) ? result[0] : null;
    const style = (Array.isArray(result) ? result[1] : null) || {};
    // MathJax не кидает исключение на неизвестные макросы — рисует красный бокс
    // с текстом ошибки внутри SVG. Ищем маркеры ошибок в разметке.
    const markup = svg && svg.outerHTML ? svg.outerHTML : '';
    const errMatch = markup.match(/(Undefined control sequence[^<]*|Math Processing Error[^<]*|Unknown [^<]*|Missing [^<]*|Extra [^<]*|Misplaced [^<]*)/);
    if (errMatch) {
      return { tex: String(tex), ok: false, error: errMatch[1].trim(), reason: 'Ошибка TeX (Айрен отрисует красный бокс с ошибкой)' };
    }
    return {
      tex: String(tex),
      ok: true,
      width: style.width || (svg && svg.getAttribute && svg.getAttribute('width')) || null,
      height: style.height || (svg && svg.getAttribute && svg.getAttribute('height')) || null,
    };
  } catch (e) {
    const msg = String((e && e.message) || e);
    let reason = 'Ошибка рендеринга';
    if (/Unknown character/i.test(msg)) reason = 'Неизвестный символ или макрос (не поддерживается набором Айрен)';
    else if (/rendering failed/i.test(msg)) reason = 'Формула не отрисовалась (ошибка разметки TeX)';
    else if (/did not complete/i.test(msg)) reason = 'Движок не завершил обработку';
    return { tex: String(tex), ok: false, error: msg, reason };
  }
}

export function checkFormulas(list) {
  return list.map(checkOneFormula);
}
