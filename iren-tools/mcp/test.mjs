// Тест движка формул: node test.mjs
import { checkFormulas } from './assets/formula-engine.mjs';

const tests = [
  'm',
  'V',
  '^3',
  'p = F/S',
  '\\frac{a}{b}',
  '\\sum_{i=1}^{n} x_i^2',
  '\\sqrt[3]{8}',
  '\\left(\\frac{p_1}{p_2}\\right)^\\kappa',
  '\\rho = \\frac{m}{V}',
  '\\notaTcommand',       // неизвестный макрос — должен упасть
  'x \\le y',            // известный: \le
  'x ≤ y',               // юникод-символ в TeX
  '',                     // пустая формула
  'T = t + 273{,}15',
];

const t0 = Date.now();
let failed = 0;
for (const r of checkFormulas(tests)) {
  if (r.ok) {
    console.log('OK  ', JSON.stringify(r.tex), '->', r.width, 'x', r.height);
  } else {
    failed++;
    console.log('FAIL', JSON.stringify(r.tex), '->', r.reason, '|', r.error.slice(0, 70));
  }
}
console.log(`Время: ${Date.now() - t0} мс, сломано: ${failed}`);
