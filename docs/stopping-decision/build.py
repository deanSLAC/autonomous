import os, re

HERE = os.path.dirname(os.path.abspath(__file__))
FIGS = os.path.join(HERE, 'figs')
OUT = os.path.join(HERE, '..', 'stopping-decision.html')

CSS = """
  /* System fonts only. No external requests of any kind. */
  :root {
    --ink:   #16181c;
    --body:  #2b2e34;
    --mute:  #676a71;
    --rule:  #d9d6cf;
    --hair:  #ebe8e1;
    --page:  #fbfaf7;
    --panel: #ffffff;
    --accent:#8c1515;
    --blue:  #2a78d6;
    --code:  #f2f0ea;
    --fig-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                "Helvetica Neue", Arial, sans-serif;
    --serif: Charter, "Bitstream Charter", "Iowan Old Style", Georgia,
             "Times New Roman", serif;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    background: var(--page);
    color: var(--body);
    font-family: var(--serif);
    font-size: 17.5px;
    line-height: 1.62;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
    font-variant-numeric: lining-nums;
  }
  .wrap { max-width: 780px; margin: 0 auto; padding: 60px 26px 100px; }

  h1 { font-size: 33px; line-height: 1.18; color: var(--ink);
       margin: 0 0 10px; font-weight: 600; letter-spacing: -0.012em; }
  .sub { color: var(--mute); font-size: 18px; margin: 0 0 34px;
         line-height: 1.45; }
  .sub em { font-style: italic; }
  p.lede { font-size: 18.5px; }

  h2 { font-size: 21px; color: var(--ink); font-weight: 600;
       margin: 54px 0 2px; padding-top: 20px;
       border-top: 1px solid var(--rule); letter-spacing: -0.004em; }
  h2 .n { color: var(--accent); font-feature-settings: "tnum";
          font-variant-numeric: tabular-nums; margin-right: 12px;
          font-weight: 600; }
  h3 { font-size: 17.5px; color: var(--ink); font-weight: 600;
       margin: 30px 0 2px; }
  p { margin: 13px 0; }
  strong { color: var(--ink); font-weight: 600; }
  em.term { font-style: normal; font-weight: 600; color: var(--ink); }
  a { color: var(--accent); text-decoration: none;
      border-bottom: 1px solid rgba(140,21,21,0.3); }
  sup a { border: 0; padding: 0 1px; }

  ol.lead { margin: 14px 0 14px 0; padding-left: 24px; }
  ol.lead li { margin: 9px 0; }
  ul { margin: 13px 0; padding-left: 22px; }
  ul li { margin: 8px 0; }

  /* equations */
  .eq {
    background: var(--panel);
    border: 1px solid var(--hair);
    border-left: 2px solid var(--blue);
    padding: 15px 20px 16px; margin: 22px 0; border-radius: 0 3px 3px 0;
    font-size: 17px; line-height: 1.85; color: var(--ink);
    overflow-x: auto; text-align: center;
    font-variant-numeric: tabular-nums;
  }
  .eq.big { font-size: 17.5px; }
  .eq .lbl { display: block; font-family: var(--fig-font);
             font-size: 10.5px; color: var(--mute); margin-bottom: 9px;
             text-transform: uppercase; letter-spacing: 0.1em;
             text-align: left; font-style: normal; }
  .eq i { font-style: italic; }
  p.where { font-size: 15.5px; color: var(--mute); margin: -10px 0 18px;
            line-height: 1.55; }
  p.where i, p.where b { color: var(--body); }
  .ovl { border-top: 1px solid currentColor; padding: 1px 1px 0; }
  code, .m { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
             font-size: 0.85em; background: var(--code); padding: 1px 3px;
             border-radius: 2px; color: var(--ink); }
  .m { background: none; padding: 0; }

  /* figures */
  figure { margin: 30px 0 0; }
  figure svg { display: block; width: 100%; height: auto;
               font-family: var(--fig-font); }
  p.cap { font-family: var(--fig-font); font-size: 14px; line-height: 1.5;
          color: var(--mute); margin: 8px 0 30px; }
  p.cap b { color: var(--ink); font-weight: 600; }
  p.cap i { font-style: italic; }

  /* notes */
  .note {
    background: var(--panel); border: 1px solid var(--rule);
    border-left: 2px solid var(--accent);
    padding: 15px 20px; margin: 24px 0; border-radius: 0 3px 3px 0;
    font-size: 16.5px; line-height: 1.55;
  }
  .note b { color: var(--accent); font-weight: 600; }
  p.note-inline { font-size: 15.5px; color: var(--mute);
                  border-left: 2px solid var(--rule); padding-left: 16px;
                  margin: 24px 0; line-height: 1.55; }

  /* tables */
  table { border-collapse: collapse; width: 100%; margin: 22px 0;
          font-size: 15.5px; font-family: var(--fig-font); line-height: 1.5; }
  th, td { text-align: left; vertical-align: top; padding: 11px 13px 11px 0;
           border-bottom: 1px solid var(--hair); }
  th { color: var(--mute); font-size: 11px; text-transform: uppercase;
       letter-spacing: 0.09em; font-weight: 600;
       border-bottom: 1px solid var(--rule); padding-bottom: 8px; }
  td.q { font-weight: 600; color: var(--ink); }
  td.v { font-variant-numeric: tabular-nums; color: var(--ink);
         white-space: nowrap; font-weight: 600; }
  tr.stop td.act::before { content: "\\25A0\\00a0\\00a0"; color: var(--accent); }
  tr.go   td.act::before { content: "\\25A0\\00a0\\00a0"; color: #1a7f37; }
  table.params td:first-child { width: 30%; }
  table.params td:nth-child(2) { width: 14%; }

  /* symbol glossary */
  dl.syms { margin: 20px 0; padding: 0; }
  dl.syms > div {
    display: grid; grid-template-columns: 118px 1fr; gap: 0 22px;
    padding: 10px 0; border-bottom: 1px solid var(--hair);
  }
  dl.syms > div:first-child { border-top: 1px solid var(--rule); }
  dl.syms dt { color: var(--ink); font-weight: 600; font-size: 16.5px; }
  dl.syms dd { margin: 0; font-size: 16px; }

  /* references */
  ol.refs { font-size: 15.5px; line-height: 1.5; padding-left: 24px;
            margin: 20px 0; }
  ol.refs li { margin: 12px 0; }
  ol.refs i { font-style: italic; }

  footer { margin-top: 56px; padding-top: 18px;
           border-top: 1px solid var(--rule);
           color: var(--mute); font-size: 14px; font-family: var(--fig-font);
           line-height: 1.55; }
  footer code { font-size: 12.5px; }

  @media print {
    body { background: #fff; font-size: 10.5pt; }
    .wrap { max-width: none; padding: 0; }
    h2 { page-break-after: avoid; }
    figure, .eq, table, .note { page-break-inside: avoid; }
    p.cap { page-break-before: avoid; }
  }
"""

body = open(os.path.join(HERE, 'body.html')).read()

figmap = {
    'FIG1': 'fig1-reps', 'FIG2': 'fig2-window', 'FIG3': 'fig3-merge',
    'FIG4': 'fig4-perpoint', 'FIG5': 'fig5-c4', 'FIG6': 'fig6-floor-A',
    'FIG7': 'fig7-floor-B', 'FIG8': 'fig8-trend', 'FIG9': 'fig9-trap',
    'FIG10': 'fig10-projection',
}
for key, fname in figmap.items():
    svg = open(os.path.join(FIGS, fname + '.svg')).read().strip()
    svg = svg.replace('font-family: inherit', 'font-family: var(--fig-font)')
    body = body.replace('{{%s}}' % key, '<figure>\n%s\n</figure>' % svg)

assert '{{' not in body, 'unfilled placeholder'

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deciding when a scan series is finished</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
{body}
</div>
</body>
</html>
"""
open(OUT, 'w').write(html)
print('wrote', OUT, len(html) // 1024, 'kB')
