import os
from sqlalchemy.orm import Session
import google.generativeai as genai
from db.models import Book

# 환경변수에서 GEMINI_API_KEY를 읽어와 설정합니다.
# .env 파일에 GEMINI_API_KEY=AIza... 가 설정되어 있어야 합니다.
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

def get_ai_response(user_message: str, db: Session) -> str:
    """
    데이터베이스에서 전체 도서 정보를 읽어와 LLM 컨텍스트에 주입한 뒤,
    사용자의 질문에 대한 답변을 생성합니다.
    """
    # 1. DB에서 전체 도서 정보 가져오기 (가벼운 쿼리)
    books = db.query(Book).filter(Book.status == "AVAILABLE").all()
    
    # 2. 도서 목록을 읽기 좋은 텍스트(Markdown 형식)로 조립하기
    book_list_text = ""
    for idx, book in enumerate(books, 1):
        book_list_text += f"{idx}. 제목: {book.title}\n"
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

[우리 도서관 보유 도서 목록]
{book_list_text}
"""

    # 4. Gemini API 호출 (Full Context Injection)
    try:
        # system_instruction을 지원하는 gemini-1.5-flash 모델 사용
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=system_prompt
        )
        
        response = model.generate_content(
            user_message,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                max_output_tokens=500,
            )
        )
        return response.text
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return "죄송합니다. 현재 AI 사서 서비스가 원활하지 않습니다. 잠시 후 다시 시도해 주세요."
