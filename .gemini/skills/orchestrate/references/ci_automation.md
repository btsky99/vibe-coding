# 🤖 GitHub Actions & CI/CD Debugging

1. **로그 분석**: CI 실패 시 `.github/workflows`의 각 단계 로그를 우선 분석.
2. **자동 수정**: `yaml` 구문 오류 및 의존성 충돌 발견 시 즉시 수정 제안.
3. **보안**: API 키 및 시크릿은 반드시 `GitHub Secrets`를 통해 관리.
4. **캐싱**: `actions/cache`를 활용하여 빌드 시간 단축 유지.
