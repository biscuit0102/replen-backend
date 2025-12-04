# ReplenMobile AI Service
# Uses OpenAI GPT-4o Vision to parse Japanese invoice images

import os
import json
import base64
from typing import List, Optional
from openai import AsyncOpenAI
from pydantic import BaseModel

# Lazy initialization of OpenAI client
_client: Optional[AsyncOpenAI] = None

def get_openai_client() -> AsyncOpenAI:
    """Get or create OpenAI client (lazy initialization)."""
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable is not set")
        _client = AsyncOpenAI(api_key=api_key)
    return _client

class ParsedItem(BaseModel):
    """Parsed item from invoice"""
    name: str
    price: int
    product_code: str | None = None
    category: str = "その他"  # AI-guessed category (must be one of 9 standard categories)


# 9 Standard Fixed Categories for Japanese small businesses
# These MUST match the database exactly
STANDARD_CATEGORIES = [
    "お酒",       # 1. Alcohol (beer, sake, wine, shochu, whiskey, etc.)
    "食品",       # 2. Food (seasonings, processed food, canned goods, etc.)
    "野菜・青果", # 3. Vegetables & Produce (cabbage, carrots, onions, fruits, etc.)
    "精肉",       # 4. Meat (beef, pork, chicken, etc.)
    "鮮魚",       # 5. Fresh Fish & Seafood
    "飲料",       # 6. Beverages (juice, tea, water, coffee, soft drinks, etc.)
    "冷凍食品",   # 7. Frozen Foods
    "消耗品",     # 8. Consumables (paper, detergent, wrap, bags, etc.)
    "その他",     # 9. Other (anything that doesn't fit above)
]

SYSTEM_PROMPT = """あなたは日本の請求書や納品書を読み取るAIアシスタントです。

画像から以下の情報を抽出してください：
1. 商品名（日本語）
2. 価格（数字のみ、円記号なし）
3. 商品コード（あれば）
4. カテゴリー（【重要】必ず以下の9つから1つだけ選択）

【9つの固定カテゴリー】※必ずこの中から選んでください
1. お酒: ビール、日本酒、ワイン、焼酎、ウイスキー、チューハイ、酎ハイなど
2. 食品: 調味料、加工食品、缶詰、乾物、お菓子、パン、米など
3. 野菜・青果: キャベツ、にんじん、玉ねぎ、トマト、レタス、果物全般など
4. 精肉: 牛肉、豚肉、鶏肉、ハム、ソーセージ、ベーコンなど
5. 鮮魚: 魚、刺身、貝類、エビ、カニ、イカ、タコ、海産物など
6. 飲料: ジュース、お茶、水、コーヒー、ソフトドリンク、牛乳など
7. 冷凍食品: 冷凍野菜、冷凍肉、冷凍魚、アイス、冷凍総菜など
8. 消耗品: 紙製品、洗剤、ラップ、袋、掃除用品、衛生用品など
9. その他: 上記8つに当てはまらないもの（迷ったらこれを使用）

【厳格なルール】
- カテゴリーは上記9つ以外の名前を使用しないでください
- 不明な場合は「その他」を使用してください
- 新しいカテゴリー名を作成しないでください

注意事項:
- 価格は税込みで記載してください
- 読み取れない項目はスキップしてください
- 数量や単価ではなく、商品ごとの合計金額を抽出してください

必ず以下のJSON形式で返答してください：
[
  {"name": "アサヒスーパードライ", "price": 1000, "product_code": "ABC123", "category": "お酒"},
  {"name": "キャベツ", "price": 500, "product_code": null, "category": "野菜・青果"},
  {"name": "サーモン刺身", "price": 800, "product_code": null, "category": "鮮魚"}
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
        
        client = get_openai_client()
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
                # Validate category is in standard list, default to "その他"
                category = item.get("category", "その他")
                if category not in STANDARD_CATEGORIES:
                    category = "その他"
                
                items.append(ParsedItem(
                    name=item.get("name", "不明"),
                    price=int(item.get("price", 0)),
                    product_code=item.get("product_code"),
                    category=category
                ))
            except (ValueError, TypeError):
                continue
        
        return items
        
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse AI response as JSON: {e}")
    except Exception as e:
        raise RuntimeError(f"AI service error: {e}")
