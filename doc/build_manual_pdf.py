# -*- coding: utf-8 -*-
"""Genera il PDF del Manuale Utente di Adaptive Agent for PHD2.

§26: metadata PDF (titolo, autore, soggetto, creator, keywords) letti dal
modulo phd2_agent/__about__.py — single source of truth del branding.
Usa font DejaVu (no emoji font disponibile) -> marcatori grafici al posto
delle emoji.
"""
# §26: import branding direttamente dal file __about__.py via importlib.
# Evita di passare per phd2_agent/__init__.py (che carica controller/analyzer
# e richiede tomli/numpy/scipy non necessari per la generazione del PDF).
import os as _os, sys as _sys
import importlib.util as _ilu
_ABOUT_PATH = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    "phd2_agent", "__about__.py"
)
_about_spec = _ilu.spec_from_file_location("_phd2_about_isolated", _ABOUT_PATH)
_about = _ilu.module_from_spec(_about_spec)
_about_spec.loader.exec_module(_about)
__project_name__    = _about.__project_name__
__version__         = _about.__version__
__author__          = _about.__author__
__copyright__       = _about.__copyright__
__contact_telegram__ = _about.__contact_telegram__

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    Table, TableStyle, ListFlowable, ListItem, HRFlowable, KeepTogether
)
from reportlab.platypus.flowables import Flowable

# ---- Fonts ----
def _find_dejavu_dir():
    """Cerca i 4 file DejaVuSans*.ttf cross-platform.
    Ordine: path Linux standard -> bundle matplotlib (Windows/macOS)."""
    import os
    candidates = ["/usr/share/fonts/truetype/dejavu/"]
    try:
        import matplotlib  # type: ignore
        candidates.append(os.path.join(os.path.dirname(matplotlib.__file__),
                                       "mpl-data", "fonts", "ttf") + os.sep)
    except ImportError:
        pass
    needed = ["DejaVuSans.ttf", "DejaVuSans-Bold.ttf",
              "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"]
    for d in candidates:
        if all(os.path.isfile(d + n) for n in needed):
            return d
    raise RuntimeError("Font DejaVu non trovati. Su Windows/macOS: `pip install matplotlib`.")

FD = _find_dejavu_dir()
pdfmetrics.registerFont(TTFont("DJ",  FD + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DJB", FD + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DJI", FD + "DejaVuSans-Oblique.ttf"))
pdfmetrics.registerFont(TTFont("DJBI", FD + "DejaVuSans-BoldOblique.ttf"))
registerFontFamily("DJ", normal="DJ", bold="DJB", italic="DJI", boldItalic="DJBI")

# ---- Palette ----
INK     = colors.HexColor("#1a2332")
MUTED   = colors.HexColor("#55617a")
ACCENT  = colors.HexColor("#3b5bdb")
ACCENT2 = colors.HexColor("#7048e8")
GOLD    = colors.HexColor("#d9a300")
GREEN   = colors.HexColor("#2f9e44")
RED     = colors.HexColor("#c92a2a")
LINEC   = colors.HexColor("#d6dbe6")
BGCARD  = colors.HexColor("#f4f6fb")
DEEP    = colors.HexColor("#0b1733")

# ---- Styles ----
body = ParagraphStyle("body", fontName="DJ", fontSize=10.2, leading=15.5,
                      textColor=INK, spaceAfter=7, alignment=TA_LEFT)
lead = ParagraphStyle("lead", parent=body, fontSize=11, leading=17, textColor=MUTED)
bullet = ParagraphStyle("bullet", parent=body, spaceAfter=5, leading=15)
h3 = ParagraphStyle("h3", fontName="DJB", fontSize=11.5, leading=15, textColor=INK,
                    spaceBefore=8, spaceAfter=4)
callout_t = ParagraphStyle("ct", parent=body, fontSize=9.8, leading=14.5, spaceAfter=0)
small = ParagraphStyle("small", parent=body, fontSize=8.6, textColor=MUTED, leading=12)


class SectionHeader(Flowable):
    def __init__(self, text, color=ACCENT, width=170*mm):
        super().__init__()
        self.text = text; self.color = color; self.width = width; self.height = 11*mm
    def wrap(self, aw, ah):
        return self.width, self.height
    def draw(self):
        c = self.canv
        c.setFillColor(self.color)
        c.roundRect(0, 1.5*mm, 3.2*mm, 8*mm, 1.2, fill=1, stroke=0)
        c.setFont("DJB", 14.5)
        c.setFillColor(ACCENT)
        c.drawString(7*mm, 3.4*mm, self.text)


class NumBadge(Flowable):
    def __init__(self, n, color):
        super().__init__(); self.n=str(n); self.color=color
        self.width=7*mm; self.height=7*mm
    def wrap(self,aw,ah): return self.width,self.height
    def draw(self):
        c=self.canv; c.setFillColor(self.color)
        c.circle(3.5*mm,3*mm,3.4*mm,fill=1,stroke=0)
        c.setFillColor(colors.white); c.setFont("DJB",10)
        c.drawCentredString(3.5*mm,1.6*mm,self.n)


def feature_head(n, title, color):
    p = Paragraph('<font name="DJB" size="11.5" color="#1a2332">%s</font>' % title, h3)
    t = Table([[NumBadge(n,color), p]], colWidths=[9*mm, 161*mm])
    t.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2),
    ]))
    return t


def callout(label, label_color, text):
    hexcol = "#" + label_color.hexval()[2:]
    inner = Paragraph(text, callout_t)
    t = Table([[inner]], colWidths=[163*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),BGCARD),
        ("LEFTPADDING",(0,0),(-1,-1),9),("RIGHTPADDING",(0,0),(-1,-1),9),
        ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
        ("LINEBEFORE",(0,0),(0,-1),3,label_color),
        ("BOX",(0,0),(-1,-1),0.5,LINEC),
    ]))
    head = Paragraph('<font name="DJB" size="8.5" color="%s">%s</font>' % (hexcol, label), callout_t)
    wrap = Table([[head],[t]], colWidths=[163*mm])
    wrap.setStyle(TableStyle([
        ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(0,0),0),("BOTTOMPADDING",(0,0),(0,0),3),
        ("TOPPADDING",(0,1),(0,1),0),("BOTTOMPADDING",(0,1),(0,1),0),
    ]))
    return KeepTogether([Spacer(1,3), wrap, Spacer(1,4)])


def pill(text, color):
    return Paragraph('<font name="DJB" size="9" color="%s">%s</font>'
                     % ("#"+color.hexval()[2:], text), small)


def blist(items):
    lis=[ListItem(Paragraph(x,bullet), leftIndent=6, value="–",
                  bulletColor=ACCENT) for x in items]
    return ListFlowable(lis, bulletType="bullet", start="–",
                        bulletFontName="DJB", bulletFontSize=10,
                        leftIndent=12, bulletColor=ACCENT)

def B(s): return "<b>%s</b>" % s
def I(s): return "<i>%s</i>" % s

story=[]; S=story.append

# ---------- COVER ----------
class Cover(Flowable):
    def __init__(self,w,h): super().__init__(); self.w=w; self.h=h
    def wrap(self,aw,ah): return self.w,self.h
    def draw(self):
        import random
        c=self.canv
        c.setFillColor(DEEP); c.rect(0,0,self.w,self.h,fill=1,stroke=0)
        random.seed(7); c.setFillColor(colors.white)
        for _ in range(60):
            x=random.uniform(0,self.w); y=random.uniform(self.h*0.12,self.h)
            r=random.choice([0.3,0.4,0.6,0.8])
            c.setFillAlpha(random.uniform(0.25,0.9)); c.circle(x,y,r,fill=1,stroke=0)
        c.setFillAlpha(1)
        c.setStrokeColor(colors.HexColor("#5b7cff")); c.setLineWidth(2)
        c.line(20*mm, self.h-34*mm, 70*mm, self.h-34*mm)
        c.setFillColor(colors.HexColor("#aebbff")); c.setFont("DJB",10.5)
        c.drawString(20*mm, self.h-30*mm, "MANUALE UTENTE")
        # §26: titolo branded — letto da phd2_agent.__about__ (single source of truth)
        c.setFillColor(colors.white); c.setFont("DJB",28)
        c.drawString(20*mm, self.h-50*mm, __project_name__)
        c.setFillColor(colors.HexColor("#c9d4ff")); c.setFont("DJB",16)
        c.drawString(20*mm, self.h-62*mm, f"Versione {__version__}  ·  by {__author__}")
        c.setFillColor(colors.HexColor("#c9d4ff")); c.setFont("DJI",12)
        c.drawString(20*mm, self.h-72*mm, "Il tuo copilota astrofotografico")
        # Footer cover: copyright + community Telegram (al posto della lista setup di sviluppo)
        c.setFillColor(colors.HexColor("#8a99c9")); c.setFont("DJ",9)
        c.drawString(20*mm, 20*mm, __copyright__)
        c.drawString(20*mm, 14*mm, f"Community e supporto:  {__contact_telegram__}")

S(Cover(170*mm, 150*mm))
S(Spacer(1, 8*mm))

# =========================================================================== #
#  §89 — IL CONTENUTO VIENE DAL MARKDOWN                                      #
#                                                                             #
#  Prima questo script conteneva una PROPRIA copia del manuale, indipendente   #
#  da doc/Manuale_Utente_Agent.md. Due fonti per lo stesso documento: bastava  #
#  aggiornarne una sola perche' il PDF pubblicato — quello che gli utenti      #
#  scaricano — raccontasse un prodotto diverso da quello reale. E' successo:   #
#  il PDF ha continuato a descrivere l'AI Star Finder per mesi dopo che era    #
#  stato rimosso dal codice.                                                   #
#                                                                             #
#  Ora il .md e' la sola fonte. Questo file resta responsabile solo di COME    #
#  il manuale appare: font, colori, copertina, impaginazione.                  #
# =========================================================================== #

import re as _re

_MD = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                    "Manuale_Utente_Agent.md")

# DejaVu non copre le emoji: quelle con un significato diventano testo, le
# decorative spariscono. Meglio nulla che un rettangolo vuoto sulla pagina.
_SIMBOLI = {"\u2705": "[SI] ", "\u26d4": "[NO] ", "\u26a0\ufe0f": "[!] ", "\u26a0": "[!] "}
_FUORI = _re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u2190-\u21FF]")

def _pulisci(t):
    for k, v in _SIMBOLI.items():
        t = t.replace(k, v)
    return _FUORI.sub("", t).strip()

def _inline(t):
    """Markdown inline -> markup di reportlab. L'escape viene PRIMA, cosi' i tag
    che genero io non possono essere sfuggiti a loro volta."""
    t = _pulisci(t)
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Il codice inline si mette da parte PRIMA di tutto: dentro
    # `decisions_*.jsonl` gli asterischi non sono corsivo, e senza questa
    # protezione i tag si incrociano e reportlab si ferma.
    _cod = []
    def _stacca(m):
        _cod.append(m.group(1))
        return "\x00%d\x00" % (len(_cod) - 1)
    t = _re.sub(r"`([^`]+)`", _stacca, t)
    t = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = _re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", t)
    t = _re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<link href="\2" color="#3b5bdb">\1</link>', t)
    t = _re.sub("\x00(\\d+)\x00",
                lambda m: '<font color="#3b5bdb">%s</font>' % _cod[int(m.group(1))], t)
    return t

_CALLOUT = {"TIP": ("SUGGERIMENTO", GREEN), "NOTE": ("NOTA", ACCENT),
            "IMPORTANT": ("IMPORTANTE", GOLD), "WARNING": ("ATTENZIONE", RED),
            "CAUTION": ("ATTENZIONE", RED)}

def _tabella(righe):
    """righe: lista di liste di celle (la prima e' l'intestazione)."""
    n = len(righe[0])
    larg = {2: [58*mm, 112*mm], 3: [52*mm, 56*mm, 62*mm]}.get(n, [170.0/n*mm]*n)
    dati = [[Paragraph(_inline(c), small) for c in righe[0]]]
    for r in righe[1:]:
        dati.append([Paragraph(_inline(c), small) for c in r])
    t = Table(dati, colWidths=larg, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), ACCENT),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "DJB"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, BGCARD]),
        ("GRID", (0,0), (-1,-1), 0.4, LINEC),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
        ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    return KeepTogether([Spacer(1,3), t, Spacer(1,6)])

def _codice(linee):
    p = Paragraph("<br/>".join(_pulisci(x).replace(" ", "&nbsp;") for x in linee),
                  ParagraphStyle("code", parent=small, fontName="DJ",
                                 textColor=INK, leading=13))
    t = Table([[p]], colWidths=[163*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), BGCARD),
        ("BOX", (0,0), (-1,-1), 0.5, LINEC),
        ("LEFTPADDING", (0,0), (-1,-1), 9), ("RIGHTPADDING", (0,0), (-1,-1), 9),
        ("TOPPADDING", (0,0), (-1,-1), 7), ("BOTTOMPADDING", (0,0), (-1,-1), 7),
    ]))
    return KeepTogether([Spacer(1,3), t, Spacer(1,6)])

def _numerata(items):
    lis = [ListItem(Paragraph(x, bullet), leftIndent=6) for x in items]
    return ListFlowable(lis, bulletType="1", leftIndent=14,
                        bulletFontName="DJB", bulletFontSize=10, bulletColor=ACCENT)

def _rendi(md):
    linee = md.split("\n")
    k, saltato_h1 = 0, False
    buf_p, buf_l, buf_n, buf_t, buf_q = [], [], [], [], []
    q_tipo = [None]

    def _chiudi():
        if buf_p:
            S(Paragraph(_inline(" ".join(buf_p)), body)); buf_p.clear()
        if buf_l:
            S(blist([_inline(x) for x in buf_l])); S(Spacer(1,4)); buf_l.clear()
        if buf_n:
            S(_numerata([_inline(x) for x in buf_n])); S(Spacer(1,4)); buf_n.clear()
        if buf_t:
            S(_tabella(buf_t)); buf_t.clear()
        if buf_q:
            et, col = _CALLOUT.get(q_tipo[0] or "NOTE", ("NOTA", ACCENT))
            S(callout(et, col, _inline(" ".join(buf_q))))
            buf_q.clear(); q_tipo[0] = None

    while k < len(linee):
        l = linee[k]; sl = l.strip()

        if sl.startswith("```"):                       # blocco di codice
            _chiudi(); k += 1; blk = []
            while k < len(linee) and not linee[k].strip().startswith("```"):
                blk.append(linee[k]); k += 1
            S(_codice(blk)); k += 1; continue

        if not sl or sl in ("---", "***"):             # riga vuota / separatore
            _chiudi(); k += 1; continue

        if sl.startswith("# ") and not saltato_h1:     # titolo: gia' in copertina
            saltato_h1 = True; _chiudi(); k += 1; continue

        if sl.startswith("## "):
            _chiudi(); S(Spacer(1,6))
            # Nei titoli i simboli si tolgono e basta: un [!] davanti a una
            # intestazione di sezione e' rumore, non informazione.
            S(SectionHeader(_re.sub(r"^\[(?:SI|NO|!)\]\s*", "", _pulisci(sl[3:]))))
            S(HRFlowable(width="100%", thickness=0.6, color=LINEC, spaceAfter=8))
            k += 1; continue

        if sl.startswith("### "):
            _chiudi(); S(Paragraph(B(_inline(sl[4:])), h3)); k += 1; continue

        if sl.startswith("|"):                         # tabella
            if buf_p or buf_l or buf_n: _chiudi()
            celle = [c.strip() for c in sl.strip("|").split("|")]
            if not all(_re.fullmatch(r":?-{2,}:?", c) for c in celle):
                buf_t.append(celle)
            k += 1; continue

        if sl.startswith(">"):                         # callout / citazione
            if buf_p or buf_l or buf_n: _chiudi()
            c = sl.lstrip(">").strip()
            m = _re.match(r"\[!(\w+)\]", c)
            if m:
                q_tipo[0] = m.group(1).upper(); c = c[m.end():].strip()
            if c: buf_q.append(c)
            k += 1; continue

        m = _re.match(r"^\s*[*-]\s+(.*)", l)           # elenco puntato
        if m:
            if buf_p or buf_n or buf_t: _chiudi()
            buf_l.append(m.group(1)); k += 1; continue

        m = _re.match(r"^\s*\d+\.\s+(.*)", l)         # elenco numerato
        if m:
            if buf_p or buf_l or buf_t: _chiudi()
            buf_n.append(m.group(1)); k += 1; continue

        if buf_l or buf_n or buf_t or buf_q: _chiudi()  # paragrafo
        buf_p.append(sl); k += 1

    _chiudi()

with open(_MD, encoding="utf-8") as _f:
    _rendi(_f.read())

# ---------- DOC ----------
def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("DJ",8); canvas.setFillColor(MUTED)
    if doc.page > 1:
        canvas.drawString(20*mm, 12*mm, f"{__project_name__} - Manuale Utente v{__version__}")
        canvas.drawRightString(190*mm, 12*mm, "pag. %d" % doc.page)
        canvas.setStrokeColor(LINEC); canvas.setLineWidth(0.4)
        canvas.line(20*mm,15*mm,190*mm,15*mm)
    canvas.restoreState()

# §26: path output relativo a questo script (doc/Manuale_Utente_Agent.pdf nel repo);
# override possibile via argv[1].
import sys as _sys2
_THIS_DIR = _os.path.dirname(_os.path.abspath(__file__))
if len(_sys2.argv) > 1:
    OUT = _sys2.argv[1]
else:
    OUT = _os.path.join(_THIS_DIR, "Manuale_Utente_Agent.pdf")

# §26: metadata PDF dal modulo __about__ (single source of truth del branding).
doc = BaseDocTemplate(
    OUT, pagesize=A4,
    leftMargin=20*mm, rightMargin=20*mm, topMargin=18*mm, bottomMargin=18*mm,
    title=f"{__project_name__} - Manuale Utente v{__version__}",
    author=__author__,
    subject=f"Manuale utente per astrofotografi - {__project_name__}",
    creator=f"{__project_name__} v{__version__}",
    keywords="PHD2, autoguida, astrofotografia, adaptive agent",
)
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
doc.addPageTemplates([PageTemplate(id="t", frames=[frame], onPage=on_page)])
doc.build(story)
print("PDF creato:", OUT)
