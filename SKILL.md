---
name: limit-upcoming
description: Collects deterministic local evidence bundles and stages proactive handoffs before usage limits or 429 quota exhaustion.
---

# `limit-upcoming` Skill Guide

이 스킬은 모델의 사용 한도(Usage limit / 5-hour quota / Weekly quota)가 임박했을 때, 작업 중단으로 인한 불완전 코드를 최소화하고 타 에이전트에게 맥락을 보존한 로컬 인계 번들을 생성하는 도구입니다.

## 에이전트 행동 수칙 (Crucial Rules)

1. **거대 세션 JSONL 직접 읽기 금지**:
   - `~/.codex/sessions/...`나 `~/.claude/projects/...` 파일을 에이전트의 `read_file`로 직접 읽지 마십시오. 컨텍스트 윈도우 폭증으로 쿼터가 즉시 고갈됩니다.
   - 반드시 `python3 -m limit_upcoming.cli probe --compact` (또는 `--json`) 명령을 실행하여 1줄 요약 정보만 확인하십시오.

2. **사용량 확인 빈도 최소화 (관찰자 효과 방지)**:
   - 매 턴마다 usage를 확인하지 마십시오.
   - 단일 파일 수정 작업이 완료된 논리적 체크포인트에서만 확인하십시오.

3. **구간별 권장 행동**:
   - **`SAFE` (< 80%)**: 상태 확인 없이 정상 작업을 계속합니다.
   - **`WATCH` (80% ~ 87%)**: 대규모 다중 파일 리팩터링을 시작하지 말고 파일 단위로 원자적(Atomic)으로 수정을 완결합니다.
   - **`WARNING_PRE_LIMIT` (88% ~ 92%)**:
     - 현재 수정 중인 파일의 문법적 오류를 완결합니다.
     - `python3 -m limit_upcoming.cli guard --goal "..."`를 호출하여 백그라운드 선제 드래프트 번들을 갱신합니다.
   - **`CRITICAL_HANDOFF` (>= 93%)**:
     - **새로운 파일 수정을 즉시 중단(Freeze)**합니다.
     - `python3 -m limit_upcoming.cli bundle --goal "..." --notes "..." --verify-cmd "..."`를 호출하여 최종 번들을 생성하고, 사용자에게 후속 에이전트로의 인계를 안내합니다.

## 명령어 예시

```bash
# 1. 0-token 간이 사용량 확인
python3 -m limit_upcoming.cli probe --compact

# 2. 로컬 증거 번들 생성
python3 -m limit_upcoming.cli bundle \
  --goal "Implement user authentication flow" \
  --notes "Finished auth service, user router tests are failing at test_login" \
  --verify-cmd "pytest tests/test_auth.py"

# 3. 임계치 기반 가드 실행
python3 -m limit_upcoming.cli guard \
  --goal "Current refactoring checkpoint" \
  --warning-threshold 88.0 \
  --critical-threshold 93.0
```
