"""Small synthetic source with independently stated expected behaviors."""
from uteki.data_platform.contracts.common import digest
from uteki.data_platform.contracts.content import InputManifest,PresentResource,MissingResource

MAIN_URL='https://example.com/report/index.html'
IMAGE_URL='https://example.com/report/chart.png'


def source(extra=''):
    return ('''<!doctype html><html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
 xmlns:iso4217="http://www.xbrl.org/2003/iso4217" xmlns:ex="https://example.com/taxonomy"
 xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"
 xmlns:ixtold="http://www.xbrl.org/inlineXBRL/transformation/2015-02-26"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><head><title>Synthetic annual report</title></head><body>
<ix:header><ix:resources>
<xbrli:context id="current"><xbrli:entity><xbrli:identifier scheme="urn:entity">synthetic-entity</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2023-07-02</xbrli:startDate><xbrli:endDate>2024-06-29</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="previous"><xbrli:entity><xbrli:identifier scheme="urn:entity">synthetic-entity</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2022-07-03</xbrli:startDate><xbrli:endDate>2023-07-01</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="segment"><xbrli:entity><xbrli:identifier scheme="urn:entity">synthetic-entity</xbrli:identifier><xbrli:segment><xbrldi:explicitMember dimension="ex:RegionAxis">ex:North</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>2024-06-29</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:unit id="eur"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
<xbrli:unit id="perShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>
</ix:resources></ix:header>
<nav>Navigation must not be body text.</nav>
<h1>Annual results</h1><p>Exact <em>source</em> paragraph.<br>Second line.</p>
<p>Amounts in EUR thousands; fiscal years end in June.</p>
<table id="results"><caption>Annual comparison</caption>
<tr><th id="metric" rowspan="2">Metric</th><th id="years" colspan="2">Years</th></tr>
<tr><th id="year-now">2024</th><th id="year-before">2023</th></tr>
<tr><th id="cash">Cash movement</th><td headers="cash year-now"><ix:nonFraction id="r1" name="ex:Cash" contextRef="current" unitRef="eur" scale="3" sign="-" decimals="-3" format="ixt:num-dot-decimal">12.5</ix:nonFraction><a href="#footnote">*</a></td><td headers="cash year-before"><ix:nonFraction id="r2" name="ex:Cash" contextRef="previous" unitRef="eur" scale="3" format="ixt:num-dot-decimal">10</ix:nonFraction></td></tr>
</table><p id="footnote">* Payments are cash outflows; periods are not calendar years.</p>
<p>Repeated fact: <ix:nonFraction id="r3" name="ex:Cash" contextRef="current" unitRef="eur" scale="3" sign="-">12.5</ix:nonFraction>.</p>
<p>Per share: <ix:nonFraction id="r4" name="ex:PerShare" contextRef="segment" unitRef="perShare">1.25</ix:nonFraction>.</p>
<p>Absent: <ix:nonFraction id="r5" name="ex:Absent" contextRef="current" unitRef="eur" xsi:nil="true"></ix:nonFraction>.</p>
<p>Zero: <ix:nonFraction id="r6" name="ex:Zero" contextRef="current" unitRef="eur" format="ixt:fixed-zero">—</ix:nonFraction>.</p>
<p>Unsupported: <ix:nonFraction id="r7" name="ex:Words" contextRef="current" unitRef="eur" format="ixt:numwordsen">seven</ix:nonFraction>.</p>
<div aria-hidden="true">Aria secret.</div><div style="visibility:hidden">Style secret.</div><div hidden>Hidden secret.</div>
<script>Script secret.</script><noscript>Noscript secret.</noscript>
<img src="chart.png" alt="Synthetic chart">
'''+extra+'''</body></html>''').encode()


def inputs(store,raw,*,figure=b'synthetic image',missing=False):
    resource=MissingResource(status='missing',resource_key='figure',source_url=IMAGE_URL,reason='not_obtained') if missing else PresentResource(status='present',resource_key='figure',source_url=IMAGE_URL,object_ref=store.put_object(figure))
    return InputManifest(schema_version='uteki-input-manifest-v1',main=store.put_object(raw),main_source_url=MAIN_URL,resources=(resource,))
