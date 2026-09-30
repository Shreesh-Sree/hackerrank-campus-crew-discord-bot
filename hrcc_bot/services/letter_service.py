"""
HackerRank Campus Crew - Letter Generation Service
Handles:
1. Offer Letters (Campus Ambassador induction)
2. Permission Letters (Institutional NOC / College permissions)
"""
from __future__ import annotations

import os
import sys
import time
import logging
from datetime import datetime
import fitz

log = logging.getLogger("hrcc.letter_service")

OFFER_TEMPLATE_PATH = "/data/production/offer-letter-automation/perfect_template.pdf"
FONT_REGULAR = "/data/production/offer-letter-automation/fonts_satoshi/Satoshi_Complete/Fonts/OTF/Satoshi-Regular.otf"
FONT_BOLD = "/data/production/offer-letter-automation/fonts_satoshi/Satoshi_Complete/Fonts/OTF/Satoshi-Bold.otf"

def generate_offer_letter_pdf(
    name: str,
    college: str,
    date_str: str | None = None,
    output_pdf: str = "/tmp/offer_letter.pdf"
) -> str:
    """Generates an official HackerRank Campus Crew Offer Letter PDF."""
    if not date_str:
        date_str = datetime.now().strftime("%d %B, %Y")
    
    doc = fitz.open(OFFER_TEMPLATE_PATH)
    page = doc[0]
    
    page.insert_font(fontname="SatoshiRegular", fontfile=FONT_REGULAR)
    font_measurer = fitz.Font(fontfile=FONT_REGULAR)
    
    # 1. Date
    date_text = f"Date : {date_str}"
    page.insert_text(fitz.Point(116.6, 137.0), date_text, fontname="SatoshiRegular", fontsize=12, color=(0, 0, 0))
    
    # 2. To recipient name
    page.insert_text(fitz.Point(116.3, 172.0), name, fontname="SatoshiRegular", fontsize=12, color=(0, 0, 0))
    
    # 3. Dear greeting
    dear_text = f"Dear {name},"
    page.insert_text(fitz.Point(116.3, 223.0), dear_text, fontname="SatoshiRegular", fontsize=12, color=(0, 0, 0))
    
    # 4. College line
    college_clean = college.strip().rstrip('.')
    college_line = f"at {college_clean}."
    
    max_x = 479.1
    start_x = 116.3
    allowed_width = max_x - start_x
    
    font_size = 12.0
    text_width = font_measurer.text_length(college_line, fontsize=font_size)
    if text_width > allowed_width:
        if text_width <= allowed_width * 1.2:
            font_size = (allowed_width / text_width) * 12.0
            page.insert_text(fitz.Point(start_x, 280.0), college_line, fontname="SatoshiRegular", fontsize=font_size, color=(0, 0, 0))
        else:
            words = college_line.split()
            line1_words = []
            line2_words = []
            cur_line = ""
            for w in words:
                test_line = f"{cur_line} {w}".strip()
                if font_measurer.text_length(test_line, fontsize=11.0) <= allowed_width and not line2_words:
                    cur_line = test_line
                else:
                    line2_words.append(w)
            line1 = cur_line
            line2 = " ".join(line2_words)
            page.insert_text(fitz.Point(start_x, 276.0), line1, fontname="SatoshiRegular", fontsize=10.5, color=(0, 0, 0))
            page.insert_text(fitz.Point(start_x, 288.0), line2, fontname="SatoshiRegular", fontsize=10.5, color=(0, 0, 0))
    else:
        page.insert_text(fitz.Point(start_x, 280.0), college_line, fontname="SatoshiRegular", fontsize=12.0, color=(0, 0, 0))
    
    doc.save(output_pdf)
    return output_pdf

def generate_permission_letter_pdf(
    ambassador_name: str,
    college_name: str,
    event_name: str,
    event_date: str,
    output_pdf: str = "/tmp/permission_letter.pdf"
) -> str:
    """
    Generates an official HackerRank Campus Crew Permission / NOC Letter PDF
    on the official letterhead.
    """
    doc = fitz.open(OFFER_TEMPLATE_PATH)
    page = doc[0]
    
    # Redact offer-letter specific body text (from y=130 to y=620)
    # The background beneath is the smooth gradient image, so we overlay a clean white/clean card
    page.insert_font(fontname="SatoshiRegular", fontfile=FONT_REGULAR)
    page.insert_font(fontname="SatoshiBold", fontfile=FONT_BOLD)
    font_measurer = fitz.Font(fontfile=FONT_REGULAR)
    
    # White card background over body area for crisp readability
    body_rect = fitz.Rect(108.0, 110.0, 488.0, 620.0)
    page.draw_rect(body_rect, color=None, fill=(0.98, 0.99, 0.99))
    
    today_str = datetime.now().strftime("%d %B, %Y")
    
    # 1. Date
    page.insert_text(fitz.Point(116.0, 135.0), f"Date : {today_str}", fontname="SatoshiRegular", fontsize=11, color=(0, 0, 0))
    
    # 2. To The Principal / Head of Department
    page.insert_text(fitz.Point(116.0, 160.0), "To,", fontname="SatoshiBold", fontsize=11, color=(0, 0, 0))
    page.insert_text(fitz.Point(116.0, 175.0), "The Principal / Head of Department,", fontname="SatoshiRegular", fontsize=11, color=(0, 0, 0))
    page.insert_text(fitz.Point(116.0, 190.0), f"{college_name.strip()}", fontname="SatoshiRegular", fontsize=11, color=(0, 0, 0))
    
    # 3. Subject
    page.insert_text(fitz.Point(116.0, 220.0), f"Subject: Permission for Conducting {event_name.strip()}", fontname="SatoshiBold", fontsize=11.5, color=(0, 0, 0))
    
    # 4. Body
    page.insert_text(fitz.Point(116.0, 245.0), "Respected Sir / Madam,", fontname="SatoshiRegular", fontsize=11, color=(0, 0, 0))
    
    p1 = (
        f"We are writing on behalf of HackerRank regarding the HackerRank Campus Crew "
        f"initiative at your esteemed institution. Our appointed Campus Ambassador, "
        f"{ambassador_name.strip()}, is organizing \"{event_name.strip()}\" scheduled on "
        f"{event_date.strip()}."
    )
    
    p2 = (
        "The objective of this initiative is to foster technical problem-solving skills, coding proficiency, "
        "and developer awareness among students using official HackerRank platforms and assessments."
    )
    
    p3 = (
        "We kindly request your approval and institutional support to facilitate the venue, computer labs, "
        "and student participation for the smooth conduct of this event."
    )
    
    p4 = "Thank you for your continuous support in empowering young developers."
    
    # Helper to insert wrapped paragraphs
    def insert_para(text: str, start_y: float, font_size: float = 10.5, line_height: float = 14.0) -> float:
        words = text.split()
        lines = []
        cur = ""
        for w in words:
            test = f"{cur} {w}".strip()
            if font_measurer.text_length(test, fontsize=font_size) <= 360.0:
                cur = test
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        
        y = start_y
        for l in lines:
            page.insert_text(fitz.Point(116.0, y), l, fontname="SatoshiRegular", fontsize=font_size, color=(0, 0, 0))
            y += line_height
        return y
    
    y = 265.0
    y = insert_para(p1, y) + 8.0
    y = insert_para(p2, y) + 8.0
    y = insert_para(p3, y) + 8.0
    y = insert_para(p4, y) + 12.0
    
    # Sign-off line
    page.insert_text(fitz.Point(116.0, y), "Yours sincerely,", fontname="SatoshiRegular", fontsize=10.5, color=(0, 0, 0))
    
    doc.save(output_pdf)
    return output_pdf

if __name__ == '__main__':
    p_pdf = generate_permission_letter_pdf(
        "Rohan Gupta",
        "National Institute of Technology Karnataka",
        "CodeSprint 2026 Hackathon",
        "15 October, 2026",
        "/tmp/test_permission_letter.pdf"
    )
    print(f"Generated test permission letter: {p_pdf}")
