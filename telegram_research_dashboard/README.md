# 공개 Telegram 리서치 대시보드

공개 채널의 과거 글을 Telegram API로 읽어 SQLite에 저장하고, 보고서와 뉴스를 탐색하는 로컬 대시보드입니다.

## 현재 구현 범위

- 공개 채널 전체 기록 또는 최근 N개 동기화
- `(channel_id, message_id)` 기준 중복 방지 및 수정 글 갱신
- 원본 텍스트 보존
- 보고서/뉴스/미분류 규칙 기반 1차 판별
- 기업분석/산업분석 구분 및 한 자료와 여러 기업의 다대다 연결
- 위클리 244건을 다올선박·한투시절·하이투자증권시절 폴더로 분리
- 기업명, 목표주가, 이전 목표주가, TP 방향, URL, 이벤트 유형 추출
- 요약 카드, 보고서 유형 필터, 2016~2026 연도 접기·월별 뉴스 아카이브, 기업/통합 검색
- 신뢰도가 낮은 항목에 `검토 필요` 표시

대시보드는 외부 주소가 아니라 `127.0.0.1`에만 열립니다.

## 여러 PC와 Mac에서 보는 독립 HTML

프로젝트 상위 폴더의 `GS_최광식_리서치_대시보드.html`은 서버 없이 실행되는 단일 파일입니다. CSS, JavaScript, 보고서 613건과 뉴스 6,330건이 모두 파일 안에 포함됩니다.

- OneDrive 동기화가 끝난 뒤 집 PC, 회사 PC, Mac에서 파일을 더블클릭합니다.
- Chrome, Edge, Safari 등 현대적인 브라우저에서 사용할 수 있습니다.
- 최신 글을 반영하려면 Windows PC에서 상위 폴더의 `업데이트_대시보드.ps1`을 실행합니다.
- 갱신 스크립트는 최신 Telegram 글을 받은 뒤 같은 HTML 파일을 다시 만들며, OneDrive가 다른 기기로 전달합니다.
- 화면 우측 상단의 `최종 업데이트`에서 HTML 생성 시각을 확인할 수 있습니다.

직접 다시 만들려면 다음을 실행합니다.

```powershell
python build_static.py
```

## 1. Telegram API 준비

1. <https://my.telegram.org>에 로그인합니다.
2. **API development tools**에서 앱을 하나 만들고 `api_id`, `api_hash`를 받습니다.
3. `.env.example`을 `.env`로 복사해 값을 입력합니다.

```env
TELEGRAM_API_ID=숫자_API_ID
TELEGRAM_API_HASH=비밀_API_HASH
TELEGRAM_CHANNEL=@공개채널아이디
TELEGRAM_SESSION_PATH=data/telegram_user
DATABASE_PATH=data/dashboard.db
```

`TELEGRAM_CHANNEL`에는 `@채널아이디` 또는 `https://t.me/채널아이디`를 사용할 수 있습니다. `api_hash`, 로그인 코드, 생성된 `.session` 파일은 공유하거나 Git에 올리지 마세요. `.gitignore`에서 모두 제외합니다. 공개 채널을 읽기 위해 채널 관리자 권한이나 봇 추가는 필요하지 않습니다.

## 2. 설치 및 첫 동기화

Python 3.11 이상을 설치한 후 이 폴더에서 실행합니다.

### 간편 방식: 공개 웹 미리보기

별도 Telegram 로그인 없이 최근 5페이지를 수집합니다. 외부 패키지도 필요하지 않습니다.

```powershell
python public_importer.py --pages 5
```

과거 페이지를 가능한 범위까지 수집하려면 `--pages 0`을 사용합니다. 이 방식은 Telegram 웹 HTML 구조가 바뀌면 수집기를 조정해야 합니다.

### 안정적인 방식: Telegram API

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python telegram_importer.py --limit 100
```

첫 실행 때 Telegram 전화번호, 앱으로 전송된 로그인 코드, 계정에 설정된 경우 2단계 인증 암호를 터미널에서 묻습니다. 테스트가 끝나면 전체 기록을 동기화합니다.

```powershell
python telegram_importer.py
```

## 3. 대시보드 실행

```powershell
python app.py
```

브라우저에서 <http://127.0.0.1:8765>를 엽니다.

실제 채널 연결 전 UI만 확인하려면 다음을 실행합니다.

```powershell
python seed.py
python app.py
```

## 테스트

```powershell
python -m unittest discover -s tests -v
```

## 다음 단계

- 실제 채널 문장 형식에 맞춘 증권사/애널리스트/산업 파싱 개선
- 미분류함에서 추출 결과를 직접 수정하는 편집 API
- 첨부 PDF 메타데이터 수집
- 주간 중복 기사 묶기와 기업 상세 타임라인
- 작업 스케줄러를 통한 자동 증분 동기화
