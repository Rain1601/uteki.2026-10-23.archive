import test from 'node:test';
import assert from 'node:assert/strict';
import { brandDomain, validateBrandRegistry, resolveBrand } from './brands.mjs';

const entry = domain => ({
  website: `https://${domain}/`, src: './assets/companies/synthetic.png',
  sourcePage: `https://${domain}/about`, assetUrl: `https://cdn.${domain}/logo.png`,
  kind: 'official-site-icon', presentation: 'icon', sha256: 'a'.repeat(64),
});
const registry = () => ({ version: 1, brands: { 'cedar.example': entry('cedar.example'), 'birch.example': entry('birch.example') } });

test('same-named companies resolve by explicit website, not name or ticker', () => {
  const brands = registry();
  assert.equal(resolveBrand({ name: 'Shared', ticker: 'SAME', website: 'https://cedar.example' }, brands), brands.brands['cedar.example']);
  assert.equal(resolveBrand({ name: 'Shared', ticker: 'SAME', website: 'https://birch.example' }, brands), brands.brands['birch.example']);
});
test('www, case and trailing dot normalize to one domain', () => {
  assert.equal(brandDomain('https://WWW.CEDAR.EXAMPLE.'), 'cedar.example');
});
test('unknown and missing websites never borrow another company logo', () => {
  for (const website of [undefined, '', 'https://other.example', 'https://division.cedar.example']) assert.equal(resolveBrand({ website }, registry()), null);
});
test('invalid public website inputs fail validation', () => {
  for (const website of ['', 'cedar.example', 'http://cedar.example', 'https://user:pass@cedar.example', 'https://localhost', 'https://127.0.0.1', 'https://[::1]', 'https://cedar.example:8080', 'https://cedar.example/investor', 'https://cedar.example/?company=other']) assert.throws(() => brandDomain(website));
});
test('provenance domain mismatch is rejected', () => {
  const brands = registry(); brands.brands['cedar.example'].website = 'https://birch.example';
  assert.throws(() => validateBrandRegistry(brands), /mismatch/);
});
test('remote or escaping asset paths cannot enter the renderer', () => {
  for (const src of ['https://cdn.example/logo.png', './assets/companies/../../other.png', 'javascript:alert(1)']) {
    const brands = registry(); brands.brands['cedar.example'].src = src;
    assert.throws(() => validateBrandRegistry(brands), /local brand asset/);
  }
});
test('reviewed logos and discovered icons keep distinct provenance', () => {
  const brands = registry(); brands.brands['birch.example'].kind = 'reviewed-logo';
  assert.equal(validateBrandRegistry(brands), brands);
  brands.brands['birch.example'].kind = 'guessed';
  assert.throws(() => validateBrandRegistry(brands), /provenance/);
});

test('wordmarks and unclassified legacy assets never enter icon slots', () => {
  const brands = registry();
  const company = { website: 'https://cedar.example' };
  brands.brands['cedar.example'].presentation = 'wordmark';
  assert.equal(resolveBrand(company, brands), null);
  delete brands.brands['cedar.example'].presentation;
  assert.equal(resolveBrand(company, brands), null);
  brands.brands['cedar.example'].presentation = 'icon';
  assert.equal(resolveBrand(company, brands), brands.brands['cedar.example']);
});
