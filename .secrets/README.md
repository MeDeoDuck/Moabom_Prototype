# .secrets/

로컬 전용 비밀 파일 보관. **절대 git에 올리지 말 것.** 이 폴더 자체는 `.gitignore`로
모든 파일이 ignore되고, 이 README만 예외로 트래킹됩니다.

## 현재 사용 중인 파일

| 파일명 | 용도 | 만료 | 갱신 방법 |
|---|---|---|---|
| `yt_cookies.txt` | YouTube 자막/메타데이터 fetch 시 yt-dlp/requests에 주입할 인증 쿠키 (Netscape format) | 보통 2주~1달 | Chrome 확장 "Get cookies.txt LOCALLY"로 youtube.com 도메인 cookie 재export |

## 추출 방법 (yt_cookies.txt)

1. Chrome에서 모아봄 전용 구글 계정으로 youtube.com 로그인
2. Chrome 웹스토어에서 **Get cookies.txt LOCALLY** 설치
3. youtube.com 탭에서 확장 클릭 → **Export → Netscape format** → 다운로드
4. 받은 파일을 이 폴더에 `yt_cookies.txt` 이름으로 저장

## 운영 시

- 로컬 개발: 이 파일을 직접 사용
- Azure 배포: `base64 -w0 yt_cookies.txt`를 Container Apps Secret으로 주입,
  컨테이너 시작 시 디코딩하여 임시 파일로 복원 (구체 경로는 `transcript_service.py` 참고)
