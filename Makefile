.PHONY: venv install run-gateway run-gateway-dev mock-upstream run-client test health-gateway health-upstream check-dedicated

venv:
	python3.11 -m venv .venv

install:
	pip install -r requirements.txt

mock-upstream:
	uvicorn mock_upstream:app --port 8001

run-gateway:
	uvicorn app.main:app --port 8000

run-gateway-dev:
	uvicorn app.main:app --port 8000 --reload

run-client:
	python3.11 client.py

test:
	pytest -q

health-gateway:
	@status=$$(curl -s -o /tmp/health.out -w "%{http_code}" http://localhost:8000/healthz || true); \
	if [ "$$status" = "000" ]; then echo "Gateway not reachable on http://localhost:8000/healthz (is it running?)"; exit 1; fi; \
	if [ "$$status" = "404" ]; then echo "Endpoint /healthz not found (are you running an older gateway build? restart to load new routes)"; cat /tmp/health.out; exit 1; fi; \
	cat /tmp/health.out; echo

health-upstream:
	@status=$$(curl -s -o /tmp/ready.out -w "%{http_code}" http://localhost:8000/upstream-health || true); \
	if [ "$$status" = "000" ]; then echo "Gateway not reachable on http://localhost:8000/upstream-health (is it running?)"; exit 1; fi; \
	if [ "$$status" = "404" ]; then echo "Endpoint /upstream-health not found (are you running an older gateway build? restart to load new routes)"; cat /tmp/ready.out; exit 1; fi; \
	if grep -q '\"upstream\":false' /tmp/ready.out; then echo "Upstream unreachable (gateway is up)."; cat /tmp/ready.out; exit 1; fi; \
	cat /tmp/ready.out; echo

check-dedicated:
	@if [ -z "$$FRIENDLI_ENDPOINT_ID" ]; then echo "Set FRIENDLI_ENDPOINT_ID to your Dedicated endpoint ID"; exit 1; fi; \
	if [ -z "$$UPSTREAM_API_KEY" ]; then echo "Set UPSTREAM_API_KEY to your Friendli token"; exit 1; fi; \
	curl -s -H "Authorization: Bearer $$UPSTREAM_API_KEY" \
	  "https://api.friendli.ai/dedicated/beta/endpoint/$$FRIENDLI_ENDPOINT_ID/status" && echo
