# Bedrock LLM Monitor v2 — make targets
# 모든 Phase 종료 시 `make verify`가 0 종료코드로 통과해야 한다.

.DEFAULT_GOAL := help

# ----------------------------------------------------------------------
# 도움말
# ----------------------------------------------------------------------
.PHONY: help
help: ## 사용 가능한 타겟 목록을 출력
	@awk 'BEGIN{FS=":.*##"; printf "사용법: make <target>\n\n타겟:\n"} \
	/^[a-zA-Z0-9_-]+:.*##/ {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ----------------------------------------------------------------------
# v2 자가검증
# ----------------------------------------------------------------------
.PHONY: verify
verify: cdk-install cdk-lint cdk-typecheck cdk-test cdk-synth backend-lint backend-test frontend-lint ## CDK + 백엔드 + 프론트엔드 전체 검증
	@echo "✓ make verify PASS"

.PHONY: cdk-install
cdk-install: ## CDK 의존성 설치 (lock 있으면 ci, 없으면 install)
	@if [ ! -d cdk/node_modules ]; then \
		if [ -f cdk/package-lock.json ]; then \
			cd cdk && npm ci; \
		else \
			cd cdk && npm install; \
		fi; \
	fi

.PHONY: cdk-lint
cdk-lint: ## CDK ESLint 검사
	cd cdk && npm run lint

.PHONY: cdk-typecheck
cdk-typecheck: ## CDK TypeScript 타입 검사 (no emit)
	cd cdk && npm run typecheck

.PHONY: cdk-test
cdk-test: ## CDK Jest 단위 테스트
	cd cdk && npm test --silent

.PHONY: cdk-synth
cdk-synth: ## CDK synth (cdk-nag aspect 적용 포함)
	cd cdk && npm run synth

.PHONY: backend-lint
backend-lint: ## 백엔드 Python 정적 검사 (ruff 미설치 시 skip)
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check backend/; \
	else \
		echo "(skip) ruff 미설치 — 'pip install ruff'로 설치 권장"; \
	fi

.PHONY: backend-test
backend-test: ## 백엔드 pytest 단위 테스트
	@if command -v pytest >/dev/null 2>&1; then \
		cd backend && pytest tests/ -q; \
	else \
		echo "(skip) pytest 미설치 — 'pip install pytest pytest-asyncio'"; \
	fi

.PHONY: frontend-lint
frontend-lint: ## 프론트엔드 TypeScript 타입 검사 (lint는 v2 후속 Phase에서)
	@if [ -d frontend/node_modules ]; then \
		cd frontend && npx tsc --noEmit; \
	else \
		echo "(skip) frontend/node_modules 없음 — 'cd frontend && npm install'"; \
	fi

# ----------------------------------------------------------------------
# 빌드
# ----------------------------------------------------------------------
.PHONY: build-backend
build-backend: ## 백엔드 컨테이너 이미지 빌드
	docker build -t bedrock-monitor-backend:dev backend/

.PHONY: build-frontend
build-frontend: ## 프론트엔드 컨테이너 이미지 빌드
	docker build -t bedrock-monitor-frontend:dev frontend/

.PHONY: build
build: build-backend build-frontend ## 두 이미지 모두 빌드

# ----------------------------------------------------------------------
# CDK 작업
# ----------------------------------------------------------------------
.PHONY: synth
synth: cdk-install ## cdk synth 단축
	cd cdk && npm run synth

.PHONY: diff
diff: cdk-install ## cdk diff 단축
	cd cdk && npm run diff

.PHONY: deploy
deploy: cdk-install verify ## cdk deploy --all (verify 통과 후)
	cd cdk && npm run deploy

# ----------------------------------------------------------------------
# 정리
# ----------------------------------------------------------------------
.PHONY: clean
clean: ## 빌드 산출물 정리
	rm -rf cdk/cdk.out cdk/node_modules cdk/*.js cdk/**/*.js
	rm -rf frontend/.next frontend/node_modules
	find backend -type d -name __pycache__ -exec rm -rf {} +
	@echo "✓ clean done"
