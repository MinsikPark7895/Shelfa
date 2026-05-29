import httpx
from core.config import settings

async def search_book_from_aladin(query: str):
    """
    알라딘 API에서 책 제목이나 ISBN으로 도서 정보를 검색합니다.
    (비동기 HTTP 요청 사용)
    """
    url = "http://www.aladin.co.kr/ttb/api/ItemSearch.aspx"
    params = {
        "ttbkey": settings.ALADIN_TTB_KEY,
        "Query": query,
        "QueryType": "Keyword",
        "MaxResults": 1,
        "start": 1,
        "SearchTarget": "Book",
        "output": "js", # JSON 형식 응답
        "Version": "20131101"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            if data.get("item"):
                return data["item"][0] # 첫 번째 검색 결과 반환
        return None
