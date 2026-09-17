#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the SYM-2P reader report PDF from its markdown source.

Input:  docs/SYM-2P-reader-report.md   (a constrained markdown subset:
        headings, paragraphs, blockquote callouts, fenced code, tables,
        bullet and numbered lists, a [TOC] marker, and <!-- page break -->)
Output: docs/SYM-2P-reader-report.pdf

Run from the repository root:

    python3 docs/build-sym2p-reader-report.py
    python3 docs/build-sym2p-reader-report.py --in <md> --out <pdf>

Requires ReportLab only. No network access, no other dependencies, stdlib
elsewhere. The build is deterministic: the PDF is written with a fixed
document date, so two runs from the same source produce identical bytes.
"""

from __future__ import print_function

import argparse
import hashlib
import os
import re
import sys

from reportlab.lib import colors
from reportlab import rl_config

# Deterministic output: a fixed document timestamp and a fixed document id, so
# two builds from the same source produce byte-identical PDFs. The fixed date is
# 2026-09-17T00:00:00Z, set only when the caller has not chosen one.
os.environ.setdefault('SOURCE_DATE_EPOCH', '1789603200')
rl_config.invariant = 1
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether,
                                ListFlowable, ListItem, PageBreak, PageTemplate,
                                Paragraph, Preformatted, Spacer, Table,
                                TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.pdfgen import canvas as pdfcanvas

# ---------------------------------------------------------------------------
# layout constants
# ---------------------------------------------------------------------------

PAGE_W, PAGE_H = A4
MARGIN_X = 21.5 * mm          # generous side margins
MARGIN_Y = 20.0 * mm
FRAME_W = PAGE_W - 2 * MARGIN_X

NAVY = colors.HexColor('#12305a')
SLATE = colors.HexColor('#33415c')
ACCENT = colors.HexColor('#1f4e79')
HOLD = colors.HexColor('#8a4b08')
BODY_TEXT = colors.HexColor('#1a1a1a')
MUTED = colors.HexColor('#6b7785')
RULE = colors.HexColor('#c8d2e0')
CODE_BG = colors.HexColor('#f4f6f8')
CALL_BG = colors.HexColor('#eef3fa')
CALL_BG_HOLD = colors.HexColor('#fdf3e6')
TBL_HEAD_BG = colors.HexColor('#12305a')
TBL_ALT_BG = colors.HexColor('#f7f9fc')

FOOTER_LEFT = 'SYM-2P - a reader\'s guide to the shipped protocol'
PDF_TITLE = 'SYM-2P: A Small Message Language for Teams of Agents'
PDF_AUTHOR = 'protean-sym2p'


def make_styles():
    """Paragraph styles used across the document."""
    body = ParagraphStyle(
        'body', fontName='Helvetica', fontSize=10.4, leading=15.2,
        spaceAfter=7, alignment=TA_LEFT, textColor=BODY_TEXT,
        allowWidows=0, allowOrphans=0, splitLongWords=1)
    s = {
        'body': body,
        'h1': ParagraphStyle('h1', parent=body, fontName='Helvetica-Bold',
                             fontSize=20.5, leading=25, textColor=NAVY,
                             spaceBefore=0, spaceAfter=9, keepWithNext=1),
        'sub': ParagraphStyle('sub', parent=body, fontName='Helvetica',
                              fontSize=12.6, leading=17.5,
                              textColor=colors.HexColor('#44546a'),
                              spaceAfter=13, keepWithNext=0),
        'h2': ParagraphStyle('h2', parent=body, fontName='Helvetica-Bold',
                             fontSize=15.2, leading=19.5, textColor=NAVY,
                             spaceBefore=16, spaceAfter=7, keepWithNext=1),
        'h3': ParagraphStyle('h3', parent=body, fontName='Helvetica-Bold',
                             fontSize=11.5, leading=15.5, textColor=SLATE,
                             spaceBefore=11, spaceAfter=4, keepWithNext=1),
        'tbl': ParagraphStyle('tbl', parent=body, fontSize=9.2, leading=12.4,
                              spaceAfter=0, splitLongWords=1),
        'tblh': ParagraphStyle('tblh', parent=body, fontName='Helvetica-Bold',
                               fontSize=9.2, leading=12.4, spaceAfter=0,
                               textColor=colors.white),
        'call': ParagraphStyle('call', parent=body, fontSize=10.0, leading=14.5,
                               spaceAfter=6),
        'code': ParagraphStyle('code', parent=body, fontName='Courier',
                               fontSize=8.5, leading=11.4, spaceAfter=0),
        'li': ParagraphStyle('li', parent=body, fontSize=10.4, leading=15.0,
                             spaceAfter=5),
        'toc': ParagraphStyle('toc', parent=body, fontName='Helvetica',
                              fontSize=10.2, leading=15, spaceAfter=0),
        'tocpage': ParagraphStyle('tocpage', parent=body, fontSize=10.2,
                                  leading=15, alignment=TA_RIGHT, spaceAfter=0),
        'tochead': ParagraphStyle('tochead', parent=body, fontName='Helvetica-Bold',
                                  fontSize=15.2, leading=19.5, textColor=NAVY,
                                  spaceBefore=0, spaceAfter=10, keepWithNext=1),
    }
    return s


STYLES = make_styles()


# ---------------------------------------------------------------------------
# markdown subset parser
# ---------------------------------------------------------------------------

TABLE_SEP = re.compile(r'^\|[\s:|-]+\|$')
NUMBERED = re.compile(r'^(\d+)\.\s+(.*)$')


def _is_block_start(line):
    t = line.strip()
    if not t:
        return True
    if t.startswith('#') or t.startswith('> ') or t.startswith('|'):
        return True
    if t.startswith('- ') or t.startswith('```'):
        return True
    if t in ('[TOC]',) or t.startswith('<!--'):
        return True
    return bool(NUMBERED.match(t))


def parse_markdown(text):
    """Return a list of (kind, payload) blocks from the markdown source."""
    lines = text.split('\n')
    blocks = []
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if not s:
            i += 1
            continue
        if s.startswith('```'):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith('```'):
                buf.append(lines[i].rstrip())
                i += 1
            i += 1
            blocks.append(('code', '\n'.join(buf)))
            continue
        if s == '<!-- page break -->':
            blocks.append(('pagebreak', None))
            i += 1
            continue
        if s == '[TOC]':
            blocks.append(('toc', None))
            i += 1
            continue
        if s.startswith('### '):
            blocks.append(('h3', s[4:].strip()))
            i += 1
            continue
        if s.startswith('## '):
            blocks.append(('h2', s[3:].strip()))
            i += 1
            continue
        if s.startswith('# '):
            blocks.append(('h1', s[2:].strip()))
            i += 1
            continue
        if s.startswith('> '):
            paras = []
            while i < n and lines[i].strip().startswith('> '):
                paras.append(lines[i].strip()[2:].strip())
                i += 1
            blocks.append(('callout', paras))
            continue
        if s.startswith('|'):
            rows = []
            while i < n and lines[i].strip().startswith('|'):
                row = lines[i].strip()
                if not TABLE_SEP.match(row):
                    cells = [c.strip() for c in row.strip('|').split('|')]
                    rows.append(cells)
                i += 1
            width = max(len(r) for r in rows)
            rows = [r + [''] * (width - len(r)) for r in rows]
            blocks.append(('table', rows))
            continue
        if s.startswith('- '):
            items = []
            while i < n and lines[i].strip().startswith('- '):
                items.append(lines[i].strip()[2:].strip())
                i += 1
            blocks.append(('bullets', items))
            continue
        m = NUMBERED.match(s)
        if m:
            items = []
            while i < n:
                mm = NUMBERED.match(lines[i].strip())
                if not mm:
                    break
                items.append(mm.group(2).strip())
                i += 1
            blocks.append(('numbers', items))
            continue
        buf = [s]
        i += 1
        while i < n and not _is_block_start(lines[i]):
            buf.append(lines[i].strip())
            i += 1
        blocks.append(('p', ' '.join(buf)))
    return blocks


# ---------------------------------------------------------------------------
# inline markup
# ---------------------------------------------------------------------------

def inline(text):
    """Escape XML and apply bold / inline-code markup."""
    s = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'`([^`]+)`', r'<font face="Courier" size="9">\1</font>', s)
    return s


def plain(text):
    return re.sub(r'[`*]', '', text)


# ---------------------------------------------------------------------------
# flowable builders
# ---------------------------------------------------------------------------

CODE_MAX_CHARS = int((FRAME_W - 16) / stringWidth('0', 'Courier', 8.5))


def wrap_code_line(line):
    if len(line) <= CODE_MAX_CHARS:
        return [line]
    out, rest = [], line
    indent = len(rest) - len(rest.lstrip(' '))
    cont = ' ' * (indent + 2)
    while len(rest) > CODE_MAX_CHARS:
        cut = rest.rfind(' ', 0, CODE_MAX_CHARS)
        if cut <= indent:
            cut = CODE_MAX_CHARS
        out.append(rest[:cut].rstrip())
        rest = cont + rest[cut:].lstrip()
    out.append(rest)
    return out


def make_code(text, style='code'):
    lines = []
    for line in text.split('\n'):
        lines.extend(wrap_code_line(line.rstrip()))
    flow = Preformatted('\n'.join(lines), STYLES[style])
    tbl = Table([[flow]], colWidths=[FRAME_W])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CODE_BG),
        ('BOX', (0, 0), (-1, -1), 0.5, RULE),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return [Spacer(1, 3), tbl, Spacer(1, 8)]


def make_callout(paras):
    hold = 'Phase 3' in paras[0] or 'held, not implemented' in paras[0]
    accent = HOLD if hold else ACCENT
    bg = CALL_BG_HOLD if hold else CALL_BG
    data = [[Paragraph(inline(p), STYLES['call'])] for p in paras]
    tbl = Table(data, colWidths=[FRAME_W])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg),
        ('LINEBEFORE', (0, 0), (0, -1), 2.6, accent),
        ('LEFTPADDING', (0, 0), (-1, -1), 11),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (0, 0), 7),
        ('TOPPADDING', (0, 1), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    return [Spacer(1, 3), tbl, Spacer(1, 9)]


def _column_widths(rows):
    """Distribute the frame width over columns without letting a word clip."""
    ncols = len(rows[0])
    pad = 12.0
    min_w = [pad] * ncols
    ideal = [pad] * ncols
    for row in rows:
        for i, cell in enumerate(row):
            txt = plain(cell)
            ideal[i] = max(ideal[i], min(stringWidth(txt, 'Helvetica', 9.2) + pad,
                                          0.62 * FRAME_W))
            for tok in txt.split():
                tw = max(stringWidth(tok, 'Helvetica', 9.2),
                         stringWidth(tok, 'Courier', 9.0))
                min_w[i] = max(min_w[i], tw + pad)
    total = sum(ideal)
    if total > FRAME_W:
        widths = [w * FRAME_W / total for w in ideal]
    else:
        widths = list(ideal)
    deficit = sum(max(0.0, min_w[i] - widths[i]) for i in range(ncols))
    if deficit > 0:
        donors = [i for i in range(ncols) if widths[i] > min_w[i] + 1]
        slack = sum(widths[i] - min_w[i] for i in donors)
        for i in donors:
            widths[i] -= (widths[i] - min_w[i]) * deficit / slack
        widths = [max(widths[i], min_w[i]) for i in range(ncols)]
    free = FRAME_W - sum(widths)
    if free > 0:
        widths[-1] += free
    return widths


def make_table(rows):
    header = [Paragraph(inline(c), STYLES['tblh']) for c in rows[0]]
    body = [[Paragraph(inline(c), STYLES['tbl']) for c in r] for r in rows[1:]]
    widths = _column_widths(rows)
    data = [header] + body
    tbl = Table(data, colWidths=widths, repeatRows=1, splitByRow=1)
    style = [
        ('BACKGROUND', (0, 0), (-1, 0), TBL_HEAD_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.4, RULE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4.5),
    ]
    for r in range(1, len(data)):
        if r % 2 == 0:
            style.append(('BACKGROUND', (0, r), (-1, r), TBL_ALT_BG))
    if len(data) > 4:
        # keep the header and the first two body rows together: a table that
        # cannot fit them starts on the next page instead of splitting there
        style.append(('NOSPLIT', (0, 0), (-1, 2)))
    tbl.setStyle(TableStyle(style))
    return [Spacer(1, 3), tbl, Spacer(1, 9)]


# ---------------------------------------------------------------------------
# story assembly
# ---------------------------------------------------------------------------

class ReportToc(TableOfContents):
    """Table of contents drawn as two clean columns: section title, page.

    TableOfContents already resolves page numbers across build passes and
    hands drawing to an embedded table, so only the table is replaced here.
    """

    def __init__(self, entry_style, page_style):
        TableOfContents.__init__(self, dotsMinLevel=-1)
        self._entry_style = entry_style
        self._page_style = page_style

    def wrap(self, availWidth, availHeight):
        entries = self._lastEntries or self._entries
        if not entries:
            rows = [[Paragraph('(resolved on the second build pass)',
                               self._entry_style), Paragraph('', self._page_style)]]
        else:
            rows = [[Paragraph(inline(text), self._entry_style),
                     Paragraph(str(page), self._page_style)]
                    for (_level, text, page, _key) in entries]
        self._table = Table(rows, colWidths=[availWidth - 36, 36])
        self._table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 2.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
            ('LINEBELOW', (0, 0), (-1, -2), 0.3, RULE),
        ]))
        self.width, self.height = self._table.wrapOn(self.canv, availWidth, availHeight)
        return (self.width, self.height)


def make_toc():
    return ReportToc(STYLES['toc'], STYLES['tocpage'])


def build_story(blocks):
    story = []
    for kind, payload in blocks:
        if kind == 'h1':
            story.append(Paragraph(inline(payload), STYLES['h1']))
        elif kind == 'h3':
            story.append(Paragraph(inline(payload), STYLES['sub']))
        elif kind == 'h2':
            story.append(Paragraph(inline(payload), STYLES['h2']))
        elif kind == 'p':
            story.append(Paragraph(inline(payload), STYLES['body']))
        elif kind == 'bullets':
            items = [ListItem(Paragraph(inline(x), STYLES['li']), leftIndent=16)
                     for x in payload]
            story.append(ListFlowable(items, bulletType='bullet', start='\u2022',
                                      bulletFontSize=7.5, bulletOffsetY=-1,
                                      leftIndent=16, spaceAfter=8))
        elif kind == 'numbers':
            items = [ListItem(Paragraph(inline(x), STYLES['li']), leftIndent=18)
                     for x in payload]
            story.append(ListFlowable(items, bulletType='1', bulletFormat='%s.',
                                      bulletFontSize=9.5, leftIndent=18,
                                      spaceAfter=8))
        elif kind == 'code':
            story.extend(make_code(payload))
        elif kind == 'callout':
            story.extend(make_callout(payload))
        elif kind == 'table':
            story.extend(make_table(payload))
        elif kind == 'pagebreak':
            story.append(PageBreak())
        elif kind == 'toc':
            story.append(PageBreak())
            story.append(Paragraph('Contents', STYLES['tochead']))
            story.append(make_toc())
            story.append(PageBreak())
        else:
            raise ValueError('unknown block kind: %r' % (kind,))
    return story


# ---------------------------------------------------------------------------
# document template, page numbers, deterministic output
# ---------------------------------------------------------------------------

class NumberedCanvas(pdfcanvas.Canvas):
    """Draws the footer rule, the running title, and 'Page N of M'."""

    def __init__(self, *args, **kwargs):
        pdfcanvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            pdfcanvas.Canvas.showPage(self)
        pdfcanvas.Canvas.save(self)

    def _draw_footer(self, total):
        self.saveState()
        y = MARGIN_Y - 14
        self.setStrokeColor(RULE)
        self.setLineWidth(0.5)
        self.line(MARGIN_X, y, PAGE_W - MARGIN_X, y)
        self.setFont('Helvetica', 8.3)
        self.setFillColor(MUTED)
        self.drawString(MARGIN_X, y - 10.5, FOOTER_LEFT)
        self.drawRightString(PAGE_W - MARGIN_X, y - 10.5,
                             'Page %d of %d' % (self._pageNumber, total))
        self.restoreState()


class ReportCanvas(NumberedCanvas):
    """Numbered canvas with a fixed document date, so builds are repeatable."""

    def __init__(self, *args, **kwargs):
        try:
            NumberedCanvas.__init__(self, *args, invariant=1, **kwargs)
        except TypeError:
            NumberedCanvas.__init__(self, *args, **kwargs)


class ReportDoc(BaseDocTemplate):
    def __init__(self, filename, **kwargs):
        BaseDocTemplate.__init__(
            self, filename, pagesize=A4,
            leftMargin=MARGIN_X, rightMargin=MARGIN_X,
            topMargin=MARGIN_Y, bottomMargin=MARGIN_Y,
            title=PDF_TITLE, author=PDF_AUTHOR,
            subject='Reader report for the SYM-2P message language',
            creator='docs/build-sym2p-reader-report.py', **kwargs)
        frame = Frame(MARGIN_X, MARGIN_Y, FRAME_W, PAGE_H - 2 * MARGIN_Y,
                      id='body', leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id='main', frames=[frame])])

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == 'h2':
            self.notify('TOCEntry', (0, flowable.getPlainText(), self.page))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Build the SYM-2P reader report PDF from its markdown source.')
    parser.add_argument('--in', dest='src', default=os.path.join('docs', 'SYM-2P-reader-report.md'),
                        help='input markdown (default: docs/SYM-2P-reader-report.md)')
    parser.add_argument('--out', dest='dst', default=os.path.join('docs', 'SYM-2P-reader-report.pdf'),
                        help='output PDF (default: docs/SYM-2P-reader-report.pdf)')
    args = parser.parse_args(argv)

    root = os.getcwd()
    src = args.src if os.path.isabs(args.src) else os.path.join(root, args.src)
    dst = args.dst if os.path.isabs(args.dst) else os.path.join(root, args.dst)

    print('repository root: %s' % root)
    print('input:  %s' % src)
    print('output: %s' % dst)

    if not os.path.isfile(src):
        print('error: input not found: %s' % src, file=sys.stderr)
        return 2

    with open(src, encoding='utf-8') as fh:
        text = fh.read()

    blocks = parse_markdown(text)
    story = build_story(blocks)
    os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)

    doc = ReportDoc(dst)
    doc.multiBuild(story, canvasmaker=ReportCanvas)

    size = os.path.getsize(dst)
    digest = sha256_file(dst)
    print('blocks: %d' % len(blocks))
    print('pages:  %d' % doc.page)
    print('bytes:  %d' % size)
    print('sha256: %s' % digest)
    if size <= 0:
        print('error: empty output', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
