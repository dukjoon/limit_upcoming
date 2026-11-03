# 실험 및 검증 프로토콜 (Experiment Protocol)

본 문서는 `limit-upcoming`의 검증을 **(A) 로컬 결정론적 지표**와 **(B) 비결정론적 에이전트 행동 실험**으로 명확히 분리하여 규정합니다.

---

## 1. 그룹 A: 로컬 결정론적 측정 지표 (Local Deterministic Metrics)

로컬 머신에서 외부 LLM 호출 없이 완전히 자동화하여 반복 측정 가능한 지표입니다.

| 지표명 | 측정 단위 | 측정 방법 | 성공 기준 |
| :--- | :--- | :--- | :--- |
| **`bundle_generation_duration_ms`** | 밀리초 (ms) | `manifest.generation_duration_ms` | 단일 프로젝트 기준 < 500ms (100개 미만 파일) |
| **`total_bundle_bytes`** | 바이트 (Bytes) | `manifest.total_bundle_bytes` | 번들 디렉터리 내 실제 파일 합계와 일치 |
| **`untracked_file_inclusion_rate`** | 비율 (%) | `included_files` 내 untracked 수 / 실제 유효 텍스트 신규 파일 수 | 100% (누락 0개) |
| **`excluded_files_manifest_accuracy`** | 일치 여부 | 시크릿, 바이너리, 대용량 파일의 제외 사유 검증 | 100% 매핑 (`reason` 명시) |
| **`verification_record_fidelity`** | 일치 여부 | `verify_cmd`의 실제 exit code, stdout, stderr 보존 | 100% 왜곡 없이 기록 |
| **`probe_extraction_latency_ms`** | 밀리초 (ms) | 역방향 256KB 스캔 및 JSON 추출 시간 | < 50ms |

---

## 2. 그룹 B: 에이전트 실행 및 인계 비교 실험 (Agent Behavioral Experiments)

실제 LLM 에이전트가 인입되어 작업을 이어갈 때의 동작을 측정하는 비결정론적 실험입니다.

### 실험 설정
1. **대조군 (Baseline - Naive Handoff)**:
   - 429 또는 쿼터 제한 발생 시 강제 중단된 상태에서 후속 에이전트에게 기본 프롬프트("이어서 작업해줘")만 전달.
2. **실험군 (limit-upcoming)**:
   - 93% 임계치에서 안전 동결 후 생성된 `HANDOFF_BUNDLE.md`를 후속 에이전트의 첫 프롬프트 컨텍스트로 제공.

### 관측 지표
1. **재개 시점의 토큰 소비량 (Resumption Tokens)**:
   - 후속 에이전트가 첫 유의미한 코드 수정을 커밋하기 전까지 소비한 누적 토큰 수.
2. **불완전 코드 발생 빈도 (Broken Syntax Rate)**:
   - 이전 에이전트가 중단된 시점에 워킹 트리가 문법 오류(Syntax Error) 상태인지 여부.
3. **태스크 성공률 (Task Completion Rate)**:
   - 사전에 정의된 유닛 테스트 스위트를 최종 통과했는지 여부.
4. **인간 개입 필요 횟수 (Human Interventions)**:
   - 맥락 소실로 인해 사용자가 수동으로 설명해야 했던 턴 수.
