SERVICES := control-plane tiering-engine

.PHONY: install test lint run kind-up deploy-local accept-m1 destroy

install:
	@for s in $(SERVICES); do \
		python3 -m venv $$s/.venv && \
		$$s/.venv/bin/pip install -q -e "$$s[dev]"; \
	done

test:
	@for s in $(SERVICES); do \
		echo "== $$s"; \
		(cd $$s && .venv/bin/pytest -q) || exit 1; \
	done

lint:
	@for s in $(SERVICES); do \
		(cd $$s && .venv/bin/ruff check .) || exit 1; \
	done

run:
	cd control-plane && .venv/bin/uvicorn app.main:app --reload --port 8471

kind-up:
	kind create cluster --config deploy/kind/cluster.yaml

deploy-local:
	docker build -t minifiles/control-plane:dev control-plane
	docker build -t minifiles/tiering-engine:dev tiering-engine
	docker build -t minifiles/nfs-godzilla:dev data-plane
	kind load docker-image minifiles/control-plane:dev --name minifiles
	kind load docker-image minifiles/tiering-engine:dev --name minifiles
	kind load docker-image minifiles/nfs-godzilla:dev --name minifiles
	kubectl apply -k deploy/k8s/overlays/dev

accept-m1:
	bash scripts/accept-m1.sh

accept-m2:
	bash scripts/accept-m2.sh

destroy:
	kind delete cluster --name minifiles
