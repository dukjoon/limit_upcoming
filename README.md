# limit-upcoming

> **Deterministic local evidence bundle generator and proactive usage limit handoff tool**

`limit-upcoming`은 현재 워킹 트리(staged/unstaged diff 및 untracked 신규 파일)와 사용자가 선택한 검증 명령 결과를 로컬 인계 번들로 수집하는 0-token(LLM 미호출) 로컬 도구입니다.

모델 사용량(5시간 롤링 윈도우 및 주간/개인 한도)이 임계치(기본 88%/93%)에 도달하기 전, 불완전 코드를 최소화하고 안전하게 후속 에이전트로 작업을 인계할 수 있도록 돕습니다.

---

## 주요 기능

1. **완전한 Git 워킹 트리 증거 수집 (Evidence Bundle)**:
   - `git diff` (unstaged) 및 `git diff --cached` (staged) 분리 저장.
   - `git diff`에서 누락되는 **untracked 신규 파일의 전문 수집**.
   - 시크릿 패턴(`.env*`, 키 파일), 바이너리, 대용량 파일 자동 제외 및 `manifest.json` 내 제외 사유 명시.
   - 단일 자립형 마크다운 `HANDOFF_BUNDLE.md` 및 기계 판독용 `manifest.json` 생성.
2. **0-Token 패시브 Usage 감지**:
   - OpenAI Codex CLI의 로컬 세션 JSONL 역방향 스캔을 통해 슬래시 명령어 입력 없이 실시간 쿼터(`primary` 5h, `secondary` 7d) 추출.
   - 서브에이전트 턴의 `null` 건너뛰기 및 만료 시각(`resets_at`) 기반 stale 검증.
3. **적응형 임계치 기반 사전 인계 가드 (Pre-limit Staging Guard)**:
   - 88% 도달 시 선제 드래프트 번들(`.handoff/latest-draft`) 백그라운드 갱신.
   - 93% 도달 시 코드 수정 동결(Freeze) 권고 및 최종 번들 생성.

---

## 빠른 시작 (Quick Start)

### 1. 사용량 상태 확인 (0-Token Probe)
```bash
# 전체 JSON 출력
python3 -m limit_upcoming.cli probe --json

# 간이 1줄 요약 출력 (에이전트 컨텍스트 절약용)
python3 -m limit_upcoming.cli probe --compact
```

### 2. 로컬 증거 번들 즉시 생성 (Bundle)
```bash
python3 -m limit_upcoming.cli bundle \
  --goal "Fix database transaction rollback" \
  --notes "auth.py is modified, schema test is failing" \
  --verify-cmd "pytest tests/test_db.py"
```

### 3. 사전 인계 가드 실행 (Guard)
```bash
python3 -m limit_upcoming.cli guard \
  --goal "Checkpoint before complex multi-file edit" \
  --warning-threshold 88.0 \
  --critical-threshold 93.0
```

---

## 프로젝트 문서
- [상세 명세서 (SPEC.md)](file:///Users/ever/Desktop/starhub/limit_upcoming/docs/SPEC.md)
- [실험 및 검증 프로토콜 (EXPERIMENT_PROTOCOL.md)](file:///Users/ever/Desktop/starhub/limit_upcoming/docs/EXPERIMENT_PROTOCOL.md)
- [스킬 가이드 (SKILL.md)](file:///Users/ever/Desktop/starhub/limit_upcoming/SKILL.md)
