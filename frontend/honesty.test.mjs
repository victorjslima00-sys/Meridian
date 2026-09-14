import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {formatCurrency, isValidNumber} from './src/utils/formatters.js';
const source = file => readFileSync(new URL(`./src/${file}`, import.meta.url),'utf8');
test('missing capital stays unavailable and genuine zero remains zero', () => {
  const expression = source('App.jsx').match(/const patTotal = (.*);/)[1];
  const read = new Function('cap','connected', `return ${expression}`);
  assert.equal(formatCurrency(read({patrimonio_total:null},true)), 'Indisponível');
  assert.notEqual(formatCurrency(read({patrimonio_total:0},true)), 'Indisponível');
});
test('unknown provenance status cannot pass verification just by hash', () => {
  const expression = source('components/ProvenanceTooltip.jsx').match(/const isUnverified = (.*);/)[1];
  const read = new Function('provenance','is64Hex', `return ${expression}`);
  for (const status of [undefined,'database_records_not_independently_verified','unavailable','rejected']) {
    assert.equal(read({verification_status:status},true),true);
  }
  assert.equal(read({verification_status:'verified'},true),false);
});
test('capital actions receive actual connection state', () => {
  assert.match(source('App.jsx'), /<CapitalVault\s[^>]*connected=\{connected\}/);
});
test('null position pnl cannot be classified as a gain', () => {
  const expression = source('PositionNarrative.jsx').match(/const isGain = (.*);/)[1];
  const read = new Function('pos','isValidNumber', `return ${expression}`);
  assert.notEqual(read({pnl_pct:null},isValidNumber),true);
});
test('malformed numeric hash cannot crash provenance rendering', () => {
  const expression = source('components/ProvenanceTooltip.jsx').match(/const truncatedHash = ([\s\S]*?);/)[1];
  const read = new Function('hash','is64Hex', `return ${expression}`);
  assert.doesNotThrow(() => read(123, false));
  assert.equal(read(null, false), null);
});
test('missing source is unavailable, never fabricated local origin', () => {
  const expression = source('components/ProvenanceTooltip.jsx').match(/\{(provenance\.source_ref[^}]+)\}/)[1];
  const read = new Function('provenance', `return ${expression}`);
  assert.equal(read({}), 'Origem indisponível');
  assert.equal(read({source_ref:'reports/source.json'}), 'reports/source.json');
});
test('fail closed banner is bound to connection and api error state', () => {
  assert.match(source('App.jsx'), /<FailClosedBanner\s[^>]*connected=\{connected\}[^>]*apiError=\{apiError\}/);
});
test('capital vault blocks actions and displays unavailable on disconnect or unverified status', () => {
  const expression = source('components/CapitalVault.jsx').match(/const isUnavailable = (.*);/)[1];
  const read = new Function('connected','capital', `return ${expression}`);
  assert.equal(read(false, {verification_status:'verified'}), true);
  assert.equal(read(true, {verification_status:'unavailable'}), true);
  assert.equal(read(true, {verification_status:'verified'}), false);
});
