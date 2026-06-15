import json
import os
from sqlalchemy.orm import Session
import google.generativeai as genai
from db.models import Book

# 환경변수에서 GEMINI_API_KEY를 읽어와 설정합니다.
# .env 파일에 GEMINI_API_KEY=AIza... 가 설정되어 있어야 합니다.
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

def get_ai_response(user_message: str, db: Session) -> dict:
    """
    데이터베이스에서 전체 도서 정보를 읽어와 LLM 컨텍스트에 주입한 뒤,
    사용자의 질문에 대한 답변을 생성합니다.
    """
    # 1. DB에서 전체 도서 정보 가져오기 (가벼운 쿼리)
    books = db.query(Book).filter(Book.status == "AVAILABLE").all()
    
    # 2. 도서 목록을 읽기 좋은 텍스트(Markdown 형식)로 조립하기
    book_list_text = ""
    for idx, book in enumerate(books, 1):
        book_list_text += f"{idx}. 제목: {book.title} (ID: {book.id})\n"
        book_list_text += f"   - 저자: {book.author}\n"
        book_list_text += f"   - 책장 위치: {book.shelf_location}\n"
        if book.description:
            book_list_text += f"   - 줄거리 요약: {book.description[:200]}...\n"
        else:
            book_list_text += "   - 줄거리 요약: 정보 없음\n"
        book_list_text += "\n"
        
    # 만약 책이 하나도 없다면 예외 처리
    if not books:
        book_list_text = "현재 대출 가능한 도서가 없습니다."

    # 3. 강력한 시스템 프롬프트 구성 (가스라이팅)
    system_prompt = f"""당신은 'Shelfa 도서관'의 친절하고 지적인 AI 사서입니다.
사용자의 질문에 답변할 때, **반드시 아래 제공된 [우리 도서관 보유 도서 목록] 안에서만** 책을 찾아 추천하거나 답변해야 합니다.
도서 목록에 없는 책을 지어내거나 외부 지식으로 추천하는 것(Hallucination)은 절대 금지합니다.
답변은 항상 존댓말로 친절하게 작성하며, 책을 추천할 때는 반드시 해당 책이 꽂혀 있는 '책장 위치(예: ZONE_1)'를 함께 안내해 주세요.

당신은 반드시 아래의 JSON 포맷으로만 응답해야 합니다. 다른 부가적인 텍스트는 허용되지 않습니다.
{{
  "reply": "사용자에게 할 친절한 답변 텍스트 (마크다운 없이 일반 텍스트로 작성)",
  "recommended_book_id": "추천하는 책의 ID (목록에 있는 책을 추천할 경우 해당 책의 ID값, 추천할 책이 없거나 일반 대화일 경우 null)",
  "recommended_book_title": "추천하는 책의 제목 (추천할 책이 없거나 일반 대화일 경우 null)"
}}

[우리 도서관 보유 도서 목록]
{book_list_text}
"""

    # 4. Gemini API 호출 (Full Context Injection)
    try:
        # system_instruction을 지원하는 gemini-3.5-flash 모델 사용
        model = genai.GenerativeModel(
            model_name="gemini-3.5-flash",
            system_instruction=system_prompt
        )
        
        response = model.generate_content(
            user_message,
            generation_config=genai.types.GenerationConfig(
                temperature=0.4,
            ),
            stream=False
        )
        
        # Markdown 백틱이 섞여 나올 경우를 대비해 전처리 후 파싱
        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
            
        try:
            return json.loads(raw_text.strip(), strict=False)
        except Exception as e:
            print(f"JSON Parse Error: {e}")
            raise e

    except Exception as e:
        print(f"Gemini API Error: {e}")
        return {
            "reply": "죄송합니다. 현재 AI 사서 서비스가 원활하지 않습니다. 잠시 후 다시 시도해 주세요.",
            "recommended_book_id": None,
            "recommended_book_title": None
        }
