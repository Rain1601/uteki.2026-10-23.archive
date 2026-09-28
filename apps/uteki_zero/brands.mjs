// Website identity and local assets are independent of company names and tickers.
export function brandDomain(website) {
  if (typeof website !== 'string' || !website.trim()) throw new Error('Company website is required');
  const url = new URL(website);
  if (url.protocol !== 'https:' || url.username || url.password || url.port) throw new Error('Company website must use public HTTPS');
  if (url.pathname !== '/' || url.search || url.hash) throw new Error('Company website must be an origin');
  const domain = url.hostname.toLowerCase().replace(/^www\./, '').replace(/\.$/, '');
  if (!domain.includes('.') || /[:\[\]]/.test(domain) || /^\d[\d.]+$/.test(domain) || /\.(localhost|local|internal)$/.test(domain)) throw new Error('Public company domain required');
  return domain;
}

export function validateBrandRegistry(registry) {
  if (registry?.version !== 1 || !registry.brands || typeof registry.brands !== 'object' || Array.isArray(registry.brands)) throw new Error('Invalid brand registry');
  for (const [domain, brand] of Object.entries(registry.brands)) {
    if (brandDomain(brand.website) !== domain) throw new Error(`Brand domain mismatch: ${domain}`);
    if (!/^\.\/assets\/companies\/[a-z0-9][a-z0-9_.-]*\.(png|jpe?g|webp|ico|svg)$/i.test(brand.src)) throw new Error(`Invalid local brand asset: ${domain}`);
    if (!['reviewed-logo', 'official-site-icon'].includes(brand.kind)) throw new Error(`Unknown brand provenance: ${domain}`);
    if (brand.presentation !== undefined && !['icon', 'wordmark'].includes(brand.presentation)) throw new Error(`Unknown brand presentation: ${domain}`);
    if (!/^[a-f0-9]{64}$/.test(brand.sha256)) throw new Error(`Missing brand hash: ${domain}`);
    for (const field of ['sourcePage', 'assetUrl']) {
      const url = new URL(brand[field]);
      if (url.protocol !== 'https:' || url.username || url.password) throw new Error(`Invalid brand source: ${domain}`);
    }
  }
  return registry;
}

export function resolveBrand(company, registry) {
  try {
    const domain = brandDomain(company.website);
    const brand = registry.brands[domain];
    // A verified wide wordmark is still unsuitable for the compact company slot.
    return brand?.presentation === 'icon' ? brand : null;
  } catch { return null; }
}
