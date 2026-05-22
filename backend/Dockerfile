# 가벼운 파이썬 3.10 이미지 사용
FROM python:3.10-slim

WORKDIR /app

# 기본 시스템 빌드 패키지 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 파이썬 라이브러리 목록 복사 및 설치
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 백엔드 서버가 실행될 때의 명령어를 설정
# 실제 파이썬 서버 코드가 작성되면 CMD를 알맞게 수정해 주세요.
CMD ["tail", "-f", "/dev/null"]
