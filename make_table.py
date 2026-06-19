import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

# ---- Data -------------------------------------------------------------
cols = ["", "2024", "2025", "3Q25", "4Q25", "1Q26"]

# row: (label, [vals], style)
# style: 'group' company header, 'metric' bold-ish, 'sub' indented sub-row, 'val' normal
rows = [
    ("SALESFORCE (CRM)  ·  FY ends Jan 31  ·  FY26 = CY25", ["", "", "", "", ""], "group"),
    ("Total revenue", ["37,900", "41,500", "10,300", "11,200", "11,100"], "metric"),
    ("   YoY reported / cc", ["+9% / +9%", "+10% / +9%", "+9% / +8%", "+12% / +10%", "+13% / +12%"], "sub"),
    ("   o/w Informatica (inorganic)", ["—", "400", "—", "400", "440"], "sub"),
    ("   Organic total (ex-Inf.)", ["37,900", "~41,100", "10,300", "~10,800", "~10,660"], "subb"),
    ("   Organic YoY", ["+9%", "~+8%", "+9%", "~+8%", "~+8%"], "sub"),
    ("Subscription & support", ["35,700", "39,390", "9,700", "n/d", "10,600"], "metric"),
    ("   YoY reported / cc", ["+10% / +10%", "+10% / n/d", "+10% / +9%", "n/d", "+14% / +12%"], "sub"),

    ("SERVICENOW (NOW)  ·  FY = calendar year", ["", "", "", "", ""], "group"),
    ("Total revenue", ["10,984", "13,280", "3,407", "3,568", "3,770"], "metric"),
    ("   YoY reported / cc", ["+22% / n/d", "+21% / n/d", "+22% / +20.5%", "+20.5% / +19.5%", "+22% / +19%"], "sub"),
    ("Subscription revenue", ["10,646", "12,880", "3,299", "3,466", "3,671"], "metric"),
    ("   YoY reported / cc", ["+23% / +22.5%", "+21% / n/d", "+21.5% / +20.5%", "+21% / +19.5%", "+22% / +19%"], "sub"),
    ("   Organic", ["≈ reported", "≈ reported", "≈ reported", "≈ reported", "≈ reported"], "sub"),

    ("WORKDAY (WDAY)  ·  FY ends Jan 31  ·  FY26 = CY25", ["", "", "", "", ""], "group"),
    ("Total revenue", ["8,446", "9,552", "2,432", "2,532", "2,542"], "metric"),
    ("   YoY reported / cc", ["+16.4% / n/d", "+13.1% / n/d", "+12.6% / n/d", "+14.5% / n/d", "+13.5% / n/d"], "sub"),
    ("Subscription revenue", ["7,718", "8,833", "2,244", "2,360", "2,354"], "metric"),
    ("   YoY reported / cc", ["+16.9% / n/d", "+14.5% / n/d", "+14.6% / n/d", "+15.7% / n/d", "+14.3% / n/d"], "sub"),
    ("   Organic", ["≈ reported", "≈ reported", "≈ reported", "≈ reported", "≈ reported"], "sub"),
]

# ---- Colours ----------------------------------------------------------
C_SF   = "#1798c1"   # salesforce blue
C_NOW  = "#62d84e"   # servicenow green
C_WDAY = "#f38b00"   # workday orange
HEADER = "#1f2d3d"
ALT    = "#f4f7fa"
WHITE  = "#ffffff"
TXT    = "#1f2d3d"
SUBTXT = "#5b6b7b"

group_color = {0: C_SF, 8: C_NOW, 14: C_WDAY}

# ---- Layout -----------------------------------------------------------
nrows = len(rows) + 1          # +1 header
ncols = len(cols)
col_w = [0.40, 0.14, 0.14, 0.14, 0.14, 0.14]  # relative widths (label wider)
# normalize
s = sum(col_w); col_w = [w/s for w in col_w]
x_edges = [0]
for w in col_w:
    x_edges.append(x_edges[-1] + w)

row_h = 1.0 / nrows

fig_w, fig_h = 13.5, 0.52 * nrows
fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=200)
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

def ytop(i):   # i=0 header
    return 1 - i * row_h

# Title
fig.suptitle("Revenue Comparison — Salesforce · ServiceNow · Workday   (US$ millions, calendar periods)",
             x=0.01, ha="left", fontsize=15, fontweight="bold", color=HEADER, y=1.0)

# ---- Header row -------------------------------------------------------
for c in range(ncols):
    x0, x1 = x_edges[c], x_edges[c+1]
    ax.add_patch(plt.Rectangle((x0, ytop(1)), x1-x0, row_h,
                 facecolor=HEADER, edgecolor=WHITE, lw=1.2))
    ha = "left" if c == 0 else "center"
    tx = x0 + 0.008 if c == 0 else (x0+x1)/2
    label = "Metric" if c == 0 else cols[c]
    ax.text(tx, ytop(1)+row_h/2, label, ha=ha, va="center",
            color="white", fontsize=11.5, fontweight="bold")

# ---- Data rows --------------------------------------------------------
for ri, (label, vals, style) in enumerate(rows):
    r = ri + 1               # grid row index (header is 0)
    y0 = ytop(r+1)
    if style == "group":
        gc = group_color[ri]
        for c in range(ncols):
            x0, x1 = x_edges[c], x_edges[c+1]
            ax.add_patch(plt.Rectangle((x0, y0), x1-x0, row_h,
                         facecolor=gc, edgecolor=WHITE, lw=1.2))
        ax.text(x_edges[0]+0.008, y0+row_h/2, label, ha="left", va="center",
                color="white", fontsize=11.5, fontweight="bold")
        continue

    # background
    bg = ALT if (style in ("metric",)) else WHITE
    if style == "subb":
        bg = "#fff7ec"
    for c in range(ncols):
        x0, x1 = x_edges[c], x_edges[c+1]
        ax.add_patch(plt.Rectangle((x0, y0), x1-x0, row_h,
                     facecolor=bg, edgecolor="#dfe6ec", lw=0.8))

    # label cell
    is_metric = style == "metric"
    lbl_color = TXT if is_metric else SUBTXT
    lbl_weight = "bold" if is_metric else "normal"
    lbl_size = 11 if is_metric else 9.8
    indent = 0.008 if is_metric else 0.025
    ax.text(x_edges[0]+indent, y0+row_h/2, label.strip() if is_metric else label.lstrip(),
            ha="left", va="center", color=lbl_color, fontsize=lbl_size, fontweight=lbl_weight)

    # value cells
    for c in range(1, ncols):
        x0, x1 = x_edges[c], x_edges[c+1]
        v = vals[c-1]
        vcolor = TXT if is_metric else SUBTXT
        vweight = "bold" if is_metric else "normal"
        vsize = 10.8 if is_metric else 9.6
        if style == "subb":
            vcolor = "#b35c00"; vweight = "bold"
        ax.text((x0+x1)/2, y0+row_h/2, v, ha="center", va="center",
                color=vcolor, fontsize=vsize, fontweight=vweight)

# ---- Footnote ---------------------------------------------------------
foot = ("Notes:  Ex-extraordinaries = reported revenue (no one-off items in revenue line).  "
        "Constant currency (cc) shown as growth rate only — Workday does not disclose cc.  "
        "Organic differs from reported only at Salesforce (Informatica, closed 4Q25); organic $/% are calculated.\n"
        "Calendar mapping: Salesforce/Workday Jan-31 FYE — Q3 FY26 / Q4 FY26 / Q1 FY27 shown as 3Q25 / 4Q25 / 1Q26; FY2026 = CY2025.")
fig.text(0.01, -0.018, foot, ha="left", va="top", fontsize=8.2, color=SUBTXT)

plt.subplots_adjust(left=0.005, right=0.995, top=0.955, bottom=0.06)
fig.savefig("/home/user/teste/revenue_table.png", bbox_inches="tight",
            pad_inches=0.25, facecolor="white")
print("saved")
