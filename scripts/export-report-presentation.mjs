#!/usr/bin/env node
// Explicit, read-only bridge used by the static report PDF builder.
import { buildReportPresentation } from '../docs/design/company-workspace-swiss-c/report-presentation.mjs';
const names = new Map([['--company','companyId'],['--manager','managerId'],['--report','reportId'],['--version','version'],['--language','language']]);
const scope = {}, args = process.argv.slice(2);
try {
  for (let i = 0; i < args.length; i += 2) {
    const key = names.get(args[i]);
    if (!key || !args[i + 1] || args[i + 1].startsWith('--') || Object.hasOwn(scope,key)) throw new Error('Expected each explicit scope option exactly once');
    scope[key] = args[i + 1];
  }
  process.stdout.write(JSON.stringify(buildReportPresentation(scope)));
} catch (error) {
  process.stderr.write(`${error.message}\n`); process.exitCode = 2;
}
