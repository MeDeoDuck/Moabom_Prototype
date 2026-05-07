# Azure 배포 가이드 — 모아봄

이 문서는 모아봄을 Azure Container Apps에 배포하고 운영하기 위한 재현 가능한
가이드입니다. 2026-05-07 첫 성공적 배포 기준으로 정리되었습니다.

## 1. 인프라 구성

| 자원 | 이름 | SKU/구성 | 용도 |
|---|---|---|---|
| Resource Group | `rg-moabom` | koreacentral | 모든 자원 컨테이너 |
| Container Registry | `acrmoabom` | Basic, admin enabled | Docker 이미지 보관 |
| PostgreSQL Flexible Server | `pg-moabom` | B1ms, v15, public-access All, db `techdb` | 영상/댓글/보고서 DB |
| Log Analytics Workspace | `log-moabom` | 30일 보존 | 컨테이너 로그·진단 |
| Container Apps Environment | `cae-moabom` | koreacentral | 앱 호스팅 env |
| Container App | `ca-moabom` | CPU 0.5 / Mem 1Gi, min/max=1 | FastAPI 본 앱 (port 8000) |

기본 도메인: `https://ca-moabom.<env-default-domain>.koreacentral.azurecontainerapps.io`

## 2. 사전 준비물

- Azure 구독 (`Azure for Students` 크레딧으로 운영 가능)
- `az` CLI 2.85+ (Container Apps extension 자동 설치됨)
- 로컬 `.secrets/yt_cookies.txt` (YouTube cookie 풀세트 — §5 참조)
- 로컬 `.env` (`AZURE_OPENAI_*`, `YOUTUBE_API_KEY`, `GROQ_API_KEY`, `GROQ_MODEL`)
- `.secrets/azure_pg.txt` (PG 비밀번호 — 첫 배포 시 자동 생성)

## 3. 처음부터 배포하기 (재현 절차)

```bash
# 0. 로그인 + 구독 선택
az login
az account set -s "<subscription>"

# 1. RG
az group create -n rg-moabom -l koreacentral

# 2. ACR
az acr create -g rg-moabom -n acrmoabom --sku Basic --admin-enabled true

# 3. 이미지 빌드 (로컬 Docker 불필요 — ACR Tasks가 클라우드에서 빌드)
az acr build -r acrmoabom -t moabom-app:v1 -f Dockerfile .

# 4. PostgreSQL Flexible Server (5~10분)
PG_PWD=$(openssl rand -base64 32 | tr -d '/+=' | head -c 28)P1!
printf 'PG_HOST=pg-moabom.postgres.database.azure.com\nPG_USER=moabomadmin\nPG_PWD=%s\nPG_DB=techdb\n' "$PG_PWD" > .secrets/azure_pg.txt
chmod 600 .secrets/azure_pg.txt
az postgres flexible-server create \
  -g rg-moabom -n pg-moabom -l koreacentral \
  -u moabomadmin -p "$PG_PWD" \
  --sku-name Standard_B1ms --tier Burstable \
  --version 15 --storage-size 32 \
  --public-access All --yes
az postgres flexible-server db create -g rg-moabom -s pg-moabom -d techdb

# 5. Log Analytics
az monitor log-analytics workspace create \
  -g rg-moabom -n log-moabom -l koreacentral --retention-time 30

# 6. Container Apps Environment (3~5분)
LA_ID=$(az monitor log-analytics workspace show -g rg-moabom -n log-moabom \
  --query customerId -o tsv | tr -d '\r\n ')
LA_KEY=$(az monitor log-analytics workspace get-shared-keys -g rg-moabom -n log-moabom \
  --query primarySharedKey -o tsv | tr -d '\r\n ')
az containerapp env create \
  -g rg-moabom -n cae-moabom -l koreacentral \
  --logs-workspace-id "$LA_ID" --logs-workspace-key "$LA_KEY"

# 7. Container App (secrets + env vars 한 번에)
set -a; source .env; source .secrets/azure_pg.txt; set +a
COOKIE_B64=$(base64 -w0 .secrets/yt_cookies.txt)
az containerapp create \
  -g rg-moabom -n ca-moabom \
  --environment cae-moabom \
  --image acrmoabom.azurecr.io/moabom-app:v1 \
  --registry-server acrmoabom.azurecr.io \
  --target-port 8000 --ingress external \
  --cpu 0.5 --memory 1Gi \
  --min-replicas 1 --max-replicas 1 \
  --secrets \
      db-url="postgresql://$PG_USER:$PG_PWD@$PG_HOST:5432/$PG_DB?sslmode=require" \
      yt-cookies-b64="$COOKIE_B64" \
      aoai-key="$AZURE_OPENAI_API_KEY" \
      yt-api-key="$YOUTUBE_API_KEY" \
      groq-key="$GROQ_API_KEY" \
  --env-vars \
      DATABASE_URL=secretref:db-url \
      YT_COOKIES_B64=secretref:yt-cookies-b64 \
      AZURE_OPENAI_API_KEY=secretref:aoai-key \
      YOUTUBE_API_KEY=secretref:yt-api-key \
      GROQ_API_KEY=secretref:groq-key \
      AZURE_OPENAI_ENDPOINT="$AZURE_OPENAI_ENDPOINT" \
      AZURE_OPENAI_DEPLOYMENT="$AZURE_OPENAI_DEPLOYMENT" \
      AZURE_OPENAI_API_VERSION="$AZURE_OPENAI_API_VERSION" \
      GROQ_MODEL="$GROQ_MODEL" \
      PORT=8000

# 8. FQDN 확인 + 헬스체크
FQDN=$(az containerapp show -g rg-moabom -n ca-moabom \
  --query properties.configuration.ingress.fqdn -o tsv)
curl -sS "https://$FQDN/products" -o /dev/null -w "HTTP %{http_code}\n"
```

## 4. 코드 변경을 반영해 재배포

```bash
# 새 이미지 빌드 + 푸시
az acr build -r acrmoabom -t moabom-app:v2 -f Dockerfile .

# Container App 이미지 갱신
az containerapp update -g rg-moabom -n ca-moabom \
  --image acrmoabom.azurecr.io/moabom-app:v2
```

`update`는 새 revision을 만들고 트래픽을 자동 전환합니다.

## 5. YouTube cookie 운영 (가장 중요)

Azure datacenter IP는 YouTube에서 봇으로 분류됩니다. 인증 사용자 cookie를
주입해야만 자막 fetch가 가능합니다. `scripts/youtube/cookies.py` + `transcript_service.py`
가 `YT_COOKIES_B64` 환경변수에서 cookie를 읽습니다.

### 5-1. cookie 추출 (만료 시 매번)

`__Secure-1PSIDTS` 만료가 가장 짧고 보통 2주~1달입니다. 만료되면 자막 fetch가
다시 봇 차단을 받기 시작합니다.

> ⚠️ Chrome 127+ 부터 cookie가 ABE(App-Bound Encryption)로 추가 암호화돼서
> `yt-dlp --cookies-from-browser chrome`은 동작하지 않습니다 (yt-dlp issue #10927).
> 아래 확장 방법만 안정적입니다.

1. Chrome 닫기 (트레이까지)
2. Chrome 확장 ["Get cookies.txt LOCALLY"](https://chrome.google.com/webstore) 설치
3. 모아봄 전용 구글 계정으로 youtube.com 로그인
4. **youtube.com 탭** 열고 → 확장 → Export → Netscape format → `cookies_yt.txt`
5. **www.google.com 탭** 열고 → 확장 → Export → `cookies_g.txt`
   (이게 핵심: youtube.com만 export하면 datacenter IP에서 인증 부족)
6. 두 파일 합치기:
   ```bash
   { echo "# Netscape HTTP Cookie File"; \
     cat .secrets/cookies_yt.txt .secrets/cookies_g.txt | grep -v '^#' | grep -v '^$' | sort -u; \
   } > .secrets/yt_cookies.txt
   ```
7. 검증 (둘 다 ~20개 cookie + 1P/3P SID·HSID·SSID·APISID·SAPISID 포함):
   ```bash
   awk -F'\t' '!/^#/ && NF>=7 {print $1}' .secrets/yt_cookies.txt | sort | uniq -c
   ```

### 5-2. Container App에 반영

```bash
COOKIE_B64=$(base64 -w0 .secrets/yt_cookies.txt)
az containerapp secret set -g rg-moabom -n ca-moabom \
  --secrets yt-cookies-b64="$COOKIE_B64"
# secret 변경은 새 revision을 만들지 않으니 명시 재시작 필요
LATEST=$(az containerapp revision list -g rg-moabom -n ca-moabom \
  --query '[?properties.active] | [0].name' -o tsv)
az containerapp revision restart -g rg-moabom -n ca-moabom --revision "$LATEST"
```

### 5-3. 배포 환경 자막 fetch 검증

`scripts/diagnostics/transcript_probe.py` 로컬·ACI 양쪽에서 동일 동작 확인 가능:

```bash
# 로컬
YT_COOKIES_PATH=.secrets/yt_cookies.txt python -m scripts.diagnostics.transcript_probe

# Azure datacenter IP에서 격리 진단 (1회용 ACI)
az group create -n rg-moabom-probe -l koreacentral
COOKIE_B64=$(base64 -w0 .secrets/yt_cookies.txt)
az container create -g rg-moabom-probe -n probe \
  --image mcr.microsoft.com/azure-functions/python:4-python3.11 \
  --restart-policy Never --cpu 0.5 --memory 1.5 --location koreacentral \
  --secure-environment-variables YT_COOKIES_B64="$COOKIE_B64" \
  --command-line "/bin/bash -c 'python3 -m pip install --quiet yt-dlp==2026.3.17 requests==2.33.1 && curl -fsSL -o /tmp/p.py https://raw.githubusercontent.com/moabom-official/Moabom_Prototype/main/scripts/diagnostics/transcript_probe.py && python3 /tmp/p.py'"
# 확인 후
az group delete -n rg-moabom-probe --yes --no-wait
```

## 6. 트러블슈팅 (실제로 발생한 함정들)

| 증상 | 원인 | 해결 |
|---|---|---|
| `--database-name can only be used when --cluster-option is set to ElasticCluster` | `az postgres flexible-server create --database-name`이 cluster mode 전용으로 변경됨 | `db create` 명령으로 분리 |
| `LogAnalyticsConfiguration.CustomerId is invalid` | `az ... -o tsv` 결과에 trailing newline | `tr -d '\r\n '` 로 sanitize |
| ACI에서 `exit 127`, `python: command not found` | `mcr.microsoft.com/azurelinux/base/python:3.12`은 minimal base — python 바이너리 미포함 | `mcr.microsoft.com/azure-functions/python:4-python3.11` 사용 |
| `index.docker.io` rate limit으로 ACI image pull 실패 | 익명 풀 한도 | MCR 이미지로 변경 |
| 자막 fetch 시 `Sign in to confirm you're not a bot` | datacenter IP 봇 분류 | cookie 풀세트 + process=False (§5) |
| 자막 fetch 시 `No video formats found` (cookie 적용 후) | 인증 사용자가 되면 yt-dlp가 tv-downgraded player → n-challenge·PO Token | `extract_info(..., process=False)` |

## 7. 비용 (2026-05 기준 추정)

| 자원 | 월 비용 (KRW 환산 ~$1=1370원) |
|---|---|
| PG B1ms + 32GB | ~$13 (~18,000원) |
| Container App 0.5 vCPU 1 replica 24h | ~$10 (~14,000원) |
| ACR Basic | ~$5 (~7,000원) |
| Log Analytics 30일 (저트래픽) | ~$2 (~3,000원) |
| **합계** | **~$30/월 (~40,000원)** |

Azure for Students $100 크레딧 안에서 3개월 운영 가능.

## 8. 관련 문서·코드

- `scripts/youtube/cookies.py` — cookie 로딩 헬퍼 (env → file/jar)
- `scripts/youtube/transcript_service.py` — cookie 적용 자막 fetch
- `scripts/diagnostics/transcript_probe.py` — 4단계 격리 진단 도구
- `.secrets/README.md` — 로컬 비밀 파일 위치·용도
- `Dockerfile` — 컨테이너 이미지 정의
