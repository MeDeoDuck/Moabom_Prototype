# 자막 fetch 안정화 — 심층 조사 보고서

> 작성 2026-06-27 · deep-research 워크플로우(서브에이전트 104, 소스 22, 검증 통과 16/반증 9)
> 목적: 제3자 유튜브 영상 자막을 IP/ASN 차단·rate-limit 없이 안정적으로 대량 수집하는 방법과 비용 비교.
> 대상 독자: 모아봄 팀(레지덴셜 워커 + Azure, 쿠키풀·키풀 이미 구현).

---

## 0. TL;DR (핵심 결론 5줄)

1. **근본 원인은 "요청량"이 아니라 YouTube의 PO Token(attestation) 체제다.** PO Token이 없으면 yt-dlp 공식 문서가 *"계정 또는 IP가 차단될 수 있다"* 고 명시 — 이게 F2(몇 시간 IP 밴)의 정체.
2. **희소식: 모아봄이 쓰는 원어 ko/en 자막은 429 rate-limit의 직접 대상이 아니다.** yt-dlp 메인테이너가 *"수동 자막과 원어 자동자막은 이 429 이슈의 영향을 받지 않는다"* 고 명시. 즉 우리는 이미 비교적 안전한 경로를 타고 있다(F1 노출이 작음).
3. **PO Token 플러그인은 "예방책"이지 "치료제"가 아니다.** 이미 밴된 IP를 복구하진 못함(공식 문서가 직접 인정). 트래픽을 정상처럼 보이게 해서 *밴 확률을 낮추는* 용도.
4. **F2(IP 밴)의 진짜 레버는 딱 둘 — ① IP 다양성(프록시/추가 회선) ② 차단 외주화(관리형 자막 API).** 그리고 timedtext 페이로드가 작아서 **프록시 비용이 의외로 싸다(월 $3~30 추정).**
5. **ASR(오디오+음성모델)은 F2를 못 푼다(유현님 직관 맞음).** 오디오 다운로드도 같은 player API(extract_info)를 거쳐 같은 IP로 나가므로, IP가 밴되면 오디오도 같이 막힘. ASR의 유일한 고유 가치는 "자막이 아예 없는 영상" 커버뿐(F1의 일부).

---

## 1. 문제 재정의 — 차단은 두 종류 (F1 / F2)

| | **F1. timedtext rate-limit / 무자막** | **F2. IP·ASN 통째 밴** |
|---|---|---|
| 증상 | `extract_info`는 되는데 caption URL이 429/빈값, 혹은 자막 자체가 없음 | `extract_info` 자체가 `Sign in to confirm you are not a bot`으로 죽음 (몇 시간 지속) |
| 메커니즘 | timedtext rate-limit. **단 원어 ko/en은 영향 작음** | PO Token attestation 실패 → IP/계정 차단 |
| 쿠키 회전으로? | 부분 도움 | ❌ 무용(같은 IP) |
| ASR로? | △ 무자막만 커버 | ❌ 오디오도 같이 막힘 |
| **진짜 처방** | 페이싱 + 쿠키 위생 + (무자막은 ASR) | **IP 다양성** 또는 **차단 외주화** + PO Token으로 예방 |

유현님이 겪는 *"몇 개 받다 보면 몇 시간 차단"* 은 **F2**다. 그리고 F2는 "요청을 줄이면 되는" 문제라기보다 **PO Token 없는 트래픽이 봇으로 플래그되는** 문제다.

---

## 2. 근본 원인 — PO Token 체제 (검증 완료, confidence: high)

- yt-dlp 공식 위키 원문: *"Without it, requests for the affected clients' format URLs may return HTTP Error 403, or **result in your account or IP address being blocked.**"* — [PO-Token-Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide)
- PO Token은 Web=BotGuard / Android=DroidGuard / iOS=iOSGuard 같은 **attestation 엔진**이 "진짜 클라이언트에서 온 요청"임을 증명해 생성. 이게 `not a bot` 봇탐지 계층의 핵심.
- **자막(Subs)도 PO Token use case에 포함**됨(커밋 `32ed5f1` "Add PO token support for subtitles #13234"). 단 위 #2 finding대로 **원어 자막은 429 비대상**.
- **플러그인 한계(중요):** `bgutil-ytdlp-pot-provider` 공식 문서가 직접 — *"Providing a PO token does **not guarantee** bypassing 403 errors or bot checks, but it _may_ help your traffic seem more legitimate."* → **예방용. 밴 복구 불가.**
  - 검증에서 "bgutil이 정확히 F2(IP 플래그)를 타깃해 해결한다"는 더 강한 주장은 **0-3 반증**.
- 데이터센터 IP는 ASN 대역이 공개돼 *"첫 바이트 읽기 전에"* 봇으로 분류 → Azure 직결이 첫 호출부터 막히는 이유(우리 운영 경험과 정확히 일치, confidence: high). 레지덴셜 성공률 85~99% vs 데이터센터 20~40%(벤더 집계).

---

## 3. 방법별 카드 (효과 F1/F2 · 비용 · 운영부담 · 모아봄 난이도)

> 비용은 **2026년 현재가**. 프록시는 GB 단가만 확정됐고 모아봄 transcript당 대역폭은 미측정이라 **월비용은 추정**(★표시).

### A. 자체 인프라 강화 (0원) — 예방 중심
- **A-1 셀프 페이싱(동시성↓·지터·token bucket):** F2 *빈도* 감소. 비용 0. 난이도 낮음. ⚠️ 임계 수치는 이번 조사서 미확정(open).
- **A-2 PO Token provider 통합(bgutl plugin):** 트래픽을 정상화 → F2 *확률* 감소. 비용 0(자체 호스팅). 난이도 중. **밴 복구는 안 됨.**
- **A-3 쿠키 위생/자동 갱신:** 쿠키 만료(2주~1달) 대응. F1·F2 모두 마진↑. 비용 0. ⚠️ 구체 전략 이번 조사서 미확정(open).
- **A-4 원어 ko/en 유지:** 이미 함. auto-translated보다 429 노출 작음. **공짜 안전마진.**
- 효과: **F1 ◎ / F2 △(예방만)**

### B. IP 다양성 (저비용) — F2 직접 처방
- **작동:** 워커가 레지덴셜/모바일/ISP 프록시 풀로 출구 IP를 회전 → 한 IP 밴돼도 다른 IP로 계속.
- **핵심 장점:** timedtext 페이로드가 작아(요청당 수백 KB~1MB) **pay-per-GB 프록시가 싸다.**
- **비용(★추정, ~0.5–1MB/건 가정):**
  - 레지덴셜 $1/GB(DataImpulse): 일200 ≈ **$3~6/월**, 일1000 ≈ **$15~30/월**
  - 모바일 $2~3.6/GB: 위의 2~3.6배
  - ISP static residential: **IP당 월 $1.5~5 정액** → 몇 개면 월 $5~25, 고볼륨일수록 유리
- 효과: **F1 ○ / F2 ◎** · 운영부담 중(프록시 연동·헬스체크) · 모아봄 난이도 중(워커에 proxy rotation 추가)

### C. 관리형 자막 API (유료 백스톱) — 차단 외주화
- **C-1 Apify YouTube Transcript Scraper:** transcript당 **$0.0005(~$0.5/1k)**. 일200 ≈ **$3/월**, 일1000 ≈ **$15/월**(+플랫폼 구독 별도, free $5 크레딧). 제3자 영상 지원 확인. ⚠️ "내장 프록시로 F2 무설정 외주화" 마케팅은 **0-3 반증** → 백스톱으로만.
- **C-2 Supadata:** "No OAuth/API key/quota", 제3자 자막 지원. **월 100크레딧 무료(카드 불요)**, 유료 Basic $5/300cr · Pro $17/3,000cr · Mega $47/30,000cr(1 transcript=1 credit). 일200(6,000/월)·일1000(30,000/월)이면 **Mega $47/월**. ⚠️ "무자막은 동일가 Whisper fallback"은 **0-3 반증**.
- 효과: **F1 ○(무자막 제외) / F2 ◎(외주화)** · 운영부담 낮음(HTTP 호출) · 난이도 낮음(폴백 1단 추가)

### D. 오디오 + ASR (특수 목적 한정)
- **작동:** 오디오만 받아 Whisper로 전사. 호스팅 ASR Groq Whisper Large v3 Turbo **$0.04/시간**(15분 영상 ≈ $0.01/건).
- **F2 못 품(확정 reasoning):** 오디오도 player API/extract_info 경유 → IP 밴 시 같이 죽음.
- **고유 가치:** **자막이 아예 없는 영상**만 커버(F1의 일부). 그 외엔 비효율(대역폭 큼: 오디오 ~10MB/건 → 프록시비·ASR비 동시 상승).
- 효과: **F1 △(무자막만) / F2 ✗** · 무자막 비율만큼만 비용 발생

---

## 4. 한눈에 비교 표

| 방법 | F1 | F2 | 월 비용(일200 / 일1000) | 운영부담 | 모아봄 난이도 |
|---|:--:|:--:|---|:--:|:--:|
| A. 페이싱+PO Token+쿠키위생 (0원) | ◎ | △예방 | **$0 / $0** | 중 | 낮~중 |
| B. 레지덴셜 프록시 풀 | ○ | ◎ | **~$3–6 / ~$15–30** ★ | 중 | 중 |
| B′. ISP static 프록시(정액) | ○ | ◎ | **~$5–25 정액** ★ | 중 | 중 |
| C-1. Apify 관리형 | ○ | ◎ | **$3 / $15** | 낮 | 낮 |
| C-2. Supadata 관리형 | ○ | ◎ | **무료~$47 / $47** | 낮 | 낮 |
| D. 오디오+ASR(Groq) | △무자막 | ✗ | 무자막 비율×$0.01/건 | 높 | 높 |

★ = 대역폭 미측정 추정. 캐시 적중으로 실제 신규 fetch는 가정치보다 적을 수 있음(→ 실비용 더 낮음).

---

## 5. 단계적 권장 (0원 → 저비용 → 유료 백스톱)

**철학: F2를 "0으로" 만들 수는 없다. "빈도↓(예방) + 막혔을 때 다른 경로(다양성/외주)"의 다층 체인으로 사실상 실패 0에 수렴시킨다.**

### 0단계 — 0원 예방 (먼저, 무조건)
1. **워커 페이싱 강화**: 동시성 5→1~2, 요청 간 지터(예: 2~5s 랜덤), 영상 간 간격 확보. burst를 없애 F2 트리거 자체를 줄임.
2. **PO Token provider 통합**: 워커에 `bgutil-ytdlp-pot-provider`(또는 동급) 붙여 트래픽 정상화 → 밴 확률↓.
3. **쿠키 위생**: 로그인 상태 쿠키 유지·만료 모니터링(이미 풀 있음). 자동 갱신 루틴은 후속 조사 필요.
4. (이미 함) 캐시·coarse-to-fine·원어 ko/en 유지.

### 1단계 — 저비용 F2 직접 처방 (예방으로 부족할 때)
5. **워커에 레지덴셜/ISP 프록시 풀 회전 추가.** timedtext가 가벼워 월 $3~30(또는 ISP 정액 $5~25)로 IP 다양성 확보 → F2를 준실시간 회피. 후보: DataImpulse(레지덴셜 $1/GB·최저가군), ISP static(정액·예측가능).

### 2단계 — 유료 백스톱 (체인 최종단)
6. **자체 경로(워커+프록시) 전부 실패한 건만** 관리형 API로 폴백 → 실패분만 과금돼 저렴. **Apify(~$0.5/1k = 월 $3~15)가 최저가**, Supadata는 무료 100/월로 PoC 시작 가능. 차단 책임을 외주화.

### (선택) 무자막 영상 한정
7. 자막이 진짜 없는 영상에만 오디오+ASR(Groq $0.04/hr). F2 해결책 아님 — 커버리지 보강용.

**최종 권장 체인:** `캐시 → 워커(페이싱+PO Token+쿠키풀) → 프록시 회전 → 관리형 API 백스톱 → (무자막 시 ASR)`. 0단계+1단계만으로도 월 $3~30 수준에서 F2가 크게 완화되고, 2단계가 "사실상 실패 0"을 보장.

---

## 6. 이번 조사가 확정 못 한 것 (open questions)

검증을 통과한 claim이 없어 **본 보고서가 확답을 못 준 영역** — 후속 조사 또는 자체 실측 필요:

1. **페이싱 임계치**: burst 몇 건/시간이면 레지덴셜 IP가 몇 시간 밴되는지(0단계 수치 튜닝의 근거).
2. **쿠키 자동 갱신 전략**: 만료(2주~1달) 자동 리프레시 구체 방법, 확장 export vs `--cookies-from-browser`의 2024~2026 변화.
3. **모바일/ISP 프록시의 YouTube 한정 실효성 우위**: 단가는 확정됐으나 "일반 레지덴셜보다 YouTube에 더 강한가"는 미확정.
4. **오디오 vs timedtext 차단 비교(연구차원 6)**: "extract_info 죽으면 둘 다 죽는다" 가설은 *엔지니어링 추론*으로는 견고하나 출처 확정 claim은 부재.
5. **transcript당 실제 프록시 대역폭 측정** → 월 프록시비 확정(현재 ★추정).

---

## 7. 반증된 주장 (권장에 직접 영향 — 믿으면 안 되는 것들)

- ❌ `bgutil-pot-provider`가 IP 밴(F2)을 타깃 해결한다 (0-3) → **예방일 뿐 복구 불가**
- ❌ Apify가 내장 프록시로 F2를 무설정 외주화한다 (0-3) → **백스톱으로만**
- ❌ Supadata가 무자막 영상을 동일가 Whisper로 커버한다 (0-3)
- ❌ 429는 CAPTCHA로 풀리는 비영구 soft-block이다 (0-3) → **IP-keyed 단순 soft-block 아님**

---

## 8. 주요 출처

**1차(primary):**
- yt-dlp PO Token Guide — https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide
- bgutil-ytdlp-pot-provider — https://github.com/Brainicism/bgutil-ytdlp-pot-provider
- yt-dlp #13831 (자막 429, 메인테이너 노트) — https://github.com/yt-dlp/yt-dlp/issues/13831
- yt-dlp FAQ — https://github.com/yt-dlp/yt-dlp/wiki/FAQ
- Apify YouTube Transcript Scraper — https://apify.com/supreme_coder/youtube-transcript-scraper
- Supadata — https://supadata.ai/youtube-transcript-api · https://supadata.ai/pricing
- Groq Whisper Large v3 Turbo — https://groq.com/pricing

**프록시 단가(벤더 공식/집계로 교차검증):**
- SOAX pricing — https://soax.com/pricing
- DataImpulse pricing — https://dataimpulse.com/pricing
- aimultiple proxy pricing — https://aimultiple.com/proxy-pricing
- iproyal YouTube proxies — https://iproyal.com/blog/best-proxies-for-youtube/

**쿠키/운영:**
- 6 ways to get YouTube cookies for yt-dlp in 2026 — https://dev.to/osovsky/6-ways-to-get-youtube-cookies-for-yt-dlp-in-2026-only-1-works-2cnb
- yt-dlp cookie auth guide — https://www.jnzlab.io/posts/ytdlp-cookie-auth-guide/

---

## 9. 신뢰도·주의

- 모든 단가는 2026 현재가이나 벤더가 자주 개편(예: SOAX $99/15GB→$90/25GB). 발주 직전 공식 페이지 재확인 권장.
- 프록시 단가 1차 출처 다수가 벤더 블로그(마케팅 편향) → 핵심 수치는 공식 pricing·비벤더 집계로 교차검증함. "적정 범위"는 지표이지 하드 바운드 아님.
- 월비용 ★는 대역폭 미측정 추정. 모아봄에서 transcript 10건 정도 실측해 GB를 곱하면 확정 가능.
