# utils/text_parser.py
import re
from dataclasses import dataclass


@dataclass
class RichTextSegment:
    text: str
    is_bold: bool = False


def parse_markdown_style(text: str) -> list[RichTextSegment]:
    parts = re.split(r"\*\*(.*?)\*\*", text)
    segments = []
    for i, part in enumerate(parts):
        if not part:
            continue
        # 奇数索引为加粗内容
        is_bold = i % 2 == 1
        segments.append(RichTextSegment(text=part, is_bold=is_bold))
    return segments
