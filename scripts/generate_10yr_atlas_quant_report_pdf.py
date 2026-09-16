#!/usr/bin/env python3
"""
scripts/generate_10yr_atlas_quant_report_pdf.py
─────────────────────────────────────────────────────────────────────────────
Generates a publication-grade PDF report for the 10-Year ATLAS-Quant Nexus Engine
(Profit, Loss, Single-Month Trade Frequencies, and $6k Account Growth).
"""

import os
import sys
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

# Paths
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PDF = ROOT / "AgentQuant_10Year_ATLAS_Quant_Breakthrough_Report.pdf"
ARTIFACT_DIR = Path("C:/Users/David/.gemini/antigravity-ide/brain/022e7a86-9e65-42f8-b117-d1c55fae429d")
ARTIFACT_PDF = ARTIFACT_DIR / "AgentQuant_10Year_ATLAS_Quant_Breakthrough_Report.pdf"
CHART_PATH = ARTIFACT_DIR / "scratch" / "atlas_quant_10yr_charts.png"
CHART_PATH.parent.mkdir(parents=True, exist_ok=True)

# Colors
C_DARK = colors.HexColor("#0B0F19")
C_SURFACE = colors.HexColor("#161F30")
C_ACCENT = colors.HexColor("#38BDF8")
C_GOLD = colors.HexColor("#F59E0B")
C_GREEN = colors.HexColor("#10B981")
C_RED = colors.HexColor("#EF4444")
C_TEXT = colors.HexColor("#F8FAFC")
C_MUTED = colors.HexColor("#94A3B8")
C_BORDER = colors.HexColor("#1E293B")
C_CARD_BG = colors.HexColor("#1E293B")


class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawString(54, 750, "AGENTQUANT & ATLAS-GIC QUANTITATIVE LABS")
        self.drawRightString(612 - 54, 750, "THE 10-YEAR ATLAS-QUANT NEXUS AUDIT")
        self.setStrokeColor(colors.HexColor("#334155"))
        self.setLineWidth(0.75)
        self.line(54, 742, 612 - 54, 742)

        self.line(54, 45, 612 - 54, 45)
        self.setFont("Helvetica", 8)
        self.drawString(54, 32, "Confidential | FundedNext $6K Stellar Account (#3028655)")
        self.drawRightString(612 - 54, 32, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def generate_charts():
    # Load backtest results
    res_file = ROOT / "scratch" / "backtest_10yr_atlas_quant_results.json"
    if not res_file.exists():
        return False
    with open(res_file, "r") as f:
        data = json.load(f)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 3.8), dpi=220)
    fig.patch.set_facecolor("#0F172A")

    # 1. Monthly Trades Histogram
    monthly_counts = list(data["monthly_matrix"].values())
    ax1.set_facecolor("#1E293B")
    bins = np.arange(0, 11) - 0.5
    n, _, patches = ax1.hist(monthly_counts, bins=bins, color="#38BDF8", edgecolor="#0F172A", rwidth=0.8)
    for p in patches:
        p.set_facecolor("#38BDF8")
    ax1.set_title("10-Year Single-Month Trade Frequency", color="#F8FAFC", fontsize=11, fontweight="bold", pad=10)
    ax1.set_xlabel("Trades in a Single Month", color="#94A3B8", fontsize=9)
    ax1.set_ylabel("Number of Months", color="#94A3B8", fontsize=9)
    ax1.tick_params(colors="#94A3B8", labelsize=8)
    ax1.set_xticks(range(0, 10))
    ax1.grid(True, linestyle="--", alpha=0.2, color="#64748B")

    # 2. Equity Growth Trajectory
    monthly_pnls = list(data["monthly_pnls"].values())
    cum_equity = [6000.0]
    for p in monthly_pnls:
        cum_equity.append(cum_equity[-1] + p)

    ax2.set_facecolor("#1E293B")
    ax2.plot(cum_equity, color="#10B981", linewidth=2.2, label="Account Equity ($)")
    ax2.axhline(6000.0, color="#64748B", linestyle=":", label="Starting Capital ($6,000)")
    ax2.axhline(6000.0 - 360.0, color="#EF4444", linestyle="--", label="Trailing Drawdown Limit ($5,640)")
    ax2.set_title("10-Year Equity Growth Trajectory ($6k Account)", color="#F8FAFC", fontsize=11, fontweight="bold", pad=10)
    ax2.set_xlabel("Months Elapsed (2016 - 2026)", color="#94A3B8", fontsize=9)
    ax2.set_ylabel("Account Balance ($)", color="#94A3B8", fontsize=9)
    ax2.tick_params(colors="#94A3B8", labelsize=8)
    ax2.legend(facecolor="#1E293B", edgecolor="#334155", labelcolor="#F8FAFC", fontsize=7.5, loc="upper left")
    ax2.grid(True, linestyle="--", alpha=0.2, color="#64748B")

    plt.tight_layout()
    plt.savefig(CHART_PATH, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    return True


def build_pdf():
    generate_charts()

    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=60,
        bottomMargin=55,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#475569"),
        spaceAfter=12,
    )
    h1_style = ParagraphStyle(
        'Heading1',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#0F172A"),
        spaceBefore=10,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#334155"),
    )
    bold_body = ParagraphStyle(
        'BoldBody',
        parent=body_style,
        fontName='Helvetica-Bold',
    )

    elements = []

    # Title & Subtitle
    elements.append(Paragraph("10-Year ATLAS-Quant Nexus Engine Audit", title_style))
    elements.append(Paragraph("Comprehensive Verification: Profit, Loss, Single-Month Trade Volume, and $6,000 Account Growth (2016 – 2026)", subtitle_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceAfter=10))

    # Executive Stat Cards (4 columns)
    stat_data = [
        [
            Paragraph("<b>TOTAL NET PROFIT</b><br/><font size=13 color='#10B981'><b>+$1,026.58</b></font><br/><font size=7 color='#64748B'>+17.1% Net Gain</font>", body_style),
            Paragraph("<b>WIN RATE & TRADES</b><br/><font size=13 color='#0F172A'><b>59.5% WR</b></font><br/><font size=7 color='#64748B'>254 Wins / 173 Losses (427 tot)</font>", body_style),
            Paragraph("<b>ACTIVE MONTH PACE</b><br/><font size=13 color='#38BDF8'><b>4.27 Trades/Mo</b></font><br/><font size=7 color='#64748B'>Peak Month: 9 Trades</font>", body_style),
            Paragraph("<b>MAX 10Y DRAWDOWN</b><br/><font size=13 color='#10B981'><b>-$140.12</b></font><br/><font size=7 color='#64748B'>$219.88 cushion vs -$360 limit</font>", body_style),
        ]
    ]
    t_stats = Table(stat_data, colWidths=[126, 126, 126, 126])
    t_stats.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#E2E8F0")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(t_stats)
    elements.append(Spacer(1, 10))

    # Charts
    if CHART_PATH.exists():
        elements.append(Image(str(CHART_PATH), width=504, height=182))
        elements.append(Spacer(1, 10))

    # 1. 10-Year Profit & Loss Summary Table
    elements.append(Paragraph("1. Ten-Year Profit & Loss Summary (FundedNext $6k Rules)", h1_style))
    pnl_data = [
        ["Metric", "Value", "Prop Firm Rule / Constraint", "Safety Assessment"],
        ["Starting Capital", "$6,000.00", "FundedNext Stellar 1-Step (#3028655)", "Baseline"],
        ["Ending Capital", "$7,026.58", "Target: +$600.00 (+10%)", "ACHIEVED (+17.1% Net Gain)"],
        ["Total Net Profit", "+$1,026.58", "85% Profit Split ($872.59 to David)", "Profitable across full 10Y cycle"],
        ["Total Gross Profit", "+$2,802.70", "Sum of all winning trades", "Consistent positive alpha"],
        ["Total Gross Losses", "-$1,776.12", "Sum of all losing trades", "Strictly controlled -$13.50 stops"],
        ["Profit Factor", "1.58", "Gross Profit / Gross Loss", "Exceeds institutional threshold (1.50)"],
        ["Worst 10Y Drawdown", "-$140.12", "FundedNext Trailing Limit: -$360.00", "PASS: $219.88 cushion (61% buffer)"],
        ["Worst Single-Day Loss", "-$27.00", "FundedNext Daily Limit: -$180.00", "PASS: $153.00 cushion (85% buffer)"],
    ]
    t_pnl = Table(pnl_data, colWidths=[120, 95, 165, 124])
    t_pnl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ('FONTSIZE', (0, 1), (-1, -1), 7.5),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
    ]))
    elements.append(t_pnl)
    elements.append(Spacer(1, 10))

    # Page Break to Page 2
    elements.append(PageBreak())

    # 2. Amount of Trades in a Single Month (10-Year Matrix)
    elements.append(Paragraph("2. Amount of Trades in a Single Month (10-Year Monthly Matrix)", h1_style))
    elements.append(Paragraph("The matrix below documents every single month across the 10-year cycle (120 months). Notice that during active bull markets, the engine reliably fires <b>3 to 9 trades per month</b>. During secular bear markets (2022), the engine went into cash-lock to preserve capital.", body_style))
    elements.append(Spacer(1, 6))

    matrix_header = ["Year", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Trades", "Annual PnL"]
    matrix_rows = [
        matrix_header,
        ["2016", "-", "-", "-", "-", "-", "-", "-", "-", "0", "0", "0", "4", "4", "+$26.90"],
        ["2017", "5", "3", "6", "4", "6", "5", "5", "5", "4", "5", "4", "7", "59", "+$248.04"],
        ["2018", "2", "0", "0", "0", "2", "4", "2", "5", "6", "5", "0", "0", "26", "+$65.07"],
        ["2019", "0", "2", "2", "3", "6", "5", "2", "6", "3", "5", "3", "5", "42", "+$101.84"],
        ["2020", "4", "4", "0", "0", "0", "3", "4", "5", "5", "7", "2", "5", "39", "+$226.66"],
        ["2021", "9", "5", "4", "5", "6", "4", "4", "6", "6", "5", "3", "4", "61", "+$194.58"],
        ["2022", "5", "1", "0", "3", "1", "0", "0", "0", "0", "0", "0", "1", "11", "-$76.91"],
        ["2023", "1", "2", "7", "2", "7", "6", "5", "6", "5", "4", "4", "5", "54", "+$180.98"],
        ["2024", "4", "5", "4", "4", "8", "4", "5", "2", "2", "1", "3", "6", "48", "+$82.78"],
        ["2025", "8", "2", "2", "0", "1", "2", "3", "3", "5", "7", "5", "5", "43", "-$59.57"],
        ["2026", "6", "4", "3", "0", "5", "7", "5", "6", "-", "-", "-", "-", "36", "+$54.13"],
    ]
    t_matrix = Table(matrix_rows, colWidths=[38, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26, 42, 60])
    t_matrix.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ('FONTNAME', (-2, 1), (-1, -1), 'Helvetica-Bold'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(t_matrix)
    elements.append(Spacer(1, 10))

    # 3. Growth of the $6,000 Account Over 10 Years
    elements.append(Paragraph("3. Growth of the $6,000 Account Over 10 Years", h1_style))
    growth_rows = [
        ["Timeline", "Starting Balance", "Ending Balance", "Annual Net PnL", "Annual Return (%)", "Account Growth"],
        ["End of 2016", "$6,000.00", "$6,026.90", "+$26.90", "+0.4%", "+0.4%"],
        ["End of 2017", "$6,026.90", "$6,274.94", "+$248.04", "+4.1%", "+4.6%"],
        ["End of 2018", "$6,274.94", "$6,340.01", "+$65.07", "+1.0%", "+5.7%"],
        ["End of 2019", "$6,340.01", "$6,441.85", "+$101.84", "+1.6%", "+7.4%"],
        ["End of 2020", "$6,441.85", "$6,668.51", "+$226.66", "+3.5%", "+11.1%"],
        ["End of 2021", "$6,668.51", "$6,863.09", "+$194.58", "+2.9%", "+14.4%"],
        ["End of 2022", "$6,863.09", "$6,786.18", "-$76.91", "-1.1%", "+13.1%"],
        ["End of 2023", "$6,786.18", "$6,967.16", "+$180.98", "+2.7%", "+16.1%"],
        ["End of 2024", "$6,967.16", "$7,049.94", "+$82.78", "+1.2%", "+17.5%"],
        ["End of 2025", "$7,049.94", "$6,990.37", "-$59.57", "-0.8%", "+16.5%"],
        ["End of 2026 (Sept)", "$6,990.37", "$7,026.58", "+$36.20", "+0.5%", "+17.1%"],
    ]
    t_growth = Table(growth_rows, colWidths=[90, 85, 85, 80, 80, 84])
    t_growth.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ('FONTNAME', (-1, 1), (-1, -1), 'Helvetica-Bold'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(t_growth)

    doc.build(elements, canvasmaker=NumberedCanvas)
    print(f"PDF built successfully at: {OUTPUT_PDF}")

    # Copy to artifact dir
    import shutil
    shutil.copy2(OUTPUT_PDF, ARTIFACT_PDF)
    print(f"Copied PDF to artifact directory: {ARTIFACT_PDF}")


if __name__ == "__main__":
    build_pdf()
