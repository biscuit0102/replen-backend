from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import os

VERMILION = '#ea3323'
CANVAS_SIZE = 300
BORDER_WIDTH = 10

# Use absolute path for font (same as fax_service.py)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_PATH = os.path.join(BASE_DIR, "fonts", "ipaexg.ttf")


def create_hanko_image(text: str) -> BytesIO:
    """
    Generate a traditional Japanese company seal (hanko/inkan) image.
    
    Args:
        text: 1-4 Japanese characters (company name, family name, etc.)
        
    Returns:
        BytesIO containing PNG image data with transparent background
    """
    # Create transparent RGBA canvas
    img = Image.new('RGBA', (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw thick circular border
    draw.ellipse(
        [
            (BORDER_WIDTH // 2, BORDER_WIDTH // 2),
            (CANVAS_SIZE - BORDER_WIDTH // 2, CANVAS_SIZE - BORDER_WIDTH // 2)
        ],
        outline=VERMILION,
        width=BORDER_WIDTH
    )

    # Load font with appropriate size based on text length
    text = text.strip()[:4]  # Max 4 chars
    
    if len(text) == 1:
        font_size = 160
    elif len(text) == 2:
        font_size = 110
    else:
        font_size = 90
    
    try:
        font = ImageFont.truetype(FONT_PATH, size=font_size)
        print(f"SUCCESS: Hanko font loaded from {FONT_PATH}")
    except Exception as e:
        print(f"WARNING: Could not load font: {e}")
        font = ImageFont.load_default()

    fill = VERMILION
    center = CANVAS_SIZE // 2

    # Layout logic based on character count
    if len(text) == 1:
        # Single character - center it
        bbox = draw.textbbox((0, 0), text, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = center - w // 2
        y = center - h // 2 - bbox[1]  # Adjust for font baseline
        draw.text((x, y), text, font=font, fill=fill)
        
    elif len(text) == 2:
        # Two characters - stack vertically (traditional: top to bottom)
        spacing = font_size * 0.1
        
        bbox0 = draw.textbbox((0, 0), text[0], font=font)
        bbox1 = draw.textbbox((0, 0), text[1], font=font)
        
        h0 = bbox0[3] - bbox0[1]
        h1 = bbox1[3] - bbox1[1]
        total_h = h0 + spacing + h1
        
        # First character (top)
        w0 = bbox0[2] - bbox0[0]
        x0 = center - w0 // 2
        y0 = center - total_h // 2 - bbox0[1]
        draw.text((x0, y0), text[0], font=font, fill=fill)
        
        # Second character (bottom)
        w1 = bbox1[2] - bbox1[0]
        x1 = center - w1 // 2
        y1 = y0 + h0 + spacing
        draw.text((x1, y1), text[1], font=font, fill=fill)
        
    elif len(text) == 3:
        # Three characters - 2 on top, 1 on bottom (right-to-left reading)
        spacing_h = font_size * 0.05
        spacing_v = font_size * 0.1
        
        # Top row: chars 0,1 (right to left means 0 on right, 1 on left)
        bbox0 = draw.textbbox((0, 0), text[0], font=font)
        bbox1 = draw.textbbox((0, 0), text[1], font=font)
        bbox2 = draw.textbbox((0, 0), text[2], font=font)
        
        w0, h0 = bbox0[2] - bbox0[0], bbox0[3] - bbox0[1]
        w1, h1 = bbox1[2] - bbox1[0], bbox1[3] - bbox1[1]
        w2, h2 = bbox2[2] - bbox2[0], bbox2[3] - bbox2[1]
        
        row_width = w0 + spacing_h + w1
        total_h = max(h0, h1) + spacing_v + h2
        
        # Top row
        y_top = center - total_h // 2
        x0 = center + spacing_h // 2
        x1 = center - w1 - spacing_h // 2
        draw.text((x0, y_top - bbox0[1]), text[0], font=font, fill=fill)
        draw.text((x1, y_top - bbox1[1]), text[1], font=font, fill=fill)
        
        # Bottom row (centered)
        y_bottom = y_top + max(h0, h1) + spacing_v
        x2 = center - w2 // 2
        draw.text((x2, y_bottom - bbox2[1]), text[2], font=font, fill=fill)
        
    else:  # 4 characters
        # Four characters - 2x2 grid (Japanese reading: right-to-left, top-to-bottom)
        # Layout: [0][1]  (top row, 0 on right, 1 on left)
        #         [2][3]  (bottom row, 2 on right, 3 on left)
        spacing_h = font_size * 0.05
        spacing_v = font_size * 0.1
        
        bboxes = [draw.textbbox((0, 0), c, font=font) for c in text]
        sizes = [(b[2] - b[0], b[3] - b[1]) for b in bboxes]
        
        max_w = max(s[0] for s in sizes)
        max_h = max(s[1] for s in sizes)
        
        total_w = max_w * 2 + spacing_h
        total_h = max_h * 2 + spacing_v
        
        start_x = center - total_w // 2
        start_y = center - total_h // 2
        
        positions = [
            (start_x + max_w + spacing_h, start_y),  # 0: top-right
            (start_x, start_y),                       # 1: top-left
            (start_x + max_w + spacing_h, start_y + max_h + spacing_v),  # 2: bottom-right
            (start_x, start_y + max_h + spacing_v),   # 3: bottom-left
        ]
        
        for i, char in enumerate(text):
            x, y = positions[i]
            # Center each character in its cell
            w, h = sizes[i]
            offset_x = (max_w - w) // 2
            offset_y = -bboxes[i][1]
            draw.text((x + offset_x, y + offset_y), char, font=font, fill=fill)

    # Output as PNG bytes
    output = BytesIO()
    img.save(output, format='PNG', optimize=True)
    output.seek(0)
    return output
