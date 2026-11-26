# Heritage Short pipeline. `make help` lists the targets.
# Each stage is one script in pipeline/ that reads storyboard.json and writes outputs/<stage>/.
# Outputs are cached by input hash, so re-running only regenerates what changed.

PY_VERSION ?= 3.12
VENV       ?= .venv
PY         := $(VENV)/bin/python
DEPS       := $(VENV)/.deps-installed
KIND       ?= shots
ifndef RUN_ID
RUN_ID := $(shell date -u +%Y%m%dT%H%M%SZ)
endif
export RUN_ID MOCK FORCE ONLY ALLOW_PRIVATE ALLOW_FALLBACK

STAGES := draft keyframes shots music narration assemble
.PHONY: help setup validate film mock radio smoke costs site check consent test clean-mock portraits keyframe-candidates \
        kaggle-push kaggle-status kaggle-pull kaggle-import $(STAGES)

help: ## list targets
	@grep -E '^[a-zA-Z_ -]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /|/' | awk -F'|' '{printf "  %-22s %s\n", $$1, $$2}'

$(DEPS): requirements.txt
	@if command -v uv >/dev/null 2>&1; then \
	  [ -x $(PY) ] || uv venv -q --python $(PY_VERSION) $(VENV); \
	  uv pip install -q --python $(PY) -r requirements.txt; \
	else \
	  [ -x $(PY) ] || $$(command -v python$(PY_VERSION) || command -v python3) -m venv $(VENV); \
	  $(PY) -m pip install -q -r requirements.txt; \
	fi
	@command -v ffmpeg >/dev/null || { echo "ffmpeg not found: brew install ffmpeg (macOS) or apt install ffmpeg"; exit 1; }
	@touch $(DEPS)

setup: $(DEPS) ## create .venv (Python $(PY_VERSION) via uv) and install deps

validate: $(DEPS) ## check storyboard.json against schema/storyboard.schema.json
	$(PY) -m pipeline.validate

$(STAGES): $(DEPS)
	$(PY) -m pipeline.$@

film: validate draft keyframes shots music narration assemble ## run every stage (cached) -> outputs/film/
	$(PY) -m pipeline.check --soft

mock: ## the whole pipeline offline, no API keys -> build/mock/
	$(MAKE) film MOCK=1

radio: narration ## radio cut: narration + subtitles over placeholder music, on black
	$(PY) -m pipeline.radio

keys: $(DEPS) ## type your API keys into .env (input hidden)
	$(PY) -m pipeline.setkeys

portraits: $(DEPS) ## N face candidates per character (N=3; MODEL=@cf/... to compare); pick by setting its seed
	$(PY) -m pipeline.keyframes --candidates $(or $(N),3) $(if $(MODEL),--model $(MODEL))

keyframe-candidates: $(DEPS) ## N versions of the ONLY= shots (N=3); pick one by setting that shot's seed
	$(PY) -m pipeline.keyframes --shot-candidates $(or $(N),3)

smoke: $(DEPS) ## one tiny call per provider; latency logged to runs.jsonl
	$(PY) -m pipeline.smoke

costs: $(DEPS) ## summarise runs.jsonl into COSTS.md
	$(PY) -m pipeline.costs

site: $(DEPS) ## index.html: a Screening Room page for the film, from the repo's own files (GitHub Pages)
	$(PY) -m pipeline.site

check: $(DEPS) ## QA the deliverables against the brief (fails on problems)
	$(PY) -m pipeline.check

consent: $(DEPS) ## show the consent gate status
	$(PY) -m pipeline.consent

test: $(DEPS) ## unit tests + "edit one line, only that shot regenerates" (mock)
	$(PY) -m unittest discover -s tests -v

kaggle-push: $(DEPS) ## upload pending jobs and start the GPU kernel (KIND=shots|music)
	$(PY) -m pipeline.kaggle_jobs push $(KIND)

kaggle-status: $(DEPS) ## show the Kaggle kernel status (KIND=shots|music)
	$(PY) -m pipeline.kaggle_jobs status $(KIND)

kaggle-pull: $(DEPS) ## download kernel output into inbox/ (KIND=shots|music), then run make $(KIND)
	$(PY) -m pipeline.kaggle_jobs pull $(KIND)

kaggle-import: $(DEPS) ## manual fallback: make kaggle-import KIND=shots ZIP=~/Downloads/output.zip
	$(PY) -m pipeline.kaggle_jobs import $(KIND) $(ZIP)

clean-mock: ## delete build/mock
	rm -rf build/mock
