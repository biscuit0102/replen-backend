# ReplenMobile AI Service
# Uses OpenAI GPT-4o Vision to parse Japanese invoice images

import os
import json
import base64
from typing import List
from openai import AsyncOpenAI
from pydantic import BaseModel

# Initialize OpenAI client
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class ParsedItem(BaseModel):
    """Parsed item from invoice"""
    name: str
    price: int
    product_code: str | None = None


SYSTEM_PROMPT = """あなたは日本の請求書や納品書を読み取るAIアシスタントです。

画像から以下の情報を抽出してください：
1. 商品名（日本語）
2. 価格（数字のみ、円記号なし）
3. 商品コード（あれば）

注意事項:
- 価格は税込みで記載してください
- 読み取れない項目はスキップしてください
- 数量や単価ではなく、商品ごとの合計金額を抽出してください

必ず以下のJSON形式で返答してください：
[
  {"name": "商品名", "price": 1000, "product_code": "ABC123"},
  {"name": "別の商品", "price": 500, "product_code": null}
]

JSON以外のテキストは含めないでください。"""


async def parse_invoice(base64_image: str) -> List[ParsedItem]:
    """
    Parse a Japanese invoice image using GPT-4o Vision.
    
    Args:
        base64_image: Base64 encoded image string
        
    Returns:
        List of parsed items with name, price, and product_code
    """
    try:
        # Ensure proper base64 data URL format
        if not base64_image.startswith("data:"):
            # Detect image type (default to jpeg)
            base64_image = f"data:image/jpeg;base64,{base64_image}"
        
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": base64_image,
                                "detail": "high"
                            }
                        },
                        {
                            "type": "text",
                            "text": "この請求書から商品名と価格を抽出してJSON形式で返してください。"
                        }
                    ]
                }
            ],
            max_tokens=2000,
            temperature=0.1  # Low temperature for more consistent parsing
        )
        
        # Extract JSON from response
        content = response.choices[0].message.content.strip()
        
        # Remove markdown code blocks if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        
        # Parse JSON
        items_data = json.loads(content)
        
        # Convert to ParsedItem objects
        items = []
        for item in items_data:
            try:
                items.append(ParsedItem(
                    name=item.get("name", "不明"),
                    price=int(item.get("price", 0)),
                    product_code=item.get("product_code")
                ))
            except (ValueError, TypeError):
                continue
        
        return items
        
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse AI response as JSON: {e}")
    except Exception as e:
        raise RuntimeError(f"AI service error: {e}")
