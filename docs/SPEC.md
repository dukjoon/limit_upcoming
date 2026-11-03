# limit-upcoming 명세서 (Specification)

## 1. 목적 및 핵심 정의 (Core Specification)

> **핵심 명세 문구**
> `limit-upcoming`은 현재 워킹 트리와 사용자가 선택한 검증 결과를 로컬 인계 번들로 수집하는 도구다. 세션 내부 상태를 이식하거나 다음 에이전트의 동작·성공을 보장하지 않는다. 초기 버전은 사용자가 입력한 작업 목표와 명시적으로 허용한 로컬 정보만 수집하며, 벤더별 세션 로그 파싱과 자동 쿼터 감지는 기본 보장 기능으로 주장하지 않는다(지원 환경에 한해 명시적 로컬 어댑터로 분리). 번들 생성과 후속 CLI 실행은 분리하고, 자동 실행은 사용자가 선택한 어댑터에서만 수행한다.

---

## 2. 제외된 가설 및 교정 (Kill List)

1. **`git diff`에 모든 수정/신규 파일이 포함된다는 가정 삭제**
   - 교정: `git diff` 및 `git diff --cached`는 추적 중인 파일 변경만 수집합니다. 신규 untracked 파일은 `git ls-files --others --exclude-standard`로 별도 추출하여 번들에 전문을 수록합니다.
   - 제외 파일 명시: 시크릿 패턴(`.env*`, `*.pem`, `*.key` 등), 바이너리 파일, 대용량 파일(>100KB)은 내용을 제외하고 `manifest.json`의 `excluded_files`에 제외 사유와 함께 명시합니다.

2. **서로 다른 CLI 세션 로그를 공통 방식으로 자동 파싱한다는 가정 삭제**
   - 교정: 벤더별 세션 형식은 제각각이며 안정적인 범용 파싱이 불가능합니다. 따라서 **사용자가 입력한 작업 목표(`--goal`) 및 작업 메모(`--notes`)를 유일한 기본 진실 원천(Primary Source of Truth)**으로 취급합니다.

3. **전체 프로세스가 0-token 및 결정론적이라는 단정 삭제**
   - 교정: `0-token`은 로컬 스크립트가 번들을 수집하고 로컬 파일의 쿼터를 읽는 단계(LLM API 미호출)에만 국한됩니다. 후속 CLI가 번들을 입력받아 재개할 때는 모델 호출과 토큰 소비가 발생합니다.
   - 결정론적 수집 vs 비결정론적 실행: 검증 명령(`--verify-cmd`) 실행은 프로젝트 스크립트, 시스템 환경, 네트워크에 따라 달라질 수 있으므로, 도구는 **"실행된 명령, 종료 코드, stdout/stderr, 소요 시간, 환경 메타데이터를 있는 그대로 캡처(Evidence Capture)"**하는 역할로 한정합니다.

4. **수 초 완료, 토큰 절감률, 코드 보존율 개선, 다운타임 제로 등의 성과 주장 삭제**
   - 교정: 실제 에이전트를 포함한 실험으로 측정되기 전까지 성과를 약속하지 않습니다.

---

## 3. 로컬 0-Token Usage 감지 아키텍처

### 근거 수준 및 감지 방식
1. **OpenAI Codex CLI (로컬 실측 검증 완료)**:
   - 파일: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`
   - 메커니즘: 파일 끝부분(256KB 이내)을 역방향 스캔하여 `type: "event_msg"`, `payload.type: "token_count"` 이벤트 추출.
   - 보조 모델/서브에이전트 턴에서 `primary: null`이 들어간 줄을 건너뛰고, 직전 유효 스냅샷 추출.
   - 5시간 윈도우(`primary`)와 주간/개인 한도(`secondary`, 10080분 윈도우) 중 **더 높은 사용률(`max(primary, secondary)`)**을 유효 사용률(`effective_used_percent`)로 채택.
2. **Claude Code CLI (실험적 로컬 캐시 지원)**:
   - 메커니즘: `statusLine` 파이프라인에서 전달되는 JSON을 `limit-upcoming hook-statusline`을 통해 로컬 캐시(`~/.cache/limit_upcoming/claude_status.json`)에 저장한 뒤 0-token으로 읽음.
3. **Gemini CLI / Antigravity / API Key 직접 호출 환경**:
   - 로컬 파일에 사전 쿼터 스냅샷이 기록되지 않으므로 `detection_mode = "unsupported"`로 처리하고 수동 `bundle` 모드 사용.

### 스냅샷 신선도(Staleness) 관리
- 로컬 파일의 최종 수정 시간(`mtime`)을 기준으로 `snapshot_age_s`를 기록합니다.
- `resets_at` 타임스탬프가 현재 시각보다 과거인 경우 `stale = true`로 처리하여 만료된 쿼터 정보로 인한 오판을 방지합니다.

---

## 4. Usage 임계 구간 및 최소 토큰 타이밍 설계

| 구간 (Effective Used %) | 등급 (`Tier`) | 권장 동작 |
| :--- | :--- | :--- |
| **< 80%** | `SAFE` | 일반 작업 진행 (에이전트 토큰 개입 0회) |
| **80% ~ 87%** | `WATCH` | 단일 파일 단위로 편집 유지, 대규모 리팩터링 시작 자제 |
| **88% ~ 92%** | `WARNING_PRE_LIMIT` | 현재 수정 중인 파일만 문법적/논리적으로 완결, 백그라운드 0-token 드래프트 번들(`.handoff/latest-draft`) 생성 |
| **>= 93%** | `CRITICAL_HANDOFF` | **신규 코드 수정 동결(Freeze)**, 최종 로컬 증거 번들 확정 및 후속 에이전트 인계 안내 |
