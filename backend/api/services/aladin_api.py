import httpx
from core.config import settings

async def search_book_from_aladin(query: str):
    """
    알라딘 API에서 책 제목이나 ISBN으로 도서 정보를 검색합니다.
    (비동기 HTTP 요청 사용)
    """
    url = "https://www.aladin.co.kr/ttb/api/ItemSearch.aspx"
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

async def search_book_by_isbn(isbn: str):
    """
    알라딘 API에서 ISBN으로 정확한 도서 정보 1건을 조회합니다.
    (바코드 연동 대량 입고용)
    """
    url = "https://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
    params = {
        "ttbkey": settings.ALADIN_TTB_KEY,
        "itemIdType": "ISBN13",
        "ItemId": isbn,
        "output": "js",
        "Version": "20131101",
        "OptResult": "fulldescription"
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                if data.get("item"):
                    return data["item"][0]
            print(f"[Aladin] ISBN {isbn} 조회 실패 - status: {response.status_code}, body: {response.text[:200]}")
            return None
    except Exception as e:
        print(f"[Aladin] ISBN {isbn} 요청 에러: {e}")
        return None

