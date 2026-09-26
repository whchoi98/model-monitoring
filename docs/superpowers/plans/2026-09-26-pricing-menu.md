# 비용 단가 메뉴 (v2.30.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a public `/pricing` menu ("비용 단가" / "Unit Prices") whose unit prices come from one backend source, `price_history`, refreshed every 12 hours from official sources, and price every cost and efficiency figure at the unit price in effect at each probe's time.

**Architecture:** A new PricingSync Fargate task (EventBridge `rate(12 hours)`) reads the Bedrock agreement-offer rate cards, the AWS Price List API and Anthropic `pricing.md`, and records per-`model_id` price rows in `price_history` and `price_sync_runs`; changes above 50% wait for admin approval. The backend seeds the 55 active channels at startup, joins every probe row to the price effective at its timestamp for `/api/cost/*` and `/api/efficiency/score`, and serves `/api/pricing` with CSV, Markdown and JSON exports. The frontend renders `/pricing` from that API and drops its price mirror, and Model Explorer and Comparison Lab read `/api/pricing` `models`.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy <2.1 (PostgreSQL 16 in production, in-memory SQLite in tests), boto3 (`bedrock`, `pricing`), httpx, pytest; Next.js 16, React 18, TypeScript, Tailwind, vitest, Playwright (chromium); AWS CDK v2 (TypeScript, jest, cdk-nag).

**Spec:** docs/superpowers/specs/2026-09-26-pricing-menu-design.md

## Global Constraints

These apply to every task.

- **Plan blocks.** Every file this plan creates and every patch it applies is stored byte for byte in the **Appendix** (or inline in the task) as a sha256-checked plan block. Tasks name blocks by id (for example `t03-parsers`). Write them with the block extractor (see "Applying plan blocks" under Execution Order) instead of retyping them, and do not read the Appendix into context unless you are reviewing it. Code excerpts shown inside tasks are for reading; the block is the source of truth.
- Runtime is Python 3.11 (Docker `python:3.11-slim`). Run backend tests with `(cd backend && python3.12 -m pytest tests/ -q)` (the dev host's system `python3` is 3.9, which is fine for the plan extractor and the doc check but not for backend code). SQLAlchemy is pinned `<2.1` with psycopg2. Tests use in-memory SQLite built by `models.Base.metadata.create_all` (`sqlite://` + `StaticPool`, as in `backend/tests/test_label_repair.py` and `test_auto_probe_latest.py`; `backend/tests/conftest.py` only sets import-time env).
- Tests are offline: no AWS, no network. Fetchers are injected, and fixtures live under `backend/tests/fixtures/pricing/`. Fixtures must NOT contain `offerToken`, `legalTerm.url`, `X-Amz-*` query strings or any presigned URL.
- Every timestamp is a timezone-aware datetime bound through ORM/Core parameters; no raw timestamp string literals in SQL.
- Frontend: never run `next dev`. Unit tests `(cd frontend && npm test)` (vitest) and `(cd frontend && npm run typecheck)`; e2e only via `(cd frontend && npm run build && PLAYWRIGHT_USE_PRODUCTION=1 CI=1 npx playwright test <spec> --project=chromium)` (webkit cannot launch on the dev host). After any build or test, revert incidental changes with `git checkout -- frontend/next-env.d.ts frontend/CLAUDE.md AGENTS.md` (`frontend/tsconfig.tsbuildinfo` is gitignored by `*.tsbuildinfo`, so there is nothing to revert for it).
- CDK tests: `(cd cdk && npm test)`.
- Backend, frontend and CDK commands are written as `(cd backend && …)`, `(cd frontend && …)` and `(cd cdk && …)` subshells run from the repository or worktree root, so the working directory never changes between lines (one shell running a fenced block keeps its `cd`); do not chain bare `cd` lines.
- `npm run build` fetches the Inter font from fonts.googleapis.com (`next/font/google` in `frontend/src/app/layout.tsx`), so every build and e2e step needs outbound HTTPS; without it the build fails with `next/font: error: Failed to fetch Inter from Google Fonts.` Vitest, typecheck, backend pytest and CDK jest are fully offline.
- Korean UI copy: commas instead of middle dots, numbered lists "1.", assertive wording; no emojis.
- Commit after each task with the conventional-commit message given in the task (feat/fix/test/refactor/infra/docs/chore with the scope style of `git log`). Never stage `tests/20260810_SB/` or this plan file (it stays untracked in the main checkout unless the controller commits it separately). Never commit spike raw files, plan-block patches or the one-off check scripts (they are written outside the repository).
- Exact numbers and strings come from the spec: disclaimer text, change threshold 0.5 inclusive, advisory lock keys 917350003 (seed) and 917350004 (sync), sync deadline 300 s, `/api/pricing` cache 60 s, reference URLs.
- Python bytecode: clear `__pycache__` (`find backend -name __pycache__ -prune -exec rm -rf {} +`) before re-running tests after an in-place edit that keeps the file size and modification second; stale bytecode was observed while verifying Task 1.
- Worktrees: a git worktree has no `frontend/node_modules`, `cdk/node_modules` or `cdk/cdk.context.json`. Copy `frontend/node_modules` from the main checkout (`cp -a /home/ec2-user/my-project/model-monitoring/frontend/node_modules frontend/`) or run `npm ci`; a symlink is not enough, because `next build` (Turbopack) fails with "Symlink [project]/node_modules is invalid, it points out of the filesystem root" (vitest and typecheck work with a symlink). A `cdk/node_modules` symlink works for jest and `cdk synth`; `cdk synth` also needs a copy of the gitignored `cdk/cdk.context.json`.

## Interface Contract

Every task uses these exact names and signatures. Everything below was checked by running all 14 tasks in order on a clone of `91008c6` (backend 706 tests, vitest 249, Playwright chromium 100, CDK jest 85, doc check `DOCCHECK OK`). Items marked **(added)** are additions or refinements accepted during planning because the real code needed them; the list of behavioural decisions follows the signatures.

### backend/models.py (append two ORM classes; tables come from `Base.metadata.create_all` via `database.create_tables()`)

```python
class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (Index("ix_price_history_model_eff", "model_id", "effective_from"),)
    id = Column(Integer, primary_key=True, autoincrement=True)   # autoincrement=True: models.py convention (added)
    model_id = Column(Text, nullable=False)
    family_key = Column(Text, nullable=False)
    channel = Column(Text, nullable=False)          # "cp" | "global" | "us" | "inregion:<aws-region>"
    input_per_mtok = Column(Float, nullable=False)  # USD per 1M input tokens
    output_per_mtok = Column(Float, nullable=False) # USD per 1M output tokens
    effective_from = Column(DateTime(timezone=True), nullable=False)
    source_id = Column(Text, nullable=False)
    status = Column(Text, nullable=False)           # "seed" | "verified" | "pending_review" | "rejected"
    observed_at = Column(DateTime(timezone=True), nullable=True)
    run_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))  # the inline UTC default models.py uses

class PriceSyncRun(Base):
    __tablename__ = "price_sync_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime(timezone=True), nullable=False)   # no default: run_sync binds it explicitly
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Text, nullable=False)           # "running" | "completed" | "partial" | "failed"
    summary = Column(JSON, nullable=True)           # {"sources": {...}, "channels": {model_id: result}, "errors": [...]}
    changes = Column(Integer, nullable=False, default=0)
    pending = Column(Integer, nullable=False, default=0)
```

### backend/pricing_sources.py (pure data + classification, no DB, no network)

```python
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
PROVIDER_ORDER = ("anthropic", "amazon", "openai")
FAMILY_ORDER: tuple[str, ...]  # byte-identical to frontend/src/lib/sortModels.ts FAMILY_ORDER (19 strings)

@dataclass(frozen=True)
class PriceIdentity:
    family_key: str   # "claude-fable-5-1", "claude-opus-4-6", "claude-haiku-4-5", "nova-2-lite", "gpt-6-astra", "gpt-5.6-sol", "gpt-5.4", ...
    family: str       # FAMILY_ORDER string: "Claude Opus 5.5", "Nova 2.0 Lite", "GPT 5.6 Sol", ...
    provider: str     # "anthropic" | "amazon" | "openai"
    channel: str      # "cp" | "global" | "us" | "inregion:us-east-1" ...
    source_kind: str  # "offer" | "pricelist" | "anthropic_doc"
    source_ref: str   # offer: FM id ("anthropic.claude-opus-4-6-v1", "anthropic.claude-haiku-4-5-20251001-v1:0", "openai.gpt-6-sol");
                      # pricelist: family_key (look up NOVA_USAGETYPES); anthropic_doc: exact doc model name ("Claude Opus 5.5")

def price_identity(model_id: str) -> PriceIdentity | None
def tier_of(channel: str) -> str             # "cp" | "global" | "us" | "in_region"; ValueError for anything else
def region_of(channel: str) -> str | None    # "inregion:us-east-1" -> "us-east-1", else None
def active_channels(models: Mapping[str, str], hidden: Sequence[str]) -> dict[str, PriceIdentity]
    # models = {model_id: label}; drops labels containing any hidden pattern silently; drops unclassifiable ids with a warning log
NOVA_USAGETYPES: dict[str, tuple[str, str]] = {"nova-2-lite": ("USE1-Nova2.0Lite-input-tokens", "USE1-Nova2.0Lite-output-tokens")}
ANTHROPIC_DOC_NAMES: dict[str, str]          # family_key -> exact Anthropic doc model name (9 CP families)
ANTHROPIC_PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
ANTHROPIC_SOURCE_ID = "anthropic-pricing"
def offer_source_id(offer_id: str) -> str    # "offer:<offerId>"
def pricelist_source_id(usagetype: str) -> str  # "pricelist:<usagetype>"
def official_source_id(slug: str) -> str     # "official:<slug>"        (added, used by pricing_payload)
def note_source_id(family_key: str) -> str   # "note:<family_key>"      (added, used by pricing_payload, pricing_export)
OFFER_REFERENCE_URL = "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html"   # (added)
PRICELIST_REFERENCE_URL = "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html"  # (added)
ANTHROPIC_REFERENCE_URL = "https://platform.claude.com/docs/en/about-claude/pricing#model-pricing"                            # (added)
DISCLAIMER: dict[str, str]                   # {"ko": ..., "en": ...} exact spec text
OFFICIAL_PAGES: list[dict]                   # [{"slug", "title_en", "title_ko", "url"}]: Bedrock pricing + 8 OpenAI model cards
PRICE_NOTES: list[dict]                      # spec format; one entry for "gpt-5.6-sol"
```

Real active model_ids (production /api/models, 2026-09-26) that `price_identity` must classify (pinned in `backend/tests/pricing_catalog.py`, Task 1):
- Bedrock Global 10: global.anthropic.claude-{fable-5-1,fable-5,opus-5-5,opus-5,opus-4-8,opus-4-7,opus-4-6-v1,sonnet-5,sonnet-4-6,haiku-4-5-20251001-v1:0}
- Bedrock US 10: us.anthropic.<same 10>
- Nova: us.amazon.nova-2-lite-v1:0
- CP 9: anthropic:claude-{fable-5-1,fable-5,opus-5-5,opus-5,opus-4-8,opus-4-7,sonnet-5,sonnet-4-6,haiku-4-5-20251001}
- OpenAI 25: openai:global:global.openai.gpt-6-{astra,sol,luna}, openai:us:us.openai.gpt-6-{astra,sol,luna}, openai:us-west-2:openai.gpt-6-astra,
  openai:us-east-1:openai.gpt-6-{sol,luna}, openai:global:global.openai.gpt-5.6-{sol,terra,luna}, openai:us-east-1:openai.gpt-5.6-{sol,terra,luna},
  openai:us-east-2:openai.gpt-5.6-{sol,terra,luna}, openai:us-west-2:openai.gpt-5.6-{terra,luna}, openai:us-east-{1,2}:openai.gpt-5.5, openai:us-{east-1,east-2,west-2}:openai.gpt-5.4
- Hidden/dormant 1P ids look like openai:1p:gpt-5.x with labels "OpenAI GPT 5.x (1P)" and must be excluded by `active_channels` via hidden patterns. `price_identity` also returns `None` for them (no 1P price tier).

### backend/pricing_seed.py

```python
SEED: dict[str, tuple[float, float, str]]      # model_id -> (input, output, source_id) for all 46 non-CP active channels (official values, Claude US +10%, Nova 0.33/2.75)
CP_SEED: dict[str, tuple[float, float, str]]   # family_key -> (input, output, ANTHROPIC_SOURCE_ID) for the 9 CP families
SEED_SOURCE_DATE = date(2026, 9, 26)
def seed_rows(active: Mapping[str, PriceIdentity]) -> dict[str, tuple[float, float, str]]  # model_id -> seed for active ids (CP via family_key); ids without a seed are logged and left out
def ensure_seed(engine, active: Mapping[str, PriceIdentity]) -> int   # rows inserted; per-model_id idempotent; own transaction; pg_advisory_xact_lock(917350003) on PostgreSQL; raises (callers catch)
```

### backend/pricing_parsers.py (pure)

```python
class PriceParseError(ValueError): ...
@dataclass(frozen=True)
class UnitPrice:
    input: Decimal
    output: Decimal
DIMENSION_RE: re.Pattern  # spec regex, rc allow-list APN2|USE1|USE2|USW2
def single_public_offer(response: dict) -> tuple[str, list[dict]]   # (offer_id, rate_card); raises PriceParseError unless exactly one offer
def select_offer_price(rate_card: list[dict], channel: str) -> UnitPrice | None   # spec selection order per channel; None for "cp" and unknown regions
def parse_pricelist(price_list: list, input_usagetype: str, output_usagetype: str) -> UnitPrice   # items are JSON strings or dicts as returned by pricing.get_products; x1000 from "1K tokens"; raises PriceParseError
def parse_anthropic_pricing_md(markdown: str) -> dict[str, UnitPrice]   # cleaned doc model name -> price; raises PriceParseError if the table/headers are missing
```

### backend/pricing_sync.py

```python
CHANGE_THRESHOLD = Decimal("0.5")
SYNC_DEADLINE_S = 300.0
SYNC_LOCK_KEY = 917350004
USER_AGENT = "bedrock-llm-monitor-pricing-sync (+https://github.com/whchoi98/model-monitoring)"   # (added)
AWS_REGION = "us-east-1"                                                                          # (added)
@dataclass
class Fetchers:
    offers: Callable[[str], dict]            # FM id -> list_foundation_model_agreement_offers response
    pricelist: Callable[[str, str], list]    # (input_usagetype, output_usagetype) -> PriceList items
    anthropic_doc: Callable[[], str]         # markdown text
def default_fetchers(*, bedrock=None, pricing=None, http=None, sleep=time.sleep) -> Fetchers
    # boto3 bedrock and pricing clients in us-east-1 (botocore retries off), httpx GET with USER_AGENT; up to 3 retries after the
    # first attempt, 1 s / 2 s / 4 s (keyword-only injection points are additions; a call without arguments is the contract)
def classify_change(current: tuple[float, float] | None, new: UnitPrice) -> str   # "unchanged" | "changed" | "pending" | "no_baseline"
def run_sync(session_factory, active: Mapping[str, PriceIdentity], fetchers: Fetchers, *,
             now: Callable[[], datetime] | None = None, deadline_s: float = SYNC_DEADLINE_S) -> int   # returns price_sync_runs.id
```

### backend/pricing_sync_runner.py
`main(argv: list[str] | None = None) -> int`; CLI `python -m pricing_sync_runner --once`: create_tables, register CP/OpenAI models (`prober._discover_anthropic_models`, `prober._register_openai_models`, each non-fatal), `active_channels(AVAILABLE_MODELS, hidden_patterns())`, `ensure_seed`, `run_sync` under `pg_advisory_lock(SYNC_LOCK_KEY)` (skip the lock on SQLite), log summary, `_finish(code)` = dispose engine, flush logs, `os._exit(code)`. Exit 0 for `completed` and `partial`; exit 1 for `failed`, a held lock, and a failure of `create_tables`, `ensure_seed` or `run_sync`.

### backend/price_history.py

```python
EFFECTIVE_STATUSES = ("seed", "verified")                    # (added)
def as_utc(value: datetime | None) -> datetime | None        # (added) SQLite returns naive datetimes; every stored value is UTC
def effective_prices_subquery():            # Subquery columns: model_id, input_per_mtok, output_per_mtok, effective_from, effective_to (LEAD over (model_id) ORDER BY effective_from, id), status IN ('seed','verified')
def with_row_cost(query):                   # -> (query, row_cost) : outer-joins a ProbeResult query with effective prices on model_id + timestamp range; row_cost float or NULL
def current_rows(db, model_ids, *, now: datetime | None = None) -> dict[str, PriceHistory]    # effective at `now` (default: current UTC time; `now` added for the payload builder)
def pending_rows(db, model_ids) -> dict[str, PriceHistory]    # latest pending_review per model_id
def last_finished_run(db) -> PriceSyncRun | None              # latest run with finished_at not null (any status)
def verification_of(row: PriceHistory | None, last_run: PriceSyncRun | None) -> str   # "seed_only" | "verified" | "stale" | "none"
```

### backend/pricing_payload.py

```python
def build_pricing_payload(db, active: Mapping[str, PriceIdentity], *, now: datetime) -> dict   # exact /api/pricing JSON (spec)
def price_number(v: float) -> float | int   # <= 6 decimals, trailing zeros removed (4.0 -> 4, 4.40 -> 4.4)
def price_text(v: float) -> str            # same rule as text for CSV and Markdown, never scientific notation
def iso_z(value: datetime | None) -> str | None   # (added) "YYYY-MM-DDTHH:MM:SSZ" in UTC
```

### backend/pricing_export.py

```python
EXPORT_FORMATS = ("csv", "md", "json"); LANGS = ("ko", "en"); BOM = chr(0xFEFF)   # (added)
def to_json(payload: dict) -> str
def to_markdown(payload: dict, lang: str) -> str
def to_csv(payload: dict, lang: str) -> str   # UTF-8 BOM, first line "# <disclaimer>"
def export_filename(fmt: str, today: date) -> str   # llm-monitor-unit-prices-YYYY-MM-DD.<csv|md|json>; ValueError for another format
```

### backend/routers/pricing.py

```python
router = APIRouter(prefix="/api/pricing", tags=["pricing"])
#   GET ""        -> build_pricing_payload (60 s in-process cache, CACHE_TTL_S = 60.0)
#   GET "/export" -> format=csv|md|json (required), lang=ko|en (default ko), Content-Disposition attachment; 422 otherwise
admin_router = APIRouter(prefix="/api/admin/pricing", tags=["admin"])
#   GET "/pending"; POST "/pending/{row_id}/approve"; POST "/pending/{row_id}/reject"  (admin only; 404 unknown id, 409 not pending_review)
def invalidate_cache() -> None
CP_RECENT_DAYS = 30   # (added) CP model_ids observed in price_history within 30 days join the active set
_monotonic            # (added) test patch point for the cache clock
```
Both routers are registered in backend/main.py.

### Frontend

```ts
// frontend/src/lib/types.ts
export type PriceVerification = "verified" | "stale" | "seed_only" | "none";
export interface PricingPending { id: number; input: number; output: number; observed_at: string }
export interface PricingTier { input: number; output: number; model_ids: string[]; source_ids: string[]; footnotes: number[];
  verification: PriceVerification; observed_at: string | null; pending: PricingPending | null }
export interface PricingInRegionTier extends PricingTier { regions: string[] }
export interface PricingNote { family_key: string; kind: "promo"; min_until: string;
  prior_price: Record<string, { input: number; output: number }>; text_ko: string; text_en: string; source: "manual_note" }
export interface PricingFamily { family_key: string; family: string; provider: "anthropic" | "amazon" | "openai";
  tiers: { cp: PricingTier | null; global: PricingTier | null; us: PricingTier | null; in_region: PricingInRegionTier[] }; notes: PricingNote[] }
export interface PricingReference { n: number; id: string; kind: "agreement_offer" | "price_list" | "anthropic_doc" | "official_page" | "manual_note";
  title_en: string; title_ko: string; url: string | null; as_of: string | null }
export interface PricingModelPrice { input: number; output: number; verification: PriceVerification }
export interface PricingResponse { currency: "USD"; unit: "per_1m_tokens"; generated_at: string;
  last_sync: { id: number; started_at: string; finished_at: string | null; status: string } | null; pending_review: number;
  families: PricingFamily[]; models: Record<string, PricingModelPrice>; references: PricingReference[]; disclaimer: { en: string; ko: string } }

// frontend/src/lib/api.ts
export function fetchPricing(signal?: AbortSignal): Promise<PricingResponse>
export function pricingExportUrl(format: "csv" | "md" | "json", lang: "ko" | "en"): string   // "/api/pricing/export?format=..&lang=.."

// frontend/src/lib/pricingTable.ts (pure; no sorting, no numbering)
export function formatUnitPrice(v: number): string            // "$4.00"
export function formatPricePair(t: { input: number; output: number }): string   // "$4.00 / $20.00"
export type PricingBadge = { kind: "unverified" | "pending" | "promo" | "promo_check"; label: string; title: string }
export function tierBadges(tier: PricingTier, notes: PricingNote[], lang: "ko" | "en", today: Date): PricingBadge[]
export function costFromPrices(models: Record<string, PricingModelPrice> | null | undefined, modelId: string,
  inputTokens: number | null | undefined, outputTokens: number | null | undefined): number | null
// (added) PricingTierKey ("cp" | "global" | "us" | "in_region"), TIER_LABELS, utcDate(value: string | null | undefined): string | null,
//         notesForTier(notes: PricingNote[], tier: PricingTierKey): PricingNote[] — tierBadges has no tier key, so callers narrow
//         the notes (and their prior_price) to one tier with notesForTier first
```
- `frontend/src/components/PricingPanel.tsx` (default export; **(added)** named exports `PricingContent({ data, lang, today, highlight, onFootnote })` and `providerSections(families)` for the static-render vitest), `frontend/src/app/pricing/page.tsx`, nav item `{ key: "pricing", label: L("Unit Prices", "비용 단가"), href: "/pricing" }` right after the `cost` item in `frontend/src/components/AppHeader.tsx`.
- `frontend/src/lib/pricing.ts` keeps only `formatCost` (PRICE_TABLE, getPricing, estimateCost removed).
- **(added)** `frontend/src/components/ComparePanel.tsx` exports `compareMatrix(runs, prices)` and `RunningState` (Comparison Lab is not mounted by any route, so vitest covers its cost); `frontend/e2e/fixtures.ts` exports `pricingFixture: PricingResponse`, shared by vitest and e2e.

### Accepted deviations (behaviour decided while planning)

1. **Shared test data modules** (not collected by pytest): `backend/tests/pricing_catalog.py` (the 55 real channels, labels, dormant 1P ids, the 2026-09-23 CP discovery order; Task 1), `backend/tests/_legacy_pricing_v2291.py` (frozen v2.29.1 price table, equivalence test only; Task 6) and `backend/tests/_pricing_dataset.py` (payload and export golden dataset; Task 7).
2. **Classification is allow-listed.** OpenAI in-region ids classify only for `us-east-1`, `us-east-2`, `us-west-2` (the offer dimension prefixes that exist); Nova is the exact id `us.amazon.nova-2-lite-v1:0`. A new region or id returns `None` (cost "-") until the mapping grows. `_is_point_release_of` is duplicated in `pricing_sources` (prober pulls in boto3 and the DB); a test pins it to `prober._match_anthropic_model`.
3. **Seed tables** are built from compact per-FM tables in `pricing_seed.py`; values equal the explicit spec values and are pinned by the tests' own literal tables. `PRICE_NOTES.prior_price` keeps the spec literals (`5.5`, `33`, `5`, `30`).
4. **Sync fetch order** is Anthropic doc → Price List → offers (the spec does not order them), so slow offers cannot push the cheap sources into `skipped:deadline`. The deadline is checked only before each call; an in-flight call (with retries) is not cut. Retries: up to 3 after the first attempt, 1/2/4 s, for Throttling codes, HTTP 5xx and 429, botocore connection errors and httpx transport errors; botocore's own retries are off.
5. **Channel results** add `rejected` (the observed value equals a `rejected` row: only `observed_at` is refreshed, it is a successful observation and not counted as pending). `no_baseline` reuses a pending or rejected row of the same value too, so a new model does not add a pending row every 12 hours. `unchanged` also refreshes `source_id` (a reissued offerId). `PriceSyncRun.changes` = new verified rows, `pending` = channels waiting for review after the run, `summary.errors` capped at 50.
6. **Run status**: `failed` when no channel got an official value (all sources failed, empty active set, deadline before the first call); `partial` when any channel is `skipped:<reason>` or a source had no active channel (CP discovery failed → `"anthropic_doc: no active channels"`); otherwise `completed`.
7. **Runner**: if `ensure_seed` fails the sync does not run (exit 1) — syncing without seeds would create `no_baseline` rows and, by the per-model_id idempotency rule, block the seed forever. A held lock also exits 1 (spec: "즉시 종료(로그만)").
8. **Parsers fail closed** beyond the spec: offer entries whose `unit` is not `"Units"` are ignored; a dimension or document model name that appears twice with different values is dropped; an unknown `inregion:` region returns `None` instead of falling back to the flat scheme; Price List needs exactly one product and one OnDemand dimension.
9. **`pricing_sync` does not import `price_history`**: it keeps a private `_effective_row` with the same meaning (status seed/verified, `effective_from <=` run start, latest `(effective_from, id)`), so Tasks 4-5 do not depend on Task 6.
10. **Payload**: cells of one tier are grouped by (price, verification, pending value), so one element never mixes states; `cp`/`global`/`us` show the group with the best verification. Agreement-offer and Price List reference titles are defined in `pricing_payload` (offerId or usagetype plus the family names). `official_page` and `manual_note` references carry `as_of: null`, and a `manual_note` has `url: null`. The spec's auxiliary CP anchor `#claude-platform-on-aws-pricing` is carried only by the Anthropic reference title ("Claude Platform on AWS uses standard pricing"), because a reference has a single `url`. `pending_review` counts the pending rows of active model_ids; the admin list shows every pending row.
11. **Markdown export** prints prices with `price_text` and no `$` (GFM inline math cannot trigger) and adds a notes item "6. 최종 가격은 공식 요금 페이지에서 확인한다[^8][^9]." so every footnote definition is referenced in payload order (GFM drops unreferenced definitions and renumbers by first reference).
12. **Admin endpoints** return 404 for an unknown id and 409 for a row that is not `pending_review`; export `format` is required. `routers/pricing.py` reuses `routers.admin._ensure_admin`. The cost trend normalizes naive SQLite timestamps with `as_utc` before bucketing (no change on PostgreSQL).
13. **Frontend**: `verification: "none"` shows no badge. Chromium sends `<a download>` requests through the download manager, bypassing `page.route` and `context.route`, so the e2e asserts `href`/`download` and fetches each href in the page to check `Content-Disposition`. Model Explorer shows a separate retryable error for `/api/pricing`, and its Refresh refetches the catalog and the prices together. The promo tooltip's basis date (2026-09-23) comes from the backend `PRICE_NOTES` text.
14. **CDK**: the L2 `EcsRunFargateTask` target already adds a revision-pinned `ecs:RunTask` and a PassRole for each target's role; the explicit `PassTaskRoles` entry keeps the ADR-011 explicit set complete. `PricingSyncTaskRole` gets a resource-level cdk-nag `AwsSolutions-IAM5` suppression with an accurate reason. `cdk/test/image-pinning.test.ts` pins the number of scheduler task definitions (5 → 6).
15. **Docs**: exact test file names are listed in `backend/tests/CLAUDE.md` and `backend/routers/CLAUDE.md`; the README `/pricing` screenshot is taken from production after deploy (not in this plan); the git tag `v2.30.0` is created at the merge to `main`.

## File Map

Every repository file the plan creates, modifies or deletes, with its owning task. Tasks 9-12 run in the frontend worktree, Task 13 in the CDK worktree (see Execution Order).

| File | Change | Task |
|---|---|---|
| `backend/models.py` | Modify | 1 |
| `backend/pricing_sources.py` | Create | 1 |
| `backend/tests/pricing_catalog.py` | Create | 1 |
| `backend/tests/test_pricing_sources.py` | Create | 1 |
| `backend/main.py` | Modify | 2, 8, 14 |
| `backend/pricing_seed.py` | Create | 2 |
| `backend/tests/test_pricing_seed.py` | Create | 2 |
| `backend/pricing_parsers.py` | Create | 3 |
| `backend/tests/fixtures/pricing/anthropic_pricing.md` | Create | 3 |
| `backend/tests/fixtures/pricing/offers_claude-haiku-4-5.json` | Create | 3 |
| `backend/tests/fixtures/pricing/offers_claude-opus-5-5.json` | Create | 3 |
| `backend/tests/fixtures/pricing/offers_claude-sonnet-4-6.json` | Create | 3 |
| `backend/tests/fixtures/pricing/offers_gpt-5.4.json` | Create | 3 |
| `backend/tests/fixtures/pricing/offers_gpt-6-astra.json` | Create | 3 |
| `backend/tests/fixtures/pricing/pricelist_nova-2-lite.json` | Create | 3 |
| `backend/tests/test_pricing_parsers.py` | Create | 3 |
| `backend/pricing_sync.py` | Create | 4 |
| `backend/tests/test_pricing_sync.py` | Create | 4 |
| `backend/pricing_sync_runner.py` | Create | 5 |
| `backend/tests/test_pricing_sync_runner.py` | Create | 5 |
| `backend/price_history.py` | Create | 6 |
| `backend/pricing.py` | Delete | 6 |
| `backend/routers/cost.py` | Modify | 6 |
| `backend/routers/efficiency.py` | Modify | 6 |
| `backend/tests/_legacy_pricing_v2291.py` | Create | 6 |
| `backend/tests/test_cost_time_effective.py` | Create | 6 |
| `backend/tests/test_fable51_catalog.py` | Modify | 6 |
| `backend/tests/test_openai_pricing.py` | Modify | 6 |
| `backend/tests/test_opus55_gpt6_catalog.py` | Modify | 6 |
| `backend/tests/test_price_history.py` | Create | 6 |
| `backend/pricing_export.py` | Create | 7 |
| `backend/pricing_payload.py` | Create | 7 |
| `backend/tests/_pricing_dataset.py` | Create | 7 |
| `backend/tests/test_pricing_export.py` | Create | 7 |
| `backend/tests/test_pricing_payload.py` | Create | 7 |
| `backend/routers/pricing.py` | Create | 8 |
| `backend/tests/test_pricing_router.py` | Create | 8 |
| `backend/CLAUDE.md` | Modify | 14 |
| `backend/routers/CLAUDE.md` | Modify | 14 |
| `backend/tests/CLAUDE.md` | Modify | 14 |
| `frontend/src/lib/api.ts` | Modify | 9 |
| `frontend/src/lib/pricingTable.test.ts` | Create | 9 |
| `frontend/src/lib/pricingTable.ts` | Create | 9 |
| `frontend/src/lib/types.ts` | Modify | 9 |
| `frontend/e2e/fixtures.ts` | Modify | 10, 12 |
| `frontend/src/app/pricing/page.tsx` | Create | 10 |
| `frontend/src/components/AppHeader.tsx` | Modify | 10 |
| `frontend/src/components/PricingPanel.test.tsx` | Create | 10 |
| `frontend/src/components/PricingPanel.tsx` | Create | 10 |
| `frontend/src/components/ComparePanel.test.ts` | Create | 11 |
| `frontend/src/components/ComparePanel.tsx` | Modify | 11 |
| `frontend/src/components/CostDashboardPanel.tsx` | Modify | 11 |
| `frontend/src/components/ModelExplorer.tsx` | Modify | 11 |
| `frontend/src/lib/pricing.test.ts` | Modify | 11 |
| `frontend/src/lib/pricing.ts` | Modify | 11 |
| `frontend/e2e/pricing.spec.ts` | Create | 12 |
| `frontend/CLAUDE.md` | Modify | 14 |
| `frontend/package-lock.json` | Modify | 14 |
| `frontend/package.json` | Modify | 14 |
| `frontend/src/app/CLAUDE.md` | Modify | 14 |
| `frontend/src/components/CLAUDE.md` | Modify | 14 |
| `frontend/src/lib/CLAUDE.md` | Modify | 14 |
| `frontend/src/lib/version.ts` | Modify | 14 |
| `cdk/lib/stacks/scheduler-stack.ts` | Modify | 13 |
| `cdk/test/image-pinning.test.ts` | Modify | 13 |
| `cdk/test/scheduler-stack.test.ts` | Modify | 13 |
| `cdk/CLAUDE.md` | Modify | 14 |
| `AGENTS.md` | Modify | 14 |
| `CHANGELOG.md` | Modify | 14 |
| `CLAUDE.md` | Modify | 14 |
| `README.md` | Modify | 14 |
| `docs/api-reference.md` | Modify | 14 |
| `docs/architecture.md` | Modify | 14 |
| `docs/decisions/ADR-025-openai-global-cris-channels.md` | Modify | 14 |
| `docs/decisions/ADR-028-claude-opus-5-5-and-gpt-6-sol-luna.md` | Modify | 14 |
| `docs/decisions/ADR-030-pricing-auto-sync-time-effective-cost.md` | Create | 14 |
| `docs/onboarding.md` | Modify | 14 |
| `docs/runbooks/deploy.md` | Modify | 14 |
| `docs/runbooks/rollback.md` | Modify | 14 |
| `docs/runbooks/troubleshooting.md` | Modify | 14 |

Not committed (written next to the block extractor, outside the repository): every `@scratch/patches/*.patch` block, `@scratch/e2_doccheck.py` and `@scratch/mermaid-check.cjs` (Task 14).

## Execution Order

```text
backend  (branch feat/v2-30-pricing-menu, sequential)
  Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8
frontend (worktree, branch feat/v2-30-pricing-frontend from 91008c6, sequential, in parallel with backend)
  Task 9 → Task 10 → Task 11 → Task 12        (depends on the API shape only, through e2e/fixtures.ts)
cdk      (worktree, branch feat/v2-30-pricing-cdk from 91008c6, in parallel)
  Task 13                                      (depends only on the CLI name `python -m pricing_sync_runner --once`)
merge    frontend and cdk branches into feat/v2-30-pricing-menu, run every suite
release  Task 14 (docs and version bump) last
```

1. **Backend (Tasks 1-8)** run in order on `feat/v2-30-pricing-menu`. Tasks 3-5 depend on Tasks 1-2 (models, `pricing_sources`, `pricing_seed`); Task 6 on Tasks 1-2; Task 7 on Task 6; Task 8 on Task 7. Task 2 and Task 8 both edit `backend/main.py`: Task 2 inserts the seed block in the lifespan (after the label repair, before `yield`, so `yield` moves from line 163 to 175), and Task 8's anchors (import after line 27, include lines after line 257) already assume that change.
2. **Frontend (Tasks 9-12)** in a separate worktree, in parallel with the backend:
   ```bash
   cd /home/ec2-user/my-project/model-monitoring
   git worktree add -b feat/v2-30-pricing-frontend ../model-monitoring-frontend 91008c6
   cp -a frontend/node_modules ../model-monitoring-frontend/frontend/
   ```
   It touches no backend file; the tests use `frontend/e2e/fixtures.ts` `pricingFixture` in place of the API.
3. **CDK (Task 13)** in its own worktree in parallel (or on the backend branch after Task 8; it touches only `cdk/`):
   ```bash
   cd /home/ec2-user/my-project/model-monitoring
   git worktree add -b feat/v2-30-pricing-cdk ../model-monitoring-cdk 91008c6
   ln -s /home/ec2-user/my-project/model-monitoring/cdk/node_modules ../model-monitoring-cdk/cdk/node_modules
   cp cdk/cdk.context.json ../model-monitoring-cdk/cdk/
   ```
4. **Merge** (after Tasks 8, 12 and 13), then run every suite once on the merged tree:
   ```bash
   cd /home/ec2-user/my-project/model-monitoring
   git merge --no-ff feat/v2-30-pricing-frontend -m "Merge branch 'feat/v2-30-pricing-frontend' into feat/v2-30-pricing-menu"
   git merge --no-ff feat/v2-30-pricing-cdk -m "Merge branch 'feat/v2-30-pricing-cdk' into feat/v2-30-pricing-menu"
   (cd backend && python3.12 -m pytest tests/ -q)          # 706 passed
   (cd frontend && npm test && npm run typecheck)            # 15 files, 249 tests
   (cd frontend && npm run build && PLAYWRIGHT_USE_PRODUCTION=1 CI=1 npx playwright test --project=chromium)   # 100 passed
   (cd cdk && npm test)                                      # 10 suites, 85 tests
   git checkout -- frontend/next-env.d.ts frontend/CLAUDE.md AGENTS.md
   # after both merges succeeded (the worktrees hold only copied node_modules, build output and cdk.context.json):
   git worktree remove --force ../model-monitoring-frontend && git worktree remove --force ../model-monitoring-cdk
   ```
   The branches touch disjoint files, so both merges are conflict-free.
5. **Task 14** last, on the merged `feat/v2-30-pricing-menu`.
6. **After Task 14 (controller, outside this plan)**: add `pricing_sources.py` and `pricing_seed.py` to the model-add checklist in the user auto-memory file `adding-a-monitored-model.md` (outside the repository; the in-repo checklist is in root `CLAUDE.md` and `backend/CLAUDE.md` from Task 14), open the PR, deploy by `docs/runbooks/deploy.md` §5-4 (digest-pinned `--exclusively BedrockMonitor-AppServices BedrockMonitor-Scheduler`, then one manual PricingSync `run-task` and the checks listed there), take the README `/pricing` screenshot from production, and tag `v2.30.0` at the merge to `main`.

### Applying plan blocks

The Appendix holds about 590 KB of exact file contents and patches; the extractor writes them and checks each against its sha256. Create the extractor once per agent in a scratch directory outside the repository. In the tasks, `"$PB"` stands for the extractor path this bootstrap prints; shell variables do not persist between tool calls, so write the path literally or prefix each command with `PB=<path>`.

```bash
S=<your scratchpad>/pricing-plan-blocks; mkdir -p "$S" && python3 - "$S" <<'PY'
import re, sys
plan = "/home/ec2-user/my-project/model-monitoring/docs/superpowers/plans/2026-09-26-pricing-menu.md"
text = open(plan, encoding="utf-8").read()
src = re.search(r"<!-- plan-extractor -->\n```python\n(.*?)\n```\n", text, re.S).group(1)
open(sys.argv[1] + "/plan_blocks.py", "w", encoding="utf-8").write(src + "\n")
print(sys.argv[1] + "/plan_blocks.py")
PY
python3 <printed path> --verify      # expected: "55 blocks OK"
```

Then, from the repository or worktree you work in (repository paths are written under its git top level):

- `python3 "$PB" <id> [<id> ...]` writes file blocks, and patch blocks to `<extractor dir>/patches/<id>.patch`.
- `python3 "$PB" --apply <id> [<id> ...]` writes each patch block and runs `git apply --check` then `git apply` (it stops on the first failure and changes nothing for that patch).
- `python3 "$PB" --list` lists ids, sizes and target paths.

The plan file itself stays in the main checkout (`/home/ec2-user/my-project/model-monitoring/docs/superpowers/plans/2026-09-26-pricing-menu.md`), so worktrees read it from there; set `PLAN=<path>` if it moves.

<!-- plan-extractor -->
```python
"""Plan block extractor for docs/superpowers/plans/2026-09-26-pricing-menu.md (v2.30.0). Python 3.9+.

usage: python3 plan_blocks.py ID [ID ...]          write the blocks (sha256-checked)
       python3 plan_blocks.py --apply ID [ID ...]  write patch blocks, then `git apply --check` + `git apply` each
       python3 plan_blocks.py --verify             check every block of the plan against its sha256
       python3 plan_blocks.py --list               list block ids and target paths

A block is announced in the plan by `<!-- plan-block id=<id> path=<path> sha256=<hex> -->` followed by a fenced
code block; the body is the fence content plus a final newline. Repository paths are written under the git top
level of the current directory (run from the repository or worktree you are working in). Paths starting with
`@scratch/` (patches and one-off tools, never committed) are written next to this script.
Env PLAN overrides the plan path.
"""

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PLAN = os.environ.get(
    "PLAN", "/home/ec2-user/my-project/model-monitoring/docs/superpowers/plans/2026-09-26-pricing-menu.md")
MARK = re.compile(r"^<!-- plan-block id=(\S+) path=(\S+) sha256=([0-9a-f]{64}) -->$")
FENCE = re.compile(r"^(`{3,})")


def read_blocks():
    lines = Path(PLAN).read_text(encoding="utf-8").split("\n")
    found, i = {}, 0
    while i < len(lines):
        m = MARK.match(lines[i])
        if m:
            fence = FENCE.match(lines[i + 1]).group(1)
            j = i + 2
            while lines[j] != fence:
                j += 1
            found[m.group(1)] = (m.group(2), m.group(3), "\n".join(lines[i + 2:j]) + "\n")
            i = j
        i += 1
    return found


def repo_root():
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def target(path):
    if path.startswith("@scratch/"):
        return Path(__file__).resolve().parent / path[len("@scratch/"):]
    return repo_root() / path


def main(argv):
    blocks = read_blocks()
    if argv[:1] == ["--list"]:
        for bid, (path, _, body) in blocks.items():
            print(f"{bid:24} {len(body.encode('utf-8')):7} {path}")
        return 0
    bad = [bid for bid, (_, sha, body) in blocks.items() if hashlib.sha256(body.encode("utf-8")).hexdigest() != sha]
    if bad:
        print("sha256 mismatch: " + ", ".join(bad), file=sys.stderr)
        return 1
    if argv[:1] == ["--verify"]:
        print(f"{len(blocks)} blocks OK")
        return 0
    apply = argv[:1] == ["--apply"]
    ids = argv[1:] if apply else argv
    for bid in ids:
        if bid not in blocks:
            print(f"unknown block id: {bid}", file=sys.stderr)
            return 1
        path, _, body = blocks[bid]
        dest = target(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body.encode("utf-8"))
        print(f"{bid} -> {dest}")
        if apply:
            if not path.endswith(".patch"):
                print(f"--apply needs a patch block: {bid}", file=sys.stderr)
                return 1
            subprocess.run(["git", "apply", "--check", str(dest)], cwd=repo_root(), check=True)
            subprocess.run(["git", "apply", str(dest)], cwd=repo_root(), check=True)
            print(f"{bid} applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```


---

## Task 1: Price tables (ORM) and price identity module

Shared by later tasks: `backend/tests/pricing_catalog.py` (not collected) holds the 55 real active channels (`EXPECTED_IDENTITY`, `ACTIVE_MODELS` with production labels, `HIDDEN_1P_MODELS`, `CP_MODEL_IDS_20260923`); import it as `from tests.pricing_catalog import ...`. `pricing_sources` also exports the spec's fixed reference URLs (`OFFER_REFERENCE_URL`, `PRICELIST_REFERENCE_URL`, `ANTHROPIC_REFERENCE_URL`, used by Task 7) and `official_source_id` / `note_source_id`.

**Files:**
- Modify: `backend/models.py` lines 244-248 (insert after the last `GptBenchResult` column at line 245, before `def ensure_performance_indexes` at line 248; `_PERF_INDEXES` line 143 unchanged, `create_all` builds the new index with the new table)
- Create: `backend/pricing_sources.py`, `backend/tests/pricing_catalog.py`
- Test: `backend/tests/test_pricing_sources.py`

**Interfaces:**
- Consumes: `database.Base`; tests: `prober._ANTHROPIC_TARGETS`, `_match_anthropic_model`, `_discover_anthropic_models`, `_register_openai_models`, `AVAILABLE_MODELS`, `frontend/src/lib/sortModels.ts` (text)
- Produces: `models.PriceHistory`, `models.PriceSyncRun`; `pricing_sources.EPOCH`, `PROVIDER_ORDER`, `FAMILY_ORDER`, `PriceIdentity`, `price_identity`, `tier_of`, `region_of`, `active_channels`, `NOVA_USAGETYPES`, `ANTHROPIC_DOC_NAMES`, `ANTHROPIC_PRICING_URL`, `ANTHROPIC_SOURCE_ID`, `offer_source_id`, `pricelist_source_id`, `official_source_id`, `note_source_id`, `OFFER_REFERENCE_URL`, `PRICELIST_REFERENCE_URL`, `ANTHROPIC_REFERENCE_URL`, `DISCLAIMER`, `OFFICIAL_PAGES`, `PRICE_NOTES`; `tests.pricing_catalog.*`

- [ ] **Step 1: Write the failing test.** Write blocks `t01-catalog` and `t01-test` (`python3 "$PB" t01-catalog t01-test`).

`backend/tests/pricing_catalog.py`:

<!-- plan-block id=t01-catalog path=backend/tests/pricing_catalog.py sha256=3e9753535f1d205be260cfee9838477e6767ca5b7b924fcda276191d6486face -->
```python
"""pricing 테스트 공용 데이터 — 운영 /api/models(2026-09-26) 활성 55채널 (v2.30.0). 수집 대상 아님."""

_CLAUDE = [  # (FM id, family_key, family) — Global, US가 같은 FM id
    ("anthropic.claude-fable-5-1", "claude-fable-5-1", "Claude Fable 5.1"),
    ("anthropic.claude-fable-5", "claude-fable-5", "Claude Fable 5"),
    ("anthropic.claude-opus-5-5", "claude-opus-5-5", "Claude Opus 5.5"),
    ("anthropic.claude-opus-5", "claude-opus-5", "Claude Opus 5"),
    ("anthropic.claude-opus-4-8", "claude-opus-4-8", "Claude Opus 4.8"),
    ("anthropic.claude-opus-4-7", "claude-opus-4-7", "Claude Opus 4.7"),
    ("anthropic.claude-opus-4-6-v1", "claude-opus-4-6", "Claude Opus 4.6"),
    ("anthropic.claude-sonnet-5", "claude-sonnet-5", "Claude Sonnet 5"),
    ("anthropic.claude-sonnet-4-6", "claude-sonnet-4-6", "Claude Sonnet 4.6"),
    ("anthropic.claude-haiku-4-5-20251001-v1:0", "claude-haiku-4-5", "Claude Haiku 4.5"),
]
# CP 디스커버리 id (Opus 4.6은 CP 채널 없음, Haiku는 날짜 접미사)
_CP_IDS = {
    "claude-fable-5-1": "claude-fable-5-1", "claude-fable-5": "claude-fable-5",
    "claude-opus-5-5": "claude-opus-5-5", "claude-opus-5": "claude-opus-5",
    "claude-opus-4-8": "claude-opus-4-8", "claude-opus-4-7": "claude-opus-4-7",
    "claude-sonnet-5": "claude-sonnet-5", "claude-sonnet-4-6": "claude-sonnet-4-6",
    "claude-haiku-4-5": "claude-haiku-4-5-20251001",
}
_OPENAI = [  # (FM id, family_key, family, channels) — prober _OPENAI_MODEL_SPECS와 같은 리전
    ("openai.gpt-6-astra", "gpt-6-astra", "GPT 6 Astra", ("global", "us", "us-west-2")),
    ("openai.gpt-6-sol", "gpt-6-sol", "GPT 6 Sol", ("global", "us", "us-east-1")),
    ("openai.gpt-6-luna", "gpt-6-luna", "GPT 6 Luna", ("global", "us", "us-east-1")),
    ("openai.gpt-5.6-sol", "gpt-5.6-sol", "GPT 5.6 Sol", ("global", "us-east-1", "us-east-2")),
    ("openai.gpt-5.6-terra", "gpt-5.6-terra", "GPT 5.6 Terra", ("global", "us-east-1", "us-east-2", "us-west-2")),
    ("openai.gpt-5.6-luna", "gpt-5.6-luna", "GPT 5.6 Luna", ("global", "us-east-1", "us-east-2", "us-west-2")),
    ("openai.gpt-5.5", "gpt-5.5", "GPT 5.5", ("us-east-1", "us-east-2")),
    ("openai.gpt-5.4", "gpt-5.4", "GPT 5.4", ("us-east-1", "us-east-2", "us-west-2")),
]


def _openai_id(fm: str, region: str) -> str:
    return f"openai:{region}:{region}.{fm}" if region in ("global", "us") else f"openai:{region}:{fm}"


def _channel(region: str) -> str:
    return region if region in ("global", "us") else f"inregion:{region}"


# model_id → (family_key, family, provider, channel, source_kind, source_ref)
EXPECTED_IDENTITY: dict[str, tuple[str, str, str, str, str, str]] = {
    **{f"{p}.{fm}": (fk, fam, "anthropic", p, "offer", fm) for p in ("global", "us") for fm, fk, fam in _CLAUDE},
    "us.amazon.nova-2-lite-v1:0": ("nova-2-lite", "Nova 2.0 Lite", "amazon", "us", "pricelist", "nova-2-lite"),
    **{f"anthropic:{_CP_IDS[fk]}": (fk, fam, "anthropic", "cp", "anthropic_doc", fam) for _, fk, fam in _CLAUDE if fk in _CP_IDS},
    **{_openai_id(fm, r): (fk, fam, "openai", _channel(r), "offer", fm) for fm, fk, fam, rs in _OPENAI for r in rs},
}


def _label(identity: tuple) -> str:
    _, family, provider, channel, _, _ = identity
    if channel == "cp":
        return f"Anthropic {family} (US)"
    suffix = {"global": "Global", "us": "US"}.get(channel) or channel.split(":", 1)[1]
    return f"{'OpenAI' if provider == 'openai' else 'Bedrock'} {family} ({suffix})"


ACTIVE_MODELS: dict[str, str] = {mid: _label(i) for mid, i in EXPECTED_IDENTITY.items()}  # prober 라벨 규약

HIDDEN_1P_MODELS: dict[str, str] = {  # 휴면 1P — 기본 숨김 패턴 "(1P)"
    f"openai:1p:{fk}": f"OpenAI {fam} (1P)"
    for fk, fam in (("gpt-5.6-sol", "GPT 5.6 Sol"), ("gpt-5.6-terra", "GPT 5.6 Terra"),
                    ("gpt-5.6-luna", "GPT 5.6 Luna"), ("gpt-5.4", "GPT 5.4"), ("gpt-5.5", "GPT 5.5"))
}

# 2026-09-23 CP /v1/models 실측 순서 — 점 버전이 base보다 먼저 온다
CP_MODEL_IDS_20260923 = [
    "claude-opus-5-5", "claude-fable-5-1", "claude-opus-5", "claude-sonnet-5", "claude-fable-5",
    "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-4-6", "claude-opus-4-6",
    "claude-opus-4-5-20251101", "claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929",
]
```

`backend/tests/test_pricing_sources.py`:

<!-- plan-block id=t01-test path=backend/tests/test_pricing_sources.py sha256=b85d9d6976538cfa980dd9feb08cf7bd4cbb26ed70cd57ca9aa55ec4f494bc89 -->
```python
"""단가 식별과 출처 메타데이터 (v2.30.0, ADR-030) — 55채널 정확 분류, 점 버전 안전성(2026-09-23 Opus 5.5 CP
오등록 실사고 유형), prober 등록 결과와 일치, FAMILY_ORDER = frontend sortModels.ts."""

import logging
import pathlib
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect

import models
import prober
import pricing_sources as ps
from pricing_sources import PriceIdentity, active_channels, price_identity, region_of, tier_of
from tests.pricing_catalog import ACTIVE_MODELS, CP_MODEL_IDS_20260923, EXPECTED_IDENTITY, HIDDEN_1P_MODELS

SORT_MODELS_TS = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "sortModels.ts"

_ENV = {
    "ANTHROPIC_API_KEY": "sk-ant-fake", "ANTHROPIC_WORKSPACE_ID": "wrkspc_fake",  # pragma: allowlist secret
    "OPENAI_API_KEY": "ABSK-fake", "OPENAI_1P_API_KEY": "sk-proj-fake",  # pragma: allowlist secret
    "OPENAI_GLOBAL_BASE_URL": "https://gl/v1", "OPENAI_US_BASE_URL": "https://us/v1",
    "OPENAI_US_EAST_1_BASE_URL": "https://e1/v1", "OPENAI_US_EAST_2_BASE_URL": "https://e2/v1",
    "OPENAI_US_WEST_2_BASE_URL": "https://w2/v1",
    **{f"BEDROCK_OPENAI_GPT_{k}_MODEL_ID": f"openai.gpt-{v}" for k, v in (
        ("6_ASTRA", "6-astra"), ("6_SOL", "6-sol"), ("6_LUNA", "6-luna"), ("56_SOL", "5.6-sol"),
        ("56_TERRA", "5.6-terra"), ("56_LUNA", "5.6-luna"), ("54", "5.4"), ("55", "5.5"))},
    **{f"OPENAI_1P_GPT_{k}_MODEL_ID": f"gpt-{v}" for k, v in (
        ("56_SOL", "5.6-sol"), ("56_TERRA", "5.6-terra"), ("56_LUNA", "5.6-luna"), ("54", "5.4"), ("55", "5.5"))},
}


class _FakeAnthropic:
    """_discover_anthropic_models가 부르는 /v1/models만 흉내 낸다(네트워크 없음)."""

    def __init__(self, **kwargs):
        page = SimpleNamespace(data=[SimpleNamespace(id=i) for i in CP_MODEL_IDS_20260923])
        self.models = SimpleNamespace(list=lambda limit=100: page)


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "pricing_sources" and r.levelno >= logging.WARNING]


def test_create_all_creates_price_tables():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    insp = inspect(engine)
    assert {c["name"] for c in insp.get_columns("price_history")} == {
        "id", "model_id", "family_key", "channel", "input_per_mtok", "output_per_mtok", "effective_from",
        "source_id", "status", "observed_at", "run_id", "created_at"}
    assert {c["name"] for c in insp.get_columns("price_sync_runs")} == {
        "id", "started_at", "finished_at", "status", "summary", "changes", "pending"}
    idx = {i["name"]: i["column_names"] for i in insp.get_indexes("price_history")}
    assert idx["ix_price_history_model_eff"] == ["model_id", "effective_from"]
    for table, cols in ((models.PriceHistory, ("effective_from", "observed_at", "created_at")),
                        (models.PriceSyncRun, ("started_at", "finished_at"))):
        assert all(table.__table__.c[c].type.timezone for c in cols)
    assert models.PriceHistory.__table__.c.observed_at.nullable is True


@pytest.mark.parametrize("model_id", sorted(EXPECTED_IDENTITY))
def test_every_real_active_model_id_is_classified(model_id):
    assert price_identity(model_id) == PriceIdentity(*EXPECTED_IDENTITY[model_id])


def test_expected_table_is_the_55_active_channels():
    counts: dict[tuple[str, str], int] = {}
    for _, _, provider, channel, _, _ in EXPECTED_IDENTITY.values():
        counts[(provider, tier_of(channel))] = counts.get((provider, tier_of(channel)), 0) + 1
    assert counts == {("anthropic", "global"): 10, ("anthropic", "us"): 10, ("anthropic", "cp"): 9,
                      ("amazon", "us"): 1, ("openai", "global"): 6, ("openai", "us"): 3, ("openai", "in_region"): 16}


def test_registered_catalog_minus_hidden_is_exactly_the_55_channels(monkeypatch):
    """prober 등록 함수를 운영 env로 실제로 돌린다 — 새 모델, 리전을 넣고 매핑을 잊으면 실패."""
    import anthropic

    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(prober.AVAILABLE_MODELS))
    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)
    for name, value in _ENV.items():
        monkeypatch.setenv(name, value)
    prober._discover_anthropic_models()
    prober._register_openai_models()
    catalog = prober.AVAILABLE_MODELS
    assert {m: lbl for m, lbl in catalog.items() if "(1P)" in lbl} == HIDDEN_1P_MODELS
    active = active_channels(catalog, ["(1P)"])
    assert {m: catalog[m] for m in active} == ACTIVE_MODELS  # 라벨까지 prober 규약과 같다


def test_active_channels_hidden_and_unclassifiable(caplog):
    with caplog.at_level(logging.WARNING, logger="pricing_sources"):
        assert list(active_channels({**HIDDEN_1P_MODELS, **ACTIVE_MODELS}, ["(1P)"])) == list(ACTIVE_MODELS)
    assert _warnings(caplog) == []  # 숨김은 조용히 뺀다
    catalog = {"openai:1p:gpt-5.4": "OpenAI GPT 5.4 (1P)",
               "global.anthropic.claude-sonnet-5-5": "Bedrock Claude Sonnet 5.5 (Global)",
               "global.anthropic.claude-sonnet-5": "Bedrock Claude Sonnet 5 (Global)"}
    with caplog.at_level(logging.WARNING, logger="pricing_sources"):
        assert list(active_channels(catalog, [""])) == ["global.anthropic.claude-sonnet-5"]
    warned = " ".join(_warnings(caplog))
    assert "openai:1p:gpt-5.4" in warned and "claude-sonnet-5-5" in warned


@pytest.mark.parametrize("model_id", [
    *HIDDEN_1P_MODELS, "openai:eu-west-1:openai.gpt-5.4", "openai:global:openai.gpt-6-sol",
    "openai:us-east-1:global.openai.gpt-5.4", "openai:us-east-1:openai.gpt-6-sol-mini", "openai:global",
    "eu.anthropic.claude-opus-5", "anthropic.claude-opus-5", "us.anthropic.claude-opus-5-5-v1:0",
    "global.amazon.nova-2-lite-v1:0", "us.amazon.nova-lite-v1:0", "anthropic:claude-opus-4-6",
    "anthropic:claude-opus-4-5-20251101", "anthropic:claude-sonnet-4-5-20250929", "anthropic:claude-mythos-5-1", "",
])
def test_unclassifiable_model_ids_return_none(model_id):
    assert price_identity(model_id) is None


def test_cp_point_release_safety():
    fk = {m: price_identity(f"anthropic:{m}") for m in (
        "claude-opus-5", "claude-opus-5-5", "claude-fable-5", "claude-fable-5-1", "claude-haiku-4-5-20251001",
        "claude-opus-5-20261015", "claude-fable-5-1-20261015", "claude-sonnet-5-5", "claude-opus-5-6")}
    assert {m: (i.family_key if i else None) for m, i in fk.items()} == {
        "claude-opus-5": "claude-opus-5", "claude-opus-5-5": "claude-opus-5-5",
        "claude-fable-5": "claude-fable-5", "claude-fable-5-1": "claude-fable-5-1",
        "claude-haiku-4-5-20251001": "claude-haiku-4-5",  # 8자리 날짜 접미사는 점 버전이 아니다
        "claude-opus-5-20261015": "claude-opus-5", "claude-fable-5-1-20261015": "claude-fable-5-1",
        "claude-sonnet-5-5": None, "claude-opus-5-6": None,  # 타깃 없는 점 버전은 fail-closed
    }
    assert price_identity("global.anthropic.claude-sonnet-5-5") is None


@pytest.mark.parametrize("actual_id", [
    *CP_MODEL_IDS_20260923, "claude-sonnet-5-5", "claude-opus-5-6", "claude-fable-5-2",
    "claude-opus-5-20261015", "claude-fable-5-1-20261015", "claude-haiku-4-5", "claude-sonnet-4-6-20260101",
])
def test_cp_classification_agrees_with_prober_matching(actual_id):
    ident = price_identity(f"anthropic:{actual_id}")
    hits = [s for s, _ in prober._ANTHROPIC_TARGETS if prober._match_anthropic_model(s, [actual_id]) == actual_id]
    assert (ident.family_key if ident else None) == (f"claude-{hits[0]}" if hits else None)


def test_cp_targets_and_static_labels_mirror_prober():
    assert [fk.removeprefix("claude-") for fk in ps.ANTHROPIC_DOC_NAMES] == [s for s, _ in prober._ANTHROPIC_TARGETS]
    for sub, label in prober._ANTHROPIC_TARGETS:
        assert label == f"Anthropic {price_identity(f'anthropic:claude-{sub}').family} (US)"
    for model_id, label in prober.AVAILABLE_MODELS.items():
        if model_id.startswith(("anthropic:", "openai:")):
            continue  # 런타임 등록 채널은 위 등록 테스트가 본다
        ident = price_identity(model_id)
        assert label == f"Bedrock {ident.family} ({'Global' if ident.channel == 'global' else 'US'})", model_id


def test_family_order_matches_frontend_sort_models():
    m = re.search(r"export const FAMILY_ORDER = \[(.*?)\];", SORT_MODELS_TS.read_text(encoding="utf-8"), re.S)
    assert m and ps.FAMILY_ORDER == tuple(re.findall(r'"([^"]+)"', m.group(1)))
    assert len(ps.FAMILY_ORDER) == 19
    assert {v[1] for v in EXPECTED_IDENTITY.values()} == set(ps.FAMILY_ORDER)
    assert ps.PROVIDER_ORDER == ("anthropic", "amazon", "openai")


def test_tier_of_and_region_of():
    assert [tier_of(c) for c in ("cp", "global", "us", "inregion:us-west-2")] == ["cp", "global", "us", "in_region"]
    with pytest.raises(ValueError):
        tier_of("1p")
    assert (region_of("inregion:us-east-1"), region_of("global")) == ("us-east-1", None)


def test_source_metadata_constants():
    assert ps.offer_source_id("offer-7sp77cpl4rveu") == "offer:offer-7sp77cpl4rveu"
    assert ps.pricelist_source_id("USE1-Nova2.0Lite-input-tokens") == "pricelist:USE1-Nova2.0Lite-input-tokens"
    assert ps.official_source_id("bedrock-pricing") == "official:bedrock-pricing"
    assert ps.note_source_id("gpt-5.6-sol") == "note:gpt-5.6-sol"
    assert ps.ANTHROPIC_SOURCE_ID == "anthropic-pricing"
    assert ps.ANTHROPIC_PRICING_URL == "https://platform.claude.com/docs/en/about-claude/pricing.md"
    assert (ps.OFFER_REFERENCE_URL, ps.PRICELIST_REFERENCE_URL, ps.ANTHROPIC_REFERENCE_URL) == (
        "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html",
        "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html",
        "https://platform.claude.com/docs/en/about-claude/pricing#model-pricing",
    )
    assert ps.NOVA_USAGETYPES == {"nova-2-lite": ("USE1-Nova2.0Lite-input-tokens", "USE1-Nova2.0Lite-output-tokens")}
    assert ps.ANTHROPIC_DOC_NAMES["claude-opus-5-5"] == "Claude Opus 5.5" and len(ps.ANTHROPIC_DOC_NAMES) == 9
    assert ps.EPOCH.isoformat() == "1970-01-01T00:00:00+00:00"
    assert ps.DISCLAIMER == {
        "ko": "이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. "
              "최종 가격은 반드시 공식 사이트에서 확인하세요.",
        "en": "This price list is compiled automatically from public sources for reference only and is not "
              "an official AWS statement. Always confirm final prices on the official pricing pages.",
    }


def test_official_pages_and_price_notes():
    card = "https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-{}.html"
    assert [p["url"] for p in ps.OFFICIAL_PAGES] == ["https://aws.amazon.com/bedrock/pricing/"] + [
        card.format(s) for s in ("gpt-54", "gpt-55", "gpt-56-sol", "gpt-56-terra", "gpt-56-luna",
                                 "gpt-6-astra", "gpt-6-sol", "gpt-6-luna")]
    assert all(set(p) == {"slug", "title_en", "title_ko", "url"} and "·" not in p["title_ko"] for p in ps.OFFICIAL_PAGES)
    assert len({p["slug"] for p in ps.OFFICIAL_PAGES}) == 9
    (note,) = ps.PRICE_NOTES
    assert set(note) == {"family_key", "kind", "min_until", "prior_price", "text_ko", "text_en", "source"}
    assert (note["family_key"], note["kind"], note["min_until"], note["source"]) == (
        "gpt-5.6-sol", "promo", "2026-11-21", "manual_note")
    assert note["prior_price"] == {"in_region": {"input": 5.5, "output": 33}, "global": {"input": 5, "output": 30}}
    assert "2026-11-21" in note["text_ko"] and "·" not in note["text_ko"]
```

- [ ] **Step 2: Run it** — `(cd backend && python3.12 -m pytest tests/test_pricing_sources.py -q)` — Expected: FAIL, collection error `ModuleNotFoundError: No module named 'pricing_sources'`.

- [ ] **Step 3: Implement.**

3a. `backend/models.py` (`python3 "$PB" --apply t01-models` performs exactly this edit): replace

```python
    output_tokens = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)


def ensure_performance_indexes(engine) -> None:
```

with (all names already imported at the top of `models.py`; `autoincrement=True` and the inline `created_at` default follow the file's convention):

```python
    output_tokens = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)


class PriceHistory(Base):
    """모델 채널(model_id)별 토큰 단가 이력 (v2.30.0, ADR-030).

    유효 행 = 같은 model_id에서 status IN ('seed','verified')이고 effective_from <= t인 행 중
    (effective_from, id)가 가장 늦은 행. 비용은 각 프로브 시각의 유효 단가로 계산한다
    (price_history.py). seed 행은 effective_from=1970-01-01Z, observed_at=NULL (pricing_seed.py).
    단가는 float로 저장한다 — numeric은 PostgreSQL에서 Decimal로 돌아와 float 누적과 섞이면 TypeError.
    """

    __tablename__ = "price_history"
    __table_args__ = (
        Index("ix_price_history_model_eff", "model_id", "effective_from"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(Text, nullable=False)          # probe_results.model_id와 같은 값
    family_key = Column(Text, nullable=False)        # claude-opus-5-5 | gpt-6-sol | nova-2-lite ...
    channel = Column(Text, nullable=False)           # cp | global | us | inregion:<aws-region>
    input_per_mtok = Column(Float, nullable=False)   # USD per 1M input tokens
    output_per_mtok = Column(Float, nullable=False)  # USD per 1M output tokens
    effective_from = Column(DateTime(timezone=True), nullable=False)
    source_id = Column(Text, nullable=False)         # offer:<offerId> | pricelist:<usagetype> | anthropic-pricing
    status = Column(Text, nullable=False)            # seed | verified | pending_review | rejected
    observed_at = Column(DateTime(timezone=True), nullable=True)  # 출처에서 마지막으로 확인한 시각, seed는 NULL
    run_id = Column(Integer, nullable=True)          # 이 행을 만든(또는 마지막으로 관측한) price_sync_runs.id
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PriceSyncRun(Base):
    """공식 단가 동기화 런 1회 (v2.30.0) — PricingSync 태스크가 12시간마다 기록.

    런을 시작할 때 status='running' 행을 먼저 넣고, 끝나면 completed | partial | failed로 닫는다.
    summary: {"sources": {출처: {"calls", "ok", "failed"}}, "channels": {model_id: 결과}, "errors": [...]}.
    """

    __tablename__ = "price_sync_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Text, nullable=False)  # running | completed | partial | failed
    summary = Column(JSON, nullable=True)
    changes = Column(Integer, nullable=False, default=0)  # 적용한 새 행 수 (verified)
    pending = Column(Integer, nullable=False, default=0)  # 런 뒤 검토 대기 채널 수 (pending, no_baseline, 재관측 포함)


def ensure_performance_indexes(engine) -> None:
```

3b. Create `backend/pricing_sources.py` (`python3 "$PB" t01-sources`):

<!-- plan-block id=t01-sources path=backend/pricing_sources.py sha256=00d7628d7a74266255a1ccbf6985626e904f9e32c62695396f31f8121777dd06 -->
```python
"""단가 식별과 공식 출처 메타데이터 — 순수 데이터와 분류, DB와 네트워크 없음 (v2.30.0, ADR-030).

price_identity는 전부 정확 일치다(v2.29.1 get_pricing의 prefix fallback이 Claude US를 Global 단가로, Nova 2.0
Lite를 1세대 Nova Lite 단가로 매칭한 오류). CP는 prober _ANTHROPIC_TARGETS와 같은 substring 규칙 + 점 버전 제외.
분류할 수 없으면 None(비용 "-"). 새 모델은 이 매핑과 pricing_seed.py를 함께 고친다(tests가 prober 등록으로 잡는다).
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

logger = logging.getLogger(__name__)

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)  # seed, no_baseline 행의 effective_from
PROVIDER_ORDER: tuple[str, ...] = ("anthropic", "amazon", "openai")
# frontend/src/lib/sortModels.ts FAMILY_ORDER와 바이트 단위로 같아야 한다(tests가 파일을 읽어 고정).
FAMILY_ORDER: tuple[str, ...] = (
    "Claude Fable 5.1", "Claude Fable 5", "Claude Opus 5.5", "Claude Opus 5", "Claude Opus 4.8",
    "Claude Opus 4.7", "Claude Opus 4.6", "Claude Sonnet 5", "Claude Sonnet 4.6", "Claude Haiku 4.5",
    "Nova 2.0 Lite", "GPT 6 Astra", "GPT 6 Sol", "GPT 6 Luna", "GPT 5.6 Sol", "GPT 5.6 Terra",
    "GPT 5.6 Luna", "GPT 5.5", "GPT 5.4",
)


@dataclass(frozen=True)
class PriceIdentity:
    family_key: str   # claude-opus-4-6 | claude-haiku-4-5 | nova-2-lite | gpt-6-astra | gpt-5.6-sol | gpt-5.4 ...
    family: str       # FAMILY_ORDER 문자열
    provider: str     # anthropic | amazon | openai
    channel: str      # cp | global | us | inregion:<aws-region>
    source_kind: str  # offer | pricelist | anthropic_doc
    source_ref: str   # offer: FM id / pricelist: NOVA_USAGETYPES 키 / anthropic_doc: 문서 모델명


# Bedrock Claude offer FM id → (family_key, family). global./us. 접두를 뗀 값과 정확 일치.
_BEDROCK_CLAUDE_FM: dict[str, tuple[str, str]] = {
    "anthropic.claude-fable-5-1": ("claude-fable-5-1", "Claude Fable 5.1"),
    "anthropic.claude-fable-5": ("claude-fable-5", "Claude Fable 5"),
    "anthropic.claude-opus-5-5": ("claude-opus-5-5", "Claude Opus 5.5"),
    "anthropic.claude-opus-5": ("claude-opus-5", "Claude Opus 5"),
    "anthropic.claude-opus-4-8": ("claude-opus-4-8", "Claude Opus 4.8"),
    "anthropic.claude-opus-4-7": ("claude-opus-4-7", "Claude Opus 4.7"),
    "anthropic.claude-opus-4-6-v1": ("claude-opus-4-6", "Claude Opus 4.6"),
    "anthropic.claude-sonnet-5": ("claude-sonnet-5", "Claude Sonnet 5"),
    "anthropic.claude-sonnet-4-6": ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
    "anthropic.claude-haiku-4-5-20251001-v1:0": ("claude-haiku-4-5", "Claude Haiku 4.5"),
}
_CLAUDE_FAMILY_NAMES = {fk: fam for fk, fam in _BEDROCK_CLAUDE_FM.values()}
# CP — prober._ANTHROPIC_TARGETS와 같은 substring, 같은 순서(tests가 고정). family_key = "claude-" + substring.
_CP_TARGETS = ("fable-5-1", "fable-5", "opus-5-5", "opus-5", "opus-4-8", "opus-4-7", "sonnet-5", "sonnet-4-6", "haiku-4-5")
ANTHROPIC_DOC_NAMES: dict[str, str] = {f"claude-{s}": _CLAUDE_FAMILY_NAMES[f"claude-{s}"] for s in _CP_TARGETS}
ANTHROPIC_PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
ANTHROPIC_SOURCE_ID = "anthropic-pricing"
# Nova — Price List usagetype(USE1 regional, 1K tokens). us.amazon.* 는 us-east-1 호출 US(Geo) 채널.
NOVA_USAGETYPES: dict[str, tuple[str, str]] = {
    "nova-2-lite": ("USE1-Nova2.0Lite-input-tokens", "USE1-Nova2.0Lite-output-tokens"),
}
_PRICELIST_MODEL_IDS = {"us.amazon.nova-2-lite-v1:0": ("nova-2-lite", "Nova 2.0 Lite", "us")}
# OpenAI offer FM id(= Mantle in-region id) → (family_key, family)
_OPENAI_FM: dict[str, tuple[str, str]] = {
    "openai.gpt-6-astra": ("gpt-6-astra", "GPT 6 Astra"), "openai.gpt-6-sol": ("gpt-6-sol", "GPT 6 Sol"),
    "openai.gpt-6-luna": ("gpt-6-luna", "GPT 6 Luna"), "openai.gpt-5.6-sol": ("gpt-5.6-sol", "GPT 5.6 Sol"),
    "openai.gpt-5.6-terra": ("gpt-5.6-terra", "GPT 5.6 Terra"), "openai.gpt-5.6-luna": ("gpt-5.6-luna", "GPT 5.6 Luna"),
    "openai.gpt-5.5": ("gpt-5.5", "GPT 5.5"), "openai.gpt-5.4": ("gpt-5.4", "GPT 5.4"),
}
# in-region은 offer 차원 리전 접두(USE1_/USE2_/USW2_)가 있는 리전만 — 새 리전은 fail-closed(단가 없음).
_INREGION_REGIONS = ("us-east-1", "us-east-2", "us-west-2")


def _is_point_release_of(substring: str, model_id: str) -> bool:
    """prober._is_point_release_of 복제(prober는 boto3, DB를 끌어온다). tests가 prober와 동등성을 고정."""
    return re.search(re.escape(substring) + r"-\d{1,2}(?!\d)", model_id) is not None


def _cp_family_key(actual_id: str) -> str | None:
    for sub in _CP_TARGETS:
        longer = [s for s in _CP_TARGETS if s != sub and sub in s]
        if sub in actual_id and not any(s in actual_id for s in longer) and not _is_point_release_of(sub, actual_id):
            return f"claude-{sub}"
    return None


def price_identity(model_id: str) -> PriceIdentity | None:
    """활성 채널 model_id → 단가 식별자, 분류할 수 없으면 None(예외 아님)."""
    if model_id.startswith("anthropic:"):
        fk = _cp_family_key(model_id[len("anthropic:"):])
        if fk is None:
            return None
        return PriceIdentity(fk, _CLAUDE_FAMILY_NAMES[fk], "anthropic", "cp", "anthropic_doc", ANTHROPIC_DOC_NAMES[fk])
    if model_id.startswith("openai:"):
        parts = model_id.split(":", 2)
        if len(parts) != 3:
            return None
        _, region, actual = parts
        if region in ("global", "us"):
            if not actual.startswith(f"{region}."):
                return None
            fm, channel = actual[len(region) + 1:], region
        elif region in _INREGION_REGIONS:
            fm, channel = actual, f"inregion:{region}"
        else:
            return None  # openai:1p:*(휴면 1P) 또는 모르는 리전
        if fm not in _OPENAI_FM:
            return None
        return PriceIdentity(*_OPENAI_FM[fm], "openai", channel, "offer", fm)
    if model_id in _PRICELIST_MODEL_IDS:
        fk, fam, channel = _PRICELIST_MODEL_IDS[model_id]
        return PriceIdentity(fk, fam, "amazon", channel, "pricelist", fk)
    prefix, _, fm = model_id.partition(".")
    if prefix in ("global", "us") and fm in _BEDROCK_CLAUDE_FM:
        return PriceIdentity(*_BEDROCK_CLAUDE_FM[fm], "anthropic", prefix, "offer", fm)
    return None


def tier_of(channel: str) -> str:
    """채널 → /api/pricing tiers 키(cp | global | us | in_region)."""
    if channel in ("cp", "global", "us"):
        return channel
    if channel.startswith("inregion:"):
        return "in_region"
    raise ValueError(f"unknown price channel: {channel!r}")


def region_of(channel: str) -> str | None:
    return channel[len("inregion:"):] if channel.startswith("inregion:") else None


def active_channels(models: Mapping[str, str], hidden: Sequence[str]) -> dict[str, PriceIdentity]:
    """{model_id: label} → 숨김 라벨은 조용히, 분류 불가 id는 경고 후 뺀 {model_id: PriceIdentity}(순서 유지)."""
    out: dict[str, PriceIdentity] = {}
    for model_id, label in models.items():
        if any(p and p in label for p in hidden):
            continue
        ident = price_identity(model_id)
        if ident is None:
            logger.warning("No price identity for active model %s (%s) - cost shows '-'", model_id, label)
            continue
        out[model_id] = ident
    return out


def offer_source_id(offer_id: str) -> str:
    return f"offer:{offer_id}"


def pricelist_source_id(usagetype: str) -> str:
    return f"pricelist:{usagetype}"


def official_source_id(slug: str) -> str:
    return f"official:{slug}"


def note_source_id(family_key: str) -> str:
    return f"note:{family_key}"


# references 고정 URL(셀 인용 출처, pricing_payload.py가 쓴다). CP 표준 요금 근거(#claude-platform-on-aws-pricing)는
# Anthropic 참고 자료 제목("Claude Platform on AWS는 표준 요금")으로만 싣는다 — PricingReference의 url은 하나다.
OFFER_REFERENCE_URL = "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html"
PRICELIST_REFERENCE_URL = "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html"
ANTHROPIC_REFERENCE_URL = "https://platform.claude.com/docs/en/about-claude/pricing#model-pricing"

# 화면과 다운로드 3형식 공용 — KO, EN은 여기 한 곳에만 둔다.
DISCLAIMER: dict[str, str] = {
    "ko": "이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. "
          "최종 가격은 반드시 공식 사이트에서 확인하세요.",
    "en": "This price list is compiled automatically from public sources for reference only and is not "
          "an official AWS statement. Always confirm final prices on the official pricing pages.",
}

# 고정 안내 항목(official_page, source_id official:<slug>) — 하드코딩, 런타임 존재 확인 없음
OFFICIAL_PAGES: list[dict] = [
    {"slug": "bedrock-pricing", "title_en": "Amazon Bedrock pricing", "title_ko": "Amazon Bedrock 요금",
     "url": "https://aws.amazon.com/bedrock/pricing/"},
    *(
        {"slug": f"model-card-openai-{slug}", "title_en": f"Amazon Bedrock model card: OpenAI {name}",
         "title_ko": f"Amazon Bedrock 모델 카드: OpenAI {name}",
         "url": f"https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-{slug}.html"}
        for slug, name in (
            ("gpt-54", "GPT-5.4"), ("gpt-55", "GPT-5.5"), ("gpt-56-sol", "GPT-5.6 Sol"),
            ("gpt-56-terra", "GPT-5.6 Terra"), ("gpt-56-luna", "GPT-5.6 Luna"), ("gpt-6-astra", "GPT-6 Astra"),
            ("gpt-6-sol", "GPT-6 Sol"), ("gpt-6-luna", "GPT-6 Luna"),
        )
    ),
]

# 수동 메모(manual_note, 공식 출처 아님) — 근거: 2026-09-23 AWS 모델 카드 기재(현재 미게재), CHANGELOG v2.28.1
PRICE_NOTES: list[dict] = [{
    "family_key": "gpt-5.6-sol",
    "kind": "promo",
    "min_until": "2026-11-21",
    "prior_price": {"in_region": {"input": 5.5, "output": 33}, "global": {"input": 5, "output": 30}},
    "text_ko": "프로모션 단가다. 2026-09-23 AWS 모델 카드에 최소 2026-11-21까지 적용한다고 기재됐고, "
               "지금은 공식 출처에 표시가 없어 수동 메모로 관리한다(CHANGELOG v2.28.1).",
    "text_en": "Promotional price. The AWS model card stated on 2026-09-23 that it applies at least through "
               "2026-11-21; no official source shows it now, so it is kept as a manual note (CHANGELOG v2.28.1).",
    "source": "manual_note",
}]
```

- [ ] **Step 4: Run tests**

```bash
(cd backend && python3.12 -m pytest tests/test_pricing_sources.py -q)
(cd backend && python3.12 -m pytest tests/ -q)
(cd backend && ruff check models.py pricing_sources.py tests/pricing_catalog.py tests/test_pricing_sources.py)
```

Expected: PASS, `104 passed`; full suite `534 passed` (430 at `91008c6` + 104); `test_perf_indexes.py`, `test_startup_migration.py`, `test_opus55_gpt6_catalog.py`, `test_fable51_catalog.py`, `test_openai_probe.py` stay green; ruff `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add backend/models.py backend/pricing_sources.py backend/tests/pricing_catalog.py backend/tests/test_pricing_sources.py
git commit -m "feat(pricing): price_history tables and exact price identity for the 55 active channels"
```

---

## Task 2: Official price seed and startup seeding

**Files:**
- Create: `backend/pricing_seed.py`
- Modify: `backend/main.py` lines 157-161 (after label repair, which follows the migration block lines 55-120 and model registration lines 143-149; before `yield` line 163 — `yield` moves to line 175)
- Test: `backend/tests/test_pricing_seed.py`

**Interfaces:**
- Consumes: Task 1 (`PriceHistory`, `PriceSyncRun`, `EPOCH`, `ANTHROPIC_SOURCE_ID`, `NOVA_USAGETYPES`, `PriceIdentity`, `offer_source_id`, `pricelist_source_id`, `active_channels`, `price_identity`, `tests.pricing_catalog`); `prober.AVAILABLE_MODELS`; `visibility.hidden_patterns`
- Produces: `pricing_seed.SEED` (46 non-CP model_ids), `CP_SEED` (9 family_keys), `SEED_SOURCE_DATE`, `seed_rows(active)`, `ensure_seed(engine, active) -> int`; non-fatal lifespan hook

Values: offer channels use the 2026-09-26 spike rate card (`global_from_APN2` for Global, `regional_USE1/USE2/USW2` for US and in-region) and `offer:<offerIds[0]>`; Nova uses Price List `USE1-Nova2.0Lite-input-tokens` 0.00033 / `-output-tokens` 0.00275 per 1K tokens (x1000). All 46 SEED entries and 18 offerIds were matched against the spike data (0 mismatches). The Nova `source_id` is `pricelist_source_id(NOVA_USAGETYPES["nova-2-lite"][0])` = `pricelist:USE1-Nova2.0Lite-input-tokens`, the same id the sync (Task 4) records, so the reference list has one Nova entry.

- [ ] **Step 1: Write the failing test.** `python3 "$PB" t02-test` writes `backend/tests/test_pricing_seed.py`:

<!-- plan-block id=t02-test path=backend/tests/test_pricing_seed.py sha256=979af7df404eda6a703d609b25529f859ec4279d7d9b6514667fa763d774f1e2 -->
```python
"""단가 seed (v2.30.0, ADR-030) — 55채널 공식 단가, 교정 11채널(결정 8), model_id 단위 멱등, lifespan 훅 위치."""

import logging
import pathlib
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from pricing_seed import CP_SEED, SEED, SEED_SOURCE_DATE, ensure_seed, seed_rows
from pricing_sources import (
    ANTHROPIC_SOURCE_ID, EPOCH, NOVA_USAGETYPES, PriceIdentity, active_channels, price_identity, pricelist_source_id,
)
from tests.pricing_catalog import ACTIVE_MODELS, HIDDEN_1P_MODELS

MAIN_SRC = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
SEED_CALL = "ensure_seed(engine, active_channels(AVAILABLE_MODELS, hidden_patterns()))"
ACTIVE = {mid: price_identity(mid) for mid in ACTIVE_MODELS}

CORRECTED = {  # v2.29.1 값이 처음부터 틀린 11채널(US는 Global 값, Nova는 1세대 Nova Lite 값)
    "us.anthropic.claude-fable-5-1": (11.0, 55.0), "us.anthropic.claude-fable-5": (11.0, 55.0),
    "us.anthropic.claude-opus-5-5": (4.4, 22.0), "us.anthropic.claude-opus-5": (5.5, 27.5),
    "us.anthropic.claude-opus-4-8": (5.5, 27.5), "us.anthropic.claude-opus-4-7": (5.5, 27.5),
    "us.anthropic.claude-opus-4-6-v1": (5.5, 27.5), "us.anthropic.claude-sonnet-5": (2.2, 11.0),
    "us.anthropic.claude-sonnet-4-6": (3.3, 16.5), "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.1, 5.5),
    "us.amazon.nova-2-lite-v1:0": (0.33, 2.75),
}
STANDARD = {  # Anthropic 표준 단가 = Bedrock Global = CP (family_key 기준, Opus 4.6은 CP 없음)
    "claude-fable-5-1": (10.0, 50.0), "claude-fable-5": (10.0, 50.0), "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0), "claude-opus-4-8": (5.0, 25.0), "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0), "claude-sonnet-5": (2.0, 10.0), "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
OPENAI = {  # family_key → (US CRIS와 in-region, Global CRIS)
    "gpt-6-astra": ((11.0, 55.0), (10.0, 50.0)), "gpt-6-sol": ((2.2, 11.0), (2.0, 10.0)),
    "gpt-6-luna": ((0.11, 0.55), (0.1, 0.5)), "gpt-5.6-sol": ((4.4, 22.0), (4.0, 20.0)),
    "gpt-5.6-terra": ((2.2, 13.2), (2.0, 12.0)), "gpt-5.6-luna": ((0.22, 1.32), (0.2, 1.2)),
    "gpt-5.5": ((5.5, 33.0), None), "gpt-5.4": ((2.75, 16.5), None),
}


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(eng)
    return eng


def _rows(eng):
    with sessionmaker(bind=eng)() as s:
        return {r.model_id: r for r in s.execute(select(models.PriceHistory)).scalars()}


def _utc(dt):  # SQLite는 DateTime(timezone=True)를 naive로 돌려준다
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _add(eng, **row):
    with sessionmaker(bind=eng)() as s:
        s.add(models.PriceHistory(**row))
        s.commit()


def test_seed_covers_every_active_channel():
    assert len(SEED) == 46
    assert set(SEED) == {m for m, i in ACTIVE.items() if i.channel != "cp"}
    assert set(CP_SEED) == {i.family_key for i in ACTIVE.values() if i.channel == "cp"}
    rows = seed_rows(ACTIVE)
    assert set(rows) == set(ACTIVE)
    assert rows["anthropic:claude-haiku-4-5-20251001"] == (1.0, 5.0, ANTHROPIC_SOURCE_ID)  # CP 날짜 접미사 id
    assert SEED_SOURCE_DATE.isoformat() == "2026-09-26"


@pytest.mark.parametrize("model_id", sorted(CORRECTED))
def test_corrected_eleven_channels(model_id):
    assert SEED[model_id][:2] == CORRECTED[model_id]


def test_values_per_channel():
    for mid, ident in ACTIVE.items():
        inp, out, src = seed_rows(ACTIVE)[mid]
        assert isinstance(inp, float) and isinstance(out, float), mid
        if ident.channel in ("cp", "global") and ident.provider == "anthropic":
            assert (inp, out) == STANDARD[ident.family_key], mid
        elif ident.channel == "us" and ident.provider == "anthropic":
            g_in, g_out = STANDARD[ident.family_key]
            assert (inp, out) == (round(g_in * 1.1, 6), round(g_out * 1.1, 6)), mid
        elif ident.provider == "openai":
            regional, global_ = OPENAI[ident.family_key]
            assert (inp, out) == (global_ if ident.channel == "global" else regional), mid
    assert {src for _, _, src in CP_SEED.values()} == {ANTHROPIC_SOURCE_ID}


def test_seed_source_ids_follow_the_price_identity():
    by_fm: dict[str, set[str]] = {}
    for mid, (_, _, src) in SEED.items():
        ident = ACTIVE[mid]
        if ident.source_kind == "offer":
            assert re.fullmatch(r"offer:offer-[a-z0-9]{13}", src), (mid, src)
            by_fm.setdefault(ident.source_ref, set()).add(src)
        else:
            assert src == pricelist_source_id(NOVA_USAGETYPES[ident.source_ref][0])
    assert len(by_fm) == 18 and all(len(v) == 1 for v in by_fm.values())  # FM당 오퍼 1개를 모든 채널이 인용
    assert len(set().union(*by_fm.values())) == 18
    assert by_fm["anthropic.claude-opus-5-5"] == {"offer:offer-7sp77cpl4rveu"}
    assert by_fm["openai.gpt-5.4"] == {"offer:offer-5l5a5izq5fbec"}
    assert by_fm["openai.gpt-6-astra"] == {"offer:offer-7epta7rbw5aws"}


def test_seed_rows_skip_active_ids_without_seed(caplog):
    new = PriceIdentity("claude-opus-9", "Claude Opus 9", "anthropic", "global", "offer", "anthropic.claude-opus-9")
    with caplog.at_level(logging.WARNING, logger="pricing_seed"):
        rows = seed_rows({"global.anthropic.claude-opus-9": new,
                          "global.anthropic.claude-opus-5": ACTIVE["global.anthropic.claude-opus-5"]})
    assert list(rows) == ["global.anthropic.claude-opus-5"]
    assert "global.anthropic.claude-opus-9" in caplog.text


def test_ensure_seed_inserts_every_active_channel_then_is_idempotent(engine):
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    assert ensure_seed(engine, ACTIVE) == 55
    assert not any("pg_advisory" in s for s in statements)  # SQLite는 잠금 생략
    rows = _rows(engine)
    assert set(rows) == set(ACTIVE)
    for mid, row in rows.items():
        assert (row.input_per_mtok, row.output_per_mtok, row.source_id) == seed_rows(ACTIVE)[mid]
        assert (row.family_key, row.channel) == (ACTIVE[mid].family_key, ACTIVE[mid].channel)
        assert (row.status, row.observed_at, row.run_id) == ("seed", None, None)
        assert _utc(row.effective_from) == EPOCH and row.created_at is not None
    assert ensure_seed(engine, ACTIVE) == 0
    assert len(_rows(engine)) == 55


def test_existing_row_blocks_seeding_only_that_model_id(engine):
    _add(engine, model_id="us.amazon.nova-2-lite-v1:0", family_key="nova-2-lite", channel="us",
         input_per_mtok=0.06, output_per_mtok=0.24, effective_from=EPOCH, status="rejected",
         source_id="pricelist:USE1-Nova2.0Lite-input-tokens", observed_at=datetime(2026, 9, 26, 3, tzinfo=timezone.utc))
    assert ensure_seed(engine, ACTIVE) == 54
    rows = _rows(engine)
    assert (rows["us.amazon.nova-2-lite-v1:0"].status, rows["us.amazon.nova-2-lite-v1:0"].input_per_mtok) == ("rejected", 0.06)
    assert sum(r.status == "seed" for r in rows.values()) == 54


def test_sync_first_then_seed_still_fills_the_rest(engine):
    started = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)
    with sessionmaker(bind=engine)() as s:
        run = models.PriceSyncRun(started_at=started, status="completed")
        s.add(run)
        s.commit()
        run_id = run.id
    _add(engine, model_id="us.anthropic.claude-opus-5-5", family_key="claude-opus-5-5", channel="us",
         input_per_mtok=4.4, output_per_mtok=22.0, effective_from=started, status="verified",
         source_id="offer:offer-7sp77cpl4rveu", observed_at=started, run_id=run_id)
    assert ensure_seed(engine, active_channels({**ACTIVE_MODELS, **HIDDEN_1P_MODELS}, ["(1P)"])) == 54
    rows = _rows(engine)
    assert set(rows) == set(ACTIVE)
    assert rows["us.anthropic.claude-opus-5-5"].status == "verified"
    assert _utc(rows["us.anthropic.claude-opus-5-5"].effective_from) == started
    assert rows["global.anthropic.claude-opus-5-5"].status == "seed"


def test_ensure_seed_postgres_takes_transaction_advisory_lock_first():
    log: list[str] = []
    conn = SimpleNamespace(execute=lambda stmt, params=None: log.append(str(stmt)) or SimpleNamespace(scalars=lambda: iter(())))

    class _Begin:
        def __enter__(self):
            return conn

        def __exit__(self, *exc):
            return False

    pg = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), begin=_Begin)
    assert ensure_seed(pg, {"us.amazon.nova-2-lite-v1:0": ACTIVE["us.amazon.nova-2-lite-v1:0"]}) == 1
    assert log[0] == "SELECT pg_advisory_xact_lock(917350003)"
    assert log[1].startswith("SELECT DISTINCT price_history.model_id")
    assert log[2].startswith("INSERT INTO price_history") and len(log) == 3
    assert ensure_seed(SimpleNamespace(dialect=pg.dialect, begin=None), {}) == 0  # 빈 활성 집합은 DB를 건드리지 않는다


def test_lifespan_seeds_after_migration_and_registration_non_fatal():
    unlock = MAIN_SRC.index("SELECT pg_advisory_unlock(917350001)")
    register = re.search(r"^\s+_register_openai_models\(\)$", MAIN_SRC, re.M).start()
    seed = MAIN_SRC.index(SEED_CALL)
    assert unlock < register < seed < re.search(r"^\s{4}yield$", MAIN_SRC, re.M).start()
    block = MAIN_SRC[MAIN_SRC.rindex("    try:\n", 0, seed):MAIN_SRC.index("    except Exception:\n", seed)]
    assert "from pricing_seed import ensure_seed" in block and "yield" not in block
    after = MAIN_SRC[MAIN_SRC.index("    except Exception:\n", seed):].splitlines()[1].strip()
    assert after.startswith('logger.exception("Price seed failed')
```

- [ ] **Step 2: Run it** — `(cd backend && python3.12 -m pytest tests/test_pricing_seed.py -q)` — Expected: FAIL, `ModuleNotFoundError: No module named 'pricing_seed'` (after 3a alone: 19 pass, `test_lifespan_seeds_after_migration_and_registration_non_fatal` fails with `ValueError: substring not found`).

- [ ] **Step 3: Implement.**

3a. Create `backend/pricing_seed.py` (`python3 "$PB" t02-seed`):

<!-- plan-block id=t02-seed path=backend/pricing_seed.py sha256=4bc3d18efaface45df316b237b4743a1749fd92f5f041c04eec4e2dd345bd2c0 -->
```python
"""단가 seed — 활성 55채널 공식 단가 초기값과 model_id 단위 멱등 삽입 (v2.30.0, ADR-030).

출처(2026-09-26 스파이크, USD per 1M tokens, Standard 입력/출력): Bedrock agreement offer rate card(FM 18개,
offerId 리전 무관), AWS Price List(Nova 2.0 Lite USE1, 1K tokens × 1000), Anthropic pricing.md(CP 9).
v2.29.1 대비 교정 11채널(결정 8, 과거까지): Bedrock Claude US 10 = Global × 1.1, Nova 2.0 Lite 0.33 / 2.75.
나머지 44채널은 v2.29.1 값과 같다. 새 모델은 pricing_sources.py 매핑과 함께 여기 표를 고친다.
"""

import logging
from datetime import date, datetime, timezone
from typing import Mapping

from sqlalchemy import insert, select, text

from models import PriceHistory
from pricing_sources import (
    ANTHROPIC_SOURCE_ID, EPOCH, NOVA_USAGETYPES, PriceIdentity, offer_source_id, pricelist_source_id,
)

logger = logging.getLogger(__name__)

SEED_SOURCE_DATE = date(2026, 9, 26)  # seed만 있는 참고 자료의 확인일(as_of)
# backend 태스크 기동과 PricingSync 러너가 겹쳐도 같은 model_id를 두 번 seed하지 않는다(트랜잭션 잠금).
_SEED_LOCK_SQL = "SELECT pg_advisory_xact_lock(917350003)"

# Bedrock Claude FM id → (offerId, Global in, Global out, US in, US out). US = USE1_*, Global = APN2_*_global.
_CLAUDE: dict[str, tuple[str, float, float, float, float]] = {
    "anthropic.claude-fable-5-1": ("offer-icq4574v6gz3i", 10.0, 50.0, 11.0, 55.0),
    "anthropic.claude-fable-5": ("offer-vk3fuman5qwzy", 10.0, 50.0, 11.0, 55.0),
    "anthropic.claude-opus-5-5": ("offer-7sp77cpl4rveu", 4.0, 20.0, 4.4, 22.0),
    "anthropic.claude-opus-5": ("offer-f3u6lgbrem3zs", 5.0, 25.0, 5.5, 27.5),
    "anthropic.claude-opus-4-8": ("offer-wdkl4yk6s7uu4", 5.0, 25.0, 5.5, 27.5),
    "anthropic.claude-opus-4-7": ("offer-sltne4evyuyeu", 5.0, 25.0, 5.5, 27.5),
    "anthropic.claude-opus-4-6-v1": ("offer-ee7a27hh4hr62", 5.0, 25.0, 5.5, 27.5),
    "anthropic.claude-sonnet-5": ("offer-2ykemehpsyf7g", 2.0, 10.0, 2.2, 11.0),
    "anthropic.claude-sonnet-4-6": ("offer-ldnd26nhxx676", 3.0, 15.0, 3.3, 16.5),
    "anthropic.claude-haiku-4-5-20251001-v1:0": ("offer-fudwqbphlos64", 1.0, 5.0, 1.1, 5.5),
}
# OpenAI FM id → (offerId, US CRIS와 in-region in, out, Global in, out, 채널 리전)
_OPENAI: dict[str, tuple[str, float, float, float | None, float | None, tuple[str, ...]]] = {
    "openai.gpt-6-astra": ("offer-7epta7rbw5aws", 11.0, 55.0, 10.0, 50.0, ("global", "us", "us-west-2")),
    "openai.gpt-6-sol": ("offer-pycji3sz5gpcc", 2.2, 11.0, 2.0, 10.0, ("global", "us", "us-east-1")),
    "openai.gpt-6-luna": ("offer-gmo53nkzc5or6", 0.11, 0.55, 0.1, 0.5, ("global", "us", "us-east-1")),
    "openai.gpt-5.6-sol": ("offer-gnqokrqqvdbgw", 4.4, 22.0, 4.0, 20.0, ("global", "us-east-1", "us-east-2")),
    "openai.gpt-5.6-terra": ("offer-3dvyrx3okd4lq", 2.2, 13.2, 2.0, 12.0, ("global", "us-east-1", "us-east-2", "us-west-2")),
    "openai.gpt-5.6-luna": ("offer-bklbyf2ewuawu", 0.22, 1.32, 0.2, 1.2, ("global", "us-east-1", "us-east-2", "us-west-2")),
    "openai.gpt-5.5": ("offer-rtwlbb46hcxpw", 5.5, 33.0, None, None, ("us-east-1", "us-east-2")),
    "openai.gpt-5.4": ("offer-5l5a5izq5fbec", 2.75, 16.5, None, None, ("us-east-1", "us-east-2", "us-west-2")),
}


def _openai_seed(fm: str, region: str, spec: tuple) -> tuple[str, tuple[float, float, str]]:
    offer, r_in, r_out, g_in, g_out, _ = spec
    src = offer_source_id(offer)
    if region == "global":
        return f"openai:global:global.{fm}", (g_in, g_out, src)
    mid = f"openai:us:us.{fm}" if region == "us" else f"openai:{region}:{fm}"
    return mid, (r_in, r_out, src)


# model_id → (input, output, source_id) — CP를 뺀 활성 46채널
SEED: dict[str, tuple[float, float, str]] = {
    **{f"global.{fm}": (g_in, g_out, offer_source_id(o)) for fm, (o, g_in, g_out, _, _) in _CLAUDE.items()},
    **{f"us.{fm}": (u_in, u_out, offer_source_id(o)) for fm, (o, _, _, u_in, u_out) in _CLAUDE.items()},
    "us.amazon.nova-2-lite-v1:0": (0.33, 2.75, pricelist_source_id(NOVA_USAGETYPES["nova-2-lite"][0])),
    **dict(_openai_seed(fm, r, spec) for fm, spec in _OPENAI.items() for r in spec[5]),
}

# Claude Platform on AWS — model_id가 디스커버리로 정해지므로(날짜 접미사) family_key 단위
CP_SEED: dict[str, tuple[float, float, str]] = {
    fk: (i, o, ANTHROPIC_SOURCE_ID)
    for fk, i, o in (
        ("claude-fable-5-1", 10.0, 50.0), ("claude-fable-5", 10.0, 50.0), ("claude-opus-5-5", 4.0, 20.0),
        ("claude-opus-5", 5.0, 25.0), ("claude-opus-4-8", 5.0, 25.0), ("claude-opus-4-7", 5.0, 25.0),
        ("claude-sonnet-5", 2.0, 10.0), ("claude-sonnet-4-6", 3.0, 15.0), ("claude-haiku-4-5", 1.0, 5.0),
    )
}


def seed_rows(active: Mapping[str, PriceIdentity]) -> dict[str, tuple[float, float, str]]:
    """활성 채널 → {model_id: seed}. CP는 family_key로 풀고, seed 없는 id는 경고 후 뺀다(동기화가 no_baseline)."""
    out: dict[str, tuple[float, float, str]] = {}
    for model_id, ident in active.items():
        seed = CP_SEED.get(ident.family_key) if ident.channel == "cp" else SEED.get(model_id)
        if seed is None:
            logger.warning("No seed price for %s (%s, %s)", model_id, ident.family_key, ident.channel)
            continue
        out[model_id] = seed
    return out


def ensure_seed(engine, active: Mapping[str, PriceIdentity]) -> int:
    """price_history에 행이 하나도 없는 활성 model_id에만 seed 행을 넣고 넣은 수를 돌려준다.

    model_id 단위 멱등(테이블 전체 비었는지 보지 않음), 자체 트랜잭션, PostgreSQL은
    pg_advisory_xact_lock(917350003) 아래(SQLite 생략). effective_from=EPOCH, status='seed',
    observed_at=NULL. 예외는 호출부(main.py lifespan, pricing_sync_runner)로 올린다.
    """
    rows = seed_rows(active)
    if not rows:
        return 0
    table = PriceHistory.__table__
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text(_SEED_LOCK_SQL))
        existing = set(conn.execute(
            select(table.c.model_id).where(table.c.model_id.in_(list(rows))).distinct()
        ).scalars())
        created_at = datetime.now(timezone.utc)
        values = [
            {"model_id": mid, "family_key": active[mid].family_key, "channel": active[mid].channel,
             "input_per_mtok": float(i), "output_per_mtok": float(o), "effective_from": EPOCH,
             "source_id": src, "status": "seed", "observed_at": None, "run_id": None, "created_at": created_at}
            for mid, (i, o, src) in rows.items() if mid not in existing
        ]
        if values:
            conn.execute(insert(table), values)
    if values:
        logger.info("Price seed inserted %d rows (%d already had price history)", len(values), len(existing))
    return len(values)
```

3b. `backend/main.py` (`python3 "$PB" --apply t02-main` performs exactly this edit): replace

```python
        repair_model_labels(engine, AVAILABLE_MODELS)
    except Exception:
        logger.exception("Label repair failed (non-fatal)")

    logger.info("Database tables ready.")
```

with (local imports like the neighbouring blocks; `from routers import models` shadows the ORM module name):

```python
        repair_model_labels(engine, AVAILABLE_MODELS)
    except Exception:
        logger.exception("Label repair failed (non-fatal)")

    # 단가 seed (v2.30.0, ADR-030) — price_history에 행이 하나도 없는 활성 model_id에만 공식 단가 seed를 넣는다.
    # CP seed는 family_key 단위라 현재 활성 CP model_id로 풀어 넣어야 하므로 모델 등록 다음에 둔다.
    # 마이그레이션과 분리된 자체 트랜잭션 + pg_advisory_xact_lock(917350003) — 실패해도 기동은 계속한다.
    try:
        from pricing_seed import ensure_seed
        from pricing_sources import active_channels
        from prober import AVAILABLE_MODELS
        from visibility import hidden_patterns
        ensure_seed(engine, active_channels(AVAILABLE_MODELS, hidden_patterns()))
    except Exception:
        logger.exception("Price seed failed (non-fatal, backend continues)")

    logger.info("Database tables ready.")
```

- [ ] **Step 4: Run tests**

```bash
(cd backend && python3.12 -m pytest tests/test_pricing_seed.py tests/test_pricing_sources.py tests/test_startup_migration.py -q)
(cd backend && python3.12 -m pytest tests/ -q)
(cd backend && ruff check pricing_seed.py main.py tests/test_pricing_seed.py)
```

Expected: PASS, `127 passed` (20 + 104 + 3); full suite `554 passed`; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add backend/pricing_seed.py backend/main.py backend/tests/test_pricing_seed.py
git commit -m "feat(pricing): official price seed with Claude US and Nova corrections, seeded at startup"
```

---

## Task 3: 공식 단가 출처 파서 + 정제된 fixture

이 태스크부터 Task 5까지는 기존 파일을 하나도 수정하지 않는다(모두 Create). Task 1-2의 계약 이름에 의존한다: `models.PriceHistory`/`PriceSyncRun`, `pricing_sources`(`EPOCH`, `PriceIdentity`, `price_identity`, `active_channels`, `NOVA_USAGETYPES`, `ANTHROPIC_DOC_NAMES`, `ANTHROPIC_PRICING_URL`, `ANTHROPIC_SOURCE_ID`, `offer_source_id`, `pricelist_source_id`), `pricing_seed.ensure_seed`.

**Files:**
- Create: `backend/pricing_parsers.py` (273행)
- Create: `backend/tests/test_pricing_parsers.py` (247행, 54 tests)
- Create: `backend/tests/fixtures/pricing/` 7개 파일 — `offers_claude-opus-5-5.json`(리전 접두 스킴), `offers_claude-sonnet-4-6.json`(레거시), `offers_claude-haiku-4-5.json`(두 스킴 중복), `offers_gpt-6-astra.json`(평면, 단위 기준점), `offers_gpt-5.4.json`(리전 접두 + 0원 long_ctx_priority), `pricelist_nova-2-lite.json`, `anthropic_pricing.md`(Model pricing 절 + 뒤따르는 Batch 표)
- Modify: 없음

**Interfaces:**
- Consumes: `pricing_sources.ANTHROPIC_DOC_NAMES`, `pricing_sources.NOVA_USAGETYPES`(테스트에서만)
- Produces: `PriceParseError(ValueError)`, `UnitPrice(input: Decimal, output: Decimal)`(frozen), `DIMENSION_RE`, `single_public_offer(response) -> (offer_id, rate_card)`, `select_offer_price(rate_card, channel) -> UnitPrice | None`, `parse_pricelist(price_list, input_usagetype, output_usagetype) -> UnitPrice`, `parse_anthropic_pricing_md(markdown) -> dict[str, UnitPrice]`

fixture 출처: 2026-09-26 스파이크 원본(offers 17개, Price List, `platform-pricing.md`)을 결정적 정제 스크립트로 축약했다(스크립트와 원본은 커밋하지 않는다). 정제 규칙은 다음과 같다. 1. 오퍼마다 `modelId`, `offerId`, `rateCard[]`(dimension/price/description/unit)만 남긴다. 2. 접두 `""|APN2|USE1|USE2|USW2|UGE1|EU` 중 필요한 차원과 부정 예시(batch/priority/flex/long_ctx/_LCtx/cache, Reserved는 APN2/USE1만)만 남긴다. 3. 원본과 축약본에서 spec 정규식에 걸리는 항목 집합이 같은지 확인했다. 4. 부정 예시와 0원 항목이 있는지 확인했다. 5. 출력에 `offerToken`, `X-Amz`, `legalTerm`, `awsmp-offer-legal`, `Security-Token`이 없음을 확인했다. Reserved 부정 예시를 APN2/USE1로 제한한 이유는 USE2/USW2 Reserved `*_Global` 이름이 저장소 `.pre-commit-config.yaml`의 detect-secrets `Base64HighEntropyString`에 오탐으로 걸리기 때문이다(정제 후 detect-secrets 1.5.0 scan 결과 `{}`). 7개 fixture는 plan block으로 바이트 단위 그대로 들어 있다(sha256은 Appendix 표지에 있다).

| block | 파일 | bytes |
|---|---|---|
| `t03-fx-opus55` | `offers_claude-opus-5-5.json` | 5371 |
| `t03-fx-sonnet46` | `offers_claude-sonnet-4-6.json` | 16447 |
| `t03-fx-haiku45` | `offers_claude-haiku-4-5.json` | 17100 |
| `t03-fx-astra` | `offers_gpt-6-astra.json` | 3166 |
| `t03-fx-gpt54` | `offers_gpt-5.4.json` | 21511 |
| `t03-fx-nova` | `pricelist_nova-2-lite.json` | 5590 |
| `t03-fx-anthropic` | `anthropic_pricing.md` | 11191 |

- [ ] **Step 1: fixture와 실패하는 테스트를 쓴다**

  ```bash
  python3 "$PB" t03-fx-opus55 t03-fx-sonnet46 t03-fx-haiku45 t03-fx-astra t03-fx-gpt54 t03-fx-nova t03-fx-anthropic t03-test
  grep -lE "offerToken|X-Amz|legalTerm|awsmp-offer-legal|Security-Token" backend/tests/fixtures/pricing/* ; echo "grep exit $? (1 = 정제됨)"
  ```
  테스트(`t03-test`)가 고정하는 동작은 다음과 같다.
  - fixture 정제 여부
  - 오퍼 0개, 2개, 키 없음, rateCard 없음 → `PriceParseError`
  - 실카드 선택값: Opus 5.5 global 4/20, us 4.4/22, Sonnet 4.6 3/15, 3.3/16.5, Haiku 1/5, 1.1/5.5, Astra us 11/55, global 10/50, inregion:us-west-2 11/55, GPT-5.4 in-region 3리전 2.75/16.5
  - `cp`, 미지 리전, `inregion:` → None
  - 허용 목록 수락 7종, 거부 12종(UGE1, UGW1, EU, batch, priority, flex, long_ctx, LCtx, Global_Batch, cache, Reserved, 소문자)
  - 실카드의 UGE1/EU 항목만으로는 후보 없음
  - 0원 제외 후 다음 후보 사용, unit≠"Units" 무시, 값이 다른 중복 차원 제거, 입력과 출력이 모두 있어야 후보
  - 채널별 선택 순서(`_drain`): global [1,2,3,4,5], us [6,7,8], us-east-1 [6,7], us-east-2 [9,7], us-west-2 [11,7]
  - Nova ×1000 → 0.33/2.75(문자열 항목과 dict 항목 모두), 단위 불일치, 상품 누락이나 중복, 잘못된 JSON → 예외
  - 실제 문서의 CP 9패밀리 값 + `ANTHROPIC_DOC_NAMES` 값 집합 일치
  - Sonnet 5 값 셀 `<sup>` 제거 → 2/10, Batch 표 미사용
  - 마크다운 링크 괄호 제거(Mythos 5.1/5, Opus 4.1)
  - Opus 5 ↔ 5.5, Fable 5 ↔ 5.1(+Mythos 5.1) 정확 일치
  - 헤더 이름 기반 열 선택, 형식이 다른 값 행은 건너뜀, 같은 이름이 서로 다른 값으로 두 번 나오면 제거
  - 구조 변경 4종 → 예외
- [ ] **Step 2: 실행** — `(cd backend && python3.12 -m pytest tests/test_pricing_parsers.py -q)` — Expected: FAIL. 수집 단계에서 `ModuleNotFoundError: No module named 'pricing_parsers'`가 난다.
- [ ] **Step 3: 구현** — `python3 "$PB" t03-parsers`(`backend/pricing_parsers.py`). 핵심은 다음과 같다(파일에 그대로 있다).
  ```python
  DIMENSION_RE = re.compile(
      r"^(?:(?P<rc>APN2|USE1|USE2|USW2)_)?"
      r"(?:(?P<io>input|output)_tokens(?P<g>_global)?_standard"
      r"|(?P<IO>Input|Output)TokenCount(?P<G>_Global)?)$"
  )
  _GLOBAL_ORDER = (("new","APN2",True), ("new","USE1",True), ("new","",True), ("legacy","APN2",True), ("legacy","USE1",True))
  _US_ORDER = (("new","USE1",False), ("new","",False), ("legacy","USE1",False))
  # inregion:<r> -> (("new", {"us-east-1":"USE1","us-east-2":"USE2","us-west-2":"USW2"}[r], False), ("new","",False)); 미지 리전 -> ()
  _TRAILING_PAREN_RE = re.compile(r"\s*\((?:[^()]|\([^()]*\))*\)\s*$")
  _PRICE_CELL_RE = re.compile(r"^\$(\d+(?:\.\d+)?) / MTok$")
  ```
  동작 규칙은 다음과 같다. 1. 값은 `Decimal(str(price))`로 읽고 `<= 0`은 버린다. 2. Price List는 상품과 OnDemand 차원이 정확히 1개일 때만 받고, unit이 `"1K tokens"`일 때만 ×1000 한다. 3. 문서는 `## Model pricing` 아래 첫 표만 읽는다(다음 `#` 제목이나 표 끝에서 멈춘다). 4. 헤더 `model`/`base input tokens`/`output tokens`(공백 정규화, 소문자)로 열을 찾는다. 5. 이름 셀과 값 셀 모두에서 `<sup>…</sup>`를 먼저 지운다.
- [ ] **Step 4: 테스트** — `(cd backend && python3.12 -m pytest tests/test_pricing_parsers.py -q)` → `54 passed`. 이어서 `(cd backend && python3.12 -m pytest tests/ -q)` → `608 passed`. `(cd backend && ruff check pricing_parsers.py tests/test_pricing_parsers.py)` → `All checks passed!`.
- [ ] **Step 5: 커밋**
  ```bash
  git add backend/pricing_parsers.py backend/tests/test_pricing_parsers.py backend/tests/fixtures/pricing/
  git status --short   # tests/20260810_SB/ 와 이 계획 파일이 스테이징되지 않았는지 확인
  git commit -m "feat(pricing): parsers for agreement offers, Price List and Anthropic pricing.md with sanitized fixtures"
  ```

---

## Task 4: 12시간 동기화 `backend/pricing_sync.py`

**Files:**
- Create: `backend/pricing_sync.py` (452행)
- Create: `backend/tests/test_pricing_sync.py` (428행, 35 tests)
- Modify: 없음

**Interfaces:**
- Consumes: `models.PriceHistory`, `models.PriceSyncRun`, `pricing_sources.{EPOCH, PriceIdentity, NOVA_USAGETYPES, ANTHROPIC_PRICING_URL, ANTHROPIC_SOURCE_ID, offer_source_id, pricelist_source_id}`, 테스트에서만 `price_identity`, 그리고 Task 3의 파서 전부
- Produces: `CHANGE_THRESHOLD = Decimal("0.5")`, `SYNC_DEADLINE_S = 300.0`, `SYNC_LOCK_KEY = 917350004`, `Fetchers(offers, pricelist, anthropic_doc)`, `default_fetchers(*, bedrock=None, pricing=None, http=None, sleep=time.sleep) -> Fetchers`, `classify_change(current, new) -> "unchanged"|"changed"|"pending"|"no_baseline"`, `run_sync(session_factory, active, fetchers, *, now=None, deadline_s=SYNC_DEADLINE_S) -> int`, 상수 `USER_AGENT`, `AWS_REGION = "us-east-1"`

`pricing_sync`는 `price_history.current_rows`(Task 6)를 쓰지 않는다. 같은 의미의 private `_effective_row`(status seed/verified, `effective_from <=` 런 시작, `(effective_from, id)` 최신)를 둬서 태스크 순서 의존을 없앴다.

- [ ] **Step 1: 실패하는 테스트** — `python3 "$PB" t04-test`(`backend/tests/test_pricing_sync.py`). 고정하는 동작은 다음과 같다.
  - 상수
  - `classify_change` 10 케이스: 22→33, 20→30, −50% 정확은 changed, 22→33.01, −50.1%, −80%, 기준 0은 pending, float 왕복과 Price List Decimal은 unchanged, 기준 없음은 no_baseline
  - 같은 값이면 observed_at과 run_id만 갱신(행 수 불변, status seed 유지, sources calls/ok 집계)
  - 50% 이하 변경 → 새 verified 행(effective_from = observed_at = run started_at), 이전 행은 이력으로 보존
  - 33.01 → pending_review
  - 같은 pending 값 재관측 시 중복 없음(effective_from 유지, observed_at 갱신)
  - rejected 값은 결과 `rejected`로 재등장하지 않고, 값이 달라지면 새 pending
  - 기준 없음 → pending_review, effective_from EPOCH, 재관측 시 중복 없음
  - 출처 하나 실패 → 그 채널은 `skipped:fetch_failed` + 행 불변 + `partial`
  - 오퍼 하나 실패나 오퍼 2개 → 해당 모델만 skipped(`fetch_failed`/`offer_count`)
  - CP 채널 없음 → `partial` + `"anthropic_doc: no active channels"`
  - 데드라인: 가짜 시계에서 호출마다 200 s, doc→pricelist 뒤 400 s > 300 s → offers 4채널 `skipped:deadline`, `finished_at` = T0+400s
  - 모든 출처 실패 → `failed`
  - 첫 fetch 시점에 런 행이 이미 `running`으로 커밋됨
  - 내부 오류 → 런 `failed` + `internal: …` + 재발생, naive 시계 → ValueError
  - 가짜 offerToken과 presigned URL이 로그(caplog DEBUG), summary, 행 어디에도 없음
  - 기본 fetcher: offers가 `offerType="PUBLIC"`으로 호출되고 토큰, legalTerm, supportTerm이 제거됨, pricelist가 `TERM_MATCH usagetype` 2회 + 페이지 연결, anthropic이 UA 헤더를 보내고 503은 1회 재시도, 404는 재시도 없음, 재시도 정책: Throttling과 연결 오류 → [1,2], 502 → [1], Throttling 4회 → [1,2,4] 후 포기, AccessDenied와 Validation → 재시도 없음
  - 인자 없는 기본 fetcher(운영 경로): `boto3.client`를 monkeypatch해 네트워크 없이 `bedrock`, `pricing` 두 클라이언트가 모두 `us-east-1`, botocore `max_attempts` 1로 만들어지는지 고정(Price List API에는 ap-northeast-2 엔드포인트가 없다)
- [ ] **Step 2: 실행** — `(cd backend && python3.12 -m pytest tests/test_pricing_sync.py -q)` — Expected: FAIL. 수집 단계에서 `ModuleNotFoundError: No module named 'pricing_sync'`가 난다.
- [ ] **Step 3: 구현** — `python3 "$PB" t04-sync`(`backend/pricing_sync.py`). 핵심 규칙은 다음과 같다.
  ```python
  def classify_change(current, new):
      if current is None:
          return "no_baseline"
      old_in, old_out = _dec(current[0]), _dec(current[1])          # Decimal(str(round(v, 6)))
      if old_in == new.input and old_out == new.output:
          return "unchanged"
      for old, value in ((old_in, new.input), (old_out, new.output)):
          if old <= 0 or abs(value - old) / old > CHANGE_THRESHOLD:  # 0.5 경계 포함
              return "pending"
      return "changed"

  def _run_status(channels, sources):
      skipped = sum(1 for r in channels.values() if r.startswith("skipped:"))
      if len(channels) == skipped:
          return "failed"
      if skipped or any(s["failed"] or not s["calls"] for s in sources.values()):
          return "partial"
      return "completed"
  ```
  흐름은 다음과 같다.
  1. `_open_run`으로 `running` 행을 먼저 커밋한다.
  2. `_fetch_all`에서 채널을 `source_kind`별로, 이어서 `source_ref`별로 묶어 FM id 중복 없이 순차 호출한다. 순서는 anthropic_doc → pricelist → offers다. 호출 직전마다 `(now() - started_at) > deadline_s`를 검사하고, 사유는 `fetch_failed`, `offer_count`, `parse_failed`, `not_found`, `unmapped`, `deadline` 중 하나다.
  3. `_apply`는 한 세션에서 채널별로 판정하고, 런 행 마감(`finished_at`, `status`, `summary={"sources","channels","errors"[:50]}`, `changes`, `pending`)과 함께 한 번에 커밋한다. `unchanged`는 유효 행의 `observed_at`, `run_id`, `source_id`를 갱신하고, 관측값이 같은 model_id의 `rejected` 행과 같으면 결과는 `rejected`다(Interface Contract 결정 5).
  4. 예외가 나면 롤백하고 `_close_failed`로 표시한 뒤 재발생시킨다.
  기본 fetcher는 다음과 같다. boto3 `bedrock`/`pricing` us-east-1에 `Config(retries={"max_attempts": 1, "mode": "standard"}, connect_timeout=10, read_timeout=30)`을 쓴다. httpx는 `Timeout(30, connect=10)`, `follow_redirects=True`, `User-Agent: bedrock-llm-monitor-pricing-sync (+https://github.com/whchoi98/model-monitoring)`이다. `_with_retries`는 첫 시도 외에 최대 3회 재시도하며 1/2/4 s 간격이다. 재시도 대상은 Throttling 계열 코드, HTTP 5xx, botocore 연결 오류와 HTTPClientError, httpx 429/5xx와 TransportError다.
- [ ] **Step 4: 테스트** — `(cd backend && python3.12 -m pytest tests/test_pricing_sync.py -q)` → `35 passed`. 이어서 `(cd backend && python3.12 -m pytest tests/ -q)` → `643 passed`, `(cd backend && ruff check pricing_sync.py tests/test_pricing_sync.py)` → `All checks passed!`.
- [ ] **Step 5: 커밋**
  ```bash
  git add backend/pricing_sync.py backend/tests/test_pricing_sync.py
  git commit -m "feat(pricing): 12-hour official price sync with 50% review gate and run records"
  ```

---

## Task 5: PricingSync one-shot 러너 `backend/pricing_sync_runner.py`

**Files:**
- Create: `backend/pricing_sync_runner.py` (149행)
- Create: `backend/tests/test_pricing_sync_runner.py` (193행, 12 tests)
- Modify: 없음(구조는 `backend/auto_prober_runner.py`를 따른다)

**Interfaces:**
- Consumes: `database.{SessionLocal, create_tables, engine}`, `models.PriceSyncRun`, `prober.{AVAILABLE_MODELS, _discover_anthropic_models, _register_openai_models}`(둘 다 인자 없음, 반환 None, `AVAILABLE_MODELS`를 제자리에서 수정), `visibility.hidden_patterns`, `pricing_sources.active_channels`, `pricing_seed.ensure_seed(engine, active)`, `pricing_sync.{SYNC_LOCK_KEY, default_fetchers, run_sync}`
- Produces: `main(argv: list[str] | None = None) -> int`, `_finish(exit_code, _exit=os._exit)`, CLI `python -m pricing_sync_runner --once`(Task 13의 command). exit 0은 completed/partial이고, exit 1은 failed, 잠금 점유, create_tables/ensure_seed/run_sync 예외다.

- [ ] **Step 1: 실패하는 테스트** — `python3 "$PB" t05-test`(`backend/tests/test_pricing_sync_runner.py`). 고정하는 동작은 다음과 같다.
  - 순서: `create_tables → discover_cp → register_openai → ensure_seed → run_sync`. 등록된 CP와 OpenAI id가 active에 들어가고, `(1P)`는 숨겨지며, CP identity의 channel은 `cp`다.
  - exit code: completed 0, partial 0, failed 1
  - 등록 함수 실패는 non-fatal이다.
  - ensure_seed가 실패하면 동기화하지 않고 1, run_sync 예외도 1
  - `--once`가 없으면 SystemExit
  - 가짜 PostgreSQL 엔진: 잠금이 비어 있으면 `SELECT pg_try_advisory_lock(:key)` → `SELECT pg_advisory_unlock(:key)`(`{"key": 917350004}`)을 실행하고 커넥션을 닫는다. 잠금이 점유 중이면 exit 1, run_sync 미호출, unlock 없음.
  - SQLite는 잠금을 생략한다.
  - `HIDDEN_MODEL_PATTERNS=(1P),(us-east-1)`이면 분류 가능한 `openai:us-east-1:openai.gpt-6-sol`도 seed와 sync의 활성 집합에서 빠진다(`hidden_patterns()`가 실제로 적용되는지 고정한다. 기본 `(1P)` id는 `price_identity`도 None이라 그것만으로는 구분되지 않는다).
  - `python -m` 서브프로세스(SQLite 파일 DB, 멈춘 non-daemon 스레드): exit 0, `run_id=1 status=partial` 로그 flush, 30 s 안에 종료
- [ ] **Step 2: 실행** — `(cd backend && python3.12 -m pytest tests/test_pricing_sync_runner.py -q)` — Expected: FAIL. 수집 단계에서 `ModuleNotFoundError: No module named 'pricing_sync_runner'`가 난다.
- [ ] **Step 3: 구현** — `python3 "$PB" t05-runner`(`backend/pricing_sync_runner.py`). 핵심은 다음과 같다.
  ```python
  @contextmanager
  def _sync_lock(bind):
      if bind.dialect.name != "postgresql":
          yield True
          return
      conn = bind.connect()
      acquired = False
      try:
          acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": SYNC_LOCK_KEY}).scalar())
          conn.commit()
          yield acquired
      finally:
          try:
              if acquired:
                  conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": SYNC_LOCK_KEY})
                  conn.commit()
          except Exception:
              logger.exception("pricing_sync_runner: advisory unlock failed — invalidating the connection")
              conn.invalidate()
          finally:
              conn.close()
  ```
  `main`의 흐름은 다음과 같다.
  1. argparse로 `--once`를 필수로 받는다.
  2. `create_tables()`를 호출한다.
  3. `_register_models()`로 등록 함수를 각각 try로 감싸 호출한다.
  4. `active_channels(AVAILABLE_MODELS, hidden_patterns())`를 구한다.
  5. `ensure_seed(engine, active)`를 호출한다. 실패하면 exit 1이다(seed 없이 돌면 `no_baseline` 행이 생기고, model_id 단위 멱등 규칙 때문에 이후 seed가 영구히 빠진다).
  6. `with _sync_lock(engine)`에서 잠금을 못 잡으면 경고 후 1을 반환하고, 잡으면 `run_sync(SessionLocal, active, default_fetchers())`를 호출한다.
  7. `_report(run_id)`가 결과 Counter를 로그로 남기고(`pricing_sync_runner: run_id=… status=… changes=… pending=… results=… errors=…`) 상태로 exit code를 정한다.
  `if __name__ == "__main__": _finish(main())`의 `_finish`는 `engine.dispose()` → `logging.shutdown()` → stdout/stderr flush → `os._exit`다.
- [ ] **Step 4: 테스트** — `(cd backend && python3.12 -m pytest tests/test_pricing_sync_runner.py -q)` → `12 passed`. 이어서 `(cd backend && python3.12 -m pytest tests/ -q)` → `655 passed`, `(cd backend && ruff check pricing_sync_runner.py tests/test_pricing_sync_runner.py)` → `All checks passed!`. 서브프로세스 테스트가 SQLite 파일을 임시 디렉터리에 만들므로 `git status --short`에 이 태스크의 두 파일만 보여야 한다.
- [ ] **Step 5: 커밋**
  ```bash
  git add backend/pricing_sync_runner.py backend/tests/test_pricing_sync_runner.py
  git commit -m "feat(pricing): PricingSync one-shot runner (advisory lock 917350004, os._exit)"
  ```

---

## Task 6: Time-effective row cost (`price_history.py`), cost/efficiency refactor, delete `pricing.py`

**Files:**
- Create: `backend/price_history.py`
- Modify: `backend/routers/cost.py` (lines 1-7 docstring, 24 import, 82-103 summary, 150-174 channel-compare, 213-235 trend)
- Modify: `backend/routers/efficiency.py` (line 27 import, 111-120, 146-148)
- Delete: `backend/pricing.py`
- Create (test helper): `backend/tests/_legacy_pricing_v2291.py` (frozen copy of v2.29.1 `pricing.py`)
- Create tests: `backend/tests/test_price_history.py`, `backend/tests/test_cost_time_effective.py`
- Modify tests: `backend/tests/test_openai_pricing.py` (full rewrite, lines 1-93), `backend/tests/test_fable51_catalog.py` (lines 3-6, 34-37), `backend/tests/test_opus55_gpt6_catalog.py` (lines 13-16, 81-86, 144-156)

**Interfaces:**
- Consumes: `models.PriceHistory`, `models.PriceSyncRun`, `models.ProbeResult`; `pricing_sources.EPOCH`, `price_identity`, `active_channels`, `ANTHROPIC_SOURCE_ID`; `pricing_seed.SEED`, `CP_SEED`, `ensure_seed`.
- Produces: `price_history.effective_prices_subquery()`, `with_row_cost(query) -> (query, row_cost)`, `current_rows(db, model_ids, *, now=None)`, `pending_rows(db, model_ids)`, `last_finished_run(db)`, `verification_of(row, last_run)`; helpers `as_utc(dt)`, `EFFECTIVE_STATUSES`.

- [ ] **Step 1: Write the failing tests and the frozen legacy copy**

1. Frozen copy (verbatim body of v2.29.1, main `8ffb283`): `python3 "$PB" t06-legacy` writes `backend/tests/_legacy_pricing_v2291.py`. It is `git show 8ffb283:backend/pricing.py` with lines 1-7 (the original module docstring) replaced by:
```python
"""FROZEN copy of backend/pricing.py at v2.29.1 (git 8ffb283) — equivalence test only (ADR-030).

backend/pricing.py was deleted in v2.30.0; costs now come from price_history (price_history.py).
test_cost_time_effective.py checks that the new per-row cost equals this copy on the 44 channels
whose price did not change, and that the 11 corrected channels (Bedrock Claude US x1.1, Nova 2.0
Lite 0.33/2.75) differ from it. Never edit the table below and never import this module from
application code.
"""
```
Check the body is unchanged (must print nothing):
```bash
diff <(git show 8ffb283:backend/pricing.py | tail -n +8) <(tail -n +9 backend/tests/_legacy_pricing_v2291.py)
```

2. `backend/tests/test_price_history.py` (block `t06-test-history`, 13 tests). SQLite fixture with one `ProbeRun`; helpers `_price(db, model_id, inp, out, effective_from, *, status="verified", observed_at=None, source_id="offer:offer-test", channel="global", family_key="claude-sonnet-5")`, `_probe(db, model_id, ts, input_tokens=1_000_000, output_tokens=1_000_000)`, `_costs(db)` = `with_row_cost(db.query(ProbeResult.id))` + `add_columns(row_cost)`. `T = datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc)`, `M = "global.anthropic.claude-sonnet-5"`. Tests:
   - `test_row_exactly_at_effective_from_uses_the_new_price`: seed 1/5 at EPOCH, verified 2/10 at T; probes at T-1s, T, T+1s cost 6.0, 12.0, 12.0.
   - `test_model_without_price_rows_keeps_its_row_with_null_cost`: unknown model row present with cost None (LEFT OUTER JOIN).
   - `test_null_tokens_count_as_zero`: (None, 1000) at 1/5 -> 0.005; (None, None) -> 0.0, not None.
   - `test_pending_and_rejected_rows_never_price_a_probe`.
   - `test_same_effective_from_higher_id_wins_without_duplicating_the_probe_row`: two verified rows at T (2/10, 3/15) -> exactly one joined row, cost 18.0.
   - `test_row_cost_is_a_python_float`: `type(cost) is float`.
   - `test_row_cost_sql_is_portable_to_postgresql`: compiled with `postgresql.dialect()` contains `LEFT OUTER JOIN`, `lead(price_history.effective_from) OVER (PARTITION BY price_history.model_id ORDER BY price_history.effective_from, price_history.id)`, `AS FLOAT)`, `coalesce(probe_results.input_tokens`.
   - `test_current_rows_returns_the_row_effective_at_now`, `test_pending_rows_returns_the_most_recently_observed_pending_row`, `test_last_finished_run_ignores_running_rows_and_keeps_any_status` (latest finished run is the failed one).
   - `test_verification_states`: none / seed_only (also with no run) / verified at the boundary `observed_at == run.started_at` / stale 1 s earlier / stale with no finished run.
   - `test_cp_cells_go_stale_after_a_partial_run_where_only_the_anthropic_source_failed`.
   - `test_as_utc_normalizes_naive_and_foreign_offsets`.

3. `backend/tests/test_cost_time_effective.py` (block `t06-test-cost`, 6 tests). TestClient app with `routers.cost.router` + `routers.efficiency.router`, `HIDDEN_MODEL_PATTERNS=(1P)`. `ACTIVE_IDS` = the 55 production ids from the contract (CP haiku with date suffix `anthropic:claude-haiku-4-5-20251001`); `UNCHANGED` = Bedrock Global 10 + CP 9 + OpenAI 25 = 44; `CORRECTED` = the 10 `us.anthropic.*` ids (Fable 5.1 11/55, Fable 5 11/55, Opus 5.5 4.4/22, Opus 5/4.8/4.7/4.6 5.5/27.5, Sonnet 5 2.2/11, Sonnet 4.6 3.3/16.5, Haiku 4.5 1.1/5.5) + Nova 0.33/2.75. Dataset: model A (`global.anthropic.claude-sonnet-5`) seed 1/5 at EPOCH, verified 2/10 from `CHANGE_AT`; one 100k/100k success probe on each side (0.6 and 1.2), an error row, an unpriced `mystery.model-v9` row, a hidden `(1P)` row. Tests:
   - `test_summary_sums_each_probe_at_its_own_price`: A cost 1.8, avg 0.9, unknown cost/avg None, total 1.8, total tokens include the unpriced model, row order by cost.
   - `test_channel_compare_adds_unpriced_models_as_zero`: "Bedrock Global" 1.8, "Other" 0.0.
   - `test_trend_buckets_per_row_cost`: bucket_minutes 60, points `[(HOUR, A, 0.6), (HOUR+2h, A, 1.2)]`.
   - `test_efficiency_averages_priced_success_rows_only`: samples 3, success_rate 0.6667, avg_cost 0.9, unknown avg None and cost component None.
   - `test_efficiency_category_filter_still_applies`.
   - `test_seeded_costs_match_v2291_on_unchanged_channels_and_fix_the_11_corrected_ones`: `pricing_seed.ensure_seed(engine, active)`, one 12,345/6,789 probe per id; 44 unchanged equal `legacy.estimate_cost_usd` (rel 1e-12) and are `float`; 11 corrected equal the official values and differ from the legacy value. If an unchanged channel fails, the Task 2 seed is wrong: fix the seed, not the test.

4. Migrate existing price assertions (they pass before and after the deletion; they only stop importing `pricing`). `python3 "$PB" --apply t06-tests` performs all three edits:
   - `backend/tests/test_openai_pricing.py`: full rewrite (8 tests): `price_identity` channels (`inregion:us-east-1`, `global`, `us`, `inregion:us-west-2`), one family key for Global and in-region (`gpt-5.6-sol`, `source_ref == "openai.gpt-5.6-sol"`), `test_dormant_1p_channel_is_not_priced` (`"openai:1p:gpt-5.4" not in SEED`, `active_channels({...: "OpenAI GPT 5.4 (1P)"}, ["(1P)"]) == {}`), seed values with `pytest.approx` (Astra 11/55, 11/55, 10/50; GPT 5.4 2.75/16.5; GPT 5.5 5.5/33; GPT 5.6 Global vs in-region; `us.anthropic.claude-fable-5` 11/55; CP Opus 4.8 5/25), and the unchanged `test_channel_openai`.
   - `backend/tests/test_fable51_catalog.py`: replace
```python
import pricing
import prober
```
with
```python
import pytest

import pricing_seed
import prober
```
add `from pricing_sources import ANTHROPIC_SOURCE_ID, price_identity` above `from routers.reliability import _LABEL_RE`, and replace the body of `test_pricing_all_three_channels` with:
```python
    # v2.30.0: per-model_id seed rows (ADR-030). Global and CP are $10/$50, Bedrock US is Global x1.1.
    for mid in ("global.anthropic.claude-fable-5-1", "us.anthropic.claude-fable-5-1", "anthropic:claude-fable-5-1"):
        assert price_identity(mid).family_key == "claude-fable-5-1", mid
    assert pricing_seed.SEED["global.anthropic.claude-fable-5-1"][:2] == pytest.approx((10.0, 50.0))
    assert pricing_seed.SEED["us.anthropic.claude-fable-5-1"][:2] == pytest.approx((11.0, 55.0))
    assert pricing_seed.CP_SEED["claude-fable-5-1"] == (10.0, 50.0, ANTHROPIC_SOURCE_ID)
    # substring prefix collision (fable-5 ⊂ fable-5-1) must not reach the price identity either
    assert price_identity("anthropic:claude-fable-5").family_key == "claude-fable-5"
```
   - `backend/tests/test_opus55_gpt6_catalog.py`: replace `import pricing` with `import pytest` + blank line + `import pricing_seed`, add `from pricing_sources import price_identity` after the `parity.catalog` import; replace the body of `test_opus55_pricing_all_three_channels_not_opus5_fallback` with:
```python
    # v2.30.0: exact per-model_id seed rows, no prefix fallback (ADR-030). Bedrock US is Global x1.1.
    for mid in ("global.anthropic.claude-opus-5-5", "us.anthropic.claude-opus-5-5", "anthropic:claude-opus-5-5"):
        assert price_identity(mid).family_key == "claude-opus-5-5", mid
    assert pricing_seed.SEED["global.anthropic.claude-opus-5-5"][:2] == pytest.approx((4.0, 20.0))
    assert pricing_seed.SEED["us.anthropic.claude-opus-5-5"][:2] == pytest.approx((4.4, 22.0))
    assert pricing_seed.CP_SEED["claude-opus-5-5"][:2] == pytest.approx((4.0, 20.0))
    # Opus 5는 불변 — CP id claude-opus-5는 Opus 5.5가 아니라 Opus 5로 분류된다
    assert price_identity("anthropic:claude-opus-5").family_key == "claude-opus-5"
    assert pricing_seed.CP_SEED["claude-opus-5"][:2] == pytest.approx((5.0, 25.0))
```
and in `test_gpt6_sol_luna_pricing_per_channel_and_never_matches_astra` replace everything after `assert sorted(expected) == sorted(_GPT6_SOL_LUNA_KEYS)` with:
```python
    astra_prices = [
        pricing_seed.SEED[mid][:2]
        for mid in (
            "openai:global:global.openai.gpt-6-astra",
            "openai:us:us.openai.gpt-6-astra",
            "openai:us-west-2:openai.gpt-6-astra",
        )
    ]
    for mid, price in expected.items():
        seeded = pricing_seed.SEED[mid][:2]
        assert seeded == pytest.approx((price["input"], price["output"])), mid
        assert seeded not in astra_prices, mid
        assert price_identity(mid).family_key != "gpt-6-astra", mid
```

Commands for this step:
```bash
python3 "$PB" t06-legacy t06-test-history t06-test-cost
python3 "$PB" --apply t06-tests
diff <(git show 8ffb283:backend/pricing.py | tail -n +8) <(tail -n +9 backend/tests/_legacy_pricing_v2291.py)
```

- [ ] **Step 2: Run them**
```bash
(cd backend && python3.12 -m pytest tests/test_price_history.py -q)
(cd backend && python3.12 -m pytest tests/test_cost_time_effective.py tests/test_openai_pricing.py tests/test_fable51_catalog.py tests/test_opus55_gpt6_catalog.py -q)
```
Expected: FAIL. `test_price_history.py` errors at collection with `ModuleNotFoundError: No module named 'price_history'` (run it on its own: pytest stops the whole run on a collection error). The second command gives `6 failed, 25 passed`: every `test_cost_time_effective.py` test fails on values because cost still comes from the flat v2.29.1 table (A costs 2.4 instead of 1.8, corrected channels equal the legacy value), and the migrated tests pass.

- [ ] **Step 3: Implement**

`backend/price_history.py` (`python3 "$PB" t06-price-history`):

<!-- plan-block id=t06-price-history path=backend/price_history.py sha256=0c2172dd599467e6cd7272cd63012389c669f043bc395f0248e132a8fee22584 -->
```python
"""Time-effective unit prices from price_history (v2.30.0, ADR-030).

The effective row for a model_id at time t is the seed/verified row with the latest
(effective_from, id) among rows whose effective_from <= t. Costs are computed per probe row
with the price that was effective at that row's timestamp:

    effective_prices = price_history rows with status IN ('seed', 'verified') plus
                       effective_to = LEAD(effective_from) OVER (PARTITION BY model_id
                                                             ORDER BY effective_from, id)
    probe_results LEFT OUTER JOIN effective_prices
        ON model_id = model_id AND timestamp >= effective_from
           AND (effective_to IS NULL OR timestamp < effective_to)
    row_cost = CAST((COALESCE(input_tokens, 0) * input_per_mtok
                     + COALESCE(output_tokens, 0) * output_per_mtok) / 1000000.0 AS FLOAT)

A model with no price row joins nothing, so row_cost is NULL (cost "-" on screen). Two rows
with the same effective_from get an empty [t, t) interval for the lower id, so a probe row
never joins twice. Every timestamp comparison is column-to-column or a bound datetime
parameter; SQLite stores DateTime values as UTC strings of one fixed format, so the string
comparison it does matches the PostgreSQL timestamptz comparison.
"""

from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import Float, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from models import PriceHistory, PriceSyncRun, ProbeResult

EFFECTIVE_STATUSES = ("seed", "verified")


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes for DateTime(timezone=True) columns; every stored value is UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def effective_prices_subquery():
    """seed/verified rows with effective_to = the next row's effective_from for the same model_id."""
    effective_to = func.lead(PriceHistory.effective_from).over(
        partition_by=PriceHistory.model_id,
        order_by=(PriceHistory.effective_from, PriceHistory.id),
    )
    return (
        select(
            PriceHistory.model_id.label("model_id"),
            PriceHistory.input_per_mtok.label("input_per_mtok"),
            PriceHistory.output_per_mtok.label("output_per_mtok"),
            PriceHistory.effective_from.label("effective_from"),
            effective_to.label("effective_to"),
        )
        .where(PriceHistory.status.in_(EFFECTIVE_STATUSES))
        .subquery("effective_prices")
    )


def with_row_cost(query):
    """Outer-join a ProbeResult query with the price effective at each row's timestamp.

    Returns (joined query, row_cost). row_cost is a Float SQL expression, NULL when the model has
    no effective price at that time; the caller adds it as a column or inside SUM()/COUNT().
    """
    ep = effective_prices_subquery()
    joined = query.outerjoin(
        ep,
        and_(
            ep.c.model_id == ProbeResult.model_id,
            ProbeResult.timestamp >= ep.c.effective_from,
            or_(ep.c.effective_to.is_(None), ProbeResult.timestamp < ep.c.effective_to),
        ),
    )
    row_cost = cast(
        (
            func.coalesce(ProbeResult.input_tokens, 0) * ep.c.input_per_mtok
            + func.coalesce(ProbeResult.output_tokens, 0) * ep.c.output_per_mtok
        )
        / 1000000.0,
        Float,
    )
    return joined, row_cost


def _latest(rows: Iterable[PriceHistory], key) -> dict[str, PriceHistory]:
    out: dict[str, PriceHistory] = {}
    for row in rows:
        best = out.get(row.model_id)
        if best is None or key(row) > key(best):
            out[row.model_id] = row
    return out


def current_rows(db: Session, model_ids: Iterable[str], *, now: Optional[datetime] = None) -> dict[str, PriceHistory]:
    """model_id -> the seed/verified row effective at `now` (default: current UTC time)."""
    ids = sorted(set(model_ids))
    if not ids:
        return {}
    at = as_utc(now) if now is not None else datetime.now(timezone.utc)
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.model_id.in_(ids))
        .filter(PriceHistory.status.in_(EFFECTIVE_STATUSES))
        .filter(PriceHistory.effective_from <= at)
        .all()
    )
    return _latest(rows, key=lambda r: (as_utc(r.effective_from), r.id))


def pending_rows(db: Session, model_ids: Iterable[str]) -> dict[str, PriceHistory]:
    """model_id -> the most recently observed pending_review row (ties: the higher id)."""
    ids = sorted(set(model_ids))
    if not ids:
        return {}
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.model_id.in_(ids))
        .filter(PriceHistory.status == "pending_review")
        .all()
    )
    floor = datetime.min.replace(tzinfo=timezone.utc)
    return _latest(rows, key=lambda r: (as_utc(r.observed_at) or floor, r.id))


def last_finished_run(db: Session) -> Optional[PriceSyncRun]:
    """The most recently finished sync run, whatever its status (completed, partial, failed)."""
    return (
        db.query(PriceSyncRun)
        .filter(PriceSyncRun.finished_at.isnot(None))
        .order_by(PriceSyncRun.finished_at.desc(), PriceSyncRun.id.desc())
        .first()
    )


def verification_of(row: Optional[PriceHistory], last_run: Optional[PriceSyncRun]) -> str:
    """Per-cell calculation state (not the row's status column).

    none      : no effective price row
    seed_only : the seed row was never confirmed by an official source (observed_at NULL)
    verified  : observed at or after the start of the latest finished run
    stale     : anything else (a source kept failing, or no run finished since the last observation)
    """
    if row is None:
        return "none"
    observed = as_utc(row.observed_at)
    if observed is None:
        return "seed_only" if row.status == "seed" else "stale"
    if last_run is not None and observed >= as_utc(last_run.started_at):
        return "verified"
    return "stale"
```

`backend/routers/cost.py` and `backend/routers/efficiency.py`: `python3 "$PB" --apply t06-routers` performs exactly these edits.

`backend/routers/cost.py`:
1. Docstring: after the first line `"""Cost Dashboard router - 토큰 단가 × 입출력 적산으로 비용 통계.` and its blank line, insert
```
v2.30.0 (ADR-030): 단가는 price_history에서 각 프로브 시각에 유효했던 값을 행 단위로 조인한다
(price_history.with_row_cost). 단가 행이 없는 모델은 비용 NULL, 토큰 합계에는 포함.

```
2. Line 24 `from pricing import estimate_cost_usd` -> `from price_history import as_utc, with_row_cost`.
3. `get_cost_summary` (lines 83-103): wrap the existing `db.query(...)` (5 columns, unchanged) as `query, row_cost = with_row_cost(db.query(...))`, then
```python
    rows = (
        query.add_columns(
            func.sum(row_cost).label("cost"),
            func.count(row_cost).label("priced"),
        )
        .filter(ProbeResult.timestamp >= since)
        .filter(ProbeResult.status == "success")
        .filter(*[~ProbeResult.model_name.contains(p) for p in hidden_patterns()])
        .group_by(ProbeResult.model_id, ProbeResult.model_name)
        .all()
    )
```
and replace `cost = estimate_cost_usd(r.model_id, int(r.in_tok), int(r.out_tok))` with `cost = float(r.cost) if r.priced else None`.
4. `get_channel_compare` (lines 151-174): same wrap (4 columns, `group_by(ProbeResult.model_id)`), same `add_columns(sum, count)`, and replace the three lines `cost = estimate_cost_usd(...)` / `if cost is not None:` / `slot["cost_usd"] += cost` with
```python
        if r.priced:  # 단가 없는 모델은 0으로 더한다 (현행 유지)
            slot["cost_usd"] += float(r.cost)
```
5. `get_cost_trend` (lines 213-235): replace the comment, query and loop head with
```python
    # date_trunc를 사용하지 않고 Python으로 bucket 계산 (DB-portable). 비용은 행 단위 시점 단가.
    query, row_cost = with_row_cost(
        db.query(
            ProbeResult.model_name,
            ProbeResult.timestamp,
        )
    )
    rows = (
        query.add_columns(row_cost.label("cost"))
        .filter(ProbeResult.timestamp >= since)
        .filter(ProbeResult.status == "success")
        .filter(*[~ProbeResult.model_name.contains(p) for p in hidden_patterns()])
        .all()
    )

    bucket_seconds = bucket_min * 60
    points_map: dict[tuple[str, str], float] = {}
    for r in rows:
        if r.cost is None:
            continue
        cost = float(r.cost)
        # bucket start: floor timestamp to bucket_min (SQLite는 naive로 돌려주므로 UTC로 고정)
        ts = as_utc(r.timestamp).replace(microsecond=0)
```
(the rest of the loop and the response are unchanged).

`backend/routers/efficiency.py`:
1. Line 27 `from pricing import estimate_cost_usd` -> `from price_history import with_row_cost`.
2. Lines 112-120:
```python
    q, row_cost = with_row_cost(visible_only(db.query(ProbeResult), ProbeResult.model_name))
    q = q.add_columns(row_cost.label("row_cost")).filter(ProbeResult.timestamp >= since)
    if category:
        q = q.filter(ProbeResult.category == category)
    rows = q.all()

    # Aggregate per model — 비용은 각 프로브 시각의 단가(row_cost, 단가 없으면 None)
    agg: dict[str, dict] = {}
    for r, cost in rows:
```
3. Lines 146-148:
```python
            if cost is not None:
                a["costs"].append(float(cost))
```

Delete the old module: `git rm backend/pricing.py`.

(`backend/CLAUDE.md` line 36 and `backend/routers/CLAUDE.md` still describe `pricing.py`; Task 14 rewrites them. Do not edit them here.)

- [ ] **Step 4: Run tests**
```bash
(cd backend && python3.12 -m pytest tests/test_price_history.py tests/test_cost_time_effective.py tests/test_openai_pricing.py tests/test_fable51_catalog.py tests/test_opus55_gpt6_catalog.py -q)
(cd backend && python3.12 -m pytest tests/ -q)
(cd backend && ruff check price_history.py routers/cost.py routers/efficiency.py tests/)
grep -rnE "^(from pricing import|import pricing$)" backend --include=*.py
```
Expected: PASS, `44 passed` (13 + 6 + 8 + the catalog tests); full suite `671 passed`; ruff `All checks passed!`; the grep prints nothing.

- [ ] **Step 5: Commit**
```bash
git add backend/price_history.py backend/routers/cost.py backend/routers/efficiency.py \
  backend/tests/_legacy_pricing_v2291.py backend/tests/test_price_history.py backend/tests/test_cost_time_effective.py \
  backend/tests/test_openai_pricing.py backend/tests/test_fable51_catalog.py backend/tests/test_opus55_gpt6_catalog.py
git commit -m "feat(cost): time-effective unit prices from price_history, remove pricing.py (ADR-030)"
```
(`git rm` already staged the deletion.)

---

## Task 7: `/api/pricing` payload builder and CSV, Markdown, JSON exports

**Files:**
- Create: `backend/pricing_payload.py`, `backend/pricing_export.py`
- Create tests: `backend/tests/_pricing_dataset.py` (shared golden dataset, not collected), `backend/tests/test_pricing_payload.py`, `backend/tests/test_pricing_export.py`

**Interfaces:**
- Consumes: `price_history.current_rows`, `pending_rows`, `last_finished_run`, `verification_of`, `as_utc`; `pricing_sources.PriceIdentity`, `PROVIDER_ORDER`, `FAMILY_ORDER`, `tier_of`, `region_of`, `ANTHROPIC_SOURCE_ID`, `OFFER_REFERENCE_URL`, `PRICELIST_REFERENCE_URL`, `ANTHROPIC_REFERENCE_URL`, `official_source_id`, `note_source_id`, `DISCLAIMER`, `OFFICIAL_PAGES`, `PRICE_NOTES`, `EPOCH`, `price_identity`; `pricing_seed.SEED_SOURCE_DATE`.
- Produces: `pricing_payload.build_pricing_payload(db, active, *, now) -> dict`, `price_number(v)`, `price_text(v)`, helper `iso_z(dt)`; `pricing_export.to_json(payload)`, `to_markdown(payload, lang)`, `to_csv(payload, lang)`, `export_filename(fmt, today)`, constants `BOM = chr(0xFEFF)`, `EXPORT_FORMATS`, `LANGS`.

- [ ] **Step 1: Write the failing tests** — `python3 "$PB" t07-dataset t07-test-payload t07-test-export`
   - `_pricing_dataset.py`: `NOW = 2026-09-25T16:00Z`, `RUN1 = 2026-09-24T15:00Z`, `RUN2 = 2026-09-25T15:00Z`; source ids `OPUS = offer:offer-7sp77cpl4rveu`, `NOVA = pricelist:USE1-Nova2.0Lite-input-tokens`, `SOL = offer:offer-gnqokrqqvdbgw`, `TERRA`, `G55` (fictional), `G54 = offer:offer-5l5a5izq5fbec`; 15 `ACTIVE_IDS` (Opus 5.5 on cp/global/us, Nova, GPT 6 Luna without rows, GPT 5.6 Sol global + us-east-1, GPT 5.6 Terra global + 3 regions, GPT 5.5 us-east-1, GPT 5.4 3 regions); test copies of `OFFICIAL_PAGES` (2 entries) and `SOL_NOTE`; `active()`, `add_price(...)`, `load(db)` (runs 1 and 2 finished, run 3 running; Nova observed only in run 1 -> stale; Sol global pending 9/45; Sol us-east-1 seed never confirmed; Terra us-west-2 verified 2.4/14.4 from RUN2 so it splits from us-east-1/us-east-2; GPT 5.5 seed-only; inactive rows for `us.anthropic.claude-opus-4-6-v1` and a pending `openai:us-east-2:openai.gpt-5.5`); `EXPECTED_PAYLOAD` = the exact dict (7 families in PROVIDER_ORDER/FAMILY_ORDER, footnotes 1..7 in first-citation order, official pages 8-9, manual note 10, `as_of` from max observed date or seed date 2026-09-26, `pending_review == 1`).
   - `test_pricing_payload.py` (7 tests): exact golden; every footnote resolves to the cited source; `price_number`/`price_text` (4.0 -> 4 int, 4.0*1.1 -> 4.4, 0.1234567 -> 0.123457, `price_text(0.00001) == "0.00001"`); promo note drops once `prior_price` is observed (verified 5.5/33 on us-east-1); rows effective after `now` are not current; empty active set returns the fixed sections; production `OFFICIAL_PAGES` (9 spec URLs) and the gpt-5.6-sol manual note are listed after the cited sources.
   - `test_pricing_export.py` (9 tests): exact golden strings `GOLDEN_MD_KO`, `GOLDEN_MD_EN`, `GOLDEN_CSV_KO` (`BOM + """# <ko disclaimer>..."""`); EN CSV differs only in disclaimer and reference titles; CSV parses back into two tables (11 price rows, references 1..10); JSON round-trips with Korean unescaped and a trailing newline; filenames `llm-monitor-unit-prices-2026-09-26.{csv,md,json}` and `ValueError` for xlsx; unknown lang raises `ValueError`; no last_sync -> "- 마지막 자동 확인: 없음", no pending line when 0.

- [ ] **Step 2: Run them**
```bash
(cd backend && python3.12 -m pytest tests/test_pricing_payload.py tests/test_pricing_export.py -q)
```
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'pricing_payload'` and `ModuleNotFoundError: No module named 'pricing_export'` (`2 errors during collection`).

- [ ] **Step 3: Implement** — `python3 "$PB" t07-payload t07-export`

`pricing_payload.py` rules:
   - `price_number(v)`: `Decimal(str(round(float(v), 6))).normalize()`, int when integral else float. `price_text`: same value as text, `format(Decimal, "f")` (never scientific). `iso_z`: `as_utc(v).strftime("%Y-%m-%dT%H:%M:%SZ")`.
   - `build_pricing_payload(db, active, *, now)`: `current_rows(db, ids, now=now)`, `pending_rows`, `last_finished_run`, `pending_review` = count of `pending_review` rows whose model_id is active. Families grouped by `family_key`, ordered by (`PROVIDER_ORDER` index, `FAMILY_ORDER` index, key). Only ids with a current row form cells. Group key = (price_number input, output, verification, pending value); `cp`/`global`/`us` take the group with the best verification (verified < stale < seed_only), ties by first model_id; `in_region` elements sorted by region, each `{"regions", "input", "output", "model_ids", "source_ids", "footnotes", "verification", "observed_at" (earliest non-null), "pending" ({id, input, output, observed_at} of the first id or null)}`. Footnote numbers assigned on first citation while walking families then tiers cp, global, us, in_region. References: cited sources (`offer:` -> kind `agreement_offer`, title `"Amazon Bedrock agreement offer rate card, <offerId> (<families>)"` / `"Amazon Bedrock 약정 오퍼 요금표, <offerId> (<families>)"`, url `pricing_sources.OFFER_REFERENCE_URL`; `pricelist:` -> `price_list`, `"AWS Price List API, AmazonBedrock usage type <usagetype> (<families>)"` / `"... 사용 유형 ..."`, url `PRICELIST_REFERENCE_URL`; `anthropic-pricing` -> `anthropic_doc` with the spec titles and `ANTHROPIC_REFERENCE_URL`), `as_of` = max observed UTC date of current rows citing it, else `SEED_SOURCE_DATE`; then `pricing_sources.OFFICIAL_PAGES` (id `official_source_id(slug)`, `as_of: null`); then manual notes present in the response (id `note_source_id(family_key)`, titles = `text_en`/`text_ko`, `url` and `as_of` null). A note is dropped when a current row of its family with `observed_at` set equals `prior_price[tier]`. `models` = active ids with a current row -> `{input, output, verification}`. `disclaimer = {"en", "ko"}` from `pricing_sources.DISCLAIMER`. `pricing_sources` is referenced as a module at call time so tests can pin `OFFICIAL_PAGES`/`PRICE_NOTES`.

`pricing_export.py` rules: `to_json` = `json.dumps(payload, ensure_ascii=False, indent=2) + "\n"`. `to_markdown`: `> disclaimer`, `# 비용 단가` / `# Unit prices`, unit, generated, last check (or 없음/none), pending line only when > 0; one `## Anthropic Claude` / `## Amazon Nova` / `## OpenAI` table per provider with columns 모델/Model, Claude Platform on AWS, Global, US, In-Region; cells `4.4 / 22` via `price_text` (no `$`), in-region `2.2 / 13.2 us-east-1, us-east-2`, elements joined by `<br>`, markers ` (자동 확인 안 됨)` / ` (not verified automatically)` for stale and seed_only, ` (검토 대기 9 / 45)` / ` (Pending review 9 / 45)`, then `[^n]`; empty cell `—`; `## 참고 사항` / `## Notes` numbered: the 5 fixed notes, `6. 최종 가격은 공식 요금 페이지에서 확인한다[^8][^9].` (official pages referenced before manual notes), then `<family>: <text>[^n]` per note (the footnote number looked up by `note_source_id(family_key)`); `## 참고 자료` / `## References` with `[^n]: title, url, 확인일 <as_of>` (`수동 메모: ` / `Manual note: ` prefix for notes); closing `> disclaimer`. `to_csv`: `BOM + "# " + disclaimer + "\n"` raw first line, `csv.writer(lineterminator="\n")`, header `provider,family,channel,regions,model_ids,input_usd_per_1m,output_usd_per_1m,verification,observed_at,footnotes,source_ids`, one row per cell (space-separated lists, `channel` cp/global/us/in_region), blank line, `reference_n,reference_id,kind,title,url,as_of`. `export_filename(fmt, today)` -> `llm-monitor-unit-prices-YYYY-MM-DD.<fmt>`; invalid fmt or lang raises `ValueError`.

- [ ] **Step 4: Run tests**
```bash
(cd backend && python3.12 -m pytest tests/test_pricing_payload.py tests/test_pricing_export.py -q)
(cd backend && python3.12 -m pytest tests/ -q)
(cd backend && ruff check pricing_payload.py pricing_export.py tests/_pricing_dataset.py tests/test_pricing_payload.py tests/test_pricing_export.py)
```
Expected: PASS, `16 passed` (7 + 9); full suite `687 passed`; ruff `All checks passed!`.

- [ ] **Step 5: Commit**
```bash
git add backend/pricing_payload.py backend/pricing_export.py backend/tests/_pricing_dataset.py \
  backend/tests/test_pricing_payload.py backend/tests/test_pricing_export.py
git commit -m "feat(pricing): /api/pricing payload builder and CSV, Markdown, JSON exports"
```

---

## Task 8: Pricing router (public + admin), register in `main.py`

**Files:**
- Create: `backend/routers/pricing.py`
- Modify: `backend/main.py` (import after line 27, include lines after line 257 — the line numbers already include Task 2's lifespan block)
- Create test: `backend/tests/test_pricing_router.py`

**Interfaces:**
- Consumes: `build_pricing_payload`, `iso_z`, `price_number`; `to_csv`, `to_markdown`, `to_json`, `export_filename`; `active_channels`, `price_identity`, `EPOCH`; `current_rows`, `as_utc`; `prober.AVAILABLE_MODELS`; `visibility.hidden_patterns`; `auth.get_current_user`; `routers.admin._ensure_admin`.
- Produces: `routers.pricing.router` (prefix `/api/pricing`), `admin_router` (prefix `/api/admin/pricing`), `invalidate_cache()`; constants `CACHE_TTL_S = 60.0`, `CP_RECENT_DAYS = 30`, patch point `_monotonic`.

- [ ] **Step 1: Write the failing test** — `python3 "$PB" t08-test` (`backend/tests/test_pricing_router.py`, 19 test cases). Fixture: SQLite, users `admin` and `viewer@example.com` (approved), one finished run 1 h ago, Opus 5.5 global/us and GPT 5.4 us-east-1/us-east-2 rows, a `(1P)` row; `prober.AVAILABLE_MODELS` monkeypatched; `invalidate_cache()` before and after. Tests: shape (4 tier keys, in_region list, hidden 1P absent, footnotes resolve); CP ids observed within 30 days stay when discovery failed (31 days drops); 60 s cache via patched `_monotonic` (59 s cached, 60 s refreshed); approve keeps `effective_from`, returns one warning for a later verified row (`5 / 25`), clears the cache, later row still wins now; no_baseline approval returns `1970-01-01T00:00:00Z`; reject then approve -> 409, unknown id -> 404; pending list shape with `change {"input": 0.5, "output": 1.0}`; admin endpoints 401 without token and 403 for a non-admin; export content types `text/csv; charset=utf-8`, `text/markdown; charset=utf-8`, `application/json` with `Content-Disposition: attachment; filename="llm-monitor-unit-prices-<today>.<ext>"`, CSV starts with `BOM + "# "`, Markdown starts and ends with the disclaimer, JSON equals `/api/pricing`; lang defaults to ko; `format=xlsx`, `lang=ja`, missing format -> 422; source-level check that `main.py` includes both routers; `HIDDEN_MODEL_PATTERNS=(1P),(us-east-2)` drops the classifiable `openai:us-east-2:openai.gpt-5.4` from `models` while us-east-1 stays (the default `(1P)` id is also unclassifiable, so only a classifiable hidden label shows the hidden rule is applied).

- [ ] **Step 2: Run it**
```bash
(cd backend && python3.12 -m pytest tests/test_pricing_router.py -q)
```
Expected: FAIL at collection with `ImportError: cannot import name 'pricing' from 'routers'`.

- [ ] **Step 3: Implement** — `python3 "$PB" t08-router` (`backend/routers/pricing.py`; no `from __future__ import annotations`)
   - `_active(db, now)`: `dict(prober.AVAILABLE_MODELS)` plus CP ids from `price_history` with `channel == "cp"` and `observed_at >= now - 30 days` (label `f"Anthropic {ident.family} (US)"`), then `active_channels(models, hidden_patterns())`.
   - `_payload(db)`: 60 s in-process cache under a `threading.Lock` keyed by nothing (both languages in the body); `invalidate_cache()` clears it.
   - `GET ""` returns the payload. `GET "/export"`: `fmt: str = Query(..., alias="format", pattern="^(csv|md|json)$")`, `lang: str = Query("ko", pattern="^(ko|en)$")`; `Response(body.encode("utf-8"), media_type=...)` with `Content-Disposition: attachment; filename="<export_filename(fmt, today UTC)>"`.
   - Admin (each calls `_ensure_admin(user)` after `Depends(get_current_user)`): `GET /pending` -> `{"pending": [{id, model_id, family_key, channel, reason ("no_baseline" when effective_from == EPOCH else "changed"), current {input, output} | null, new, change (|new - old| / old rounded to 6) | null, source_id, effective_from, observed_at}]}` ordered by id, all pending rows. `POST /pending/{row_id}/approve`: 404 unknown, 409 not pending; status -> `verified` (effective_from untouched); `warnings` = one Korean line per later verified row: `"id {id}의 단가 {in} / {out}가 {iso}부터 적용되므로, 승인한 단가는 그 시각 전까지만 적용됩니다."`; commit, `invalidate_cache()`. `POST /pending/{row_id}/reject`: same guards, status -> `rejected`, commit, `invalidate_cache()`. Responses `{ok, id, status, effective_from, warnings}`.

`backend/main.py`: after `from routers import features as features_router` add `from routers import pricing as pricing_router`, and after `app.include_router(features_router.router)` add the two include lines. `python3 "$PB" --apply t08-main` applies exactly this patch (Task 2's lifespan hook is already in place; this task does not touch the lifespan):

<!-- plan-block id=t08-main path=@scratch/patches/t08-main.patch sha256=cb16309559b1ffd12d75622707d5461f055824f1b9552d54ceff2be34e35fd06 -->
```diff
diff --git a/backend/main.py b/backend/main.py
index 61f73f4..2a29857 100644
--- a/backend/main.py
+++ b/backend/main.py
@@ -25,6 +25,7 @@ from routers import analysis as analysis_router
 from routers import parity as parity_router
 from routers import gptbench as gptbench_router
 from routers import features as features_router
+from routers import pricing as pricing_router
 
 logging.basicConfig(
     level=logging.INFO,
@@ -255,6 +256,8 @@ app.include_router(analysis_router.router)
 app.include_router(parity_router.router)
 app.include_router(gptbench_router.router)
 app.include_router(features_router.router)
+app.include_router(pricing_router.router)
+app.include_router(pricing_router.admin_router)
 
 
 @app.get("/api/health", tags=["health"])
```

- [ ] **Step 4: Run tests**
```bash
(cd backend && python3.12 -m pytest tests/test_pricing_router.py -q)
(cd backend && python3.12 -m pytest tests/ -q)
(cd backend && ruff check .)
```
Expected: PASS (`19 passed`); full suite `706 passed`; ruff `All checks passed!` for the whole backend. Importing `main` (with `JWT_SECRET_KEY` of 32+ characters and `SEED_ADMIN_PASSWORD` set) registers `/api/pricing`, `/api/pricing/export`, `/api/admin/pricing/pending`, `/api/admin/pricing/pending/{row_id}/approve` and `/api/admin/pricing/pending/{row_id}/reject`.

- [ ] **Step 5: Commit**
```bash
git add backend/routers/pricing.py backend/main.py backend/tests/test_pricing_router.py
git commit -m "feat(api): /api/pricing, /api/pricing/export and admin pending review endpoints"
```

---

## Task 9: 단가 타입, API 클라이언트, `lib/pricingTable.ts`

Tasks 9-12는 `GET /api/pricing`(계약 `PricingResponse`)과 `GET /api/pricing/export`를 소비만 한다. 테스트는 모두 오프라인(vitest는 `fetch` stub, e2e는 `page.route`)이라 백엔드 태스크와 독립적으로 frontend 워크트리(`feat/v2-30-pricing-frontend`, Execution Order 2)에서 구현, 검증한다. 순서 Task 9 → 10 → 11 → 12. 명령은 워크트리 루트에서 실행하고 `frontend` 명령은 subshell로 감싼다.

**Files:** Modify `frontend/src/lib/types.ts`(164행 뒤 추가), `frontend/src/lib/api.ts`(11-13 import, 891행 뒤 추가); Create `frontend/src/lib/pricingTable.ts`; Test `frontend/src/lib/pricingTable.test.ts`(Create)

**Interfaces:** Consumes `fetchJson`(http.ts), `parseTimestamp`(format.ts). Produces 계약의 `PriceVerification`, `PricingPending`, `PricingTier`, `PricingInRegionTier`, `PricingNote`, `PricingFamily`, `PricingReference`, `PricingModelPrice`, `PricingResponse`; `fetchPricing(signal?)`, `pricingExportUrl(format, lang)`; `formatUnitPrice`, `formatPricePair`, `PricingBadge`, `tierBadges(tier, notes, lang, today)`, `costFromPrices(models, modelId, inputTokens, outputTokens)`. 계약에 더한 export: `PricingTierKey`, `TIER_LABELS`, `utcDate`, `notesForTier`.

규칙: `formatUnitPrice(v)` = `$${v.toFixed(2)}`. 배지 순서 unverified(stale → "마지막 확인 YYYY-MM-DD", seed_only → "초기값") → pending("새 값 $x / $y") → promo(`프로모션(최소 ${min_until}까지, 수동 메모)`, UTC 오늘 > min_until이면 promo_check "프로모션 종료 여부 확인 필요"). `tierBadges`에 티어 키가 없어 호출부가 `notesForTier(notes, tierKey)`로 그 티어 메모만 남기고 `prior_price`를 그 티어로 좁힌다. 툴팁 = "프로모션 이전 단가 $5.50 / $33.00\n" + 메모 본문(설계서의 "2026-09-23 기준"은 백엔드 `PRICE_NOTES` 본문이 싣는다). `costFromPrices`는 own-property 정확 일치만(prefix fallback 없음), 토큰 null은 0(백엔드 COALESCE와 같음), 단가 없으면 null. `verification: "none"`에는 배지가 없다.

- [ ] **Step 1: Write the failing test** — `python3 "$PB" t09-test`(`frontend/src/lib/pricingTable.test.ts`, 24 tests: 포맷 7 케이스, utcDate, 배지 9, notesForTier, costFromPrices 산술/null/`toString` id/COALESCE, `pricingExportUrl` 3형식, `fetchPricing`이 Authorization 없이 `/api/pricing` 호출).
- [ ] **Step 2: 실행** — `(cd frontend && npm test -- src/lib/pricingTable.test.ts)` — Expected: FAIL `Error: Cannot find module './pricingTable' imported from …/frontend/src/lib/pricingTable.test.ts`.
- [ ] **Step 3: Implement**
  - `python3 "$PB" --apply t09-types-api`: `types.ts` 끝에 계약 `// Frontend` 블록의 타입 9개를 추가하고, `api.ts` import 목록 `AutoProbeAnomalies,` 뒤에 `PricingResponse,`를, 파일 끝에 다음을 추가한다.

```ts
// ── Unit prices (v2.30.0) ───────────────────────────────────────────────

/** Public price table, backend single source (official sources refreshed every 12 hours). */
export async function fetchPricing(signal?: AbortSignal): Promise<PricingResponse> {
  return fetchJson(`${BASE}/api/pricing`, { signal });
}

/** Same-origin download link; the backend sets Content-Disposition with the dated file name. */
export function pricingExportUrl(format: "csv" | "md" | "json", lang: "ko" | "en"): string {
  const sp = new URLSearchParams({ format, lang });
  return `${BASE}/api/pricing/export?${sp.toString()}`;
}
```

  - `python3 "$PB" t09-pricing-table`(`frontend/src/lib/pricingTable.ts`, 94행, 위 규칙 구현).
- [ ] **Step 4: 테스트** — `(cd frontend && npm test -- src/lib/pricingTable.test.ts)`, `(cd frontend && npm test)`, `(cd frontend && npm run typecheck)` — Expected: PASS, 24 tests, 전체 13 files / 258 tests(기존 234 + 24), typecheck exit 0.
- [ ] **Step 5: 커밋** — `git add frontend/src/lib/types.ts frontend/src/lib/api.ts frontend/src/lib/pricingTable.ts frontend/src/lib/pricingTable.test.ts && git commit -m "feat(frontend): pricing API client, types and pricingTable helpers (v2.30.0)"`

---

## Task 10: `/pricing` 화면, 페이지, 메뉴, 공용 `pricingFixture`

**Files:** Create `frontend/src/components/PricingPanel.tsx`, `frontend/src/app/pricing/page.tsx`; Modify `frontend/src/components/AppHeader.tsx`(26행 뒤 1행), `frontend/e2e/fixtures.ts`(1행 뒤 import 3행, 54행 앞 블록 삽입); Test `frontend/src/components/PricingPanel.test.tsx`(Create)

**Interfaces:** Consumes Task 9 전부, `useAsyncResource`, `DataError/DataLoading/DataEmpty`, `RefreshControls`, `formatDateTime`, `useLang`, `AppShell`. Produces `PricingPanel`(default), 추가 export `PricingContent({ data, lang, today, highlight, onFootnote })`(순수 렌더), `providerSections(families)`; `/pricing`(`navKey="pricing"`); nav `{ key: "pricing", label: L("Unit Prices", "비용 단가"), href: "/pricing" }`; `export const pricingFixture: PricingResponse`(e2e/fixtures.ts — vitest와 e2e 공용).

구현 요점: 제공사 섹션은 응답 순서의 연속 provider만 묶는다(재정렬 없음). 섹션마다 표 하나, 열 모델 | Claude Platform on AWS | Global | US | In-Region. 셀 `$4.00 / $20.00` + `<sup><a href="#ref-n" aria-label="참고 자료 n">[n]</a></sup>`, null 또는 빈 `in_region`은 "—"(+ sr-only "단가 없음"), `in_region` 원소마다 한 줄(`$2.75 / $16.50 us-east-1, us-east-2`). 각주는 기본 해시 이동 + `onFootnote`가 1500 ms `data-highlighted`. 참고 자료 `li id="ref-n"`(`scroll-mt-36`, 외부 링크 `rel="noopener noreferrer"`, manual_note는 "수동 메모" 표시). 표 컨테이너 `role="region" aria-label="<제공사> 단가 표" tabIndex=0 className="relative overflow-x-auto"`, 모델 열 `sticky left-0 z-10 bg-gray-900`. `relative`는 필수다: 없으면 셀의 sr-only(absolute) 텍스트가 스크롤 컨테이너에 잘리지 않아 375px에서 페이지 scrollWidth가 720px가 됐다(재현 후 수정). 면책은 상단 `role="note" aria-label="면책 안내"` 호박색 상자(+ Amazon Bedrock 요금 `https://aws.amazon.com/bedrock/pricing/`, Anthropic 요금 `https://platform.claude.com/docs/en/about-claude/pricing`)와 참고 자료 끝 `data-disclaimer="bottom"`. 마지막 자동 확인(`finished_at`, 상태 완료/일부 출처 실패/실패/진행 중), `pending_review > 0`이면 "검토 대기 n건". 다운로드 `role="group" aria-label="가격표 내려받기"` 안 `<a href={pricingExportUrl(fmt, lang)} download>` CSV/Markdown/JSON. 참고 사항 `<ol class="list-decimal">` 5개는 설계서 KO 문구 그대로(EN: "Prices are in USD per 1M tokens, Standard tier input and output", "Global channel prices can differ from the same model's US and In-Region channels", "OpenAI prices apply to inputs of 272K tokens or less", "Cache, batch, long-context and priority prices are not included", "The cost pages use the price in effect at each probe's time"). 자동 새로고침 없음(수동 새로고침만).

- [ ] **Step 1: Write the failing test** — `python3 "$PB" t10-test` 그리고 `python3 "$PB" --apply t10-fixtures`.
  - `t10-test`는 `frontend/src/components/PricingPanel.test.tsx`(7 tests, `react-dom/server` `renderToStaticMarkup`, `pricingFixture`를 `../../e2e/fixtures`에서 import)다.
  - `t10-fixtures`는 `frontend/e2e/fixtures.ts` 1행 뒤에 `import type {\n  PricingFamily, PricingModelPrice, PricingReference, PricingResponse, PricingTier,\n} from "../src/lib/types";`를, 54행(`/** All API traffic stays in fixtures…`) 앞에 `// ── GET /api/pricing (v2.30.0)`부터 `export const pricingFixture` 끝까지의 블록을 넣는다(6 패밀리: Fable 5.1(US stale), Opus 5.5, Nova(seed_only), GPT 6 Astra, GPT 5.6 Sol(promo 메모), GPT 5.4(pending + 합성 us-west-2 분리), 참고 자료 10개, 설계서 면책 문구; offer id `offer-e2efable51`, `offer-e2esol56`과 GPT 5.4 us-west-2 단가 분리는 합성값). `mockApi`는 아직 바꾸지 않는다(Task 12).
- [ ] **Step 2: 실행** — `(cd frontend && npm test -- src/components/PricingPanel.test.tsx)` — Expected: FAIL `Error: Cannot find module './PricingPanel' imported from …/frontend/src/components/PricingPanel.test.tsx`.
- [ ] **Step 3: Implement**
  - `python3 "$PB" t10-panel t10-page`: `frontend/src/components/PricingPanel.tsx`(위 요점 구현, 337행)와 `frontend/src/app/pricing/page.tsx`:

<!-- plan-block id=t10-page path=frontend/src/app/pricing/page.tsx sha256=1cada57fd9977fdae7bea65f4d860aa5cd891808ccf2bdb324d9309944a58ab2 -->
```tsx
import AppShell from "@/components/AppShell";
import PricingPanel from "@/components/PricingPanel";

export const dynamic = "force-dynamic";

export default function PricingPage() {
  return <AppShell navKey="pricing"><PricingPanel /></AppShell>;
}
```

  - `AppHeader.tsx` 26행 `{ key: "cost", label: L("Cost", "비용"), href: "/cost" },` 바로 뒤에 `{ key: "pricing", label: L("Unit Prices", "비용 단가"), href: "/pricing" },`를 넣는다(탭 제목 "비용 단가 | LLM Monitor"). `python3 "$PB" --apply t10-appheader`가 정확히 이 편집이다:

<!-- plan-block id=t10-appheader path=@scratch/patches/t10-appheader.patch sha256=bda3b5c3efe1a6c1694c85c7dc4a7b898119ef3dd763fac1b32a870bf4d23d75 -->
```diff
diff --git a/frontend/src/components/AppHeader.tsx b/frontend/src/components/AppHeader.tsx
index 75ec59e..3842fef 100644
--- a/frontend/src/components/AppHeader.tsx
+++ b/frontend/src/components/AppHeader.tsx
@@ -24,6 +24,7 @@ export function useNavItems(currentKey: string): NavItem[] {
     { key: "models", label: L("Models", "모델 탐색"), href: "/models" },
     { key: "parity", label: L("Parity Run", "패리티 런"), href: "/parity" },
     { key: "cost", label: L("Cost", "비용"), href: "/cost" },
+    { key: "pricing", label: L("Unit Prices", "비용 단가"), href: "/pricing" },
     { key: "reliability", label: L("Reliability", "신뢰성"), href: "/reliability" },
     { key: "efficiency", label: L("Efficiency", "효율성"), href: "/efficiency" },
     { key: "analysis", label: L("Analysis", "분석"), href: "/analysis" },
```

- [ ] **Step 4: 테스트** — `(cd frontend && npm test)`, `(cd frontend && npm run typecheck)`, `(cd frontend && npm run build)`, `git checkout -- frontend/next-env.d.ts frontend/CLAUDE.md AGENTS.md` — Expected: PASS, PricingPanel 7 tests, 14 files / 265 tests, build Route 목록에 `ƒ /pricing`. (워크트리의 `frontend/node_modules`가 심볼릭 링크면 build가 Turbopack 오류로 실패한다 — Global Constraints의 Worktrees 항목대로 복사한다.)
- [ ] **Step 5: 커밋** — `git add frontend/src/components/PricingPanel.tsx frontend/src/components/PricingPanel.test.tsx frontend/src/app/pricing/page.tsx frontend/src/components/AppHeader.tsx frontend/e2e/fixtures.ts && git commit -m "feat(pricing): /pricing Unit Prices page with footnotes, badges, downloads and nav item"`

---

## Task 11: 소비자를 `/api/pricing`으로 전환, 프런트 단가 미러 제거

**Files:** Modify `frontend/src/lib/pricing.ts`(1-119 전체), `frontend/src/lib/pricing.test.ts`(1-99 전체), `frontend/src/components/ModelExplorer.tsx`(5-12, 76-79, 114-117, 196, 229, 267-268, 283, 304, 311), `frontend/src/components/ComparePanel.tsx`(3-8, 123-130, 143-147, 241-269, 467-469), `frontend/src/components/CostDashboardPanel.tsx`(3, 255-259, 264-266); Test `frontend/src/components/ComparePanel.test.ts`(Create)

**Interfaces:** Consumes `fetchPricing`, `PricingResponse`, `PricingModelPrice`, `formatUnitPrice`, `formatPricePair`, `costFromPrices`. Produces `lib/pricing.ts` = `formatCost`만; 추가 export `compareMatrix(runs, prices)`, `RunningState`(ComparePanel.tsx). `ComparePanel`은 `91008c6`에서 어떤 라우트에도 마운트되지 않아(자기 파일만 참조) vitest로 고정한다.

- [ ] **Step 1: Write the failing tests** — `python3 "$PB" t11-test-pricing t11-test-compare`: `frontend/src/lib/pricing.test.ts`(전체 교체: formatCost 4건 + "formatCost만 export한다"(`Object.keys(pricing)`) + costFromPrices 조합 2건)와 `frontend/src/components/ComparePanel.test.ts`(3건: API 단가 비용과 null 제외 최저 비용, 단가 없음 → 전부 null, 성공 행만).
- [ ] **Step 2: 실행** — `(cd frontend && npm test -- src/lib/pricing.test.ts src/components/ComparePanel.test.ts)` — Expected: FAIL `4 failed | 4 passed (8)`: `AssertionError: expected [ 'estimateCost', 'formatCost', …(1) ] to deeply equal [ 'formatCost' ]`, `TypeError: compareMatrix is not a function` ×3.
- [ ] **Step 3: Implement**
  - `python3 "$PB" t11-pricing`: `frontend/src/lib/pricing.ts` 전체를 다음으로 바꾼다.

<!-- plan-block id=t11-pricing path=frontend/src/lib/pricing.ts sha256=3f1855e7449d6e0afaa3620e71e5839a12038008c57ba8885ab73d8966812b93 -->
```ts
// 비용 표시 포맷 (USD). 단가는 v2.30.0부터 백엔드 단일 출처다 — 현재 단가는 GET /api/pricing의
// `models`, 호출 비용 계산은 lib/pricingTable.ts `costFromPrices`, 비용 화면 합계는 백엔드가
// 각 프로브 시각의 단가로 계산한다(ADR-030). 이 파일에 단가 표를 다시 두지 말 것.

export function formatCost(usd: number | null): string {
  if (usd === null || usd === undefined) return "—";
  if (usd < 0.001) return `$${(usd * 1000).toFixed(2)}m`; // milli-dollars
  if (usd < 1) return `$${(usd * 100).toFixed(2)}¢`;
  return `$${usd.toFixed(4)}`;
}
```

  - `python3 "$PB" --apply t11-components`가 아래 세 파일 편집을 정확히 수행한다.
  - `ModelExplorer.tsx`: import `getPricing` → `import { formatUnitPrice, formatPricePair } from "@/lib/pricingTable";`, types에 `PricingModelPrice, PricingResponse`, api에 `fetchPricing`. `DetailModal`은 `price: PricingModelPrice | null` prop을 받고 `getPricing` 호출 삭제, 표기 `{lang === "en" ? "Input" : "입력"} {formatUnitPrice(price.input)} / {lang === "en" ? "Output" : "출력"} {formatUnitPrice(price.output)}`. 196행 뒤:

```tsx
  const pricing = useAsyncResource<PricingResponse>("pricing", fetchPricing);
  const prices = pricing.data?.models ?? null;
  const priceOf = (id: string): PricingModelPrice | null =>
    prices && Object.prototype.hasOwnProperty.call(prices, id) ? prices[id] : null;
```

    `RefreshControls`는 `refreshing={resource.refreshing || pricing.refreshing}`, `onRefresh={() => { void resource.refresh(); void pricing.refresh(); }}`. 카탈로그 DataError 뒤에 `<DataError error={pricing.error} resource={lang === "en" ? "unit prices" : "비용 단가"} onRetry={pricing.refresh} hasData={prices !== null} />`. 카드 `const price = priceOf(m.id);`, 표기 `price ? `${formatPricePair(price)} ${lang === "en" ? "(per 1M tokens, in/out)" : "(1M 토큰당 입력/출력)"}` : pricing.loading ? (lang === "en" ? "Loading prices…" : "단가 불러오는 중…") : (lang === "en" ? "Pricing unavailable" : "단가 정보 없음")`. 모달 `price={priceOf(selected.id)}`.
  - `ComparePanel.tsx`: import `estimateCost` 제거, `costFromPrices`(pricingTable), `fetchPricing`, `PricingModelPrice` 추가. `interface RunningState` → `export interface RunningState`, 그 뒤에 `export function compareMatrix(runs: RunningState[], prices: Record<string, PricingModelPrice> | null)` — 기존 `useMemo` 본문(243-268행)을 그대로 옮기되 `estimateCost(...)`를 `costFromPrices(prices, r.model_id, r.result!.input_tokens, r.result!.output_tokens)`로, `runArray`를 `runs`로 바꾼다. 상태 `const [prices, setPrices] = useState<Record<string, PricingModelPrice> | null>(null);`, 마운트 effect에 `fetchPricing().then((pricing) => setPrices(pricing.models)).catch((e) => console.error(e));`, `const matrix = useMemo(() => compareMatrix(runArray, prices), [runArray, prices]);`. 각주 문구 EN "Best value per column shown in green. Cost is estimated from the current prices on the Unit Prices page." / KO "각 컬럼의 최적 값을 녹색으로 강조. 비용은 비용 단가 메뉴의 현재 단가로 계산한 추정치입니다."
  - `CostDashboardPanel.tsx`: `import Link from "next/link";`. 방법론 `<p>`(255-259) → `<p data-cost-methodology>` KO "토큰 수는 모델 응답의 usage 객체에서 호출별로 수집합니다. 단가는 공식 출처에서 12시간마다 자동 갱신되며 각 프로브 시각의 단가로 계산합니다. 모델별 단가와 출처는 " + `<Link href="/pricing" className="text-blue-400 hover:underline">비용 단가</Link>` + " 메뉴를 참고하세요." / EN "Token counts come from each model's response usage object (per call). Unit prices are refreshed from official sources every 12 hours, and each probe is costed at the price in effect at its time. See " + Link "Unit Prices" + " for per-model prices and sources." 채널 비교 문단(264-266)의 "Unit prices may differ slightly across channels — …" / "채널별 단가가 다를 수 있으며 …"를 EN "Unit prices are refreshed from official sources every 12 hours and each probe is costed at the price in effect at its time, see " + Link + "." / KO "단가는 공식 출처에서 12시간마다 자동 갱신되며 각 프로브 시각의 단가로 계산합니다. 채널별 단가는 " + Link + " 메뉴를 참고하세요."로 교체(앞 문장 endpoint 설명은 유지).
- [ ] **Step 4: 테스트**
  ```bash
  (cd frontend && npm test)
  (cd frontend && npm run typecheck)
  grep -rnE "\b(getPricing|estimateCost)\(|PRICE_TABLE\[" frontend/src frontend/e2e
  (cd frontend && npm run build && PLAYWRIGHT_USE_PRODUCTION=1 CI=1 npx playwright test e2e/catalog-benchmark.spec.ts e2e/analytics.spec.ts e2e/shell.spec.ts --project=chromium)
  git checkout -- frontend/next-env.d.ts frontend/CLAUDE.md AGENTS.md
  ```
  Expected: PASS, 15 files / 249 tests(이전 `pricing.test.ts`의 단가 표 테스트가 빠져 줄어든다), typecheck exit 0, grep 출력 없음(exit 1 — `pricing.test.ts` 주석과 `frontend/src/lib/CLAUDE.md`의 이름 언급은 호출이 아니라 걸리지 않는다; CLAUDE.md는 Task 14가 고친다), e2e `52 passed`(아직 `/api/pricing` 모킹 전이라 `/models`에 단가 오류 알림이 따로 뜨지만 기존 스펙은 "model catalog" 알림만 필터한다).
- [ ] **Step 5: 커밋** — `git add frontend/src/lib/pricing.ts frontend/src/lib/pricing.test.ts frontend/src/components/ModelExplorer.tsx frontend/src/components/ComparePanel.tsx frontend/src/components/ComparePanel.test.ts frontend/src/components/CostDashboardPanel.tsx && git commit -m "refactor(frontend): Model Explorer, Comparison Lab and cost copy use /api/pricing; drop the price mirror"`

---

## Task 12: e2e — `/api/pricing` 모킹과 `pricing.spec.ts`

**Files:** Modify `frontend/e2e/fixtures.ts`(`mockApi` values에 1행); Create `frontend/e2e/pricing.spec.ts`

**Interfaces:** Consumes Task 10 `pricingFixture`와 DOM 훅(`data-family`, `data-tier`, `data-price-line`, `data-badge`, `data-highlighted`, `data-disclaimer`, `data-last-sync`, `data-pending-count`), Task 11 `/models` 표기와 `[data-cost-methodology]` 링크. Produces `mockApi`의 `"/api/pricing": pricingFixture`.

Chromium의 `<a download>` 요청은 다운로드 관리자가 보내 `page.route`, `context.route`를 모두 우회한다(확인: route 0회, `suggestedFilename()` = "export"). 그래서 다운로드 테스트는 `href`/`download` 속성을 단언하고 같은 href를 페이지에서 `fetch`해 가로챈 route의 `Content-Disposition`을 검증한다. 날짜 의존 배지는 `page.clock.setFixedTime(new Date("2026-09-26T12:00:00Z"))`(타이머는 계속 돈다).

- [ ] **Step 1: Write the failing test** — `python3 "$PB" t12-spec`(`frontend/e2e/pricing.spec.ts`) — 8 tests: (1) 1280px KO 렌더: h1 "비용 단가", 제목 "비용 단가 | LLM Monitor", 내비 "비용 단가"가 `aria-current="page"`이고 "비용" 바로 뒤, 면책 상자와 하단 문구, 마지막 자동 확인 "완료", "검토 대기 1건", h2 순서 [Anthropic Claude, Amazon Nova, OpenAI, 참고 사항, 참고 자료], OpenAI 행 순서, 열 헤더 5개, Opus 5.5 셀 값과 "—", GPT 5.4 두 줄과 pending 툴팁, stale/seed_only/promo 배지와 툴팁, 참고 사항 5개 문구, 참고 자료 10개와 `rel`, 수동 메모; (2) 2026-11-22 고정 시 promo_check 2개; (3) 각주 "참고 자료 7" 클릭 → URL `#ref-7`, 강조 true, 뷰포트 안, sticky 헤더 아래, 3 s 안에 false; (4) 다운로드 3형식 href `/api/pricing/export?format=<f>&lang=ko`, `download=""`, route가 준 `attachment; filename="llm-monitor-unit-prices-2026-09-26.<ext>"`, 요청 순서 `csv:ko, md:ko, json:ko`, EN 전환 후 `lang=en`과 EN 면책; (5) 375px에서 dark/light 모두 `document.scrollingElement.scrollWidth <= clientWidth`, 표 영역만 가로 스크롤, 끝까지 스크롤해도 모델 열 x 고정, 모바일 메뉴의 "비용 단가" 활성; (6) 503 → 재시도 가능한 알림, 빈 표 문구 없음, 재시도 후 표; (7) `/models` 카드 "$12.34 / $56.78 (1M 토큰당 입력/출력)", 단가 없는 모델 "단가 정보 없음", 모달 "입력 $12.34 / 출력 $56.78"; (8) `/cost` 방법론 링크 → `/pricing`.
- [ ] **Step 2: 실행** — `(cd frontend && npm run build && PLAYWRIGHT_USE_PRODUCTION=1 CI=1 npx playwright test e2e/pricing.spec.ts --project=chromium)` — Expected: FAIL `6 failed, 2 passed`(`/api/pricing`이 mockApi에서 404라 `getByRole("note", { name: "면책 안내" })` 등이 `element(s) not found`, 각주 테스트는 click timeout, "a failed price request offers a retry…"도 실패). Task 11 뒤 소스가 바뀌지 않았으므로 이미 빌드가 있으면 `npm run build`는 생략해도 된다.
- [ ] **Step 3: Implement** — `frontend/e2e/fixtures.ts` `mockApi` values에서 `"/api/insights/latest": null,` 바로 뒤에 `"/api/pricing": pricingFixture,`를 넣는다. `python3 "$PB" --apply t12-fixtures`가 정확히 이 편집이다:

<!-- plan-block id=t12-fixtures path=@scratch/patches/t12-fixtures.patch sha256=230ecab946bf26476ca2f3cb04dc55c1dd0b059084543ca356a8d0dc44374652 -->
```diff
diff --git a/frontend/e2e/fixtures.ts b/frontend/e2e/fixtures.ts
index d2b0a5a..f4e6d4b 100644
--- a/frontend/e2e/fixtures.ts
+++ b/frontend/e2e/fixtures.ts
@@ -235,6 +235,7 @@ export async function mockApi(page: Page) {
       "/api/auto-probe/anomalies": data.anomalies,
       "/api/auto-probe/categories": categories,
       "/api/insights/latest": null,
+      "/api/pricing": pricingFixture,
 
     };
     const body = values[url.pathname];
```

- [ ] **Step 4: 테스트**
  ```bash
  (cd frontend && PLAYWRIGHT_USE_PRODUCTION=1 CI=1 npx playwright test e2e/pricing.spec.ts --project=chromium)
  (cd frontend && PLAYWRIGHT_USE_PRODUCTION=1 CI=1 npx playwright test --project=chromium)
  (cd frontend && npm run typecheck && npm test)
  git checkout -- frontend/next-env.d.ts frontend/CLAUDE.md AGENTS.md
  git status --short
  ```
  Expected: PASS, `8 passed`, 전체 `100 passed`(기존 92 + 8), vitest 249 통과, status에는 이 태스크 파일만 보인다(워크트리에는 `tests/20260810_SB/`와 이 계획 파일이 없다).
- [ ] **Step 5: 커밋** — `git add frontend/e2e/fixtures.ts frontend/e2e/pricing.spec.ts && git commit -m "test(e2e): /pricing table, footnotes, downloads, phone width, nav and price consumers"`

---

## Task 13: PricingSync scheduled task in the Scheduler stack

Runs in the CDK worktree (`feat/v2-30-pricing-cdk`, Execution Order 3) and touches only `cdk/`. The old/new text below is exactly what the two patch blocks apply: `t13-tests` (the two test files) and `t13-stack` (`scheduler-stack.ts`).

**Files:**
- Modify: `cdk/lib/stacks/scheduler-stack.ts` (header comment 11-12; new role after 134; new task def after 312-317; RunTask resources 339-347; PassRole resources 355-359; new schedule before 430; new cdk-nag suppression before 476; new output after 494-496)
- Modify: `cdk/test/scheduler-stack.test.ts` (40-42, 79-81, new `describe` block inserted before 208)
- Modify: `cdk/test/image-pinning.test.ts` (104-109, it pins the number of scheduler task definitions)
- Test: `cdk/test/scheduler-stack.test.ts`, `cdk/test/image-pinning.test.ts`

**Interfaces:**
- Consumes: the CLI `python -m pricing_sync_runner --once` (`backend/pricing_sync_runner.py` `main`, contract); the existing `buildTaskDef(id, taskRole, command, logGroupName, extraEnvironment = {})` helper (the AutoProber env and secrets, 512 CPU / 1024 MiB, ARM64, 14-day log group, container name `id.toLowerCase()`); the `schedulerInvokeRole` statements `RunTaskFamilyWildcard` and `PassTaskRoles`; `schedulerTaskSg` (RDS 5432 ingress already granted by `DbIngressFromScheduler`).
- Produces: `PricingSyncTaskRole` (inline policy `pricing`, statement `OfficialPriceReads`: `bedrock:ListFoundationModelAgreementOffers`, `pricing:GetProducts`, Resource `*`), `PricingSyncTaskDef` (family `BedrockMonitorSchedulerPricingSyncTaskDef…`, container `pricingsynctaskdef`), log group `/ecs/pricingsync`, `PricingSyncSchedule` `rate(12 hours)`, CfnOutput `PricingSyncScheduleName`. Task 14's runbooks use the family prefix, the output, the log group and the container name.

Verified in the synthesized template: the L2 `EcsRunFargateTask` target also adds its own revision-pinned `ecs:RunTask` and an `iam:PassRole` for each target's task role, so the explicit `PassTaskRoles` entry keeps the ADR-011 explicit permission set complete (it is not the only PassRole grant). The stack-level `AwsSolutions-IAM5` suppression already covers `Resource::*`, but its reason is about inference profiles, so the new role gets a resource-level suppression with an accurate reason. Nothing grants the new role DB access because none is needed: DB reachability comes from `schedulerTaskSg`, and the DB secret is injected by the shared execution role.

- [ ] **Step 1: Write the failing tests** — `python3 "$PB" --apply t13-tests` performs exactly the test edits below.

In `cdk/test/scheduler-stack.test.ts` replace the count test at lines 40-42 with:

```ts
  it("Schedule이 6개 생성된다 (AutoProber + Insights + ParityRun + GptBench + FeaturesVerify + PricingSync)", () => {
    template.resourceCountIs("AWS::Scheduler::Schedule", 6);
  });
```

and the count test at lines 79-81 with:

```ts
  it("TaskDefinition이 6개 생성된다 (PricingSync 포함, v2.30.0)", () => {
    template.resourceCountIs("AWS::ECS::TaskDefinition", 6);
  });
```

Then insert this block immediately before the existing test `it("autoprober task def에 GPT-6 Sol/Luna model id가 주입된다 (v2.27.0)", () => {` (current line 208, inside the top-level `describe("SchedulerStack", …)`, after the "AutoProber 스케줄은 5분 그대로다" test):

```ts
  describe("PricingSync (v2.30.0, ADR-030)", () => {
    const PRICING_COMMAND = ["python", "-m", "pricing_sync_runner", "--once"];
    type Container = { Command: string[]; Environment?: { Name: string; Value: string }[]; Secrets?: { Name: string }[] };
    type CfnResource = ReturnType<Template["findResources"]>[string];

    const taskDefByCommand = (command: string[]): [string, CfnResource] => {
      const found = Object.entries(template.findResources("AWS::ECS::TaskDefinition")).filter(([, resource]) =>
        (resource.Properties.ContainerDefinitions as Container[]).some(
          (container) => container.Command.join(" ") === command.join(" ")));
      expect(found).toHaveLength(1);
      return found[0]!;
    };
    const containerOf = (taskDef: CfnResource): Container => taskDef.Properties.ContainerDefinitions[0];
    const pricingRoleLogicalId = (): string => {
      const [, taskDef] = taskDefByCommand(PRICING_COMMAND);
      return taskDef.Properties.TaskRoleArn["Fn::GetAtt"][0];
    };
    const schedulerStatement = (sid: string): { Resource: unknown[] } => {
      const statements = Object.entries(template.findResources("AWS::IAM::Policy"))
        .filter(([logicalId]) => logicalId.startsWith("SchedulerInvokeRoleDefaultPolicy"))
        .flatMap(([, policy]) => policy.Properties.PolicyDocument.Statement)
        .filter((statement: { Sid?: string }) => statement.Sid === sid);
      expect(statements).toHaveLength(1);
      return statements[0];
    };

    it("컨테이너 CMD는 pricing_sync_runner --once, 로그 그룹 /ecs/pricingsync 14일, 0.5 vCPU / 1 GB", () => {
      const [, taskDef] = taskDefByCommand(PRICING_COMMAND);
      expect(taskDef.Properties.Cpu).toBe("512");
      expect(taskDef.Properties.Memory).toBe("1024");
      const logGroupRef = containerOf(taskDef) as unknown as { LogConfiguration: { Options: { "awslogs-group": { Ref: string } } } };
      const logGroupId = logGroupRef.LogConfiguration.Options["awslogs-group"].Ref;
      const logGroups = template.findResources("AWS::Logs::LogGroup");
      expect(logGroups[logGroupId]?.Properties).toEqual({ LogGroupName: "/ecs/pricingsync", RetentionInDays: 14 });
    });

    it("rate(12 hours) 스케줄이 PricingSync task def를 실행한다 (ParityRun과 별개의 12시간 스케줄)", () => {
      const [taskDefId] = taskDefByCommand(PRICING_COMMAND);
      const targeting = Object.values(template.findResources("AWS::Scheduler::Schedule"))
        .filter((schedule) => schedule.Properties.Target.EcsParameters.TaskDefinitionArn.Ref === taskDefId);
      expect(targeting).toHaveLength(1);
      expect(targeting[0]!.Properties.ScheduleExpression).toBe("rate(12 hours)");
      expect(targeting[0]!.Properties.Description).toMatch(/every 12 hours/);
      const twelveHour = Object.values(template.findResources("AWS::Scheduler::Schedule"))
        .filter((schedule) => schedule.Properties.ScheduleExpression === "rate(12 hours)");
      expect(twelveHour).toHaveLength(2);
    });

    it("AutoProber와 같은 env/secret을 받는다 (CP 디스커버리, OpenAI 등록용) — CP 주기 노브만 빠진다", () => {
      const pricing = containerOf(taskDefByCommand(PRICING_COMMAND)[1]);
      const autoProber = containerOf(taskDefByCommand(["python", "-m", "auto_prober_runner", "--once"])[1]);
      expect(pricing.Environment).toEqual(
        (autoProber.Environment ?? []).filter((variable) => variable.Name !== "ANTHROPIC_CP_PROBE_INTERVAL_S"));
      expect((pricing.Secrets ?? []).map((secret) => secret.Name).sort())
        .toEqual((autoProber.Secrets ?? []).map((secret) => secret.Name).sort());
      expect((pricing.Secrets ?? []).map((secret) => secret.Name)).toEqual(
        expect.arrayContaining(["ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "OPENAI_API_KEY", "DB_HOST", "DB_PASSWORD"]));
    });

    it("전용 task role은 가격 읽기 액션 2개만 갖는다 — bedrock:Invoke* 없음, 다른 정책 없음", () => {
      const roleId = pricingRoleLogicalId();
      const role = template.findResources("AWS::IAM::Role")[roleId];
      expect(role).toBeDefined();
      expect(role!.Properties.ManagedPolicyArns).toBeUndefined();
      const statements = (role!.Properties.Policies as { PolicyDocument: { Statement: { Action: string | string[]; Resource: unknown }[] } }[])
        .flatMap((policy) => policy.PolicyDocument.Statement);
      const actions = statements.flatMap((statement) => [statement.Action].flat()).sort();
      expect(actions).toEqual(["bedrock:ListFoundationModelAgreementOffers", "pricing:GetProducts"]);
      expect(statements.map((statement) => statement.Resource)).toEqual(["*"]);
      expect(actions.some((action) => action.startsWith("bedrock:Invoke"))).toBe(false);
      // 이 역할에 붙는 AWS::IAM::Policy(DefaultPolicy 등)가 없어야 한다.
      const attached = Object.values(template.findResources("AWS::IAM::Policy"))
        .filter((policy) => JSON.stringify(policy.Properties.Roles ?? []).includes(roleId));
      expect(attached).toEqual([]);
    });

    it("Scheduler 역할: RunTask family ':*'와 명시 PassRole 목록에 PricingSync가 들어간다 (ADR-011)", () => {
      const [, taskDef] = taskDefByCommand(PRICING_COMMAND);
      const family = taskDef.Properties.Family as string;
      expect(schedulerStatement("RunTaskFamilyWildcard").Resource).toContain(
        `arn:aws:ecs:us-east-1:111111111111:task-definition/${family}:*`);
      expect(schedulerStatement("PassTaskRoles").Resource).toContainEqual({ "Fn::GetAtt": [pricingRoleLogicalId(), "Arn"] });
    });

    it("스케줄 이름을 PricingSyncScheduleName output으로 내보낸다 (런북 수동 run-task용)", () => {
      expect(Object.keys(template.findOutputs("PricingSyncScheduleName"))).toEqual(["PricingSyncScheduleName"]);
    });
  });
```

In `cdk/test/image-pinning.test.ts` replace lines 104-109:

Old:
```ts
  it("scheduler의 autoprober/insights/parity/gptbench/features task definition도 backend digest URI를 사용한다", () => {
    const tds = schedTemplate.findResources("AWS::ECS::TaskDefinition");
    const images = Object.values(tds).map(
      (td) => (td as any).Properties.ContainerDefinitions[0].Image,
    );
    expect(images).toHaveLength(5); // autoprober + insights + parityrun (v2.11.0) + gptbench (v2.18.0) + featuresverify (v2.23.0)
```
New:
```ts
  it("scheduler의 autoprober/insights/parity/gptbench/features/pricingsync task definition도 backend digest URI를 사용한다", () => {
    const tds = schedTemplate.findResources("AWS::ECS::TaskDefinition");
    const images = Object.values(tds).map(
      (td) => (td as any).Properties.ContainerDefinitions[0].Image,
    );
    // autoprober + insights + parityrun (v2.11.0) + gptbench (v2.18.0) + featuresverify (v2.23.0) + pricingsync (v2.30.0)
    expect(images).toHaveLength(6);
```

- [ ] **Step 2: Run the tests**

```bash
(cd cdk && npx jest test/scheduler-stack.test.ts test/image-pinning.test.ts)
```

Expected: FAIL with `Tests: 9 failed, 21 passed, 30 total`: "Expected 6 resources of type AWS::Scheduler::Schedule but found 5", "Expected 6 resources of type AWS::ECS::TaskDefinition but found 5", the six `PricingSync (v2.30.0, ADR-030)` tests fail at `expect(found).toHaveLength(1)` because no task definition runs `pricing_sync_runner`, and the image-pinning test fails with "Expected length: 6, Received length: 5".

- [ ] **Step 3: Implement `cdk/lib/stacks/scheduler-stack.ts`** — `python3 "$PB" --apply t13-stack` performs exactly the eight replacements below.

Apply these eight replacements; each old block occurs exactly once in the current file. Do not change the `SchedulerTaskSg` description or any existing construct id (a description change replaces the security group).

(1) Header comment, after current lines 11-12

Old:
```ts
//     (v2.29.0: 매일 17:30 UTC = 02:30 KST 고정 1회. 이전 rate(24 hours)는 스케줄 생성 시각 기준이라 시각이 고정되지 않았다)
```
New:
```ts
//     (v2.29.0: 매일 17:30 UTC = 02:30 KST 고정 1회. 이전 rate(24 hours)는 스케줄 생성 시각 기준이라 시각이 고정되지 않았다)
//   - rate(12 hours) → PricingSync Fargate Task (pricing_sync_runner --once)
//     (v2.30.0: 공식 단가 동기화 — Bedrock agreement offers, AWS Price List, Anthropic pricing.md. 모델 호출 권한 없음, ADR-030)
```

(2) `PricingSyncTaskRole`, after current line 134 (`insightsTaskRole.addManagedPolicy`)

Old:
```ts
    insightsTaskRole.addManagedPolicy(props.agentCoreMemoryAccessPolicy);
```
New:
```ts
    insightsTaskRole.addManagedPolicy(props.agentCoreMemoryAccessPolicy);

    // PricingSync (v2.30.0, ADR-030) — 공식 단가 읽기 전용 호출 2개만. 모델 호출(bedrock:Invoke*)은 주지 않는다.
    // DB는 다른 태스크와 같다(schedulerTaskSg → RDS 5432, DB secret은 실행 역할이 주입).
    // CP/OpenAI 채널 등록(_discover_anthropic_models, _register_openai_models)은 API 키 secret과 env만 쓰므로 IAM이 필요 없다.
    const pricingSyncTaskRole = new iam.Role(this, "PricingSyncTaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description: "PricingSync task role - official price reads (agreement offers, Price List) + DB, no model invocation",
      inlinePolicies: {
        pricing: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              sid: "OfficialPriceReads",
              effect: iam.Effect.ALLOW,
              actions: ["bedrock:ListFoundationModelAgreementOffers", "pricing:GetProducts"],
              // 두 API 모두 리소스 ARN이 없는 읽기 전용 카탈로그 호출이라 Resource는 *.
              resources: ["*"],
            }),
          ],
        }),
      },
    });
```

(3) `PricingSyncTaskDef`, after current lines 312-317 (`featuresTaskDef`)

Old:
```ts
      ["python", "-m", "features_runner", "--once"],
      "/ecs/features",
    );
```
New:
```ts
      ["python", "-m", "features_runner", "--once"],
      "/ecs/features",
    );

    // 공식 단가 동기화 (v2.30.0, ADR-030) — 12시간마다 활성 55채널의 Standard 입력/출력 단가를 공식 출처에서 읽어
    // price_history에 기록한다(50% 초과 변화는 검토 대기). 같은 env/secret(buildTaskDef 기본값)으로 CP 디스커버리와
    // OpenAI 채널 등록을 AutoProber와 똑같이 해야 활성 채널 집합이 맞는다. extraEnvironment 없음.
    const pricingSyncTaskDef = buildTaskDef(
      "PricingSyncTaskDef",
      pricingSyncTaskRole,
      ["python", "-m", "pricing_sync_runner", "--once"],
      "/ecs/pricingsync",
    );
```

(4) `RunTaskFamilyWildcard` resources, after current line 346

Old:
```ts
          `arn:aws:ecs:${this.region}:${this.account}:task-definition/${featuresTaskDef.family}:*`,
```
New:
```ts
          `arn:aws:ecs:${this.region}:${this.account}:task-definition/${featuresTaskDef.family}:*`,
          `arn:aws:ecs:${this.region}:${this.account}:task-definition/${pricingSyncTaskDef.family}:*`,
```

(5) `PassTaskRoles` resources, current lines 355-359

Old:
```ts
          autoProberTaskRole.roleArn,
          insightsTaskRole.roleArn,
          executionRole.roleArn,
```
New:
```ts
          autoProberTaskRole.roleArn,
          insightsTaskRole.roleArn,
          // PricingSync 역할도 명시 목록에 둔다 — L2 target이 붙이는 revision 고정 문에 기대지 않는다(ADR-011).
          pricingSyncTaskRole.roleArn,
          executionRole.roleArn,
```

(6) `PricingSyncSchedule`, before current line 430 (`InsightsSchedule`)

Old:
```ts
    this.insightsSchedule = new scheduler.Schedule(this, "InsightsSchedule", {
```
New:
```ts
    const pricingSyncSchedule = new scheduler.Schedule(this, "PricingSyncSchedule", {
      // 12시간 주기 (v2.30.0, 사용자 결정 2026-09-26) — offers FM 18개 순차 약 25초 + Price List 1회 + Anthropic 문서 1회.
      //   런 전체 상한 300초(SYNC_DEADLINE_S), pg_advisory_lock(917350004)로 수동 실행과 겹치지 않는다.
      schedule: scheduler.ScheduleExpression.rate(cdk.Duration.hours(12)),
      description: "Official unit-price sync (Bedrock agreement offers, AWS Price List, Anthropic pricing doc) every 12 hours",
      target: new schedulerTargets.EcsRunFargateTask(props.cluster, {
        taskDefinition: pricingSyncTaskDef,
        vpcSubnets: props.appSubnets,
        securityGroups: [schedulerTaskSg],
        assignPublicIp: false,
        platformVersion: ecs.FargatePlatformVersion.LATEST,
        role: schedulerInvokeRole,
      }),
    });

    this.insightsSchedule = new scheduler.Schedule(this, "InsightsSchedule", {
```

(7) cdk-nag reason for the new role, before current lines 476-477 (`schedulerInvokeRole` suppression)

Old:
```ts
    NagSuppressions.addResourceSuppressions(
      schedulerInvokeRole,
```
New:
```ts
    NagSuppressions.addResourceSuppressions(
      pricingSyncTaskRole,
      [
        {
          id: "AwsSolutions-IAM5",
          reason:
            "ADR-030: bedrock:ListFoundationModelAgreementOffers와 pricing:GetProducts는 리소스 ARN이 없는 읽기 전용 카탈로그 호출이라 Resource *. 모델 호출 권한은 없다.",
          appliesTo: ["Resource::*"],
        },
      ],
      true,
    );

    NagSuppressions.addResourceSuppressions(
      schedulerInvokeRole,
```

(8) Output, after current lines 494-496 (`InsightsScheduleName`)

Old:
```ts
    new cdk.CfnOutput(this, "InsightsScheduleName", {
      value: this.insightsSchedule.scheduleName,
    });
```
New:
```ts
    new cdk.CfnOutput(this, "InsightsScheduleName", {
      value: this.insightsSchedule.scheduleName,
    });
    new cdk.CfnOutput(this, "PricingSyncScheduleName", {
      value: pricingSyncSchedule.scheduleName,
    });
```

- [ ] **Step 4: Run the tests**

```bash
(cd cdk && npm test)
(cd cdk && npm run typecheck)
(cd cdk && npm run lint)
(cd cdk && CDK_DEFAULT_ACCOUNT=061525506239 CDK_DEFAULT_REGION=ap-northeast-2 AWS_REGION=ap-northeast-2 \
  npx cdk synth BedrockMonitor-Scheduler --quiet -o "$(mktemp -d)/cdk.out" && echo SYNTH_OK)
```

Expected:
- `npm test` PASS: `Test Suites: 10 passed, 10 total`, `Tests: 85 passed, 85 total` (79 before plus 6 new). The existing test "autoprober task def만 Claude Platform on AWS 수집 주기 env를 명시한다" still passes because PricingSync gets no extra environment.
- `typecheck` exits 0. `lint` reports 0 errors (the 2 `no-explicit-any` warnings in `test/image-pinning.test.ts` are pre-existing).
- `cdk synth` prints the existing "backendImage context 미지정" warning, the CDK notice "13 feature flags are not configured" and `SYNTH_OK`. In `<out>/AwsSolutions--BedrockMonitor-Scheduler-NagReport.csv` the `PricingSyncTaskRole` rows are `AwsSolutions-IAM4 Compliant` and `AwsSolutions-IAM5 Suppressed` with the ADR-030 reason, and `PricingSyncTaskDef` has `AwsSolutions-ECS2 Suppressed` and `AwsSolutions-ECS7 Compliant`. Synth reads the cached AZ lookup in `cdk/cdk.context.json` (gitignored; copy it into the worktree, Execution Order 3); without that file the CLI needs AWS credentials for the lookup.

- [ ] **Step 5: Commit**

```bash
git add cdk/lib/stacks/scheduler-stack.ts cdk/test/scheduler-stack.test.ts cdk/test/image-pinning.test.ts
git commit -m "infra(scheduler): PricingSync task every 12 hours with a price-read-only task role"
```

---

## Task 14: Docs and release v2.30.0 (runs last)

Runs **last**, on the merged `feat/v2-30-pricing-menu` (Execution Order 4), because it documents every earlier task's names and bumps the release version. The exact text of every new document and every edit is in plan blocks: `t14-adr` (new ADR-030), `t14-docs` (patch over 22 modified files, including the CHANGELOG entry and the version bump), `t14-late` (patch over `frontend/CLAUDE.md` and `AGENTS.md`, applied after the test runs because the frontend tooling touches those two files), and two one-off checks that are not committed, `t14-doccheck` (`@scratch/e2_doccheck.py`) and `t14-mermaid-check` (`@scratch/mermaid-check.cjs`). The patches were produced by applying the verified edit scripts to the merged tree of Tasks 1-13 (`DOCCHECK OK`, 25 files changed) and then aligning ADR-030, the API reference, both runbooks and the module CLAUDE.md files with the final code (sync channel results including `rejected`, run status rule, exit codes and log lines, admin 404/409 and response fields, exact pricing test file names).

**Files** (line anchors at `91008c6` unless noted):
- Create: `docs/decisions/ADR-030-pricing-auto-sync-time-effective-cost.md` (Status, Date 2026-09-26, Supersedes ADR-025's query-time re-pricing rule, Related, Code; Context with the three official sources; options table (source of truth, cost timing, pre-v2.30 reconstruction, 11-channel correction, change guard, storage unit); Decision 1-7 (price history tables and effective row, seed + the 11 corrected channels table, 12-hour sync steps with the dimension regex, selection order and the unchanged/changed/pending/no_baseline/rejected/skipped table, run status and exit codes, admin approval, per-row cost join, display/verification/disclaimer/manual promo note, infra); Consequences (+/−))
- Modify: `docs/decisions/ADR-025-openai-global-cris-channels.md` (follow-up "## 후속 (v2.30.0, 2026-09-26) — 소급 정책 대체" after line 75), `docs/decisions/ADR-028-claude-opus-5-5-and-gpt-6-sol-luna.md` (follow-up after line 197: Sol/Luna model cards published and match the offers, pricing now synced, Opus 5.5 US $4.40 / $22, Sol promo note)
- Modify: `CHANGELOG.md` (new `## v2.30.0 — 2026-09-26` entry before line 10: Added (Unit Prices page, 12-hourly sync with the 50% guard and admin approval, `GET /api/pricing`), Changed (time-effective costs, Model Explorer and Comparison Lab read `/api/pricing`), Fixed (the 11 channels with old and new prices), Removed (`backend/pricing.py`, frontend `PRICE_TABLE`/`getPricing`/`estimateCost`), Infra (PricingSync CDK, 85 CDK tests, deploy path), Docs; every bullet EN then KO), `frontend/src/lib/version.ts` (3), `backend/main.py` (FastAPI `version=`, line 228 after Tasks 2 and 8), `frontend/package.json` (3), `frontend/package-lock.json` (3, 9)
- Modify: `README.md` (badge 4; EN 21, 23, 31, new feature bullet at 32, usage `curl` after 169-171, tree 232/236/238-239/241/250, API row after 305; KO 344, 346, 354, new bullet at 355, usage after 492-494, tree 555/559/561-562/564/573, API row after 628). Configuration table unchanged (no new env)
- Modify: `docs/architecture.md` (EN 14, 18 + new "Unit prices" paragraph, Mermaid 37/46-47/60-61/72-73/80, new "Unit price path" diagram after 96-101, 125, 126, 132, new "Official price sources" row after 150, new `PricingSyncSchedule` row + role sentence 160-162, 169, 177, 203, 210, ADR 030 row after 238; KO 255, 259, Mermaid 278/287-288/301-302/313-314/321, "단가 경로" diagram after 337-342, 366, 367, 373, row after 391, 401-403, 410, 418, 444, 451, row after 479)
- Modify: `docs/api-reference.md` (cost semantics 288-293, efficiency 298-299, new "## Unit Prices (Public) — v2.30.0, ADR-030" section with `GET /api/pricing` (abridged spec JSON) and `GET /api/pricing/export` before 306, admin `GET /api/admin/pricing/pending` (response fields), `POST …/{row_id}/approve`, `POST …/{row_id}/reject` (404/409) after 406-407)
- Modify: `CLAUDE.md` (overview 5, scheduling 15, pages 34 + `/pricing`, scheduler tree 49 + PricingSync, directory tree 75 (pricing.py → 8 new modules), 100, 118, 135, 152, 162, model notes 244-248/250/251 that relied on `PRICE_TABLE` keys and prefix fallback, new **단가 (v2.30.0, ADR-030)** paragraph after 257 that replaces that guidance and carries the model-add checklist (`pricing_sources.py`, `pricing_seed.py`, `FAMILY_ORDER` parity), public endpoints 301, admin 303, migration bullet after 363 (create_all, locks 917350003/917350004, tz-aware binds). Env table unchanged)
- Modify: `backend/CLAUDE.md` (11, 15, 36 → unit-price module list, 39, 42, 45, new timestamp constraint after 61), `backend/routers/CLAUDE.md` (4, 18, 20 + `pricing.py` entry, 37 — `test_cost_time_effective.py`, `test_pricing_router.py`), `backend/tests/CLAUDE.md` (4, 17 + the 11 pricing test files and the 3 shared data modules), `frontend/src/lib/CLAUDE.md` (5, 8, 15 + `pricingTable.ts`, 24 rule, 26, 30 vitest scope), `frontend/src/components/CLAUDE.md` (8, 17, 18 + `PricingPanel.tsx`, 21), `frontend/src/app/CLAUDE.md` (15, 19), `cdk/CLAUDE.md` (16, 24, 31 → 85 tests)
- Modify: `docs/runbooks/deploy.md` (106, 111, 120, new "### 5-4. v2.30.0 배포 경로와 확인" between 412 and 414 with the manual `run-task` using `PricingSyncScheduleName` and the scheduler `awsvpcConfiguration`, `/api/pricing` verified-55 check, corrected-cost check, export headers, 421), `docs/runbooks/troubleshooting.md` (three sections after line 3: "비용 단가 동기화 실패", "검토 대기 단가 승인" with admin-token `curl`, 60 s cache note, "GPT-5.6 Sol 프로모션 종료 확인 — 2026-11-21 이후"), `docs/runbooks/rollback.md` (70), `docs/onboarding.md` (62, 76)
- Modify in Step 4b, after the test runs and the incidental revert: `frontend/CLAUDE.md` (31, pages list + `/pricing`), `AGENTS.md` (11, 20: five → six scheduled task definitions)
- Test: `@scratch/e2_doccheck.py` and `@scratch/mermaid-check.cjs` (not committed)

**Interfaces:**
- Consumes (names documented; all from the Interface Contract or Task 13): `pricing_sources.py` `price_identity`, `PriceIdentity`, `active_channels`, `tier_of`, `region_of`, `FAMILY_ORDER`, `PROVIDER_ORDER`, `DISCLAIMER`, `OFFICIAL_PAGES`, `PRICE_NOTES`, `ANTHROPIC_DOC_NAMES`, `NOVA_USAGETYPES`; `pricing_seed.py` `SEED`, `CP_SEED`, `seed_rows`, `ensure_seed`; `pricing_parsers.py` `single_public_offer`, `select_offer_price`, `parse_pricelist`, `parse_anthropic_pricing_md`, `DIMENSION_RE`, `PriceParseError`; `pricing_sync.py` `run_sync`, `Fetchers`, `default_fetchers`, `CHANGE_THRESHOLD`, `SYNC_DEADLINE_S`, `SYNC_LOCK_KEY`; `price_history.py` `effective_prices_subquery`, `with_row_cost`, `current_rows`, `pending_rows`, `last_finished_run`, `verification_of`; `pricing_payload.py` `build_pricing_payload`, `price_number`; `pricing_export.py` `to_json`, `to_markdown`, `to_csv`, `export_filename`; `routers/pricing.py` `router`, `admin_router`, `invalidate_cache`; `models.py` `PriceHistory`, `PriceSyncRun`; frontend `PricingPanel.tsx`, `pricingTable.ts` (`formatUnitPrice`, `formatPricePair`, `tierBadges`, `costFromPrices`), `api.ts` `fetchPricing`, `pricingExportUrl`; Task 13 `PricingSyncTaskRole`, `PricingSyncTaskDef`, `PricingSyncSchedule`, `/ecs/pricingsync`, output `PricingSyncScheduleName`, container `pricingsynctaskdef`.
- Produces: ADR-030 and release v2.30.0 in all six version locations. The git tag `v2.30.0` is created at the merge to main, not in this task.

- [ ] **Step 1: Write the failing check** — write the two check scripts and confirm the doc blocks are intact:

```bash
python3 "$PB" --verify
python3 "$PB" t14-doccheck t14-mermaid-check
```

Expected: `55 blocks OK`, then two lines `t14-doccheck -> <extractor dir>/e2_doccheck.py` and `t14-mermaid-check -> <extractor dir>/mermaid-check.cjs`. The check script `e2_doccheck.py` asserts: the six version locations read 2.30.0 and the CHANGELOG top entry is v2.30.0; ADR-030 exists (with "Supersedes" and `us.amazon.nova-2-lite-v1:0`) and ADR-025/028 have the v2.30.0 follow-ups; README EN/KO carry the same counts of `/pricing`, `pricing_sync_runner.py`, `/api/pricing/export`, `ADR-030`, `price_history.py`, say "Eleven analytical pages" / "11개 분석 페이지" and no longer list `pricing.py`; `docs/architecture.md` has 8 Mermaid blocks with identical EN/KO copies containing `prc["PricingSync task: 12 h"]`, "6 EventBridge schedules and 6 task definitions" / "EventBridge 스케줄 6개, 태스크 정의 6개", two `PricingSyncSchedule` rows and two ADR 030 rows; api-reference, deploy §5-4, the three troubleshooting sections, every CLAUDE.md edit, rollback, onboarding and AGENTS.md are present, and the stale strings "re-prices past rows", "must change together", "prefix fallback이 나머지 채널을 오매칭", "모델 카드가 게재되면 재대조" are gone; no edited file gains a middle dot `·` compared with `HEAD` (untracked files under `docs/superpowers/` are skipped, because this plan file stays untracked there in the main checkout).

- [ ] **Step 2: Run it**

```bash
cd "$(git rev-parse --show-toplevel)" && python3 <extractor dir>/e2_doccheck.py
```

Expected: FAIL (exit 1), first lines `version.ts not v2.30.0`, `backend/main.py FastAPI version not 2.30.0`, `frontend/package.json version`, `package-lock.json versions`, `README badge`, `CLAUDE.md overview`, `CHANGELOG top entry is not v2.30.0`, `ADR-030 missing or incomplete`, then the README, architecture, api-reference, runbook and CLAUDE.md messages.

- [ ] **Step 3: Implement** (from the repository root)

```bash
cd "$(git rev-parse --show-toplevel)"
python3 "$PB" t14-adr
python3 "$PB" --apply t14-docs
git status --short   # 22 modified files + the new ADR-030 (frontend/CLAUDE.md and AGENTS.md come in Step 4b)
```

If the release commit is made on a later UTC date than 2026-09-26, change the date in the new `## v2.30.0 — 2026-09-26` heading of `CHANGELOG.md` and the ADR-030 `**Date**` line to `date -u +%F`.

Key content (exact text is in the blocks):
- Mermaid (both copies, identical): `be["backend service: FastAPI, 18 routers, port 8000"]`; `prc["PricingSync task: 12 h"]` in the ingestion subgraph; new `subgraph pricesrc[Official Price Sources]` with `offers["Bedrock agreement offers, us-east-1"]`, `plist["AWS Price List API, us-east-1"]`, `adoc["Anthropic pricing.md, platform.claude.com"]`; edges `sched --> ap & ins & par & gpt & feat & prc`, `prc --> offers & plist & adoc`, `prc -.->|"CP model list"| cp`, `be & ap & ins & par & gpt & feat & prc --> rds`; new `flowchart LR` "Unit price path": EventBridge Scheduler → PricingSync task → offers/Price List/pricing.md → price_history → backend `/api/pricing`, `/api/cost/*` → frontend `/pricing`, `/cost` → Browser.
- Runbook commands (tested with jq/JMESPath against sample payloads and botocore shapes): network config from `aws scheduler get-schedule … --query 'Target.EcsParameters.NetworkConfiguration.awsvpcConfiguration'` mapped to run-task keys with `jq -c '{awsvpcConfiguration: {subnets: .Subnets, securityGroups: .SecurityGroups, assignPublicIp: .AssignPublicIp}}'`; verification count `jq '[.models[] | .verification] | group_by(.) | map({(.[0]): length}) | add'` expecting `{"verified": 55}`; stopped-task exit code via `containers[?name=='pricingsynctaskdef'].exitCode|[0]` (containers[0] can be the GuardDuty sidecar); offer check with `--query` limited to `dimension, price` so `offerToken` and `legalTerm.url` are never printed; sync log lines as the runner writes them (`pricing_sync_runner: run_id=… status=… results=… errors=…`, `lock 917350004 held by another sync`, `pricing sync: … retry n/3`).
- ADR-030 Decision 3 follows the final sync: fetch order Anthropic doc → Price List → offers, retries 1/2/4 s (Throttling, 5xx, 429, connection errors), channel results `unchanged`/`changed`/`pending`/`no_baseline`/`rejected`/`skipped:<reason>`, run status `failed`/`partial`/`completed` by the rule in Interface Contract decision 6, runner exit 0 for completed and partial, exit 1 otherwise (held lock, seed failure).

- [ ] **Step 4: Run the checks and the test suites**

```bash
cd "$(git rev-parse --show-toplevel)"
node <extractor dir>/mermaid-check.cjs docs/architecture.md
git grep -n -E "from pricing import|import pricing$|get_pricing\(|estimate_cost_usd\(|getPricing\(|estimateCost\(" -- backend frontend/src ':!backend/tests'
git add -N docs/decisions/ADR-030-pricing-auto-sync-time-effective-cost.md
git grep -n -E "PRICE_TABLE|get_pricing|estimate_cost_usd|getPricing|estimateCost|pricing mirror|pricing 미러|backend/pricing\.py|prefix fallback" -- '*.md' ':!CHANGELOG.md' ':!docs/decisions/ADR-01*' ':!docs/decisions/ADR-02*' ':!docs/superpowers' ':!docs/reviews' ':!docs/benchmarks'
(cd backend && python3.12 -m pytest tests/ -q)
(cd frontend && npm test && npm run typecheck)
(cd cdk && npm test)
git checkout -- frontend/next-env.d.ts frontend/CLAUDE.md AGENTS.md
```

Expected:
- Mermaid: `docs/architecture.md block N ok` for N = 0 to 7, exit 0 (the check loads playwright from `frontend/node_modules` and Mermaid 11 from the jsdelivr CDN, so run it from the repo root with network access).
- Code grep: no output (Tasks 6 and 11 removed every import of `backend/pricing.py` and the frontend mirror; `backend/tests` holds the frozen v2.29.1 copy and is excluded).
- Docs grep: only lines that state the removal or the history — `CLAUDE.md` (GPT-6 Astra line "prefix fallback 없음", Claude Opus 5.5 line "prefix fallback이 없고", the **단가 (v2.30.0, ADR-030)** paragraph), `backend/CLAUDE.md` ("Unit prices … is gone"), `docs/api-reference.md` ("`backend/pricing.py` (removed)"), `frontend/src/lib/CLAUDE.md` ("v2.30.0 removed `PRICE_TABLE`"), ADR-030 lines 11, 16, 51, 52, 161, 190 (the Context, options, Decision 5 and Consequences lines that name the removed code). Any other hit is stale text to fix the same way.
- backend `706 passed`, frontend vitest `249 passed` + typecheck exit 0, CDK jest `85 passed`; the only code change here is the version string, and no test pins it.
- The checkout restores whatever the frontend tooling touched; Step 4b edits those two files on purpose afterwards.

- [ ] **Step 4b: Edit `frontend/CLAUDE.md` and `AGENTS.md`, then rerun the check**

```bash
python3 "$PB" --apply t14-late
python3 <extractor dir>/e2_doccheck.py
git diff --stat | tail -1
```

Expected: `t14-late applied`, then `DOCCHECK OK` (exit 0); `git diff --stat` ends with `25 files changed` (24 modified + the new ADR-030, which `git add -N` made visible).

- [ ] **Step 5: Commit**

```bash
git add docs/decisions/ADR-030-pricing-auto-sync-time-effective-cost.md \
  docs/decisions/ADR-025-openai-global-cris-channels.md docs/decisions/ADR-028-claude-opus-5-5-and-gpt-6-sol-luna.md \
  README.md docs/architecture.md docs/api-reference.md docs/onboarding.md \
  docs/runbooks/deploy.md docs/runbooks/troubleshooting.md docs/runbooks/rollback.md \
  CLAUDE.md AGENTS.md backend/CLAUDE.md backend/routers/CLAUDE.md backend/tests/CLAUDE.md \
  frontend/CLAUDE.md frontend/src/app/CLAUDE.md frontend/src/lib/CLAUDE.md frontend/src/components/CLAUDE.md cdk/CLAUDE.md \
  CHANGELOG.md frontend/src/lib/version.ts backend/main.py frontend/package.json frontend/package-lock.json
git status --short   # expected: only "?? tests/20260810_SB/" (and "?? docs/superpowers/plans/2026-09-26-pricing-menu.md" if the plan is not committed)
# If the detect-secrets pre-commit hook is installed, it rewrites the shifted line numbers in .secrets.baseline
# (docs/api-reference.md, docs/onboarding.md): review that diff, `git add .secrets.baseline`, and commit again.
git commit -m "chore(release): v2.30.0 — Unit Prices menu, official prices synced every 12 hours, time-effective costs" \
  -m "ADR-030, README EN/KO, architecture (six scheduled tasks, Mermaid), API reference, CLAUDE.md files, runbooks (PricingSync manual run, sync failures, pending approval, GPT-5.6 Sol promotion check), CHANGELOG v2.30.0 and the version bump."
```

Follow-ups outside this task (Execution Order 6): the README `/pricing` screenshot from production after deploy, the user auto-memory model-add checklist, and the `v2.30.0` tag at the merge to `main`.

---

## Appendix: Plan blocks

Machine-extracted content for the tasks above (see Global Constraints and "Applying plan blocks"). Each block is preceded by its id, target path and sha256; the extractor checks the sha256 before writing. Patches (`@scratch/patches/…`) apply with `git apply` to the tree the task starts from. Inline blocks (shown inside their tasks) are not repeated here.

### Block index

| Block | Task | Target | Bytes |
|---|---|---|---|
| `t01-catalog` | 1 | `backend/tests/pricing_catalog.py` | 4296 |
| `t01-test` | 1 | `backend/tests/test_pricing_sources.py` | 11804 |
| `t01-sources` | 1 | `backend/pricing_sources.py` | 10759 |
| `t01-models` | 1 | `@scratch/patches/t01-models.patch` | 3214 |
| `t02-test` | 2 | `backend/tests/test_pricing_seed.py` | 9922 |
| `t02-seed` | 2 | `backend/pricing_seed.py` | 6871 |
| `t02-main` | 2 | `@scratch/patches/t02-main.patch` | 1106 |
| `t03-fx-opus55` | 3 | `backend/tests/fixtures/pricing/offers_claude-opus-5-5.json` | 5371 |
| `t03-fx-sonnet46` | 3 | `backend/tests/fixtures/pricing/offers_claude-sonnet-4-6.json` | 16447 |
| `t03-fx-haiku45` | 3 | `backend/tests/fixtures/pricing/offers_claude-haiku-4-5.json` | 17100 |
| `t03-fx-astra` | 3 | `backend/tests/fixtures/pricing/offers_gpt-6-astra.json` | 3166 |
| `t03-fx-gpt54` | 3 | `backend/tests/fixtures/pricing/offers_gpt-5.4.json` | 21511 |
| `t03-fx-nova` | 3 | `backend/tests/fixtures/pricing/pricelist_nova-2-lite.json` | 5590 |
| `t03-fx-anthropic` | 3 | `backend/tests/fixtures/pricing/anthropic_pricing.md` | 11191 |
| `t03-test` | 3 | `backend/tests/test_pricing_parsers.py` | 12222 |
| `t03-parsers` | 3 | `backend/pricing_parsers.py` | 10547 |
| `t04-test` | 4 | `backend/tests/test_pricing_sync.py` | 20617 |
| `t04-sync` | 4 | `backend/pricing_sync.py` | 17874 |
| `t05-test` | 5 | `backend/tests/test_pricing_sync_runner.py` | 8234 |
| `t05-runner` | 5 | `backend/pricing_sync_runner.py` | 6209 |
| `t06-legacy` | 6 | `backend/tests/_legacy_pricing_v2291.py` | 6960 |
| `t06-test-history` | 6 | `backend/tests/test_price_history.py` | 9070 |
| `t06-test-cost` | 6 | `backend/tests/test_cost_time_effective.py` | 10221 |
| `t06-tests` | 6 | `@scratch/patches/t06-tests.patch` | 13812 |
| `t06-price-history` | 6 | `backend/price_history.py` | 6162 |
| `t06-routers` | 6 | `@scratch/patches/t06-routers.patch` | 7161 |
| `t07-dataset` | 7 | `backend/tests/_pricing_dataset.py` | 13703 |
| `t07-test-payload` | 7 | `backend/tests/test_pricing_payload.py` | 4734 |
| `t07-test-export` | 7 | `backend/tests/test_pricing_export.py` | 14269 |
| `t07-payload` | 7 | `backend/pricing_payload.py` | 10769 |
| `t07-export` | 7 | `backend/pricing_export.py` | 7944 |
| `t08-test` | 8 | `backend/tests/test_pricing_router.py` | 12144 |
| `t08-router` | 8 | `backend/routers/pricing.py` | 8878 |
| `t08-main` | 8 | `@scratch/patches/t08-main.patch` | 757 |
| `t09-test` | 9 | `frontend/src/lib/pricingTable.test.ts` | 9384 |
| `t09-types-api` | 9 | `@scratch/patches/t09-types-api.patch` | 3723 |
| `t09-pricing-table` | 9 | `frontend/src/lib/pricingTable.ts` | 4438 |
| `t10-test` | 10 | `frontend/src/components/PricingPanel.test.tsx` | 4847 |
| `t10-fixtures` | 10 | `@scratch/patches/t10-fixtures.patch` | 9118 |
| `t10-panel` | 10 | `frontend/src/components/PricingPanel.tsx` | 15879 |
| `t10-page` | 10 | `frontend/src/app/pricing/page.tsx` | 249 |
| `t10-appheader` | 10 | `@scratch/patches/t10-appheader.patch` | 850 |
| `t11-test-pricing` | 11 | `frontend/src/lib/pricing.test.ts` | 1748 |
| `t11-test-compare` | 11 | `frontend/src/components/ComparePanel.test.ts` | 2923 |
| `t11-pricing` | 11 | `frontend/src/lib/pricing.ts` | 621 |
| `t11-components` | 11 | `@scratch/patches/t11-components.patch` | 15423 |
| `t12-spec` | 12 | `frontend/e2e/pricing.spec.ts` | 11540 |
| `t12-fixtures` | 12 | `@scratch/patches/t12-fixtures.patch` | 448 |
| `t13-tests` | 13 | `@scratch/patches/t13-tests.patch` | 8521 |
| `t13-stack` | 13 | `@scratch/patches/t13-stack.patch` | 6800 |
| `t14-doccheck` | 14 | `@scratch/e2_doccheck.py` | 5614 |
| `t14-mermaid-check` | 14 | `@scratch/mermaid-check.cjs` | 1066 |
| `t14-adr` | 14 | `docs/decisions/ADR-030-pricing-auto-sync-time-effective-cost.md` | 22181 |
| `t14-docs` | 14 | `@scratch/patches/t14-docs.patch` | 182050 |
| `t14-late` | 14 | `@scratch/patches/t14-late.patch` | 3506 |

### Task 1 blocks

#### `t01-models` — `@scratch/patches/t01-models.patch`

<!-- plan-block id=t01-models path=@scratch/patches/t01-models.patch sha256=d9ec5dbc6172fc31b9c146a4df7d6b50a7e2e16073d3be587dfe5392cbb10ce3 -->
```diff
diff --git a/backend/models.py b/backend/models.py
index 0651df2..b5fe43d 100644
--- a/backend/models.py
+++ b/backend/models.py
@@ -245,6 +245,52 @@ class GptBenchResult(Base):
     error_message = Column(Text, nullable=True)
 
 
+class PriceHistory(Base):
+    """모델 채널(model_id)별 토큰 단가 이력 (v2.30.0, ADR-030).
+
+    유효 행 = 같은 model_id에서 status IN ('seed','verified')이고 effective_from <= t인 행 중
+    (effective_from, id)가 가장 늦은 행. 비용은 각 프로브 시각의 유효 단가로 계산한다
+    (price_history.py). seed 행은 effective_from=1970-01-01Z, observed_at=NULL (pricing_seed.py).
+    단가는 float로 저장한다 — numeric은 PostgreSQL에서 Decimal로 돌아와 float 누적과 섞이면 TypeError.
+    """
+
+    __tablename__ = "price_history"
+    __table_args__ = (
+        Index("ix_price_history_model_eff", "model_id", "effective_from"),
+    )
+
+    id = Column(Integer, primary_key=True, autoincrement=True)
+    model_id = Column(Text, nullable=False)          # probe_results.model_id와 같은 값
+    family_key = Column(Text, nullable=False)        # claude-opus-5-5 | gpt-6-sol | nova-2-lite ...
+    channel = Column(Text, nullable=False)           # cp | global | us | inregion:<aws-region>
+    input_per_mtok = Column(Float, nullable=False)   # USD per 1M input tokens
+    output_per_mtok = Column(Float, nullable=False)  # USD per 1M output tokens
+    effective_from = Column(DateTime(timezone=True), nullable=False)
+    source_id = Column(Text, nullable=False)         # offer:<offerId> | pricelist:<usagetype> | anthropic-pricing
+    status = Column(Text, nullable=False)            # seed | verified | pending_review | rejected
+    observed_at = Column(DateTime(timezone=True), nullable=True)  # 출처에서 마지막으로 확인한 시각, seed는 NULL
+    run_id = Column(Integer, nullable=True)          # 이 행을 만든(또는 마지막으로 관측한) price_sync_runs.id
+    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
+
+
+class PriceSyncRun(Base):
+    """공식 단가 동기화 런 1회 (v2.30.0) — PricingSync 태스크가 12시간마다 기록.
+
+    런을 시작할 때 status='running' 행을 먼저 넣고, 끝나면 completed | partial | failed로 닫는다.
+    summary: {"sources": {출처: {"calls", "ok", "failed"}}, "channels": {model_id: 결과}, "errors": [...]}.
+    """
+
+    __tablename__ = "price_sync_runs"
+
+    id = Column(Integer, primary_key=True, autoincrement=True)
+    started_at = Column(DateTime(timezone=True), nullable=False)
+    finished_at = Column(DateTime(timezone=True), nullable=True)
+    status = Column(Text, nullable=False)  # running | completed | partial | failed
+    summary = Column(JSON, nullable=True)
+    changes = Column(Integer, nullable=False, default=0)  # 적용한 새 행 수 (verified)
+    pending = Column(Integer, nullable=False, default=0)  # 런 뒤 검토 대기 채널 수 (pending, no_baseline, 재관측 포함)
+
+
 def ensure_performance_indexes(engine) -> None:
     """기존 DB에 성능 인덱스를 멱등하게 생성 (main.py lifespan에서 호출).
 
```

### Task 2 blocks

#### `t02-main` — `@scratch/patches/t02-main.patch`

<!-- plan-block id=t02-main path=@scratch/patches/t02-main.patch sha256=3d9274d30129437881c7de684f51266afd7b9d0be53fe4c5e970b582cd3800de -->
```diff
diff --git a/backend/main.py b/backend/main.py
index b2b3195..61f73f4 100644
--- a/backend/main.py
+++ b/backend/main.py
@@ -158,6 +158,18 @@ async def lifespan(app: FastAPI):
     except Exception:
         logger.exception("Label repair failed (non-fatal)")
 
+    # 단가 seed (v2.30.0, ADR-030) — price_history에 행이 하나도 없는 활성 model_id에만 공식 단가 seed를 넣는다.
+    # CP seed는 family_key 단위라 현재 활성 CP model_id로 풀어 넣어야 하므로 모델 등록 다음에 둔다.
+    # 마이그레이션과 분리된 자체 트랜잭션 + pg_advisory_xact_lock(917350003) — 실패해도 기동은 계속한다.
+    try:
+        from pricing_seed import ensure_seed
+        from pricing_sources import active_channels
+        from prober import AVAILABLE_MODELS
+        from visibility import hidden_patterns
+        ensure_seed(engine, active_channels(AVAILABLE_MODELS, hidden_patterns()))
+    except Exception:
+        logger.exception("Price seed failed (non-fatal, backend continues)")
+
     logger.info("Database tables ready.")
 
     yield
```

### Task 3 blocks

#### `t03-fx-opus55` — `backend/tests/fixtures/pricing/offers_claude-opus-5-5.json`

<!-- plan-block id=t03-fx-opus55 path=backend/tests/fixtures/pricing/offers_claude-opus-5-5.json sha256=95d9013390146e7700390c19f3cf2a895aa716a9941fad242ef0c35a72a04c59 -->
```json
{
 "modelId": "anthropic.claude-opus-5-5",
 "offers": [
  {
   "offerId": "offer-7sp77cpl4rveu",
   "termDetails": {
    "usageBasedPricingTerm": {
     "rateCard": [
      {
       "dimension": "APN2_input_tokens_global_standard",
       "price": "4",
       "description": "Input Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_global_standard",
       "price": "20",
       "description": "Output Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_cache_read_tokens_global_standard",
       "price": "0.2",
       "description": "Cache Read Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_global_standard",
       "price": "4",
       "description": "Input Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_global_standard",
       "price": "20",
       "description": "Output Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_cache_read_tokens_global_standard",
       "price": "0.2",
       "description": "Cache Read Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_global_standard",
       "price": "4",
       "description": "Input Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_global_standard",
       "price": "20",
       "description": "Output Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_cache_read_tokens_global_standard",
       "price": "0.2",
       "description": "Cache Read Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_global_standard",
       "price": "4",
       "description": "Input Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_global_standard",
       "price": "20",
       "description": "Output Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_cache_read_tokens_global_standard",
       "price": "0.2",
       "description": "Cache Read Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_global_standard",
       "price": "4",
       "description": "Input Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_global_standard",
       "price": "20",
       "description": "Output Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_cache_read_tokens_global_standard",
       "price": "0.2",
       "description": "Cache Read Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_standard",
       "price": "4.4",
       "description": "Input Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_standard",
       "price": "22",
       "description": "Output Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "EU_cache_read_tokens_standard",
       "price": "0.22",
       "description": "Cache Read Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_standard",
       "price": "4.4",
       "description": "Input Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_standard",
       "price": "22",
       "description": "Output Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USE1_cache_read_tokens_standard",
       "price": "0.22",
       "description": "Cache Read Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_standard",
       "price": "4.4",
       "description": "Input Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_standard",
       "price": "22",
       "description": "Output Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USE2_cache_read_tokens_standard",
       "price": "0.22",
       "description": "Cache Read Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "UGE1_input_tokens_standard",
       "price": "4.8",
       "description": "Input Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "UGE1_output_tokens_standard",
       "price": "24",
       "description": "Output Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "UGE1_cache_read_tokens_standard",
       "price": "0.24",
       "description": "Cache Read Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_standard",
       "price": "4.4",
       "description": "Input Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_standard",
       "price": "22",
       "description": "Output Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USW2_cache_read_tokens_standard",
       "price": "0.22",
       "description": "Cache Read Tokens - Standard",
       "unit": "Units"
      }
     ]
    }
   }
  }
 ]
}
```

#### `t03-fx-sonnet46` — `backend/tests/fixtures/pricing/offers_claude-sonnet-4-6.json`

<!-- plan-block id=t03-fx-sonnet46 path=backend/tests/fixtures/pricing/offers_claude-sonnet-4-6.json sha256=82e3a06483e55bb0ed5d4949f9a90ca7d1f361e054a5f8dec0b06ab88adc2b1f -->
```json
{
 "modelId": "anthropic.claude-sonnet-4-6",
 "offers": [
  {
   "offerId": "offer-ldnd26nhxx676",
   "termDetails": {
    "usageBasedPricingTerm": {
     "rateCard": [
      {
       "dimension": "APN2_InputTokenCount_Global_Batch",
       "price": "1.5",
       "description": "Million Batch Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_OutputTokenCount_Global_Batch",
       "price": "7.5",
       "description": "Million Batch Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_InputTokenCount_LCtx_Global_Batch",
       "price": "1.5",
       "description": "Million Batch Input Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_OutputTokenCount_LCtx_Global_Batch",
       "price": "7.5",
       "description": "Million Batch Output Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_InputTokenCount_Global",
       "price": "3",
       "description": "Million Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_OutputTokenCount_Global",
       "price": "15",
       "description": "Million Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_InputTokenCount_LCtx_Global",
       "price": "3",
       "description": "Million Input Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_OutputTokenCount_LCtx_Global",
       "price": "15",
       "description": "Million Output Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_InputTokenCount_Global_Batch",
       "price": "1.5",
       "description": "Million Batch Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_OutputTokenCount_Global_Batch",
       "price": "7.5",
       "description": "Million Batch Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_InputTokenCount_LCtx_Global_Batch",
       "price": "1.5",
       "description": "Million Batch Input Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_OutputTokenCount_LCtx_Global_Batch",
       "price": "7.5",
       "description": "Million Batch Output Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_InputTokenCount_Global",
       "price": "3",
       "description": "Million Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_OutputTokenCount_Global",
       "price": "15",
       "description": "Million Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_InputTokenCount_LCtx_Global",
       "price": "3",
       "description": "Million Input Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_OutputTokenCount_LCtx_Global",
       "price": "15",
       "description": "Million Output Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_InputTokenCount_Global_Batch",
       "price": "1.5",
       "description": "Million Batch Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_OutputTokenCount_Global_Batch",
       "price": "7.5",
       "description": "Million Batch Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_InputTokenCount_LCtx_Global_Batch",
       "price": "1.5",
       "description": "Million Batch Input Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_OutputTokenCount_LCtx_Global_Batch",
       "price": "7.5",
       "description": "Million Batch Output Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_InputTokenCount_Global",
       "price": "3",
       "description": "Million Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_OutputTokenCount_Global",
       "price": "15",
       "description": "Million Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_InputTokenCount_LCtx_Global",
       "price": "3",
       "description": "Million Input Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_OutputTokenCount_LCtx_Global",
       "price": "15",
       "description": "Million Output Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_InputTokenCount_Global_Batch",
       "price": "1.5",
       "description": "Million Batch Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_OutputTokenCount_Global_Batch",
       "price": "7.5",
       "description": "Million Batch Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_InputTokenCount_LCtx_Global_Batch",
       "price": "1.5",
       "description": "Million Batch Input Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_OutputTokenCount_LCtx_Global_Batch",
       "price": "7.5",
       "description": "Million Batch Output Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_InputTokenCount_Global",
       "price": "3",
       "description": "Million Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_OutputTokenCount_Global",
       "price": "15",
       "description": "Million Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_InputTokenCount_LCtx_Global",
       "price": "3",
       "description": "Million Input Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_OutputTokenCount_LCtx_Global",
       "price": "15",
       "description": "Million Output Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_InputTokenCount_Global_Batch",
       "price": "1.5",
       "description": "Million Batch Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_OutputTokenCount_Global_Batch",
       "price": "7.5",
       "description": "Million Batch Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_InputTokenCount_LCtx_Global_Batch",
       "price": "1.5",
       "description": "Million Batch Input Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_OutputTokenCount_LCtx_Global_Batch",
       "price": "7.5",
       "description": "Million Batch Output Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_InputTokenCount_Global",
       "price": "3",
       "description": "Million Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_OutputTokenCount_Global",
       "price": "15",
       "description": "Million Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_InputTokenCount_LCtx_Global",
       "price": "3",
       "description": "Million Input Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_OutputTokenCount_LCtx_Global",
       "price": "15",
       "description": "Million Output Tokens Long Context Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_InputTokenCount_Batch",
       "price": "1.65",
       "description": "Million Batch Input Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "EU_OutputTokenCount_Batch",
       "price": "8.25",
       "description": "Million Batch Response Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "EU_InputTokenCount_LCtx_Batch",
       "price": "1.65",
       "description": "Million Batch Input Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "EU_OutputTokenCount_LCtx_Batch",
       "price": "8.25",
       "description": "Million Batch Output Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "EU_InputTokenCount",
       "price": "3.3",
       "description": "Million Input Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "EU_OutputTokenCount",
       "price": "16.5",
       "description": "Million Response Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "EU_InputTokenCount_LCtx",
       "price": "3.3",
       "description": "Million Input Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "EU_OutputTokenCount_LCtx",
       "price": "16.5",
       "description": "Million Output Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE1_InputTokenCount_Batch",
       "price": "1.65",
       "description": "Million Batch Input Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE1_OutputTokenCount_Batch",
       "price": "8.25",
       "description": "Million Batch Response Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE1_InputTokenCount_LCtx_Batch",
       "price": "1.65",
       "description": "Million Batch Input Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE1_OutputTokenCount_LCtx_Batch",
       "price": "8.25",
       "description": "Million Batch Output Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE1_InputTokenCount",
       "price": "3.3",
       "description": "Million Input Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE1_OutputTokenCount",
       "price": "16.5",
       "description": "Million Response Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE1_InputTokenCount_LCtx",
       "price": "3.3",
       "description": "Million Input Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE1_OutputTokenCount_LCtx",
       "price": "16.5",
       "description": "Million Output Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE2_InputTokenCount_Batch",
       "price": "1.65",
       "description": "Million Batch Input Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE2_OutputTokenCount_Batch",
       "price": "8.25",
       "description": "Million Batch Response Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE2_InputTokenCount_LCtx_Batch",
       "price": "1.65",
       "description": "Million Batch Input Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE2_OutputTokenCount_LCtx_Batch",
       "price": "8.25",
       "description": "Million Batch Output Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE2_InputTokenCount",
       "price": "3.3",
       "description": "Million Input Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE2_OutputTokenCount",
       "price": "16.5",
       "description": "Million Response Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE2_InputTokenCount_LCtx",
       "price": "3.3",
       "description": "Million Input Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE2_OutputTokenCount_LCtx",
       "price": "16.5",
       "description": "Million Output Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "UGE1_InputTokenCount_Batch",
       "price": "1.8",
       "description": "Million Batch Input Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "UGE1_OutputTokenCount_Batch",
       "price": "9",
       "description": "Million Batch Response Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "UGE1_InputTokenCount_LCtx_Batch",
       "price": "1.8",
       "description": "Million Batch Input Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "UGE1_OutputTokenCount_LCtx_Batch",
       "price": "9",
       "description": "Million Batch Output Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "UGE1_InputTokenCount",
       "price": "3.6",
       "description": "Million Input Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "UGE1_OutputTokenCount",
       "price": "18",
       "description": "Million Response Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "UGE1_InputTokenCount_LCtx",
       "price": "3.6",
       "description": "Million Input Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "UGE1_OutputTokenCount_LCtx",
       "price": "18",
       "description": "Million Output Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USW2_InputTokenCount_Batch",
       "price": "1.65",
       "description": "Million Batch Input Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USW2_OutputTokenCount_Batch",
       "price": "8.25",
       "description": "Million Batch Response Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USW2_InputTokenCount_LCtx_Batch",
       "price": "1.65",
       "description": "Million Batch Input Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USW2_OutputTokenCount_LCtx_Batch",
       "price": "8.25",
       "description": "Million Batch Output Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USW2_InputTokenCount",
       "price": "3.3",
       "description": "Million Input Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USW2_OutputTokenCount",
       "price": "16.5",
       "description": "Million Response Tokens Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USW2_InputTokenCount_LCtx",
       "price": "3.3",
       "description": "Million Input Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USW2_OutputTokenCount_LCtx",
       "price": "16.5",
       "description": "Million Output Tokens Long Context Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "APN2_Reserved_1Month_InputTPM_Geo",
       "price": "0.198",
       "description": "Per Hour per 1K Input TPM Reserved 1 Month Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE1_Reserved_1Month_OutputTPM_Global",
       "price": "0.9",
       "description": "Per Hour per 1K Output TPM Reserved 1 Month Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_Reserved_1Month_InputTPM_Global",
       "price": "0.18",
       "description": "Per Hour per 1K Input TPM Reserved 1 Month Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_Reserved_1Month_OutputTPM_Geo",
       "price": "0.99",
       "description": "Per Hour per 1K Output TPM Reserved 1 Month Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE1_Reserved_1Month_InputTPM_Global",
       "price": "0.18",
       "description": "Per Hour per 1K Input TPM Reserved 1 Month Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_Reserved_1Month_OutputTPM_Global",
       "price": "0.9",
       "description": "Per Hour per 1K Output TPM Reserved 1 Month Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_Reserved_1Month_InputTPM_Geo",
       "price": "0.198",
       "description": "Per Hour per 1K Input TPM Reserved 1 Month Regional CRIS",
       "unit": "Units"
      },
      {
       "dimension": "USE1_Reserved_1Month_OutputTPM_Geo",
       "price": "0.99",
       "description": "Per Hour per 1K Output TPM Reserved 1 Month Regional CRIS",
       "unit": "Units"
      }
     ]
    }
   }
  }
 ]
}
```

#### `t03-fx-haiku45` — `backend/tests/fixtures/pricing/offers_claude-haiku-4-5.json`

<!-- plan-block id=t03-fx-haiku45 path=backend/tests/fixtures/pricing/offers_claude-haiku-4-5.json sha256=e7139163dd9bc90ad38021647683343c0c506af2788de5e8fc5ef58db49f3845 -->
```json
{
 "modelId": "anthropic.claude-haiku-4-5-20251001-v1:0",
 "offers": [
  {
   "offerId": "offer-fudwqbphlos64",
   "termDetails": {
    "usageBasedPricingTerm": {
     "rateCard": [
      {
       "dimension": "APN2_input_tokens_global_batch",
       "price": "0.5",
       "description": "Input Tokens - Batch, Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_global_batch",
       "price": "2.5",
       "description": "Output Tokens - Batch, Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_input_tokens_global_standard",
       "price": "1",
       "description": "Input Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_global_standard",
       "price": "5",
       "description": "Output Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_cache_read_tokens_global_standard",
       "price": "0.1",
       "description": "Cache Read Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_global_batch",
       "price": "0.5",
       "description": "Input Tokens - Batch, Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_global_batch",
       "price": "2.5",
       "description": "Output Tokens - Batch, Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_global_standard",
       "price": "1",
       "description": "Input Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_global_standard",
       "price": "5",
       "description": "Output Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_cache_read_tokens_global_standard",
       "price": "0.1",
       "description": "Cache Read Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_global_batch",
       "price": "0.5",
       "description": "Input Tokens - Batch, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_global_batch",
       "price": "2.5",
       "description": "Output Tokens - Batch, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_global_standard",
       "price": "1",
       "description": "Input Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_global_standard",
       "price": "5",
       "description": "Output Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_cache_read_tokens_global_standard",
       "price": "0.1",
       "description": "Cache Read Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_global_batch",
       "price": "0.5",
       "description": "Input Tokens - Batch, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_global_batch",
       "price": "2.5",
       "description": "Output Tokens - Batch, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_global_standard",
       "price": "1",
       "description": "Input Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_global_standard",
       "price": "5",
       "description": "Output Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_cache_read_tokens_global_standard",
       "price": "0.1",
       "description": "Cache Read Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_global_batch",
       "price": "0.5",
       "description": "Input Tokens - Batch, Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_global_batch",
       "price": "2.5",
       "description": "Output Tokens - Batch, Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_global_standard",
       "price": "1",
       "description": "Input Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_global_standard",
       "price": "5",
       "description": "Output Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_cache_read_tokens_global_standard",
       "price": "0.1",
       "description": "Cache Read Tokens - Standard, Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_input_tokens_batch",
       "price": "0.55",
       "description": "Input Tokens - Batch",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_batch",
       "price": "2.75",
       "description": "Output Tokens - Batch",
       "unit": "Units"
      },
      {
       "dimension": "APN2_input_tokens_standard",
       "price": "1.1",
       "description": "Input Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_standard",
       "price": "5.5",
       "description": "Output Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "APN2_cache_read_tokens_standard",
       "price": "0.11",
       "description": "Cache Read Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_batch",
       "price": "0.55",
       "description": "Input Tokens - Batch",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_batch",
       "price": "2.75",
       "description": "Output Tokens - Batch",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_standard",
       "price": "1.1",
       "description": "Input Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_standard",
       "price": "5.5",
       "description": "Output Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "EU_cache_read_tokens_standard",
       "price": "0.11",
       "description": "Cache Read Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_batch",
       "price": "0.55",
       "description": "Input Tokens - Batch",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_batch",
       "price": "2.75",
       "description": "Output Tokens - Batch",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_standard",
       "price": "1.1",
       "description": "Input Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_standard",
       "price": "5.5",
       "description": "Output Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USE1_cache_read_tokens_standard",
       "price": "0.11",
       "description": "Cache Read Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_batch",
       "price": "0.55",
       "description": "Input Tokens - Batch",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_batch",
       "price": "2.75",
       "description": "Output Tokens - Batch",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_standard",
       "price": "1.1",
       "description": "Input Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_standard",
       "price": "5.5",
       "description": "Output Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USE2_cache_read_tokens_standard",
       "price": "0.11",
       "description": "Cache Read Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_batch",
       "price": "0.55",
       "description": "Input Tokens - Batch",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_batch",
       "price": "2.75",
       "description": "Output Tokens - Batch",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_standard",
       "price": "1.1",
       "description": "Input Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_standard",
       "price": "5.5",
       "description": "Output Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "USW2_cache_read_tokens_standard",
       "price": "0.11",
       "description": "Cache Read Tokens - Standard",
       "unit": "Units"
      },
      {
       "dimension": "APN2_InputTokenCount_Global_Batch",
       "price": "0.5",
       "description": "Million Batch Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_OutputTokenCount_Global_Batch",
       "price": "2.5",
       "description": "Million Batch Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_InputTokenCount_Global",
       "price": "1",
       "description": "Million Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_OutputTokenCount_Global",
       "price": "5",
       "description": "Million Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_InputTokenCount_Global_Batch",
       "price": "0.5",
       "description": "Million Batch Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_OutputTokenCount_Global_Batch",
       "price": "2.5",
       "description": "Million Batch Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_InputTokenCount_Global",
       "price": "1",
       "description": "Million Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "EU_OutputTokenCount_Global",
       "price": "5",
       "description": "Million Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_InputTokenCount_Global_Batch",
       "price": "0.5",
       "description": "Million Batch Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_OutputTokenCount_Global_Batch",
       "price": "2.5",
       "description": "Million Batch Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_InputTokenCount_Global",
       "price": "1",
       "description": "Million Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_OutputTokenCount_Global",
       "price": "5",
       "description": "Million Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_InputTokenCount_Global_Batch",
       "price": "0.5",
       "description": "Million Batch Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_OutputTokenCount_Global_Batch",
       "price": "2.5",
       "description": "Million Batch Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_InputTokenCount_Global",
       "price": "1",
       "description": "Million Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USE2_OutputTokenCount_Global",
       "price": "5",
       "description": "Million Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_InputTokenCount_Global_Batch",
       "price": "0.5",
       "description": "Million Batch Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_OutputTokenCount_Global_Batch",
       "price": "2.5",
       "description": "Million Batch Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_InputTokenCount_Global",
       "price": "1",
       "description": "Million Input Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "USW2_OutputTokenCount_Global",
       "price": "5",
       "description": "Million Response Tokens Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_InputTokenCount_Batch",
       "price": "0.55",
       "description": "Input Token Count (Batch)",
       "unit": "Units"
      },
      {
       "dimension": "APN2_OutputTokenCount_Batch",
       "price": "2.75",
       "description": "Output Token Count (Batch)",
       "unit": "Units"
      },
      {
       "dimension": "APN2_InputTokenCount",
       "price": "1.1",
       "description": "Input Token Count",
       "unit": "Units"
      },
      {
       "dimension": "APN2_OutputTokenCount",
       "price": "5.5",
       "description": "Output Token Count",
       "unit": "Units"
      },
      {
       "dimension": "EU_InputTokenCount_Batch",
       "price": "0.55",
       "description": "Million Batch Input Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "EU_OutputTokenCount_Batch",
       "price": "2.75",
       "description": "Million Batch Response Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "EU_InputTokenCount",
       "price": "1.1",
       "description": "Million Input Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "EU_OutputTokenCount",
       "price": "5.5",
       "description": "Million Response Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "USE1_InputTokenCount_Batch",
       "price": "0.55",
       "description": "Million Batch Input Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "USE1_OutputTokenCount_Batch",
       "price": "2.75",
       "description": "Million Batch Response Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "USE1_InputTokenCount",
       "price": "1.1",
       "description": "Million Input Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "USE1_OutputTokenCount",
       "price": "5.5",
       "description": "Million Response Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "USE2_InputTokenCount_Batch",
       "price": "0.55",
       "description": "Million Batch Input Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "USE2_OutputTokenCount_Batch",
       "price": "2.75",
       "description": "Million Batch Response Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "USE2_InputTokenCount",
       "price": "1.1",
       "description": "Million Input Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "USE2_OutputTokenCount",
       "price": "5.5",
       "description": "Million Response Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "USW2_InputTokenCount_Batch",
       "price": "0.55",
       "description": "Million Batch Input Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "USW2_OutputTokenCount_Batch",
       "price": "2.75",
       "description": "Million Batch Response Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "USW2_InputTokenCount",
       "price": "1.1",
       "description": "Million Input Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "USW2_OutputTokenCount",
       "price": "5.5",
       "description": "Million Response Tokens Regional",
       "unit": "Units"
      },
      {
       "dimension": "APN2_Reserved_1Month_OutputTPM_Geo",
       "price": "0.33",
       "description": "Per Hour per 1K Output TPM Reserved 1 Month Regional",
       "unit": "Units"
      },
      {
       "dimension": "APN2_Reserved_1Month_InputTPM_Global",
       "price": "0.06",
       "description": "Per Hour per 1K Input TPM Reserved 1 Month Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_Reserved_1Month_InputTPM_Geo",
       "price": "0.066",
       "description": "Per Hour per 1K Input TPM Reserved 1 Month Regional",
       "unit": "Units"
      },
      {
       "dimension": "APN2_Reserved_1Month_InputTPM_Geo",
       "price": "0.066",
       "description": "Per Hour per 1K Input TPM Reserved 1 Month Regional",
       "unit": "Units"
      },
      {
       "dimension": "USE1_Reserved_1Month_OutputTPM_Geo",
       "price": "0.33",
       "description": "Per Hour per 1K Output TPM Reserved 1 Month Regional",
       "unit": "Units"
      },
      {
       "dimension": "USE1_Reserved_1Month_InputTPM_Global",
       "price": "0.06",
       "description": "Per Hour per 1K Input TPM Reserved 1 Month Global",
       "unit": "Units"
      },
      {
       "dimension": "USE1_Reserved_1Month_OutputTPM_Global",
       "price": "0.3",
       "description": "Per Hour per 1K Output TPM Reserved 1 Month Global",
       "unit": "Units"
      },
      {
       "dimension": "APN2_Reserved_1Month_OutputTPM_Global",
       "price": "0.3",
       "description": "Per Hour per 1K Output TPM Reserved 1 Month Global",
       "unit": "Units"
      }
     ]
    }
   }
  }
 ]
}
```

#### `t03-fx-astra` — `backend/tests/fixtures/pricing/offers_gpt-6-astra.json`

<!-- plan-block id=t03-fx-astra path=backend/tests/fixtures/pricing/offers_gpt-6-astra.json sha256=477724cdb448d9b1338fca59eeff4036611b51a3293b30089e8d2233092b0351 -->
```json
{
 "modelId": "openai.gpt-6-astra",
 "offers": [
  {
   "offerId": "offer-7epta7rbw5aws",
   "termDetails": {
    "usageBasedPricingTerm": {
     "rateCard": [
      {
       "dimension": "input_tokens_standard",
       "price": "11",
       "description": "input_tokens_standard",
       "unit": "Units"
      },
      {
       "dimension": "input_tokens_global_standard",
       "price": "10",
       "description": "input_tokens_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "input_tokens_global_priority",
       "price": "20",
       "description": "input_tokens_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "input_tokens_global_flex",
       "price": "5",
       "description": "input_tokens_global_flex",
       "unit": "Units"
      },
      {
       "dimension": "input_tokens_priority",
       "price": "22",
       "description": "input_tokens_priority",
       "unit": "Units"
      },
      {
       "dimension": "input_tokens_flex",
       "price": "5.5",
       "description": "input_tokens_flex",
       "unit": "Units"
      },
      {
       "dimension": "output_tokens_global_standard",
       "price": "50",
       "description": "output_tokens_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "output_tokens_global_priority",
       "price": "100",
       "description": "output_tokens_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "output_tokens_global_flex",
       "price": "25",
       "description": "output_tokens_global_flex",
       "unit": "Units"
      },
      {
       "dimension": "output_tokens_standard",
       "price": "55",
       "description": "output_tokens_standard",
       "unit": "Units"
      },
      {
       "dimension": "output_tokens_priority",
       "price": "110",
       "description": "output_tokens_priority",
       "unit": "Units"
      },
      {
       "dimension": "output_tokens_flex",
       "price": "27.5",
       "description": "output_tokens_flex",
       "unit": "Units"
      },
      {
       "dimension": "cache_read_tokens_global_standard",
       "price": "1",
       "description": "cache_read_tokens_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "cache_read_tokens_standard",
       "price": "1.1",
       "description": "cache_read_tokens_standard",
       "unit": "Units"
      },
      {
       "dimension": "input_tokens_long_ctx_global_standard",
       "price": "20",
       "description": "input_tokens_long_ctx_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "output_tokens_long_ctx_global_standard",
       "price": "75",
       "description": "output_tokens_long_ctx_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "input_tokens_long_ctx_standard",
       "price": "22",
       "description": "input_tokens_long_ctx_standard",
       "unit": "Units"
      },
      {
       "dimension": "output_tokens_long_ctx_standard",
       "price": "82.5",
       "description": "output_tokens_long_ctx_standard",
       "unit": "Units"
      }
     ]
    }
   }
  }
 ]
}
```

#### `t03-fx-gpt54` — `backend/tests/fixtures/pricing/offers_gpt-5.4.json`

<!-- plan-block id=t03-fx-gpt54 path=backend/tests/fixtures/pricing/offers_gpt-5.4.json sha256=ae40dad16c20146839a8be55e38125fddeb8365bffab7f3b4f2765c3533b40ac -->
```json
{
 "modelId": "openai.gpt-5.4",
 "offers": [
  {
   "offerId": "offer-5l5a5izq5fbec",
   "termDetails": {
    "usageBasedPricingTerm": {
     "rateCard": [
      {
       "dimension": "USE1_input_tokens_long_ctx_standard",
       "price": "5.5",
       "description": "input_tokens_long_ctx_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_long_ctx_standard",
       "price": "5.5",
       "description": "input_tokens_long_ctx_standard",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_long_ctx_standard",
       "price": "5.5",
       "description": "input_tokens_long_ctx_standard",
       "unit": "Units"
      },
      {
       "dimension": "APN2_input_tokens_long_ctx_standard",
       "price": "5.5",
       "description": "input_tokens_long_ctx_standard",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_long_ctx_standard",
       "price": "5.5",
       "description": "input_tokens_long_ctx_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_long_ctx_priority",
       "price": "0",
       "description": "input_tokens_long_ctx_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_long_ctx_priority",
       "price": "0",
       "description": "input_tokens_long_ctx_priority",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_long_ctx_priority",
       "price": "0",
       "description": "input_tokens_long_ctx_priority",
       "unit": "Units"
      },
      {
       "dimension": "APN2_input_tokens_long_ctx_priority",
       "price": "0",
       "description": "input_tokens_long_ctx_priority",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_long_ctx_priority",
       "price": "0",
       "description": "input_tokens_long_ctx_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_long_ctx_standard",
       "price": "24.75",
       "description": "output_tokens_long_ctx_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_long_ctx_standard",
       "price": "24.75",
       "description": "output_tokens_long_ctx_standard",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_long_ctx_standard",
       "price": "24.75",
       "description": "output_tokens_long_ctx_standard",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_long_ctx_standard",
       "price": "24.75",
       "description": "output_tokens_long_ctx_standard",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_long_ctx_standard",
       "price": "24.75",
       "description": "output_tokens_long_ctx_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_long_ctx_priority",
       "price": "0",
       "description": "output_tokens_long_ctx_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_long_ctx_priority",
       "price": "0",
       "description": "output_tokens_long_ctx_priority",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_long_ctx_priority",
       "price": "0",
       "description": "output_tokens_long_ctx_priority",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_long_ctx_priority",
       "price": "0",
       "description": "output_tokens_long_ctx_priority",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_long_ctx_priority",
       "price": "0",
       "description": "output_tokens_long_ctx_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_standard",
       "price": "2.75",
       "description": "input_tokens_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_standard",
       "price": "2.75",
       "description": "input_tokens_standard",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_standard",
       "price": "2.75",
       "description": "input_tokens_standard",
       "unit": "Units"
      },
      {
       "dimension": "APN2_input_tokens_standard",
       "price": "2.75",
       "description": "input_tokens_standard",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_standard",
       "price": "2.75",
       "description": "input_tokens_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_priority",
       "price": "5.5",
       "description": "input_tokens_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_priority",
       "price": "5.5",
       "description": "input_tokens_priority",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_priority",
       "price": "5.5",
       "description": "input_tokens_priority",
       "unit": "Units"
      },
      {
       "dimension": "APN2_input_tokens_priority",
       "price": "5.5",
       "description": "input_tokens_priority",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_priority",
       "price": "5.5",
       "description": "input_tokens_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_flex",
       "price": "1.375",
       "description": "input_tokens_flex",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_flex",
       "price": "1.375",
       "description": "input_tokens_flex",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_flex",
       "price": "1.375",
       "description": "input_tokens_flex",
       "unit": "Units"
      },
      {
       "dimension": "APN2_input_tokens_flex",
       "price": "1.375",
       "description": "input_tokens_flex",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_flex",
       "price": "1.375",
       "description": "input_tokens_flex",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_batch",
       "price": "1.375",
       "description": "input_tokens_batch",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_batch",
       "price": "1.375",
       "description": "input_tokens_batch",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_batch",
       "price": "1.375",
       "description": "input_tokens_batch",
       "unit": "Units"
      },
      {
       "dimension": "APN2_input_tokens_batch",
       "price": "1.375",
       "description": "input_tokens_batch",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_batch",
       "price": "1.375",
       "description": "input_tokens_batch",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_standard",
       "price": "16.5",
       "description": "output_tokens_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_standard",
       "price": "16.5",
       "description": "output_tokens_standard",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_standard",
       "price": "16.5",
       "description": "output_tokens_standard",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_standard",
       "price": "16.5",
       "description": "output_tokens_standard",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_standard",
       "price": "16.5",
       "description": "output_tokens_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_priority",
       "price": "33",
       "description": "output_tokens_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_priority",
       "price": "33",
       "description": "output_tokens_priority",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_priority",
       "price": "33",
       "description": "output_tokens_priority",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_priority",
       "price": "33",
       "description": "output_tokens_priority",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_priority",
       "price": "33",
       "description": "output_tokens_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_flex",
       "price": "8.25",
       "description": "output_tokens_flex",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_flex",
       "price": "8.25",
       "description": "output_tokens_flex",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_flex",
       "price": "8.25",
       "description": "output_tokens_flex",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_flex",
       "price": "8.25",
       "description": "output_tokens_flex",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_flex",
       "price": "8.25",
       "description": "output_tokens_flex",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_batch",
       "price": "8.25",
       "description": "output_tokens_batch",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_batch",
       "price": "8.25",
       "description": "output_tokens_batch",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_batch",
       "price": "8.25",
       "description": "output_tokens_batch",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_batch",
       "price": "8.25",
       "description": "output_tokens_batch",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_batch",
       "price": "8.25",
       "description": "output_tokens_batch",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_long_ctx_global_standard",
       "price": "5",
       "description": "input_tokens_long_ctx_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_long_ctx_global_priority",
       "price": "0",
       "description": "USE1_input_tokens_long_ctx_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_long_ctx_global_standard",
       "price": "22.5",
       "description": "USE1_output_tokens_long_ctx_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_long_ctx_global_priority",
       "price": "0",
       "description": "USE1_output_tokens_long_ctx_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_global_standard",
       "price": "2.5",
       "description": "USE1_input_tokens_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_global_priority",
       "price": "5",
       "description": "USE1_input_tokens_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_global_flex",
       "price": "1.25",
       "description": "USE1_input_tokens_global_flex",
       "unit": "Units"
      },
      {
       "dimension": "USE1_input_tokens_global_batch",
       "price": "1.25",
       "description": "USE1_input_tokens_global_batch",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_global_standard",
       "price": "15",
       "description": "USE1_output_tokens_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_global_priority",
       "price": "30",
       "description": "USE1_output_tokens_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_global_flex",
       "price": "7.5",
       "description": "USE1_output_tokens_global_flex",
       "unit": "Units"
      },
      {
       "dimension": "USE1_output_tokens_global_batch",
       "price": "7.5",
       "description": "USE1_output_tokens_global_batch",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_long_ctx_global_standard",
       "price": "5",
       "description": "USE2_input_tokens_long_ctx_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_long_ctx_global_priority",
       "price": "0",
       "description": "USE2_input_tokens_long_ctx_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_long_ctx_global_standard",
       "price": "22.5",
       "description": "USE2_output_tokens_long_ctx_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_long_ctx_global_priority",
       "price": "0",
       "description": "USE2_output_tokens_long_ctx_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_global_standard",
       "price": "2.5",
       "description": "USE2_input_tokens_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_global_priority",
       "price": "5",
       "description": "USE2_input_tokens_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_global_flex",
       "price": "1.25",
       "description": "USE2_input_tokens_global_flex",
       "unit": "Units"
      },
      {
       "dimension": "USE2_input_tokens_global_batch",
       "price": "1.25",
       "description": "USE2_input_tokens_global_batch",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_global_standard",
       "price": "15",
       "description": "USE2_output_tokens_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_global_priority",
       "price": "30",
       "description": "USE2_output_tokens_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_global_flex",
       "price": "7.5",
       "description": "USE2_output_tokens_global_flex",
       "unit": "Units"
      },
      {
       "dimension": "USE2_output_tokens_global_batch",
       "price": "7.5",
       "description": "USE2_output_tokens_global_batch",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_long_ctx_global_standard",
       "price": "5",
       "description": "USW2_input_tokens_long_ctx_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_long_ctx_global_priority",
       "price": "0",
       "description": "USW2_input_tokens_long_ctx_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_long_ctx_global_standard",
       "price": "22.5",
       "description": "USW2_output_tokens_long_ctx_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_long_ctx_global_priority",
       "price": "0",
       "description": "USW2_output_tokens_long_ctx_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_global_standard",
       "price": "2.5",
       "description": "USW2_input_tokens_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_global_priority",
       "price": "5",
       "description": "USW2_input_tokens_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_global_flex",
       "price": "1.25",
       "description": "USW2_input_tokens_global_flex",
       "unit": "Units"
      },
      {
       "dimension": "USW2_input_tokens_global_batch",
       "price": "1.25",
       "description": "USW2_input_tokens_global_batch",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_global_standard",
       "price": "15",
       "description": "USW2_output_tokens_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_global_priority",
       "price": "30",
       "description": "USW2_output_tokens_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_global_flex",
       "price": "7.5",
       "description": "USW2_output_tokens_global_flex",
       "unit": "Units"
      },
      {
       "dimension": "USW2_output_tokens_global_batch",
       "price": "7.5",
       "description": "USW2_output_tokens_global_batch",
       "unit": "Units"
      },
      {
       "dimension": "APN2_input_tokens_long_ctx_global_standard",
       "price": "5",
       "description": "APN2_input_tokens_long_ctx_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "APN2_input_tokens_long_ctx_global_priority",
       "price": "0",
       "description": "APN2_input_tokens_long_ctx_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_long_ctx_global_standard",
       "price": "22.5",
       "description": "APN2_output_tokens_long_ctx_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_long_ctx_global_priority",
       "price": "0",
       "description": "APN2_output_tokens_long_ctx_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "APN2_input_tokens_global_standard",
       "price": "2.5",
       "description": "APN2_input_tokens_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "APN2_input_tokens_global_priority",
       "price": "5",
       "description": "APN2_input_tokens_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "APN2_input_tokens_global_flex",
       "price": "1.25",
       "description": "APN2_input_tokens_global_flex",
       "unit": "Units"
      },
      {
       "dimension": "APN2_input_tokens_global_batch",
       "price": "1.25",
       "description": "APN2_input_tokens_global_batch",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_global_standard",
       "price": "15",
       "description": "APN2_output_tokens_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_global_priority",
       "price": "30",
       "description": "APN2_output_tokens_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_global_flex",
       "price": "7.5",
       "description": "APN2_output_tokens_global_flex",
       "unit": "Units"
      },
      {
       "dimension": "APN2_output_tokens_global_batch",
       "price": "7.5",
       "description": "APN2_output_tokens_global_batch",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_long_ctx_global_standard",
       "price": "5",
       "description": "EU_input_tokens_long_ctx_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_long_ctx_global_priority",
       "price": "0",
       "description": "EU_input_tokens_long_ctx_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_long_ctx_global_standard",
       "price": "22.5",
       "description": "EU_output_tokens_long_ctx_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_long_ctx_global_priority",
       "price": "0",
       "description": "EU_output_tokens_long_ctx_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_global_standard",
       "price": "2.5",
       "description": "EU_input_tokens_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_global_priority",
       "price": "5",
       "description": "EU_input_tokens_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_global_flex",
       "price": "1.25",
       "description": "EU_input_tokens_global_flex",
       "unit": "Units"
      },
      {
       "dimension": "EU_input_tokens_global_batch",
       "price": "1.25",
       "description": "EU_input_tokens_global_batch",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_global_standard",
       "price": "15",
       "description": "EU_output_tokens_global_standard",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_global_priority",
       "price": "30",
       "description": "EU_output_tokens_global_priority",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_global_flex",
       "price": "7.5",
       "description": "EU_output_tokens_global_flex",
       "unit": "Units"
      },
      {
       "dimension": "EU_output_tokens_global_batch",
       "price": "7.5",
       "description": "EU_output_tokens_global_batch",
       "unit": "Units"
      },
      {
       "dimension": "USE1_cache_read_tokens_standard",
       "price": "0.275",
       "description": "cache_read_tokens_standard",
       "unit": "Units"
      },
      {
       "dimension": "USE2_cache_read_tokens_standard",
       "price": "0.275",
       "description": "cache_read_tokens_standard",
       "unit": "Units"
      },
      {
       "dimension": "USW2_cache_read_tokens_standard",
       "price": "0.275",
       "description": "cache_read_tokens_standard",
       "unit": "Units"
      }
     ]
    }
   }
  }
 ]
}
```

#### `t03-fx-nova` — `backend/tests/fixtures/pricing/pricelist_nova-2-lite.json`

<!-- plan-block id=t03-fx-nova path=backend/tests/fixtures/pricing/pricelist_nova-2-lite.json sha256=56ff8d4b0e00c88c8a46a5fe57117f3f0043aaa46b0b93901263676f7c9d21ab -->
```json
{
 "FormatVersion": "aws_v1",
 "PriceList": [
  "{\"product\":{\"productFamily\":\"Amazon Bedrock\",\"attributes\":{\"regionCode\":\"us-east-1\",\"inferenceType\":\"Prompt cache read input tokens\",\"servicecode\":\"AmazonBedrock\",\"feature\":\"On-demand Inference\",\"usagetype\":\"USE1-Nova2.0Lite-cache-read-input-token-count\",\"locationType\":\"AWS Region\",\"location\":\"US East (N. Virginia)\",\"model\":\"Nova 2.0 Lite\",\"servicename\":\"Amazon Bedrock\",\"operation\":\"\"},\"sku\":\"NZS2WHKW9KB4K2QH\"},\"serviceCode\":\"AmazonBedrock\",\"terms\":{\"OnDemand\":{\"NZS2WHKW9KB4K2QH.JRTCKXETXF\":{\"priceDimensions\":{\"NZS2WHKW9KB4K2QH.JRTCKXETXF.6YS6EN2CT7\":{\"unit\":\"1K tokens\",\"endRange\":\"Inf\",\"description\":\"$0.0000825 per 1K tokens for USE1-Nova2.0Lite-cache-read-input-token-count in US East (N. Virginia)\",\"appliesTo\":[],\"rateCode\":\"NZS2WHKW9KB4K2QH.JRTCKXETXF.6YS6EN2CT7\",\"beginRange\":\"0\",\"pricePerUnit\":{\"USD\":\"0.0000825000\"}}},\"sku\":\"NZS2WHKW9KB4K2QH\",\"effectiveDate\":\"2026-09-01T00:00:00Z\",\"offerTermCode\":\"JRTCKXETXF\",\"termAttributes\":{}}}},\"version\":\"20260926004940\",\"publicationDate\":\"2026-09-26T00:49:40Z\"}",
  "{\"product\":{\"productFamily\":\"Amazon Bedrock\",\"attributes\":{\"regionCode\":\"us-east-1\",\"inferenceType\":\"Input tokens\",\"servicecode\":\"AmazonBedrock\",\"feature\":\"On-demand Inference\",\"usagetype\":\"USE1-Nova2.0Lite-input-tokens\",\"locationType\":\"AWS Region\",\"location\":\"US East (N. Virginia)\",\"model\":\"Nova 2.0 Lite\",\"servicename\":\"Amazon Bedrock\",\"operation\":\"\"},\"sku\":\"FY8T82UUN7VZR55K\"},\"serviceCode\":\"AmazonBedrock\",\"terms\":{\"OnDemand\":{\"FY8T82UUN7VZR55K.JRTCKXETXF\":{\"priceDimensions\":{\"FY8T82UUN7VZR55K.JRTCKXETXF.6YS6EN2CT7\":{\"unit\":\"1K tokens\",\"endRange\":\"Inf\",\"description\":\"$0.00033 per 1K tokens for USE1-Nova2.0Lite-input-tokens in US East (N. Virginia)\",\"appliesTo\":[],\"rateCode\":\"FY8T82UUN7VZR55K.JRTCKXETXF.6YS6EN2CT7\",\"beginRange\":\"0\",\"pricePerUnit\":{\"USD\":\"0.0003300000\"}}},\"sku\":\"FY8T82UUN7VZR55K\",\"effectiveDate\":\"2026-09-01T00:00:00Z\",\"offerTermCode\":\"JRTCKXETXF\",\"termAttributes\":{}}}},\"version\":\"20260926004940\",\"publicationDate\":\"2026-09-26T00:49:40Z\"}",
  "{\"product\":{\"productFamily\":\"Amazon Bedrock\",\"attributes\":{\"regionCode\":\"us-east-1\",\"inferenceType\":\"Input tokens flex\",\"servicecode\":\"AmazonBedrock\",\"feature\":\"On-demand Inference\",\"usagetype\":\"USE1-Nova2.0Lite-input-tokens-flex\",\"locationType\":\"AWS Region\",\"location\":\"US East (N. Virginia)\",\"model\":\"Nova 2.0 Lite\",\"servicename\":\"Amazon Bedrock\",\"operation\":\"\"},\"sku\":\"K3X8GZAXPXQXSM37\"},\"serviceCode\":\"AmazonBedrock\",\"terms\":{\"OnDemand\":{\"K3X8GZAXPXQXSM37.JRTCKXETXF\":{\"priceDimensions\":{\"K3X8GZAXPXQXSM37.JRTCKXETXF.6YS6EN2CT7\":{\"unit\":\"1K tokens\",\"endRange\":\"Inf\",\"description\":\"$0.000165 per 1K tokens for USE1-Nova2.0Lite-input-tokens-flex in US East (N. Virginia)\",\"appliesTo\":[],\"rateCode\":\"K3X8GZAXPXQXSM37.JRTCKXETXF.6YS6EN2CT7\",\"beginRange\":\"0\",\"pricePerUnit\":{\"USD\":\"0.0001650000\"}}},\"sku\":\"K3X8GZAXPXQXSM37\",\"effectiveDate\":\"2026-09-01T00:00:00Z\",\"offerTermCode\":\"JRTCKXETXF\",\"termAttributes\":{}}}},\"version\":\"20260926004940\",\"publicationDate\":\"2026-09-26T00:49:40Z\"}",
  "{\"product\":{\"productFamily\":\"Amazon Bedrock\",\"attributes\":{\"regionCode\":\"us-east-1\",\"inferenceType\":\"Input tokens priority\",\"servicecode\":\"AmazonBedrock\",\"feature\":\"On-demand Inference\",\"usagetype\":\"USE1-Nova2.0Lite-input-tokens-priority\",\"locationType\":\"AWS Region\",\"location\":\"US East (N. Virginia)\",\"model\":\"Nova 2.0 Lite\",\"servicename\":\"Amazon Bedrock\",\"operation\":\"\"},\"sku\":\"5ATX9W7RD5XA8J66\"},\"serviceCode\":\"AmazonBedrock\",\"terms\":{\"OnDemand\":{\"5ATX9W7RD5XA8J66.JRTCKXETXF\":{\"priceDimensions\":{\"5ATX9W7RD5XA8J66.JRTCKXETXF.6YS6EN2CT7\":{\"unit\":\"1K tokens\",\"endRange\":\"Inf\",\"description\":\"$0.0005775 per 1K tokens for USE1-Nova2.0Lite-input-tokens-priority in US East (N. Virginia)\",\"appliesTo\":[],\"rateCode\":\"5ATX9W7RD5XA8J66.JRTCKXETXF.6YS6EN2CT7\",\"beginRange\":\"0\",\"pricePerUnit\":{\"USD\":\"0.0005775000\"}}},\"sku\":\"5ATX9W7RD5XA8J66\",\"effectiveDate\":\"2026-09-01T00:00:00Z\",\"offerTermCode\":\"JRTCKXETXF\",\"termAttributes\":{}}}},\"version\":\"20260926004940\",\"publicationDate\":\"2026-09-26T00:49:40Z\"}",
  "{\"product\":{\"productFamily\":\"Amazon Bedrock\",\"attributes\":{\"regionCode\":\"us-east-1\",\"inferenceType\":\"Output tokens\",\"servicecode\":\"AmazonBedrock\",\"feature\":\"On-demand Inference\",\"usagetype\":\"USE1-Nova2.0Lite-output-tokens\",\"locationType\":\"AWS Region\",\"location\":\"US East (N. Virginia)\",\"model\":\"Nova 2.0 Lite\",\"servicename\":\"Amazon Bedrock\",\"operation\":\"\"},\"sku\":\"DY69Q8C3F88CHA2Q\"},\"serviceCode\":\"AmazonBedrock\",\"terms\":{\"OnDemand\":{\"DY69Q8C3F88CHA2Q.JRTCKXETXF\":{\"priceDimensions\":{\"DY69Q8C3F88CHA2Q.JRTCKXETXF.6YS6EN2CT7\":{\"unit\":\"1K tokens\",\"endRange\":\"Inf\",\"description\":\"$0.00275 per 1K tokens for USE1-Nova2.0Lite-output-tokens in US East (N. Virginia)\",\"appliesTo\":[],\"rateCode\":\"DY69Q8C3F88CHA2Q.JRTCKXETXF.6YS6EN2CT7\",\"beginRange\":\"0\",\"pricePerUnit\":{\"USD\":\"0.0027500000\"}}},\"sku\":\"DY69Q8C3F88CHA2Q\",\"effectiveDate\":\"2026-09-01T00:00:00Z\",\"offerTermCode\":\"JRTCKXETXF\",\"termAttributes\":{}}}},\"version\":\"20260926004940\",\"publicationDate\":\"2026-09-26T00:49:40Z\"}"
 ]
}
```

#### `t03-fx-anthropic` — `backend/tests/fixtures/pricing/anthropic_pricing.md`

<!-- plan-block id=t03-fx-anthropic path=backend/tests/fixtures/pricing/anthropic_pricing.md sha256=a6236399290a2577f09827550e1e0fe6e5ca5cca23d982aacf3fc36314f67507 -->
```markdown
---
title: Pricing
url: https://platform.claude.com/docs/en/about-claude/pricing
description: Learn about Anthropic's pricing structure for models and features
---

This page provides detailed pricing information for Anthropic's models and features. All prices are in USD.

For the most current pricing information, visit [claude.com/pricing](https://claude.com/pricing).

## Model pricing

The following table shows pricing for all Claude models:

| Model                                                                                                                                 | Base input tokens     | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens          |
| :------------------------------------------------------------------------------------------------------------------------------------ | :-------------------- | :-------------- | :-------------- | :----------------------- | :--------------------- |
| Claude Fable 5.1                                                                                                                      | $10 / MTok            | $12.50 / MTok   | $20 / MTok      | $0.25 / MTok<sup>1</sup> | $50 / MTok             |
| Claude Mythos 5.1 ([limited availability](https://anthropic.com/glasswing))                                                           | $10 / MTok            | $12.50 / MTok   | $20 / MTok      | $0.25 / MTok<sup>1</sup> | $50 / MTok             |
| Claude Fable 5                                                                                                                        | $10 / MTok            | $12.50 / MTok   | $20 / MTok      | $1 / MTok                | $50 / MTok             |
| Claude Mythos 5 ([limited availability](https://anthropic.com/glasswing))                                                             | $10 / MTok            | $12.50 / MTok   | $20 / MTok      | $1 / MTok                | $50 / MTok             |
| Claude Opus 5.5                                                                                                                       | $4 / MTok             | $5 / MTok       | $8 / MTok       | $0.20 / MTok<sup>2</sup> | $20 / MTok             |
| Claude Opus 5                                                                                                                         | $5 / MTok             | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok             | $25 / MTok             |
| Claude Opus 4.8                                                                                                                       | $5 / MTok             | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok             | $25 / MTok             |
| Claude Opus 4.7                                                                                                                       | $5 / MTok             | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok             | $25 / MTok             |
| Claude Opus 4.6                                                                                                                       | $5 / MTok             | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok             | $25 / MTok             |
| Claude Opus 4.5                                                                                                                       | $5 / MTok             | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok             | $25 / MTok             |
| Claude Opus 4.1 ([retired, except on Bedrock and Google Cloud](https://platform.claude.com/docs/en/about-claude/model-deprecations))  | $15 / MTok            | $18.75 / MTok   | $30 / MTok      | $1.50 / MTok             | $75 / MTok             |
| Claude Opus 4 ([retired, except on Google Cloud](https://platform.claude.com/docs/en/about-claude/model-deprecations))                | $15 / MTok            | $18.75 / MTok   | $30 / MTok      | $1.50 / MTok             | $75 / MTok             |
| Claude Sonnet 5                                                                                                                       | $2 / MTok<sup>3</sup> | $2.50 / MTok    | $4 / MTok       | $0.20 / MTok             | $10 / MTok<sup>3</sup> |
| Claude Sonnet 4.6                                                                                                                     | $3 / MTok             | $3.75 / MTok    | $6 / MTok       | $0.30 / MTok             | $15 / MTok             |
| Claude Sonnet 4.5                                                                                                                     | $3 / MTok             | $3.75 / MTok    | $6 / MTok       | $0.30 / MTok             | $15 / MTok             |
| Claude Sonnet 4 ([retired, except on Bedrock and Google Cloud](https://platform.claude.com/docs/en/about-claude/model-deprecations))  | $3 / MTok             | $3.75 / MTok    | $6 / MTok       | $0.30 / MTok             | $15 / MTok             |
| Claude Haiku 4.5                                                                                                                      | $1 / MTok             | $1.25 / MTok    | $2 / MTok       | $0.10 / MTok             | $5 / MTok              |
| Claude Haiku 3.5 ([retired, except on Bedrock and Google Cloud](https://platform.claude.com/docs/en/about-claude/model-deprecations)) | $0.80 / MTok          | $1 / MTok       | $1.60 / MTok    | $0.08 / MTok             | $4 / MTok              |

*<sup>1 Cache hits and refreshes on Claude Fable 5.1 and Claude Mythos 5.1 are priced at 0.025x the base input price.</sup>*

*<sup>2 Cache hits and refreshes on Claude Opus 5.5 are priced at 0.05x the base input price.</sup>*

*<sup>All other models use the standard 0.1x multiplier.</sup>*

*<sup>3 The $2/$10 per million input/output token pricing for Claude Sonnet 5, announced at launch as introductory pricing through August 31, 2026, is now the standard price. The previously scheduled increase to $3/$15 per million input/output tokens on September 1, 2026 will not occur.</sup>*

* **MTok:** Million tokens. $5 / MTok is $5 for every million tokens.
* **5m cache writes:** Writing a prompt prefix to the 5-minute prompt cache.
* **1h cache writes:** Writing a prompt prefix to the 1-hour prompt cache.
* **Cache hits and refreshes:** Reading a prompt prefix from the prompt cache, which also refreshes it.
* **Limited access:** Offered separately, by invitation only, as part of [Project Glasswing](https://anthropic.com/glasswing). For access, contact your Anthropic, AWS, or Google Cloud account team.
* **Retired:** May still be available on other cloud platforms. See [Model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) for more.

Claude 4.7 and later models and Claude Mythos Preview use a newer tokenizer that contributes to their improved performance on a wide range of tasks. This tokenizer produces approximately 30% more tokens for the same text. The exact increase depends on the content and workload shape. Claude Sonnet 4.6 and earlier models use the previous tokenizer.

### Batch processing

The Batch API allows asynchronous processing of large volumes of requests with a 50% discount on both input and output tokens.

| Model                                                                                                                                 | Batch input  | Batch output  |
| :------------------------------------------------------------------------------------------------------------------------------------ | :----------- | :------------ |
| Claude Fable 5.1                                                                                                                      | $5 / MTok    | $25 / MTok    |
| Claude Mythos 5.1 ([limited availability](https://anthropic.com/glasswing))                                                           | $5 / MTok    | $25 / MTok    |
| Claude Fable 5                                                                                                                        | $5 / MTok    | $25 / MTok    |
| Claude Mythos 5 ([limited availability](https://anthropic.com/glasswing))                                                             | $5 / MTok    | $25 / MTok    |
| Claude Opus 5.5                                                                                                                       | $2 / MTok    | $10 / MTok    |
| Claude Opus 5                                                                                                                         | $2.50 / MTok | $12.50 / MTok |
| Claude Opus 4.8                                                                                                                       | $2.50 / MTok | $12.50 / MTok |
| Claude Opus 4.7                                                                                                                       | $2.50 / MTok | $12.50 / MTok |
| Claude Opus 4.6                                                                                                                       | $2.50 / MTok | $12.50 / MTok |
| Claude Opus 4.5                                                                                                                       | $2.50 / MTok | $12.50 / MTok |
| Claude Opus 4.1 ([retired, except on Bedrock and Google Cloud](https://platform.claude.com/docs/en/about-claude/model-deprecations))  | $7.50 / MTok | $37.50 / MTok |
| Claude Opus 4 ([retired, except on Google Cloud](https://platform.claude.com/docs/en/about-claude/model-deprecations))                | $7.50 / MTok | $37.50 / MTok |
| Claude Sonnet 5                                                                                                                       | $1 / MTok    | $5 / MTok     |
| Claude Sonnet 4.6                                                                                                                     | $1.50 / MTok | $7.50 / MTok  |
| Claude Sonnet 4.5                                                                                                                     | $1.50 / MTok | $7.50 / MTok  |
| Claude Sonnet 4 ([retired, except on Bedrock and Google Cloud](https://platform.claude.com/docs/en/about-claude/model-deprecations))  | $1.50 / MTok | $7.50 / MTok  |
| Claude Haiku 4.5                                                                                                                      | $0.50 / MTok | $2.50 / MTok  |
| Claude Haiku 3.5 ([retired, except on Bedrock and Google Cloud](https://platform.claude.com/docs/en/about-claude/model-deprecations)) | $0.40 / MTok | $2 / MTok     |

* **MTok:** Million tokens. $5 / MTok is $5 for every million tokens.
* **Limited access:** Offered separately, by invitation only, as part of [Project Glasswing](https://anthropic.com/glasswing). For access, contact your Anthropic, AWS, or Google Cloud account team.
* **Retired:** May still be available on other cloud platforms. See [Model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) for more.

For more information about batch processing, see [Batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing).
```

#### `t03-test` — `backend/tests/test_pricing_parsers.py`

<!-- plan-block id=t03-test path=backend/tests/test_pricing_parsers.py sha256=53d9e5e1e5e8e3ae53139c5a2498b8a7f16e387cff746b0602cfc53447003331 -->
```python
"""Official price source parsers (v2.30.0, ADR-030) — offline, sanitized spike fixtures (tests/fixtures/pricing/)."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from pricing_parsers import (
    DIMENSION_RE, PriceParseError, UnitPrice, parse_anthropic_pricing_md, parse_pricelist,
    select_offer_price, single_public_offer,
)
from pricing_sources import ANTHROPIC_DOC_NAMES, NOVA_USAGETYPES

FIXTURES = Path(__file__).parent / "fixtures" / "pricing"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _card(name):
    return single_public_offer(_load(name))[1]


def P(i, o):
    return UnitPrice(input=Decimal(str(i)), output=Decimal(str(o)))


def E(dimension, price, unit="Units"):
    return {"dimension": dimension, "price": price, "description": dimension, "unit": unit}


def test_fixtures_are_sanitized():
    names = {f.name for f in FIXTURES.iterdir()}
    assert names >= {"offers_claude-opus-5-5.json", "offers_claude-sonnet-4-6.json", "offers_claude-haiku-4-5.json",
                     "offers_gpt-6-astra.json", "offers_gpt-5.4.json", "pricelist_nova-2-lite.json", "anthropic_pricing.md"}
    for f in FIXTURES.iterdir():
        text = f.read_text(encoding="utf-8")
        for forbidden in ("offerToken", "legalTerm", "X-Amz", "Security-Token", "awsmp-offer-legal"):
            assert forbidden not in text, f"{f.name} contains {forbidden}"


# ---------------------------------------------------------------- agreement offers


def test_single_public_offer_returns_offer_id_and_rate_card():
    offer_id, card = single_public_offer(_load("offers_claude-opus-5-5.json"))
    assert offer_id == "offer-7sp77cpl4rveu" and any(e["dimension"] == "USE1_input_tokens_standard" for e in card)


def _offer(offer_id, card):
    return {"offerId": offer_id, "termDetails": {"usageBasedPricingTerm": {"rateCard": card}}}


@pytest.mark.parametrize("response", [
    {"offers": []},
    {"offers": [_offer("offer-a", [E("input_tokens_standard", "2.2")]), _offer("offer-b", [E("input_tokens_standard", "3")])]},
    {"modelId": "openai.gpt-6-sol"},
    {"offers": [{"offerId": "offer-a", "termDetails": {}}]},
], ids=["zero-offers", "two-offers", "no-offers-key", "no-rate-card"])
def test_single_public_offer_rejects_anything_but_exactly_one_offer(response):
    with pytest.raises(PriceParseError):
        single_public_offer(response)


@pytest.mark.parametrize(("fixture", "channel", "expected"), [
    ("offers_claude-opus-5-5.json", "global", P(4, 20)),          # region-prefix scheme
    ("offers_claude-opus-5-5.json", "us", P("4.4", 22)),
    ("offers_claude-sonnet-4-6.json", "global", P(3, 15)),        # legacy TokenCount scheme
    ("offers_claude-sonnet-4-6.json", "us", P("3.3", "16.5")),
    ("offers_claude-haiku-4-5.json", "global", P(1, 5)),          # both schemes, same values
    ("offers_claude-haiku-4-5.json", "us", P("1.1", "5.5")),
    ("offers_gpt-6-astra.json", "us", P(11, 55)),                 # flat scheme; unit anchor = AWS model card
    ("offers_gpt-6-astra.json", "global", P(10, 50)),
    ("offers_gpt-6-astra.json", "inregion:us-west-2", P(11, 55)),
    ("offers_gpt-5.4.json", "inregion:us-east-1", P("2.75", "16.5")),
    ("offers_gpt-5.4.json", "inregion:us-east-2", P("2.75", "16.5")),
    ("offers_gpt-5.4.json", "inregion:us-west-2", P("2.75", "16.5")),
])
def test_select_offer_price_from_real_rate_cards(fixture, channel, expected):
    assert select_offer_price(_card(fixture), channel) == expected


@pytest.mark.parametrize("channel", ["cp", "inregion:eu-west-1", "inregion:", "bogus"])
def test_channels_without_an_offer_rule_get_none(channel):
    assert select_offer_price(_card("offers_gpt-6-astra.json"), channel) is None


@pytest.mark.parametrize("dimension", [
    "input_tokens_standard", "output_tokens_global_standard", "APN2_input_tokens_global_standard",
    "USE2_input_tokens_standard", "USW2_output_tokens_standard", "USE1_InputTokenCount", "APN2_OutputTokenCount_Global",
])
def test_dimension_allow_list_accepts(dimension):
    assert DIMENSION_RE.fullmatch(dimension)


@pytest.mark.parametrize("dimension", [
    "UGE1_input_tokens_standard", "UGW1_InputTokenCount", "EU_input_tokens_standard", "USE1_input_tokens_batch",
    "input_tokens_priority", "input_tokens_global_flex", "USE1_input_tokens_long_ctx_standard",
    "USE1_InputTokenCount_LCtx", "APN2_InputTokenCount_Global_Batch", "USE1_cache_read_tokens_standard",
    "APN2_Reserved_1Month_InputTPM_Global", "use1_input_tokens_standard",
])
def test_dimension_allow_list_rejects(dimension):
    assert DIMENSION_RE.fullmatch(dimension) is None


def test_govcloud_and_eu_entries_of_a_real_card_are_never_candidates():
    excluded = [e for e in _card("offers_claude-opus-5-5.json") if e["dimension"].startswith(("UGE1_", "EU_"))]
    assert {"UGE1_input_tokens_standard", "EU_input_tokens_standard"} <= {e["dimension"] for e in excluded}
    assert all(select_offer_price(excluded, ch) is None for ch in ("global", "us", "inregion:us-east-1"))


def test_zero_price_other_unit_and_conflicting_duplicates_are_dropped():
    zero = [E("USE1_input_tokens_standard", "0"), E("USE1_output_tokens_standard", "16.5"),
            E("input_tokens_standard", "2.75"), E("output_tokens_standard", "16.5")]
    assert select_offer_price(zero, "inregion:us-east-1") == P("2.75", "16.5")
    assert select_offer_price([E("input_tokens_standard", "11", "1K tokens"), E("output_tokens_standard", "55", "1K tokens")], "us") is None
    dup = [E("USE1_input_tokens_standard", "4.4"), E("USE1_input_tokens_standard", "5.5"), E("USE1_output_tokens_standard", "22"),
           E("input_tokens_standard", "4"), E("output_tokens_standard", "20")]
    assert select_offer_price(dup, "us") == P(4, 20)
    half = [E("USE1_input_tokens_standard", "6"), E("input_tokens_standard", "7"), E("output_tokens_standard", "70")]
    assert select_offer_price(half, "us") == P(7, 70)          # a candidate needs both input and output


def _drain(card, channel):
    seen, rc = [], list(card)
    while (price := select_offer_price(rc, channel)) is not None:
        seen.append(int(price.input))
        rc = [e for e in rc if Decimal(e["price"]) not in (price.input, price.output)]
    return seen


def test_selection_order_per_channel():
    card = [E(d, p) for d, p in [
        ("APN2_input_tokens_global_standard", "1"), ("APN2_output_tokens_global_standard", "10"),
        ("USE1_input_tokens_global_standard", "2"), ("USE1_output_tokens_global_standard", "20"),
        ("input_tokens_global_standard", "3"), ("output_tokens_global_standard", "30"),
        ("APN2_InputTokenCount_Global", "4"), ("APN2_OutputTokenCount_Global", "40"),
        ("USE1_InputTokenCount_Global", "5"), ("USE1_OutputTokenCount_Global", "50"),
        ("USE1_input_tokens_standard", "6"), ("USE1_output_tokens_standard", "60"),
        ("input_tokens_standard", "7"), ("output_tokens_standard", "70"),
        ("USE1_InputTokenCount", "8"), ("USE1_OutputTokenCount", "80"),
        ("USE2_input_tokens_standard", "9"), ("USE2_output_tokens_standard", "90"),
        ("USW2_input_tokens_standard", "11"), ("USW2_output_tokens_standard", "110"),
    ]]
    assert _drain(card, "global") == [1, 2, 3, 4, 5]
    assert _drain(card, "us") == [6, 7, 8]
    assert _drain(card, "inregion:us-east-1") == [6, 7]
    assert _drain(card, "inregion:us-east-2") == [9, 7]
    assert _drain(card, "inregion:us-west-2") == [11, 7]


# ---------------------------------------------------------------- AWS Price List


def test_nova_price_list_is_converted_from_per_1k_to_per_1m():
    items = _load("pricelist_nova-2-lite.json")["PriceList"]
    in_ut, out_ut = NOVA_USAGETYPES["nova-2-lite"]
    assert parse_pricelist(items, in_ut, out_ut) == P("0.33", "2.75")
    assert parse_pricelist([json.loads(s) for s in items], in_ut, out_ut) == P("0.33", "2.75")


def test_price_list_unit_mismatch_missing_or_duplicate_product_raises():
    items = _load("pricelist_nova-2-lite.json")["PriceList"]
    in_ut, out_ut = NOVA_USAGETYPES["nova-2-lite"]
    decoded = [json.loads(s) for s in items]
    for item in decoded:
        if item["product"]["attributes"]["usagetype"] == out_ut:
            for term in item["terms"]["OnDemand"].values():
                for dim in term["priceDimensions"].values():
                    dim["unit"] = "1M tokens"
    with pytest.raises(PriceParseError, match="unit"):
        parse_pricelist(decoded, in_ut, out_ut)
    for bad in ([s for s in items if out_ut + '"' not in s], items + items, ["not json"]):
        with pytest.raises(PriceParseError):
            parse_pricelist(bad, in_ut, out_ut)


# ---------------------------------------------------------------- Anthropic pricing markdown

CP_EXPECTED = {
    "Claude Fable 5.1": P(10, 50), "Claude Fable 5": P(10, 50), "Claude Opus 5.5": P(4, 20),
    "Claude Opus 5": P(5, 25), "Claude Opus 4.8": P(5, 25), "Claude Opus 4.7": P(5, 25),
    "Claude Sonnet 5": P(2, 10), "Claude Sonnet 4.6": P(3, 15), "Claude Haiku 4.5": P(1, 5),
}


def _doc():
    return parse_anthropic_pricing_md((FIXTURES / "anthropic_pricing.md").read_text(encoding="utf-8"))


def test_real_doc_gives_all_nine_claude_platform_on_aws_families():
    prices = _doc()
    assert sorted(ANTHROPIC_DOC_NAMES.values()) == sorted(CP_EXPECTED)
    assert {name: prices[name] for name in CP_EXPECTED} == CP_EXPECTED
    # Sonnet 5 value cells are "$2 / MTok<sup>3</sup>" / "$10 / MTok<sup>3</sup>"; the batch table later
    # in the fixture (Opus 5 $2.50 / $12.50) is never read
    assert prices["Claude Sonnet 5"] == P(2, 10) and prices["Claude Opus 5"] == P(5, 25)


def test_trailing_parentheses_with_markdown_links_are_removed_from_names():
    prices = _doc()
    assert prices["Claude Mythos 5.1"] == P(10, 50) and prices["Claude Mythos 5"] == P(10, 50)
    assert prices["Claude Opus 4.1"] == P(15, 75)   # "([retired, except on Bedrock and Google Cloud](https://…))"
    assert all("(" not in n and "[" not in n and "<" not in n for n in prices)


def _md(*rows, header="| Model | Base input tokens | Output tokens |"):
    sep = "| " + " | ".join("---" for _ in header.strip("|").split("|")) + " |"
    return "## Model pricing\n\n" + "\n".join((header, sep) + rows) + "\n"


def test_exact_names_keep_point_releases_apart():
    prices = parse_anthropic_pricing_md(_md(
        "| Claude Fable 5.1 | $12 / MTok | $60 / MTok |",
        "| Claude Mythos 5.1 ([limited availability](https://anthropic.com/glasswing)) | $99 / MTok | $99 / MTok |",
        "| Claude Fable 5 | $10 / MTok | $50 / MTok |",
        "| Claude Opus 5.5 | $4 / MTok | $20 / MTok |",
        "| Claude Opus 5 | $5 / MTok | $25 / MTok |",
    ))
    assert prices["Claude Opus 5"] == P(5, 25) and prices["Claude Opus 5.5"] == P(4, 20)
    assert prices["Claude Fable 5"] == P(10, 50) and prices["Claude Fable 5.1"] == P(12, 60)


def test_columns_by_header_name_bad_values_skipped_and_ambiguous_names_dropped():
    reordered = _md("| $25 / MTok | Claude Opus 5 | $6.25 / MTok | $5 / MTok |",
                    header="| Output tokens | Model | 5m cache writes | Base input tokens |")
    assert parse_anthropic_pricing_md(reordered) == {"Claude Opus 5": P(5, 25)}
    assert parse_anthropic_pricing_md(_md(
        "| Claude Opus 5 | $5 per MTok | $25 / MTok |",
        "| Claude Sonnet 5 | $2/MTok | $10 / MTok |",
        "| Claude Opus 4.8 | $5 / MTok | $25 / MTok |",
        "| Claude Opus 4.8 (legacy) | $15 / MTok | $75 / MTok |",
        "| Claude Haiku 4.5 | $1 / MTok | $5 / MTok |",
    )) == {"Claude Haiku 4.5": P(1, 5)}


@pytest.mark.parametrize("doc", [
    _md("| Claude Opus 5 | $5 / MTok | $25 / MTok |").replace("## Model pricing", "## Pricing"),
    _md("| Claude Opus 5 | $5 / MTok | $25 / MTok |", header="| Model | Input | Output |"),
    "## Model pricing\n\nNo table here.\n\n## Cloud platform pricing\n\n" + _md("| Claude Opus 5 | $5 / MTok | $25 / MTok |").split("\n\n", 1)[1],
    "",
], ids=["no-heading", "renamed-headers", "table-in-next-section", "empty"])
def test_structure_changes_raise(doc):
    with pytest.raises(PriceParseError):
        parse_anthropic_pricing_md(doc)
```

#### `t03-parsers` — `backend/pricing_parsers.py`

<!-- plan-block id=t03-parsers path=backend/pricing_parsers.py sha256=9da96a74c88aa89a8f28b3ffcedee3e1df2900e428296491d6ebddbe9dbbd99c -->
```python
"""Pure, fail-closed parsers for the official price sources (v2.30.0, ADR-030): Bedrock agreement offer rate
cards, AWS Price List items (Nova) and the Anthropic pricing markdown. Prices are Decimal USD per 1M tokens.
"""

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class PriceParseError(ValueError):
    """The source payload does not have the shape the parser accepts."""


@dataclass(frozen=True)
class UnitPrice:
    input: Decimal
    output: Decimal


# ---------------------------------------------------------------- agreement offers

# Full-match allow-list (spec). Region prefixes are an allow-list, so batch/flex/priority/long_ctx/
# _LCtx/cache/Reserved and GovCloud (UGE1_, UGW1_) or other prefixes (EU_, …) never become candidates.
DIMENSION_RE = re.compile(
    r"^(?:(?P<rc>APN2|USE1|USE2|USW2)_)?"
    r"(?:(?P<io>input|output)_tokens(?P<g>_global)?_standard"
    r"|(?P<IO>Input|Output)TokenCount(?P<G>_Global)?)$"
)

# Rate cards carry no scale; "Units" is read as USD per 1M tokens (pinned by the GPT-6 Astra fixture).
_OFFER_UNIT = "Units"
_REGION_CODES = {"us-east-1": "USE1", "us-east-2": "USE2", "us-west-2": "USW2"}

# (scheme, region code or "" for the flat scheme, global?) in the spec's selection order.
_GLOBAL_ORDER = (
    ("new", "APN2", True),
    ("new", "USE1", True),
    ("new", "", True),
    ("legacy", "APN2", True),
    ("legacy", "USE1", True),
)
_US_ORDER = (
    ("new", "USE1", False),
    ("new", "", False),
    ("legacy", "USE1", False),
)


def single_public_offer(response: dict) -> tuple[str, list[dict]]:
    """(offerId, rateCard) of the only PUBLIC offer; PriceParseError unless there is exactly one."""
    offers = response.get("offers") if isinstance(response, dict) else None
    if not isinstance(offers, list):
        raise PriceParseError("offers response has no 'offers' list")
    if len(offers) != 1:
        raise PriceParseError(f"expected exactly 1 public offer, got {len(offers)}")
    offer = offers[0]
    offer_id = offer.get("offerId") if isinstance(offer, dict) else None
    try:
        rate_card = offer["termDetails"]["usageBasedPricingTerm"]["rateCard"]
    except (KeyError, TypeError):
        raise PriceParseError("offer has no usageBasedPricingTerm.rateCard") from None
    if not isinstance(offer_id, str) or not offer_id or not isinstance(rate_card, list):
        raise PriceParseError("offer has no offerId or rateCard is not a list")
    return offer_id, rate_card


def _decimal(value) -> Decimal | None:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _candidates(rate_card: list[dict]) -> dict[tuple[str, str, bool], dict[str, Decimal]]:
    """Allow-listed, positive entries grouped by (scheme, region code, global?) -> {"input", "output"}.

    A key that appears twice with different values is ambiguous and dropped (fail-closed).
    """
    found: dict[tuple[str, str, bool], dict[str, Decimal]] = {}
    conflicted: set[tuple[tuple[str, str, bool], str]] = set()
    for entry in rate_card:
        if not isinstance(entry, dict) or entry.get("unit") != _OFFER_UNIT:
            continue
        m = DIMENSION_RE.fullmatch(str(entry.get("dimension", "")))
        if not m:
            continue
        price = _decimal(entry.get("price"))
        if price is None or price <= 0:
            continue
        if m.group("io"):
            key = ("new", m.group("rc") or "", bool(m.group("g")))
            side = m.group("io")
        else:
            key = ("legacy", m.group("rc") or "", bool(m.group("G")))
            side = m.group("IO").lower()
        slot = found.setdefault(key, {})
        if side in slot and slot[side] != price:
            conflicted.add((key, side))
        slot[side] = price
    for key, side in conflicted:
        found[key].pop(side, None)
    return found


def _order_for(channel: str) -> tuple[tuple[str, str, bool], ...]:
    if channel == "global":
        return _GLOBAL_ORDER
    if channel == "us":
        return _US_ORDER
    if channel.startswith("inregion:"):
        code = _REGION_CODES.get(channel.split(":", 1)[1])
        if code is None:
            return ()
        return (("new", code, False), ("new", "", False))
    return ()


def select_offer_price(rate_card: list[dict], channel: str) -> UnitPrice | None:
    """Standard input/output price for a channel ("global", "us", "inregion:<region>"), or None.

    The first candidate in the spec's per-channel order that has BOTH input and output wins.
    """
    found = _candidates(rate_card)
    for key in _order_for(channel):
        slot = found.get(key, {})
        if "input" in slot and "output" in slot:
            return UnitPrice(input=slot["input"], output=slot["output"])
    return None


# ---------------------------------------------------------------- AWS Price List

_PRICELIST_UNIT = "1K tokens"
_PER_MILLION_FROM_PER_THOUSAND = Decimal(1000)


def _pricelist_item(item) -> dict:
    if isinstance(item, str):
        try:
            item = json.loads(item)
        except ValueError:
            raise PriceParseError("price list item is not valid JSON") from None
    if not isinstance(item, dict):
        raise PriceParseError("price list item is not an object")
    return item


def _pricelist_usd_per_million(items: list[dict], usagetype: str) -> Decimal:
    matches = [
        it for it in items
        if ((it.get("product") or {}).get("attributes") or {}).get("usagetype") == usagetype
    ]
    if len(matches) != 1:
        raise PriceParseError(f"expected 1 product for usagetype {usagetype}, got {len(matches)}")
    dims = [
        dim
        for term in ((matches[0].get("terms") or {}).get("OnDemand") or {}).values()
        for dim in ((term or {}).get("priceDimensions") or {}).values()
    ]
    if len(dims) != 1:
        raise PriceParseError(f"expected 1 OnDemand price dimension for {usagetype}, got {len(dims)}")
    if dims[0].get("unit") != _PRICELIST_UNIT:
        raise PriceParseError(f"unexpected unit for {usagetype}: {dims[0].get('unit')!r}")
    usd = _decimal((dims[0].get("pricePerUnit") or {}).get("USD"))
    if usd is None or usd <= 0:
        raise PriceParseError(f"no positive USD price for {usagetype}")
    return usd * _PER_MILLION_FROM_PER_THOUSAND


def parse_pricelist(price_list: list, input_usagetype: str, output_usagetype: str) -> UnitPrice:
    """USD per 1M tokens from `pricing.get_products` items (JSON strings or dicts), "1K tokens" x 1000."""
    if not isinstance(price_list, list):
        raise PriceParseError("price list is not a list")
    items = [_pricelist_item(it) for it in price_list]
    return UnitPrice(
        input=_pricelist_usd_per_million(items, input_usagetype),
        output=_pricelist_usd_per_million(items, output_usagetype),
    )


# ---------------------------------------------------------------- Anthropic pricing markdown

_MODEL_PRICING_HEADING_RE = re.compile(r"^##\s+Model pricing\s*$")
_SUP_RE = re.compile(r"<sup>.*?</sup>", re.IGNORECASE | re.DOTALL)
# trailing parenthesis group, one nesting level — covers "([limited availability](https://…))"
_TRAILING_PAREN_RE = re.compile(r"\s*\((?:[^()]|\([^()]*\))*\)\s*$")
_PRICE_CELL_RE = re.compile(r"^\$(\d+(?:\.\d+)?) / MTok$")
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")
_COL_MODEL = "model"
_COL_INPUT = "base input tokens"
_COL_OUTPUT = "output tokens"


def _cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def _norm_header(cell: str) -> str:
    return " ".join(cell.split()).lower()


def _clean_model_name(cell: str) -> str:
    name = _SUP_RE.sub("", cell).strip()
    name = _TRAILING_PAREN_RE.sub("", name).strip()
    return " ".join(name.split())


def _price_cell(cell: str) -> Decimal | None:
    m = _PRICE_CELL_RE.fullmatch(_SUP_RE.sub("", cell).strip())
    return Decimal(m.group(1)) if m else None


def _model_pricing_table(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    start = next((i for i, ln in enumerate(lines) if _MODEL_PRICING_HEADING_RE.match(ln.strip())), None)
    if start is None:
        raise PriceParseError("'## Model pricing' heading not found")
    table: list[str] = []
    for ln in lines[start + 1:]:
        stripped = ln.strip()
        if stripped.startswith("#"):
            break  # next section before any table
        if stripped.startswith("|"):
            table.append(stripped)
        elif table:
            break  # first table ended
    if len(table) < 3:
        raise PriceParseError("no pricing table under '## Model pricing'")
    return table


def parse_anthropic_pricing_md(markdown: str) -> dict[str, UnitPrice]:
    """Cleaned doc model name -> standard price from the first table under '## Model pricing'.

    Columns are found by header name ("Model", "Base input tokens", "Output tokens"), `<sup>` is removed
    from name and value cells, and the trailing parenthesis group (incl. a markdown link) is removed from
    the name. Rows whose values are not exactly "$<n> / MTok" are skipped; a name that appears twice with
    different prices is dropped. Callers look names up by exact match only.
    """
    table = _model_pricing_table(markdown)
    header = [_norm_header(c) for c in _cells(table[0])]
    try:
        i_model, i_in, i_out = header.index(_COL_MODEL), header.index(_COL_INPUT), header.index(_COL_OUTPUT)
    except ValueError:
        raise PriceParseError(f"pricing table headers not recognised: {header}") from None
    prices: dict[str, UnitPrice] = {}
    ambiguous: set[str] = set()
    for line in table[1:]:
        cells = _cells(line)
        if all(_SEPARATOR_CELL_RE.match(c) for c in cells if c):
            continue
        if len(cells) != len(header):
            continue
        name = _clean_model_name(cells[i_model])
        p_in, p_out = _price_cell(cells[i_in]), _price_cell(cells[i_out])
        if not name or p_in is None or p_out is None:
            continue
        price = UnitPrice(input=p_in, output=p_out)
        if name in prices and prices[name] != price:
            ambiguous.add(name)
        prices[name] = price
    for name in ambiguous:
        prices.pop(name, None)
    if not prices:
        raise PriceParseError("pricing table has no parseable rows")
    return prices
```

### Task 4 blocks

#### `t04-test` — `backend/tests/test_pricing_sync.py`

<!-- plan-block id=t04-test path=backend/tests/test_pricing_sync.py sha256=9af0c76b066d83a583e2306f7824c029fb5f10abb34ddae8c28d12f046b66750 -->
```python
"""12-hour official price sync (v2.30.0, ADR-030) — fake Fetchers + in-memory SQLite, no network."""

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pricing_sync
from database import Base
from models import PriceHistory, PriceSyncRun
from pricing_parsers import UnitPrice, single_public_offer
from pricing_sources import ANTHROPIC_PRICING_URL, EPOCH, price_identity
from pricing_sync import CHANGE_THRESHOLD, SYNC_DEADLINE_S, SYNC_LOCK_KEY, Fetchers, classify_change, default_fetchers, run_sync

FIXTURES = Path(__file__).parent / "fixtures" / "pricing"
T0 = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)
T1, T2 = T0 + timedelta(hours=12), T0 + timedelta(hours=24)
OPUS_G, OPUS_US = "global.anthropic.claude-opus-5-5", "us.anthropic.claude-opus-5-5"
SOL_G, SOL_E1 = "openai:global:global.openai.gpt-5.6-sol", "openai:us-east-1:openai.gpt-5.6-sol"
NOVA = "us.amazon.nova-2-lite-v1:0"
CP_HAIKU = "anthropic:claude-haiku-4-5-20251001"  # CP ids carry the /v1/models date suffix
ALL = (OPUS_G, OPUS_US, SOL_G, SOL_E1, NOVA, CP_HAIKU)
SOL_OFFER_ID = "offer-gnqokrqqvdbgw"
BASELINE = {  # current official values = seed rows: (input, output, source_id)
    OPUS_G: (4.0, 20.0, "offer:offer-7sp77cpl4rveu"), OPUS_US: (4.4, 22.0, "offer:offer-7sp77cpl4rveu"),
    SOL_G: (4.0, 20.0, f"offer:{SOL_OFFER_ID}"), SOL_E1: (4.4, 22.0, f"offer:{SOL_OFFER_ID}"),
    NOVA: (0.33, 2.75, "pricelist:USE1-Nova2.0Lite-input-tokens"), CP_HAIKU: (1.0, 5.0, "anthropic-pricing"),
}


def P(i, o):
    return UnitPrice(input=Decimal(str(i)), output=Decimal(str(o)))


def _utc(dt):
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _active(*model_ids):
    active = {m: price_identity(m) for m in model_ids}
    assert all(active.values()), active
    return active


def _sol_offer(inp, out, g_inp, g_out, offers=1):
    card = [{"dimension": d, "price": p, "description": d, "unit": "Units"} for d, p in (
        ("input_tokens_standard", inp), ("output_tokens_standard", out), ("input_tokens_global_standard", g_inp),
        ("output_tokens_global_standard", g_out), ("input_tokens_priority", "8.8"))]
    return {"modelId": "openai.gpt-5.6-sol",
            "offers": [{"offerId": SOL_OFFER_ID, "termDetails": {"usageBasedPricingTerm": {"rateCard": card}}}] * offers}


def _fetchers(*, sol=("4.4", "22", "4", "20"), sol_offers=1, fail=(), on_call=None, calls=None, opus_extra=None):
    calls = [] if calls is None else calls

    def track(name):
        calls.append(name)
        if on_call is not None:
            on_call(name)
        if name in fail or name.split(":", 1)[0] in fail:
            raise ConnectionError(f"{name} unreachable")

    def offers(fm_id):
        track(f"offers:{fm_id}")
        if fm_id == "anthropic.claude-opus-5-5":
            response = json.loads((FIXTURES / "offers_claude-opus-5-5.json").read_text(encoding="utf-8"))
            response["offers"][0].update(opus_extra or {})
            return response
        assert fm_id == "openai.gpt-5.6-sol", fm_id
        return _sol_offer(*sol, offers=sol_offers)

    def pricelist(input_usagetype, output_usagetype):
        track("pricelist")
        return json.loads((FIXTURES / "pricelist_nova-2-lite.json").read_text(encoding="utf-8"))["PriceList"]

    def anthropic_doc():
        track("anthropic_doc")
        return (FIXTURES / "anthropic_pricing.md").read_text(encoding="utf-8")

    return Fetchers(offers=offers, pricelist=pricelist, anthropic_doc=anthropic_doc)


@pytest.fixture()
def Session():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)  # same flags as database.SessionLocal
    engine.dispose()


def _seed(Session, values=BASELINE):
    with Session() as db:
        for model_id, (i, o, source_id) in values.items():
            ident = price_identity(model_id)
            db.add(PriceHistory(model_id=model_id, family_key=ident.family_key, channel=ident.channel,
                                input_per_mtok=i, output_per_mtok=o, effective_from=EPOCH, source_id=source_id,
                                status="seed", observed_at=None, run_id=None))
        db.commit()


def _rows(Session, model_id):
    with Session() as db:
        rows = db.query(PriceHistory).filter(PriceHistory.model_id == model_id).order_by(PriceHistory.id).all()
        db.expunge_all()
        return rows


def _run(Session, run_id):
    with Session() as db:
        run = db.get(PriceSyncRun, run_id)
        db.expunge(run)
        return run


def _sync(Session, at=T0, active=None, **kw):
    return _run(Session, run_sync(Session, active or _active(*ALL), _fetchers(**kw), now=lambda: at))


def test_contract_constants():
    assert (CHANGE_THRESHOLD, SYNC_DEADLINE_S, SYNC_LOCK_KEY) == (Decimal("0.5"), 300.0, 917350004)


@pytest.mark.parametrize(("current", "new", "expected"), [
    (None, P(1, 5), "no_baseline"),
    ((4.4, 22.0), P("4.4", "22"), "unchanged"),
    ((0.33, 2.75), P("0.3300000000", "2.7500000000"), "unchanged"),  # Price List x1000 vs stored float
    ((4.4, 22.0), P("5.5", "33"), "changed"),       # GPT-5.6 Sol promo end, in-region +25 % / +50 % (boundary)
    ((4.0, 20.0), P("5", "30"), "changed"),         # Global +25 % / +50 % (boundary)
    ((4.4, 22.0), P("5.5", "33.01"), "pending"),    # just over 50 %
    ((10.0, 50.0), P("5", "25"), "changed"),        # exactly -50 %
    ((10.0, 50.0), P("4.99", "50"), "pending"),
    ((0.22, 1.32), P("0.044", "0.264"), "pending"),  # a real -80 % cut waits for review
    ((0.0, 5.0), P("1", "5"), "pending"),           # no ratio against a zero baseline
])
def test_classify_change(current, new, expected):
    assert classify_change(current, new) == expected


def test_same_values_only_refresh_observed_at_and_run_id(Session):
    _seed(Session)
    run = _sync(Session)
    assert (run.status, run.changes, run.pending) == ("completed", 0, 0)
    assert _utc(run.started_at) == T0 and _utc(run.finished_at) == T0
    assert run.summary["channels"] == {m: "unchanged" for m in sorted(ALL)}
    assert run.summary["sources"] == {"offers": {"calls": 2, "ok": 2, "failed": 0},
                                      "pricelist": {"calls": 1, "ok": 1, "failed": 0},
                                      "anthropic_doc": {"calls": 1, "ok": 1, "failed": 0}}
    for model_id in ALL:
        (row,) = _rows(Session, model_id)
        assert row.status == "seed" and _utc(row.effective_from) == EPOCH
        assert _utc(row.observed_at) == T0 and row.run_id == run.id
        assert (row.input_per_mtok, row.output_per_mtok) == BASELINE[model_id][:2]


def test_changes_up_to_fifty_percent_apply_from_the_run_start(Session):
    _seed(Session)
    run = _sync(Session, sol=("5.5", "33", "5", "30"))
    assert (run.status, run.changes, run.pending) == ("completed", 2, 0)
    for model_id, values in ((SOL_E1, (5.5, 33.0)), (SOL_G, (5.0, 30.0))):
        assert run.summary["channels"][model_id] == "changed"
        seed, new = _rows(Session, model_id)
        assert seed.status == "seed" and seed.observed_at is None      # the old row stays as history
        assert new.status == "verified" and (new.input_per_mtok, new.output_per_mtok) == values
        assert _utc(new.effective_from) == T0 and _utc(new.observed_at) == T0 and new.run_id == run.id
        assert new.source_id == f"offer:{SOL_OFFER_ID}" and new.channel == price_identity(model_id).channel


def test_a_change_just_over_fifty_percent_waits_for_review(Session):
    _seed(Session)
    run = _sync(Session, sol=("5.5", "33.01", "4", "20"))
    assert run.summary["channels"][SOL_E1] == "pending" and run.summary["channels"][SOL_G] == "unchanged"
    assert (run.changes, run.pending) == (0, 1)
    seed, pending = _rows(Session, SOL_E1)
    assert seed.status == "seed" and seed.observed_at is None      # effective value not re-confirmed
    assert pending.status == "pending_review" and (pending.input_per_mtok, pending.output_per_mtok) == (5.5, 33.01)
    assert _utc(pending.effective_from) == T0 and _utc(pending.observed_at) == T0


def test_the_same_pending_value_is_not_inserted_twice(Session):
    _seed(Session)
    first = _sync(Session, at=T0, sol=("5.5", "33.01", "4", "20"))
    second = _sync(Session, at=T1, sol=("5.5", "33.01", "4", "20"))
    assert second.summary["channels"][SOL_E1] == "pending" and second.pending == 1
    _, pending = _rows(Session, SOL_E1)
    assert _utc(pending.effective_from) == T0                        # the first observing run's start is kept
    assert _utc(pending.observed_at) == T1 and pending.run_id == second.id != first.id


def test_a_rejected_value_does_not_come_back_until_it_changes(Session):
    _seed(Session)
    _sync(Session, at=T0, sol=("5.5", "33.01", "4", "20"))
    with Session() as db:
        db.query(PriceHistory).filter(PriceHistory.status == "pending_review").update({"status": "rejected"})
        db.commit()
    again = _sync(Session, at=T1, sol=("5.5", "33.01", "4", "20"))
    assert again.summary["channels"][SOL_E1] == "rejected" and (again.status, again.pending) == ("completed", 0)
    assert _utc(_rows(Session, SOL_E1)[1].observed_at) == T1
    different = _sync(Session, at=T2, sol=("5.5", "40", "4", "20"))
    assert different.summary["channels"][SOL_E1] == "pending"
    assert [r.status for r in _rows(Session, SOL_E1)] == ["seed", "rejected", "pending_review"]


def test_a_model_without_baseline_is_pending_from_epoch(Session):
    _seed(Session, {k: v for k, v in BASELINE.items() if k != SOL_E1})
    run = _sync(Session)
    assert run.summary["channels"][SOL_E1] == "no_baseline" and run.pending == 1
    (row,) = _rows(Session, SOL_E1)
    assert row.status == "pending_review" and _utc(row.effective_from) == EPOCH and _utc(row.observed_at) == T0
    assert _sync(Session, at=T1).summary["channels"][SOL_E1] == "no_baseline"
    (row,) = _rows(Session, SOL_E1)                                   # de-duplicated, observed again
    assert _utc(row.observed_at) == T1


def test_one_failing_source_changes_nothing_for_its_channels_and_is_partial(Session):
    _seed(Session)
    run = _sync(Session, fail={"anthropic_doc"})
    assert run.status == "partial" and run.summary["channels"][CP_HAIKU] == "skipped:fetch_failed"
    assert all(run.summary["channels"][m] == "unchanged" for m in ALL if m != CP_HAIKU)
    assert run.summary["sources"]["anthropic_doc"] == {"calls": 1, "ok": 0, "failed": 1}
    assert any(e.startswith("anthropic_doc pricing.md: ConnectionError") for e in run.summary["errors"])
    (row,) = _rows(Session, CP_HAIKU)
    assert row.observed_at is None and row.run_id is None


@pytest.mark.parametrize(("kw", "reason"), [({"fail": {"offers:openai.gpt-5.6-sol"}}, "skipped:fetch_failed"),
                                            ({"sol_offers": 2}, "skipped:offer_count")])
def test_one_offer_problem_skips_only_that_models_channels(Session, kw, reason):
    _seed(Session)
    run = _sync(Session, **kw)
    assert run.status == "partial" and run.summary["channels"][OPUS_US] == "unchanged"
    assert run.summary["channels"][SOL_G] == run.summary["channels"][SOL_E1] == reason


def test_no_claude_platform_on_aws_channels_makes_the_run_partial(Session):
    _seed(Session)
    calls = []
    run = _sync(Session, active=_active(*(m for m in ALL if m != CP_HAIKU)), calls=calls)
    assert run.status == "partial" and "anthropic_doc" not in calls
    assert "anthropic_doc: no active channels" in run.summary["errors"] and CP_HAIKU not in run.summary["channels"]


def test_the_deadline_skips_the_remaining_channels(Session):
    _seed(Session)
    clock, calls = {"t": T0}, []

    def slow(_name):  # every fetch takes 200 s on the fake clock
        clock["t"] += timedelta(seconds=200)

    run = _run(Session, run_sync(Session, _active(*ALL), _fetchers(on_call=slow, calls=calls),
                                 now=lambda: clock["t"], deadline_s=300))
    assert calls == ["anthropic_doc", "pricelist"]   # 400 s > 300 s before the first offer call
    assert run.status == "partial" and run.summary["channels"][CP_HAIKU] == run.summary["channels"][NOVA] == "unchanged"
    assert all(run.summary["channels"][m] == "skipped:deadline" for m in (OPUS_G, OPUS_US, SOL_G, SOL_E1))
    assert run.summary["sources"]["offers"] == {"calls": 0, "ok": 0, "failed": 0}
    assert any(e.startswith("deadline: 300s exceeded") for e in run.summary["errors"])
    assert _utc(run.finished_at) == T0 + timedelta(seconds=400) and _rows(Session, OPUS_US)[0].observed_at is None


def test_all_sources_failing_marks_the_run_failed(Session):
    _seed(Session)
    run = _sync(Session, fail={"offers", "pricelist", "anthropic_doc"})
    assert (run.status, run.changes, run.pending) == ("failed", 0, 0) and _utc(run.finished_at) == T0
    assert set(run.summary["channels"].values()) == {"skipped:fetch_failed"}
    assert all(_rows(Session, m)[0].observed_at is None for m in ALL)


def test_the_run_row_is_committed_as_running_before_the_first_fetch(Session):
    _seed(Session)
    seen = []

    def inspect(_name):
        if not seen:
            with Session() as db:
                seen.append([(r.status, r.finished_at, _utc(r.started_at)) for r in db.query(PriceSyncRun).all()])

    run = _sync(Session, on_call=inspect)
    assert seen == [[("running", None, T0)]]
    assert run.status == "completed" and run.finished_at is not None
    assert set(run.summary) == {"sources", "channels", "errors"} and sorted(run.summary["channels"]) == sorted(ALL)


def test_an_internal_error_marks_the_run_failed_and_reraises(Session, monkeypatch):
    _seed(Session)

    def boom(*_args):
        raise RuntimeError("database went away")

    monkeypatch.setattr(pricing_sync, "_apply", boom)
    with pytest.raises(RuntimeError, match="database went away"):
        run_sync(Session, _active(*ALL), _fetchers(), now=lambda: T0)
    with Session() as db:
        (run,) = db.query(PriceSyncRun).all()
        assert run.status == "failed" and run.finished_at is not None
        assert run.summary["errors"] == ["internal: RuntimeError: database went away"]
        assert db.query(PriceHistory).filter(PriceHistory.observed_at.isnot(None)).count() == 0
    with pytest.raises(ValueError):                   # a naive clock is refused up front
        run_sync(Session, _active(*ALL), _fetchers(), now=lambda: datetime(2026, 9, 26, 15, 0))


def test_offer_token_and_presigned_url_never_reach_logs_summary_or_rows(Session, caplog):
    _seed(Session)
    caplog.set_level(logging.DEBUG)
    extra = {"offerToken": "FAKE-OFFER-TOKEN-123", "legalTerm": {"url": "https://legal.example.invalid/o?sig=FAKE-PRESIGNED-456"}}
    run = _sync(Session, opus_extra=extra, sol_offers=2, fail={"pricelist"})
    with Session() as db:
        blob = caplog.text + json.dumps(run.summary) + json.dumps([r.source_id for r in db.query(PriceHistory).all()])
    assert "FAKE-OFFER-TOKEN" not in blob and "FAKE-PRESIGNED" not in blob


# ---------------------------------------------------------------- default fetchers (fake clients)


class _FakeBedrock:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def list_foundation_model_agreement_offers(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakePricing:
    def __init__(self, pages_by_usagetype):
        self.pages, self.calls = pages_by_usagetype, []

    def get_paginator(self, name):
        assert name == "get_products"
        outer = self

        class _Paginator:
            def paginate(self, **kwargs):
                outer.calls.append(kwargs)
                return iter(outer.pages[kwargs["Filters"][0]["Value"]])

        return _Paginator()


def _client_error(code, status):
    return ClientError({"Error": {"Code": code, "Message": "x"}, "ResponseMetadata": {"HTTPStatusCode": status}}, "Op")


def _raw_offer():
    response = json.loads((FIXTURES / "offers_gpt-6-astra.json").read_text(encoding="utf-8"))
    response["offers"][0]["offerToken"] = "FAKE-OFFER-TOKEN-123"
    response["offers"][0]["termDetails"]["legalTerm"] = {"url": "https://legal.example.invalid/o?sig=FAKE-PRESIGNED-456"}
    response["offers"][0]["termDetails"]["supportTerm"] = {"refundPolicyDescription": "No refunds"}
    return response


def _defaults(bedrock=None, pricing=None, http=None, sleeps=None):
    http = http or httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(599)))
    sleep = sleeps.append if sleeps is not None else (lambda s: None)
    return default_fetchers(bedrock=bedrock or _FakeBedrock([]), pricing=pricing or _FakePricing({}), http=http, sleep=sleep)


def test_default_offers_fetcher_asks_for_public_offers_and_strips_tokens():
    bedrock = _FakeBedrock([_raw_offer()])
    response = _defaults(bedrock=bedrock).offers("openai.gpt-6-astra")
    assert bedrock.calls == [{"modelId": "openai.gpt-6-astra", "offerType": "PUBLIC"}]
    assert not any(s in json.dumps(response) for s in ("offerToken", "legalTerm", "FAKE"))
    offer_id, card = single_public_offer(response)
    assert offer_id == "offer-7epta7rbw5aws" and len(card) == 18


def test_default_pricelist_fetcher_filters_exact_usagetypes_and_follows_pages():
    in_ut, out_ut = "USE1-Nova2.0Lite-input-tokens", "USE1-Nova2.0Lite-output-tokens"
    pricing = _FakePricing({in_ut: [{"PriceList": ["a"]}, {"PriceList": ["b"]}], out_ut: [{"PriceList": ["c"]}]})
    assert _defaults(pricing=pricing).pricelist(in_ut, out_ut) == ["a", "b", "c"]
    assert pricing.calls == [{"ServiceCode": "AmazonBedrock", "FormatVersion": "aws_v1",
                              "Filters": [{"Type": "TERM_MATCH", "Field": "usagetype", "Value": ut}]} for ut in (in_ut, out_ut)]


def test_default_anthropic_fetcher_sends_a_user_agent_and_retries_5xx_but_not_404():
    seen, sleeps = [], []

    def handler(request):
        seen.append((str(request.url), request.headers.get("user-agent")))
        return httpx.Response(503) if len(seen) == 1 else httpx.Response(200, text="## Model pricing\n")

    fetchers = _defaults(http=httpx.Client(transport=httpx.MockTransport(handler)), sleeps=sleeps)
    assert fetchers.anthropic_doc() == "## Model pricing\n"
    assert seen == [(ANTHROPIC_PRICING_URL, pricing_sync.USER_AGENT)] * 2 and sleeps == [1.0]
    sleeps.clear()
    not_found = _defaults(http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))), sleeps=sleeps)
    with pytest.raises(httpx.HTTPStatusError):
        not_found.anthropic_doc()
    assert sleeps == []


@pytest.mark.parametrize(("outcomes", "succeeds", "sleeps_expected"), [
    ([_client_error("ThrottlingException", 400), EndpointConnectionError(endpoint_url="https://bedrock"), "ok"], True, [1.0, 2.0]),
    ([_client_error("SomethingElse", 502), "ok"], True, [1.0]),
    ([_client_error("ThrottlingException", 400)] * 4, False, [1.0, 2.0, 4.0]),   # gives up after 3 retries
    ([_client_error("AccessDeniedException", 403), "ok"], False, []),
    ([_client_error("ValidationException", 400), "ok"], False, []),              # e.g. "Agreement not supported"
])
def test_retry_policy(outcomes, succeeds, sleeps_expected):
    bedrock, sleeps = _FakeBedrock([_raw_offer() if o == "ok" else o for o in outcomes]), []
    fetchers = _defaults(bedrock=bedrock, sleeps=sleeps)
    if succeeds:
        assert single_public_offer(fetchers.offers("openai.gpt-6-astra"))[0] == "offer-7epta7rbw5aws"
    else:
        with pytest.raises(ClientError):
            fetchers.offers("openai.gpt-6-astra")
    assert sleeps == sleeps_expected


def test_default_fetchers_build_us_east_1_clients_without_sdk_retries(monkeypatch):
    import types

    import boto3

    made = []
    monkeypatch.setattr(boto3, "client", lambda name, **kw: made.append((name, kw)) or types.SimpleNamespace())
    default_fetchers(http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(599))))
    assert [(n, kw["region_name"], kw["config"].retries["max_attempts"]) for n, kw in made] == [
        ("bedrock", "us-east-1", 1), ("pricing", "us-east-1", 1)]
```

#### `t04-sync` — `backend/pricing_sync.py`

<!-- plan-block id=t04-sync path=backend/pricing_sync.py sha256=888ed2a888c97cc3b089fe5562f3bc39959e6b5b436477b4e19d07dbf70eda0f -->
```python
"""Official unit-price sync (v2.30.0, ADR-030) — one run every 12 hours in the PricingSync task.

Order: running row first -> Anthropic pricing.md -> Price List (Nova) -> agreement offers (one call per FM id;
cheap sources first so a slow offers API cannot starve them) -> per-channel compare -> run closed as
completed / partial / failed. offerToken and presigned legalTerm URLs are stripped by `default_fetchers`
right after the call; no response body is ever logged.
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Mapping

import httpx
from botocore.exceptions import ClientError, ConnectionError as BotoConnectionError, HTTPClientError

from models import PriceHistory, PriceSyncRun
from pricing_parsers import (
    PriceParseError,
    UnitPrice,
    parse_anthropic_pricing_md,
    parse_pricelist,
    select_offer_price,
    single_public_offer,
)
from pricing_sources import (
    ANTHROPIC_PRICING_URL,
    ANTHROPIC_SOURCE_ID,
    EPOCH,
    NOVA_USAGETYPES,
    PriceIdentity,
    offer_source_id,
    pricelist_source_id,
)

logger = logging.getLogger(__name__)

CHANGE_THRESHOLD = Decimal("0.5")
SYNC_DEADLINE_S = 300.0
SYNC_LOCK_KEY = 917350004

AWS_REGION = "us-east-1"  # agreement offers are region-independent; the Price List API lives in us-east-1
USER_AGENT = "bedrock-llm-monitor-pricing-sync (+https://github.com/whchoi98/model-monitoring)"
FETCH_RETRIES = 3            # retries after the first attempt (ThrottlingException, 5xx, connection errors)
FETCH_BACKOFF_BASE_S = 1.0   # 1 s, 2 s, 4 s

SOURCES = ("offers", "pricelist", "anthropic_doc")
_SOURCE_OF_KIND = {"offer": "offers", "pricelist": "pricelist", "anthropic_doc": "anthropic_doc"}
_EFFECTIVE_STATUSES = ("seed", "verified")
_HELD_STATUSES = ("pending_review", "rejected")
_RETRYABLE_AWS_CODES = frozenset({
    "ThrottlingException", "Throttling", "TooManyRequestsException", "RequestLimitExceeded",
    "ServiceUnavailableException", "ServiceUnavailable", "InternalServerException", "InternalFailure",
})
_MAX_ERRORS = 50


@dataclass
class Fetchers:
    offers: Callable[[str], dict]            # FM id -> list_foundation_model_agreement_offers response
    pricelist: Callable[[str, str], list]    # (input_usagetype, output_usagetype) -> PriceList items
    anthropic_doc: Callable[[], str]         # markdown text


# ---------------------------------------------------------------- default fetchers (network)


def _short(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, ClientError):
        code = (exc.response.get("Error") or {}).get("Code", "")
        status = (exc.response.get("ResponseMetadata") or {}).get("HTTPStatusCode") or 0
        return code in _RETRYABLE_AWS_CODES or status >= 500
    if isinstance(exc, (BotoConnectionError, HTTPClientError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


def _with_retries(call: Callable[[], object], *, sleep: Callable[[float], None]):
    attempt = 0
    while True:
        try:
            return call()
        except Exception as exc:
            if attempt >= FETCH_RETRIES or not _is_retryable(exc):
                raise
            delay = FETCH_BACKOFF_BASE_S * (2 ** attempt)
            attempt += 1
            logger.warning("pricing sync: %s — retry %d/%d in %.0fs", _short(exc), attempt, FETCH_RETRIES, delay)
            sleep(delay)


def _sanitize_offers(raw: dict) -> dict:
    """Keep modelId, offerId and the rate card only — drops offerToken, legalTerm (presigned URL), supportTerm."""
    raw = raw if isinstance(raw, dict) else {}
    offers = []
    for offer in raw.get("offers") or []:
        offer = offer if isinstance(offer, dict) else {}
        rate_card = ((offer.get("termDetails") or {}).get("usageBasedPricingTerm") or {}).get("rateCard")
        offers.append({"offerId": offer.get("offerId"), "termDetails": {"usageBasedPricingTerm": {"rateCard": rate_card}}})
    return {"modelId": raw.get("modelId"), "offers": offers}


def _get_products(pricing, usagetype: str) -> list:
    items: list = []
    paginator = pricing.get_paginator("get_products")
    for page in paginator.paginate(
        ServiceCode="AmazonBedrock",
        Filters=[{"Type": "TERM_MATCH", "Field": "usagetype", "Value": usagetype}],
        FormatVersion="aws_v1",
    ):
        items.extend(page.get("PriceList") or [])
    return items


def default_fetchers(*, bedrock=None, pricing=None, http=None, sleep: Callable[[float], None] = time.sleep) -> Fetchers:
    """Real sources: boto3 bedrock + pricing (us-east-1) and httpx for the Anthropic doc.

    SDK-level retries are off (botocore max_attempts=1); `_with_retries` is the only retry loop.
    The keyword arguments exist for tests (fake clients, no sleeping).
    """
    if bedrock is None or pricing is None:
        import boto3
        from botocore.config import Config

        cfg = Config(retries={"max_attempts": 1, "mode": "standard"}, connect_timeout=10, read_timeout=30)
        if bedrock is None:
            bedrock = boto3.client("bedrock", region_name=AWS_REGION, config=cfg)
        if pricing is None:
            pricing = boto3.client("pricing", region_name=AWS_REGION, config=cfg)
    if http is None:
        http = httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True)

    def offers(fm_id: str) -> dict:
        raw = _with_retries(
            lambda: bedrock.list_foundation_model_agreement_offers(modelId=fm_id, offerType="PUBLIC"),
            sleep=sleep,
        )
        return _sanitize_offers(raw)

    def pricelist(input_usagetype: str, output_usagetype: str) -> list:
        items: list = []
        for usagetype in (input_usagetype, output_usagetype):
            items.extend(_with_retries(lambda ut=usagetype: _get_products(pricing, ut), sleep=sleep))
        return items

    def anthropic_doc() -> str:
        def get() -> str:
            resp = http.get(ANTHROPIC_PRICING_URL, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            return resp.text

        return _with_retries(get, sleep=sleep)

    return Fetchers(offers=offers, pricelist=pricelist, anthropic_doc=anthropic_doc)


# ---------------------------------------------------------------- comparison


def _dec(v: float) -> Decimal:
    return Decimal(str(round(v, 6)))


def classify_change(current: tuple[float, float] | None, new: UnitPrice) -> str:
    """"unchanged" | "changed" (both |new-old|/old <= 0.5, boundary inclusive) | "pending" | "no_baseline"."""
    if current is None:
        return "no_baseline"
    old_in, old_out = _dec(current[0]), _dec(current[1])
    if old_in == new.input and old_out == new.output:
        return "unchanged"
    for old, value in ((old_in, new.input), (old_out, new.output)):
        if old <= 0 or abs(value - old) / old > CHANGE_THRESHOLD:
            return "pending"
    return "changed"


# ---------------------------------------------------------------- run


@dataclass(frozen=True)
class _Observed:
    price: UnitPrice
    source_id: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _open_run(session_factory, started_at: datetime) -> int:
    db = session_factory()
    try:
        run = PriceSyncRun(started_at=started_at, status="running", changes=0, pending=0)
        db.add(run)
        db.commit()
        return run.id
    finally:
        db.close()


def _fetch_all(active: Mapping[str, PriceIdentity], fetchers: Fetchers, clock, started_at: datetime, deadline_s: float):
    observed: dict[str, _Observed] = {}
    channels: dict[str, str] = {}
    sources = {s: {"calls": 0, "ok": 0, "failed": 0} for s in SOURCES}
    errors: list[str] = []
    groups: dict[str, dict[str, list[tuple[str, PriceIdentity]]]] = {s: defaultdict(list) for s in SOURCES}
    for model_id in sorted(active):
        ident = active[model_id]
        source = _SOURCE_OF_KIND.get(ident.source_kind)
        if source is None:
            channels[model_id] = "skipped:unmapped"
            errors.append(f"{model_id}: unknown source kind {ident.source_kind!r}")
            continue
        groups[source][ident.source_ref].append((model_id, ident))
    for source in SOURCES:
        if not groups[source]:
            errors.append(f"{source}: no active channels")

    deadline = {"hit": False}

    def fetch(source: str, what: str, call: Callable[[], object]):
        if (clock() - started_at).total_seconds() > deadline_s:
            if not deadline["hit"]:
                deadline["hit"] = True
                errors.append(f"deadline: {deadline_s:g}s exceeded before {source} {what}")
            return None, "deadline"
        sources[source]["calls"] += 1
        try:
            value = call()
        except Exception as exc:  # noqa: BLE001 — a source failure only skips its channels
            sources[source]["failed"] += 1
            message = f"{source} {what}: {_short(exc)}"
            logger.warning("pricing sync: %s", message)
            errors.append(message)
            return None, "fetch_failed"
        sources[source]["ok"] += 1
        return value, None

    def settle(members, price: UnitPrice | None, reason: str | None, source_id: str | None) -> None:
        for model_id, _ in members:
            if price is None:
                channels[model_id] = f"skipped:{reason}"
            else:
                observed[model_id] = _Observed(price, source_id)

    # 1) Anthropic pricing.md — Claude Platform on AWS
    doc_groups = groups["anthropic_doc"]
    if doc_groups:
        text, reason = fetch("anthropic_doc", "pricing.md", fetchers.anthropic_doc)
        table: dict[str, UnitPrice] = {}
        if reason is None:
            try:
                table = parse_anthropic_pricing_md(text)
            except PriceParseError as exc:
                reason = "parse_failed"
                errors.append(f"anthropic_doc: {exc}")
        for doc_name in sorted(doc_groups):
            price = table.get(doc_name)
            if reason is None and price is None:
                errors.append(f"anthropic_doc: model {doc_name!r} not in the table")
            settle(doc_groups[doc_name], price, reason or "not_found", ANTHROPIC_SOURCE_ID)

    # 2) AWS Price List — Nova
    for family_key in sorted(groups["pricelist"]):
        members = groups["pricelist"][family_key]
        usagetypes = NOVA_USAGETYPES.get(family_key)
        if usagetypes is None:
            errors.append(f"pricelist: no usagetypes for {family_key}")
            settle(members, None, "unmapped", None)
            continue
        items, reason = fetch("pricelist", family_key, lambda ut=usagetypes: fetchers.pricelist(ut[0], ut[1]))
        price = None
        if reason is None:
            try:
                price = parse_pricelist(items, usagetypes[0], usagetypes[1])
            except PriceParseError as exc:
                reason = "parse_failed"
                errors.append(f"pricelist {family_key}: {exc}")
        settle(members, price, reason, pricelist_source_id(usagetypes[0]))

    # 3) Bedrock agreement offers — Bedrock Claude + OpenAI (one call per FM id)
    for fm_id in sorted(groups["offers"]):
        members = groups["offers"][fm_id]
        response, reason = fetch("offers", fm_id, lambda fm=fm_id: fetchers.offers(fm))
        if reason is None:
            try:
                offer_id, rate_card = single_public_offer(response)
            except PriceParseError as exc:
                offers_list = response.get("offers") if isinstance(response, dict) else None
                reason = "offer_count" if isinstance(offers_list, list) and len(offers_list) != 1 else "parse_failed"
                errors.append(f"offers {fm_id}: {exc}")
        if reason is not None:
            settle(members, None, reason, None)
            continue
        for model_id, ident in members:
            price = select_offer_price(rate_card, ident.channel)
            if price is None:
                errors.append(f"offers {fm_id}: no standard price for channel {ident.channel}")
                channels[model_id] = "skipped:not_found"
            else:
                observed[model_id] = _Observed(price, offer_source_id(offer_id))
    return observed, channels, sources, errors


def _effective_row(db, model_id: str, at: datetime) -> PriceHistory | None:
    return (
        db.query(PriceHistory)
        .filter(
            PriceHistory.model_id == model_id,
            PriceHistory.status.in_(_EFFECTIVE_STATUSES),
            PriceHistory.effective_from <= at,
        )
        .order_by(PriceHistory.effective_from.desc(), PriceHistory.id.desc())
        .first()
    )


def _held_row_with_value(db, model_id: str, price: UnitPrice) -> PriceHistory | None:
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.model_id == model_id, PriceHistory.status.in_(_HELD_STATUSES))
        .order_by(PriceHistory.id.desc())
        .all()
    )
    return next(
        (r for r in rows if _dec(r.input_per_mtok) == price.input and _dec(r.output_per_mtok) == price.output),
        None,
    )


def _apply(db, model_id: str, ident: PriceIdentity, got: _Observed, started_at: datetime, run_id: int) -> str:
    current = _effective_row(db, model_id, started_at)
    result = classify_change(
        None if current is None else (current.input_per_mtok, current.output_per_mtok), got.price
    )
    if result == "unchanged":
        current.observed_at = started_at
        current.run_id = run_id
        current.source_id = got.source_id
        return result
    if result == "changed":
        status, effective_from = "verified", started_at
    else:  # "pending" | "no_baseline"
        held = _held_row_with_value(db, model_id, got.price)
        if held is not None:
            held.observed_at = started_at
            held.run_id = run_id
            return "rejected" if held.status == "rejected" else result
        status = "pending_review"
        effective_from = EPOCH if result == "no_baseline" else started_at
    db.add(
        PriceHistory(
            model_id=model_id,
            family_key=ident.family_key,
            channel=ident.channel,
            input_per_mtok=float(got.price.input),
            output_per_mtok=float(got.price.output),
            effective_from=effective_from,
            source_id=got.source_id,
            status=status,
            observed_at=started_at,
            run_id=run_id,
        )
    )
    return result


def _run_status(channels: Mapping[str, str], sources: Mapping[str, dict]) -> str:
    skipped = sum(1 for r in channels.values() if r.startswith("skipped:"))
    if len(channels) == skipped:
        return "failed"
    if skipped or any(s["failed"] or not s["calls"] for s in sources.values()):
        return "partial"
    return "completed"


def _close_failed(session_factory, run_id: int, finished_at: datetime, exc: BaseException) -> None:
    db = session_factory()
    try:
        run = db.get(PriceSyncRun, run_id)
        if run is not None:
            run.status = "failed"
            run.finished_at = finished_at
            run.summary = {"sources": {}, "channels": {}, "errors": [f"internal: {_short(exc)}"]}
            db.commit()
    except Exception:  # noqa: BLE001 — the original error is re-raised by the caller
        db.rollback()
        logger.exception("pricing sync: could not mark run %d failed", run_id)
    finally:
        db.close()


def run_sync(
    session_factory,
    active: Mapping[str, PriceIdentity],
    fetchers: Fetchers,
    *,
    now: Callable[[], datetime] | None = None,
    deadline_s: float = SYNC_DEADLINE_S,
) -> int:
    """One sync run; returns `price_sync_runs.id`. Re-raises only internal (DB) errors, after marking the run failed."""
    clock = now or _utcnow
    started_at = clock()
    if started_at.tzinfo is None:
        raise ValueError("run_sync: now() must return a timezone-aware datetime")
    run_id = _open_run(session_factory, started_at)
    try:
        observed, channels, sources, errors = _fetch_all(active, fetchers, clock, started_at, deadline_s)
        db = session_factory()
        try:
            changes = pending = 0
            for model_id in sorted(observed):
                result = _apply(db, model_id, active[model_id], observed[model_id], started_at, run_id)
                channels[model_id] = result
                if result == "changed":
                    changes += 1
                elif result in ("pending", "no_baseline"):
                    pending += 1
            status = _run_status(channels, sources)
            run = db.get(PriceSyncRun, run_id)
            run.finished_at = clock()
            run.status = status
            run.summary = {"sources": sources, "channels": dict(sorted(channels.items())), "errors": errors[:_MAX_ERRORS]}
            run.changes = changes
            run.pending = pending
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as exc:
        logger.exception("pricing sync run %d failed", run_id)
        _close_failed(session_factory, run_id, clock(), exc)
        raise
    results: dict[str, int] = defaultdict(int)
    for r in channels.values():
        results[r] += 1
    logger.info(
        "pricing sync run %d %s: changes=%d pending=%d results=%s",
        run_id, status, changes, pending, dict(sorted(results.items())),
    )
    return run_id
```

### Task 5 blocks

#### `t05-test` — `backend/tests/test_pricing_sync_runner.py`

<!-- plan-block id=t05-test path=backend/tests/test_pricing_sync_runner.py sha256=989fefe61f0077f96d1c4e05f9e4ab02ad8abb5dffc2e2857ff9b6df7a17af35 -->
```python
"""PricingSync one-shot runner (v2.30.0, ADR-030): order, exit codes, advisory lock 917350004, os._exit."""

import os
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pricing_sync_runner as runner
from database import Base
from models import PriceSyncRun

BACKEND = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)
LOCK = {"key": 917350004}


@pytest.fixture()
def wired(monkeypatch):
    """Every collaborator faked on SQLite; `calls` records the order, `status` is how the fake run ends."""
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    state = SimpleNamespace(calls=[], status="completed", seed_active=None, sync_active=None, engine=engine)
    models = {"global.anthropic.claude-opus-5-5": "Bedrock Claude Opus 5.5 (Global)"}

    def discover():
        state.calls.append("discover_cp")
        models["anthropic:claude-opus-5-5"] = "Anthropic Claude Opus 5.5 (US)"

    def register_openai():
        state.calls.append("register_openai")
        models["openai:us-east-1:openai.gpt-6-sol"] = "OpenAI GPT 6 Sol (us-east-1)"
        models["openai:1p:gpt-5.4"] = "OpenAI GPT 5.4 (1P)"  # hidden by the default HIDDEN_MODEL_PATTERNS

    def ensure_seed(bind, active):
        state.calls.append("ensure_seed")
        state.seed_active = dict(active)
        return 3

    def run_sync(session_factory, active, fetchers):
        state.calls.append("run_sync")
        assert session_factory is Session and fetchers == "fetchers"
        state.sync_active = dict(active)
        with session_factory() as db:
            run = PriceSyncRun(started_at=T0, finished_at=T0, status=state.status, changes=0, pending=0,
                               summary={"sources": {}, "channels": {m: "unchanged" for m in active}, "errors": []})
            db.add(run)
            db.commit()
            return run.id

    for name, value in {
        "engine": engine, "SessionLocal": Session, "AVAILABLE_MODELS": models,
        "create_tables": lambda: state.calls.append("create_tables"), "_discover_anthropic_models": discover,
        "_register_openai_models": register_openai, "ensure_seed": ensure_seed, "run_sync": run_sync,
        "default_fetchers": lambda: "fetchers",
    }.items():
        monkeypatch.setattr(runner, name, value)
    monkeypatch.delenv("HIDDEN_MODEL_PATTERNS", raising=False)
    yield state
    engine.dispose()


def test_registration_runs_before_ensure_seed_before_run_sync(wired):
    assert runner.main(["--once"]) == 0
    assert wired.calls == ["create_tables", "discover_cp", "register_openai", "ensure_seed", "run_sync"]
    assert set(wired.seed_active) == {"global.anthropic.claude-opus-5-5", "anthropic:claude-opus-5-5",
                                      "openai:us-east-1:openai.gpt-6-sol"}  # registered ids in, (1P) hidden
    assert wired.sync_active == wired.seed_active and wired.seed_active["anthropic:claude-opus-5-5"].channel == "cp"


@pytest.mark.parametrize(("status", "code"), [("completed", 0), ("partial", 0), ("failed", 1)])
def test_exit_code_follows_the_run_status(wired, status, code):
    wired.status = status
    assert runner.main(["--once"]) == code


def test_a_failing_registration_is_not_fatal(wired, monkeypatch):
    def broken():
        wired.calls.append("discover_cp")
        raise RuntimeError("CP /v1/models 500")

    monkeypatch.setattr(runner, "_discover_anthropic_models", broken)
    assert runner.main(["--once"]) == 0
    assert wired.calls == ["create_tables", "discover_cp", "register_openai", "ensure_seed", "run_sync"]
    assert "anthropic:claude-opus-5-5" not in wired.sync_active


def _raise(message):
    def fail(*_args):
        raise RuntimeError(message)
    return fail


def test_no_sync_when_ensure_seed_fails_and_a_raising_sync_exits_one(wired, monkeypatch):
    monkeypatch.setattr(runner, "ensure_seed", _raise("seed insert failed"))
    assert runner.main(["--once"]) == 1 and "run_sync" not in wired.calls
    monkeypatch.setattr(runner, "ensure_seed", lambda bind, active: 0)
    monkeypatch.setattr(runner, "run_sync", _raise("database went away"))
    assert runner.main(["--once"]) == 1


def test_once_is_required(wired):
    with pytest.raises(SystemExit):
        runner.main([])
    assert wired.calls == []


class _FakePgConnection:
    def __init__(self, lock_free):
        self.lock_free, self.statements, self.closed = lock_free, [], False

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        return SimpleNamespace(scalar=lambda: self.lock_free if "pg_try_advisory_lock" in str(statement) else True)

    def commit(self):
        pass

    def invalidate(self):
        pass

    def close(self):
        self.closed = True


@pytest.mark.parametrize(("lock_free", "code", "statements"), [
    (True, 0, [("SELECT pg_try_advisory_lock(:key)", LOCK), ("SELECT pg_advisory_unlock(:key)", LOCK)]),
    (False, 1, [("SELECT pg_try_advisory_lock(:key)", LOCK)]),               # busy: exit 1, nothing to release
])
def test_postgresql_runs_under_the_advisory_lock(wired, monkeypatch, lock_free, code, statements):
    conn = _FakePgConnection(lock_free)
    monkeypatch.setattr(runner, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), connect=lambda: conn))
    assert runner.main(["--once"]) == code
    assert ("run_sync" in wired.calls) is lock_free
    assert conn.statements == statements and conn.closed


def test_sqlite_skips_the_lock(wired):
    assert wired.engine.dialect.name == "sqlite"
    assert runner.main(["--once"]) == 0 and "run_sync" in wired.calls


def test_module_entrypoint_hard_exits_with_the_run_status(tmp_path):
    """`python -m pricing_sync_runner --once` on a SQLite file DB: partial run -> exit 0, logs flushed, and a
    live non-daemon thread does not keep the process alive (os._exit, as in auto_prober_runner)."""
    script = textwrap.dedent("""
        import runpy, sys, threading
        from datetime import datetime, timezone
        import prober, pricing_seed, pricing_sync

        prober._discover_anthropic_models = lambda: None
        prober._register_openai_models = lambda: None
        pricing_seed.ensure_seed = lambda bind, active: 0
        pricing_sync.default_fetchers = lambda: None

        def fake_run_sync(session_factory, active, fetchers):
            from models import PriceSyncRun
            threading.Thread(target=threading.Event().wait, daemon=False).start()  # never finishes
            with session_factory() as db:
                run = PriceSyncRun(started_at=datetime.now(timezone.utc), status="partial", changes=0, pending=0,
                                   summary={"sources": {}, "channels": {}, "errors": []})
                db.add(run)
                db.commit()
                return run.id

        pricing_sync.run_sync = fake_run_sync
        sys.argv = ["pricing_sync_runner", "--once"]
        runpy.run_module("pricing_sync_runner", run_name="__main__")
        print("UNREACHABLE: _finish must not return")
    """)
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{tmp_path / 'sync.db'}")
    t0 = time.perf_counter()
    proc = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "UNREACHABLE" not in proc.stdout
    assert "pricing_sync_runner: run_id=1 status=partial" in proc.stderr
    assert time.perf_counter() - t0 < 30


def test_hidden_model_patterns_are_applied_to_the_active_set(wired, monkeypatch):
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P),(us-east-1)")
    assert runner.main(["--once"]) == 0
    assert "openai:us-east-1:openai.gpt-6-sol" not in wired.seed_active
    assert "openai:us-east-1:openai.gpt-6-sol" not in wired.sync_active
```

#### `t05-runner` — `backend/pricing_sync_runner.py`

<!-- plan-block id=t05-runner path=backend/pricing_sync_runner.py sha256=17058a1a86695348fb0e3d56a63dbd7b62220089eb257581849d5984554dc77d -->
```python
"""PricingSync Fargate one-shot 진입점 (v2.30.0, ADR-030) — EventBridge Scheduler `rate(12 hours)`.

ECS Task Definition CMD:
  python -m pricing_sync_runner --once

순서 (spec "12시간 동기화" 1~2단계):
  1. create_tables() — price_history / price_sync_runs 보장 (backend 재배포 전에 먼저 돌 수 있음)
  2. 모델 등록 — prober._discover_anthropic_models() (CP on AWS /v1/models), prober._register_openai_models()
  3. active_channels(AVAILABLE_MODELS, hidden_patterns()) — 숨김 라벨(기본 "(1P)") 제외
  4. ensure_seed(engine, active) — 실패하면 동기화하지 않는다: seed 없이 돌면 seed 대상 채널이 전부
     no_baseline pending 행이 되고, 그 행 때문에 이후 ensure_seed가 그 model_id를 건너뛴다
  5. run_sync — PostgreSQL에서는 pg_try_advisory_lock(917350004) 아래(수동 실행과 스케줄 실행이 겹치지
     않게, 못 잡으면 즉시 종료). SQLite(로컬/테스트)는 잠금 생략
  6. os._exit — auto_prober_runner와 같은 종료 경로 (v2.28.2)

exit code: 0 = 런 completed 또는 partial, 1 = 런 failed, 잠금 점유 중, seed/동기화 예외.
"""

import argparse
import logging
import os
import sys
from collections import Counter
from contextlib import contextmanager

from sqlalchemy import text

from database import SessionLocal, create_tables, engine
from models import PriceSyncRun
from prober import AVAILABLE_MODELS, _discover_anthropic_models, _register_openai_models
from pricing_seed import ensure_seed
from pricing_sources import active_channels
from pricing_sync import SYNC_LOCK_KEY, default_fetchers, run_sync
from visibility import hidden_patterns

logger = logging.getLogger("pricing_sync_runner")

EXIT_OK = 0
EXIT_FAILED = 1
_OK_STATUSES = ("completed", "partial")


def _register_models() -> None:
    """auto_prober_runner와 같은 등록 — 하나가 실패해도 나머지는 등록한다(누락 채널은 동기화 대상에서 빠짐)."""
    for register in (_discover_anthropic_models, _register_openai_models):
        try:
            register()
        except Exception:  # noqa: BLE001 — 등록 실패는 non-fatal (CP 채널 없음 → 런 partial)
            logger.exception("pricing_sync_runner: model registration failed (non-fatal)")


@contextmanager
def _sync_lock(bind):
    """PostgreSQL 세션 advisory lock(SYNC_LOCK_KEY)을 런 전체 동안 쥔다. yield 값 = 잡았는지 여부."""
    if bind.dialect.name != "postgresql":
        yield True
        return
    conn = bind.connect()
    acquired = False
    try:
        acquired = bool(
            conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": SYNC_LOCK_KEY}).scalar()
        )
        conn.commit()  # 세션 잠금은 트랜잭션과 무관 — idle-in-transaction으로 5분 머물지 않게 닫는다
        yield acquired
    finally:
        try:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": SYNC_LOCK_KEY})
                conn.commit()
        except Exception:  # noqa: BLE001 — 해제 실패 시 커넥션을 버려 세션 잠금도 함께 끝낸다
            logger.exception("pricing_sync_runner: advisory unlock failed — invalidating the connection")
            conn.invalidate()
        finally:
            conn.close()


def _report(run_id: int) -> int:
    db = SessionLocal()
    try:
        run = db.get(PriceSyncRun, run_id)
        status = run.status if run is not None else "missing"
        summary = (run.summary if run is not None else None) or {}
        changes = run.changes if run is not None else 0
        pending = run.pending if run is not None else 0
    finally:
        db.close()
    results = Counter((summary.get("channels") or {}).values())
    logger.info(
        "pricing_sync_runner: run_id=%d status=%s changes=%d pending=%d results=%s errors=%d",
        run_id, status, changes, pending, dict(sorted(results.items())), len(summary.get("errors") or []),
    )
    return EXIT_OK if status in _OK_STATUSES else EXIT_FAILED


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Sync official unit prices once and exit")
    parser.add_argument("--once", action="store_true", help="실행 1회 후 종료 (현재 유일한 모드)")
    args = parser.parse_args(argv)
    if not args.once:
        parser.error("--once 필수")

    try:
        create_tables()
    except Exception:
        logger.exception("pricing_sync_runner: create_tables failed")
        return EXIT_FAILED

    _register_models()
    active = active_channels(AVAILABLE_MODELS, hidden_patterns())
    logger.info("pricing_sync_runner: %d active channels", len(active))

    try:
        inserted = ensure_seed(engine, active)
    except Exception:
        logger.exception("pricing_sync_runner: ensure_seed failed — sync skipped")
        return EXIT_FAILED
    logger.info("pricing_sync_runner: ensure_seed inserted %d rows", inserted)

    try:
        with _sync_lock(engine) as acquired:
            if not acquired:
                logger.warning("pricing_sync_runner: lock %d held by another sync — exiting", SYNC_LOCK_KEY)
                return EXIT_FAILED
            run_id = run_sync(SessionLocal, active, default_fetchers())
        return _report(run_id)
    except Exception:
        logger.exception("pricing_sync_runner: sync failed")
        return EXIT_FAILED


def _finish(exit_code: int, _exit=os._exit) -> None:
    """auto_prober_runner._finish와 같다: DB 엔진 정리 + 로그 flush 후 os._exit (남은 스레드를 기다리지 않음)."""
    try:
        engine.dispose()
    except Exception:  # noqa: BLE001 — 종료 경로는 어떤 정리 실패에도 막히지 않는다
        logging.exception("pricing_sync_runner: engine dispose failed (ignored)")
    logging.shutdown()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001
            pass
    _exit(exit_code)


if __name__ == "__main__":
    _finish(main())
```

### Task 6 blocks

#### `t06-legacy` — `backend/tests/_legacy_pricing_v2291.py`

<!-- plan-block id=t06-legacy path=backend/tests/_legacy_pricing_v2291.py sha256=c662382937aa7e611508da768ab371aa196db4cd3e36b81b4fc46a1e9afe2096 -->
```python
"""FROZEN copy of backend/pricing.py at v2.29.1 (git 8ffb283) — equivalence test only (ADR-030).

backend/pricing.py was deleted in v2.30.0; costs now come from price_history (price_history.py).
test_cost_time_effective.py checks that the new per-row cost equals this copy on the 44 channels
whose price did not change, and that the 11 corrected channels (Bedrock Claude US x1.1, Nova 2.0
Lite 0.33/2.75) differ from it. Never edit the table below and never import this module from
application code.
"""

from __future__ import annotations

from typing import Optional


PRICE_TABLE: dict[str, dict[str, float]] = {
    # Anthropic Claude (USD per 1M tokens: input / output)
    "claude-fable-5-1": {"input": 10.0, "output": 50.0},  # Fable 5.1 — Fable 5와 동일 티어/단가 (v2.22.0)
    "claude-fable-5": {"input": 10.0, "output": 50.0},
    # Opus 5.5 (v2.27.0) — Anthropic 정가 $4/$20 (Opus 5보다 인하). 정확 키 필수:
    # 없으면 get_pricing prefix fallback이 "claude-opus-5"($5/$25)로 조용히 매칭된다.
    "claude-opus-5-5": {"input": 4.0, "output": 20.0},
    "claude-opus-5": {"input": 5.0, "output": 25.0},
    "claude-opus-4-8": {"input": 5.0, "output": 25.0},
    "claude-opus-4-7": {"input": 5.0, "output": 25.0},
    "claude-opus-4-6-v1": {"input": 5.0, "output": 25.0},
    "claude-opus-4-6": {"input": 5.0, "output": 25.0},
    "claude-sonnet-5": {"input": 2.0, "output": 10.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001-v1:0": {"input": 1.0, "output": 5.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
    # Amazon Nova
    "nova-2-lite-v1:0": {"input": 0.06, "output": 0.24},
    # OpenAI GPT (Bedrock Mantle). cached-input 미추적 — input/output만.
    "gpt-5.4": {"input": 2.75, "output": 16.50},
    "gpt-5.5": {"input": 5.50, "output": 33.00},
    # GPT-5.6 세대 in-region/Geo 단가 — 2026-07-30 AWS 인하 반영 (Luna -80%, Terra -20%).
    # 출처: AWS 공식 모델 카드 (Standard tier, short context ≤272K — 프로브는 항상 이 구간).
    # Sol은 v2.28.1(2026-09-23, 사용자 결정)에 **프로모션 단가** 반영: In-Region·Geo $4.40/$22, Global $4/$20
    # (구 $5.50/$33, $5/$30). 모델 카드와 ListFoundationModelAgreementOffers(offer-gnqokrqqvdbgw) 일치.
    # ⚠️ 프로모션은 "최소 2026-11-21까지" — 종료 후 카드 재확인 필요. 비용은 조회 시점 계산이라 과거 행에도 소급된다.
    "gpt-5.6-sol": {"input": 4.40, "output": 22.00},
    "gpt-5.6-terra": {"input": 2.20, "output": 13.20},
    "gpt-5.6-luna": {"input": 0.22, "output": 1.32},
    # Global CRIS(openai:global:global.openai.*)는 in-region보다 저렴한 별도 단가 — "-global" suffix 키.
    # ⚠️ 새 모델에 global 리전을 추가하면 여기 "-global" 키도 반드시 함께 추가할 것 —
    # 누락 시 get_pricing의 prefix fallback이 in-region 단가로 조용히 매칭돼 과대 산정됨.
    # ⚠️ 1P direct(openai:1p:*)는 여전히 base 키(in-region 단가) 공유 — 재노출 전 "-1p" 분리 필요.
    "gpt-5.6-sol-global": {"input": 4.00, "output": 20.00},  # 프로모션 (위 Sol 주석 참고)
    "gpt-5.6-terra-global": {"input": 2.00, "output": 12.00},
    "gpt-5.6-luna-global": {"input": 0.20, "output": 1.20},
    # GPT 6 Astra — v2.25.0 미확정 → v2.27.0에서 AWS 공식 모델 카드 단가 반영 (Standard, ≤272K).
    # In-Region·Geo CRIS(US)는 OpenAI 정가 +10%, Global CRIS는 정가. 3키는 항상 함께 둔다 —
    # 하나만 있으면 prefix fallback이 나머지 채널을 그 단가로 오매칭한다.
    "gpt-6-astra": {"input": 11.00, "output": 55.00},
    "gpt-6-astra-us": {"input": 11.00, "output": 55.00},
    "gpt-6-astra-global": {"input": 10.00, "output": 50.00},
    # GPT 6 Sol / Luna (v2.27.0 출시) — 출처: AWS Bedrock ListFoundationModelAgreementOffers
    # rate card (2026-09-23 조회; Sol offer-pycji3sz5gpcc, Luna offer-gmo53nkzc5or6).
    # input/output_tokens_standard = In-Region, Geo CRIS(US) / *_global_standard = Global CRIS.
    # 교차 검증: 같은 방식으로 조회한 Astra offer(offer-7epta7rbw5aws, standard 11/55, global 10/50)가
    # Astra 공식 모델 카드와 정확히 일치하고, 값은 OpenAI 정가(Sol $2/$10, Luna $0.10/$0.50)에
    # 문서화된 In-Region, Geo +10%를 더한 값과 같다. 모델 카드 미게시 → 게시되면 카드와 재대조 (ADR-028).
    # 3키는 항상 함께 둔다 — 하나만 있으면 prefix fallback이 나머지 채널을 그 단가로 오매칭한다.
    "gpt-6-sol": {"input": 2.20, "output": 11.00},
    "gpt-6-sol-us": {"input": 2.20, "output": 11.00},
    "gpt-6-sol-global": {"input": 2.00, "output": 10.00},
    "gpt-6-luna": {"input": 0.11, "output": 0.55},
    "gpt-6-luna-us": {"input": 0.11, "output": 0.55},
    "gpt-6-luna-global": {"input": 0.10, "output": 0.50},
}

# OpenAI pseudo-region(Bedrock CRIS) — 채널 단가가 in-region과 달라 base 키에 "-<region>"
# suffix를 붙여 분리한다("-global"/"-us"). in-region, 1P 채널은 suffix 없음.
_OPENAI_CRIS_REGIONS: tuple[str, ...] = ("global", "us")


def _normalize_key(model_id: str) -> str:
    """inference profile prefix / namespace prefix를 strip해 base 키로."""
    key = model_id
    if key.startswith("anthropic:"):
        key = key[len("anthropic:"):]
    openai_cris_suffix = ""
    if key.startswith("openai:"):
        # openai:<region>:<actual_id> → <actual_id>. pseudo-region "global"/"us"(Bedrock
        # CRIS)은 in-region과 단가가 달라 base 키에 "-<region>" suffix를 붙여 구분한다.
        segs = key.split(":", 2)
        if len(segs) == 3 and segs[1] in _OPENAI_CRIS_REGIONS:
            openai_cris_suffix = f"-{segs[1]}"
        key = segs[-1]
    parts = key.split(".", 1)
    if len(parts) == 2 and parts[0] in ("global", "us", "eu", "apac"):
        key = parts[1]
    if key.startswith("anthropic."):
        key = key[len("anthropic."):]
    if key.startswith("amazon."):
        key = key[len("amazon."):]
    if key.startswith("openai."):
        key = key[len("openai."):]
    if openai_cris_suffix:
        key = f"{key}{openai_cris_suffix}"
    return key


def get_pricing(model_id: str) -> Optional[dict[str, float]]:
    """model_id → {'input': USD_per_M, 'output': USD_per_M}. 미매칭 시 None."""
    key = _normalize_key(model_id)
    if key in PRICE_TABLE:
        return PRICE_TABLE[key]
    # prefix/suffix 매칭 fallback
    for k, v in PRICE_TABLE.items():
        if key.startswith(k) or k.startswith(key):
            return v
    return None


def estimate_cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    """입·출력 토큰 → USD. 단가 없으면 None."""
    p = get_pricing(model_id)
    if p is None:
        return None
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000.0
```

#### `t06-test-history` — `backend/tests/test_price_history.py`

<!-- plan-block id=t06-test-history path=backend/tests/test_price_history.py sha256=2e6e8737ef83b2d92a0a8357724503cfec533e43c5a2760188179401e297f77b -->
```python
"""price_history.py — time-effective price join, current/pending rows, verification state (v2.30.0, ADR-030).

All data lives in in-memory SQLite built by Base.metadata.create_all; no network. Every timestamp is a
timezone-aware datetime bound through the ORM.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from price_history import (
    as_utc,
    current_rows,
    last_finished_run,
    pending_rows,
    verification_of,
    with_row_cost,
)
from pricing_sources import EPOCH

T = datetime(2026, 9, 26, 3, 0, tzinfo=timezone.utc)
M = "global.anthropic.claude-sonnet-5"
M_TOKENS = 1_000_000


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    run = models.ProbeRun(prompt="p", status="completed", is_auto=1, created_at=T)
    session.add(run)
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _price(db, model_id, inp, out, effective_from, *, status="verified", observed_at=None,
           source_id="offer:offer-test", channel="global", family_key="claude-sonnet-5"):
    row = models.PriceHistory(
        model_id=model_id, family_key=family_key, channel=channel,
        input_per_mtok=inp, output_per_mtok=out, effective_from=effective_from,
        source_id=source_id, status=status, observed_at=observed_at,
    )
    db.add(row)
    db.commit()
    return row


def _probe(db, model_id, ts, input_tokens=M_TOKENS, output_tokens=M_TOKENS, *, status="success"):
    row = models.ProbeResult(
        run_id=1, model_id=model_id, model_name=f"label {model_id}", timestamp=ts, prompt="p",
        status=status, input_tokens=input_tokens, output_tokens=output_tokens,
    )
    db.add(row)
    db.commit()
    return row.id


def _costs(db):
    query, row_cost = with_row_cost(db.query(models.ProbeResult.id))
    return {pid: cost for pid, cost in query.add_columns(row_cost).order_by(models.ProbeResult.id).all()}


def test_row_exactly_at_effective_from_uses_the_new_price(db):
    _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    _price(db, M, 2.0, 10.0, T, observed_at=T)
    before = _probe(db, M, T - timedelta(seconds=1))
    at = _probe(db, M, T)
    after = _probe(db, M, T + timedelta(seconds=1))
    costs = _costs(db)
    assert costs[before] == pytest.approx(6.0)
    assert costs[at] == pytest.approx(12.0)  # effective_from is inclusive
    assert costs[after] == pytest.approx(12.0)


def test_model_without_price_rows_keeps_its_row_with_null_cost(db):
    _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    unknown = _probe(db, "mystery.model-v9", T)
    priced = _probe(db, M, T)
    costs = _costs(db)
    assert set(costs) == {unknown, priced}  # LEFT OUTER JOIN keeps the unpriced probe row
    assert costs[unknown] is None
    assert costs[priced] == pytest.approx(6.0)


def test_null_tokens_count_as_zero(db):
    _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    only_output = _probe(db, M, T, input_tokens=None, output_tokens=1000)
    no_tokens = _probe(db, M, T, input_tokens=None, output_tokens=None)
    costs = _costs(db)
    assert costs[only_output] == pytest.approx(0.005)
    assert costs[no_tokens] == 0.0  # priced model with no tokens costs 0, not NULL


def test_pending_and_rejected_rows_never_price_a_probe(db):
    _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    _price(db, M, 100.0, 500.0, T, status="pending_review", observed_at=T)
    _price(db, M, 50.0, 250.0, T, status="rejected", observed_at=T)
    pid = _probe(db, M, T + timedelta(hours=1))
    assert _costs(db)[pid] == pytest.approx(6.0)


def test_same_effective_from_higher_id_wins_without_duplicating_the_probe_row(db):
    _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    _price(db, M, 2.0, 10.0, T, observed_at=T)
    _price(db, M, 3.0, 15.0, T, observed_at=T)
    pid = _probe(db, M, T + timedelta(minutes=5))
    query, row_cost = with_row_cost(db.query(models.ProbeResult.id))
    rows = query.add_columns(row_cost).all()
    assert len(rows) == 1  # [T, T) interval of the lower id joins nothing
    assert rows[0] == (pid, pytest.approx(18.0))


def test_row_cost_is_a_python_float(db):
    _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    pid = _probe(db, M, T, input_tokens=3, output_tokens=7)
    cost = _costs(db)[pid]
    assert type(cost) is float
    assert cost == pytest.approx((3 * 1.0 + 7 * 5.0) / 1_000_000.0)


def test_row_cost_sql_is_portable_to_postgresql(db):
    query, row_cost = with_row_cost(db.query(models.ProbeResult.id))
    sql = str(query.add_columns(row_cost).statement.compile(dialect=postgresql.dialect()))
    assert "LEFT OUTER JOIN" in sql
    assert ("lead(price_history.effective_from) OVER (PARTITION BY price_history.model_id "
            "ORDER BY price_history.effective_from, price_history.id)") in sql
    assert "AS FLOAT)" in sql
    assert "coalesce(probe_results.input_tokens" in sql


def test_current_rows_returns_the_row_effective_at_now(db):
    seed = _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    verified = _price(db, M, 2.0, 10.0, T, observed_at=T)
    _price(db, M, 9.0, 9.0, T + timedelta(hours=1), status="pending_review", observed_at=T)
    assert current_rows(db, [M], now=T + timedelta(days=1))[M].id == verified.id
    assert current_rows(db, [M], now=T - timedelta(seconds=1))[M].id == seed.id
    assert current_rows(db, [M, "mystery.model-v9"], now=T)[M].id == verified.id
    assert "mystery.model-v9" not in current_rows(db, [M, "mystery.model-v9"], now=T)
    assert current_rows(db, []) == {}


def test_pending_rows_returns_the_most_recently_observed_pending_row(db):
    _price(db, M, 1.0, 5.0, EPOCH, status="seed")
    _price(db, M, 9.0, 45.0, T, status="pending_review", observed_at=T + timedelta(hours=12))
    _price(db, M, 8.0, 40.0, T + timedelta(hours=1), status="pending_review", observed_at=T + timedelta(hours=1))
    _price(db, M, 7.0, 35.0, T, status="rejected", observed_at=T + timedelta(days=1))
    got = pending_rows(db, [M])
    assert (got[M].input_per_mtok, got[M].output_per_mtok) == (9.0, 45.0)
    assert pending_rows(db, ["mystery.model-v9"]) == {}


def test_last_finished_run_ignores_running_rows_and_keeps_any_status(db):
    assert last_finished_run(db) is None
    db.add(models.PriceSyncRun(started_at=T, finished_at=T + timedelta(seconds=30), status="completed"))
    db.add(models.PriceSyncRun(started_at=T + timedelta(hours=12), finished_at=T + timedelta(hours=12, seconds=9),
                               status="failed"))
    db.add(models.PriceSyncRun(started_at=T + timedelta(hours=24), finished_at=None, status="running"))
    db.commit()
    run = last_finished_run(db)
    assert run.status == "failed"
    assert as_utc(run.started_at) == T + timedelta(hours=12)


def test_verification_states(db):
    run = models.PriceSyncRun(started_at=T, finished_at=T + timedelta(seconds=30), status="completed")
    seed = models.PriceHistory(status="seed", observed_at=None)
    seed_confirmed = models.PriceHistory(status="seed", observed_at=T)
    fresh = models.PriceHistory(status="verified", observed_at=T)
    old = models.PriceHistory(status="verified", observed_at=T - timedelta(seconds=1))
    assert verification_of(None, run) == "none"
    assert verification_of(seed, run) == "seed_only"
    assert verification_of(seed, None) == "seed_only"
    assert verification_of(seed_confirmed, run) == "verified"  # boundary: observed_at == run start
    assert verification_of(fresh, run) == "verified"
    assert verification_of(old, run) == "stale"
    assert verification_of(fresh, None) == "stale"  # no finished run yet


def test_cp_cells_go_stale_after_a_partial_run_where_only_the_anthropic_source_failed(db):
    t1, t2 = T, T + timedelta(hours=12)
    db.add(models.PriceSyncRun(started_at=t1, finished_at=t1 + timedelta(seconds=31), status="completed"))
    cp = _price(db, "anthropic:claude-sonnet-5", 2.0, 10.0, EPOCH, status="seed", observed_at=t1,
                source_id="anthropic-pricing", channel="cp")
    offer = _price(db, M, 2.0, 10.0, EPOCH, status="seed", observed_at=t1)
    # Run 2: offers answered (observed_at moves to t2), the Anthropic document failed (CP row untouched).
    db.add(models.PriceSyncRun(started_at=t2, finished_at=t2 + timedelta(seconds=25), status="partial"))
    offer.observed_at = t2
    db.commit()
    last = last_finished_run(db)
    assert verification_of(offer, last) == "verified"
    assert verification_of(cp, last) == "stale"


def test_as_utc_normalizes_naive_and_foreign_offsets():
    kst = timezone(timedelta(hours=9))
    assert as_utc(None) is None
    assert as_utc(datetime(2026, 9, 26, 3, 0)) == T
    assert as_utc(datetime(2026, 9, 26, 12, 0, tzinfo=kst)) == T
    assert as_utc(datetime(2026, 9, 26, 12, 0, tzinfo=kst)).tzinfo == timezone.utc
```

#### `t06-test-cost` — `backend/tests/test_cost_time_effective.py`

<!-- plan-block id=t06-test-cost path=backend/tests/test_cost_time_effective.py sha256=0d4bc07ab5435aec61ebbd54ad5a3229ddce8317247726b6afd6b7870331f394 -->
```python
"""Cost and efficiency endpoints with time-effective prices (v2.30.0, ADR-030).

/api/cost/summary, /api/cost/channel-compare, /api/cost/trend and /api/efficiency/score read the price that
was effective at each probe's timestamp from price_history. The equivalence test pins the new calculation
to a frozen copy of the v2.29.1 table (tests/_legacy_pricing_v2291.py) on the 44 channels whose price did
not change, and pins the 11 corrected channels (Bedrock Claude US x1.1, Nova 2.0 Lite) to official values.
All data lives in in-memory SQLite; no network.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import pricing_seed
from database import get_db
from pricing_sources import EPOCH, price_identity
from routers import cost as cost_router
from routers import efficiency as efficiency_router
from tests import _legacy_pricing_v2291 as legacy

NOW = datetime.now(timezone.utc)
HOUR = NOW.replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
CHANGE_AT = HOUR + timedelta(hours=1)  # verified price change inside the 24h window
A = ("global.anthropic.claude-sonnet-5", "Bedrock Claude Sonnet 5 (Global)")
UNKNOWN = ("mystery.model-v9", "Bedrock Mystery (Global)")
HIDDEN = ("openai:1p:gpt-5.4", "OpenAI GPT 5.4 (1P)")

# Production /api/models on 2026-09-26: the 55 active channels (CP ids come from discovery).
_CLAUDE = ("claude-fable-5-1", "claude-fable-5", "claude-opus-5-5", "claude-opus-5", "claude-opus-4-8",
           "claude-opus-4-7", "claude-opus-4-6-v1", "claude-sonnet-5", "claude-sonnet-4-6",
           "claude-haiku-4-5-20251001-v1:0")
BEDROCK_GLOBAL = [f"global.anthropic.{m}" for m in _CLAUDE]
BEDROCK_US = [f"us.anthropic.{m}" for m in _CLAUDE]
NOVA = "us.amazon.nova-2-lite-v1:0"
CP = [f"anthropic:claude-{m}" for m in ("fable-5-1", "fable-5", "opus-5-5", "opus-5", "opus-4-8", "opus-4-7",
                                        "sonnet-5", "sonnet-4-6", "haiku-4-5-20251001")]
OPENAI = (
    [f"openai:global:global.openai.gpt-6-{f}" for f in ("astra", "sol", "luna")]
    + [f"openai:us:us.openai.gpt-6-{f}" for f in ("astra", "sol", "luna")]
    + ["openai:us-west-2:openai.gpt-6-astra", "openai:us-east-1:openai.gpt-6-sol", "openai:us-east-1:openai.gpt-6-luna"]
    + [f"openai:global:global.openai.gpt-5.6-{f}" for f in ("sol", "terra", "luna")]
    + [f"openai:{r}:openai.gpt-5.6-{f}" for r in ("us-east-1", "us-east-2") for f in ("sol", "terra", "luna")]
    + [f"openai:us-west-2:openai.gpt-5.6-{f}" for f in ("terra", "luna")]
    + [f"openai:{r}:openai.gpt-5.5" for r in ("us-east-1", "us-east-2")]
    + [f"openai:{r}:openai.gpt-5.4" for r in ("us-east-1", "us-east-2", "us-west-2")]
)
ACTIVE_IDS = BEDROCK_GLOBAL + BEDROCK_US + [NOVA] + CP + OPENAI
UNCHANGED = BEDROCK_GLOBAL + CP + OPENAI
CORRECTED = {
    "us.anthropic.claude-fable-5-1": (11.0, 55.0),
    "us.anthropic.claude-fable-5": (11.0, 55.0),
    "us.anthropic.claude-opus-5-5": (4.4, 22.0),
    "us.anthropic.claude-opus-5": (5.5, 27.5),
    "us.anthropic.claude-opus-4-8": (5.5, 27.5),
    "us.anthropic.claude-opus-4-7": (5.5, 27.5),
    "us.anthropic.claude-opus-4-6-v1": (5.5, 27.5),
    "us.anthropic.claude-sonnet-5": (2.2, 11.0),
    "us.anthropic.claude-sonnet-4-6": (3.3, 16.5),
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.1, 5.5),
    NOVA: (0.33, 2.75),
}


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P)")
    with factory() as db:
        db.add(models.ProbeRun(prompt="p", status="completed", is_auto=1, created_at=NOW))
        db.commit()

    app = FastAPI()
    app.include_router(cost_router.router)
    app.include_router(efficiency_router.router)

    def db_override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    with TestClient(app) as client:
        yield engine, factory, client
    engine.dispose()


def _price(factory, model_id, inp, out, effective_from, *, status="verified"):
    ident = price_identity(model_id)
    with factory() as db:
        db.add(models.PriceHistory(
            model_id=model_id, family_key=ident.family_key if ident else "unknown",
            channel=ident.channel if ident else "global", input_per_mtok=inp, output_per_mtok=out,
            effective_from=effective_from, source_id="offer:offer-test", status=status,
            observed_at=None if status == "seed" else effective_from,
        ))
        db.commit()


def _probe(factory, model, ts, input_tokens, output_tokens, *, status="success", category="chat-short"):
    model_id, model_name = model
    with factory() as db:
        db.add(models.ProbeResult(
            run_id=1, model_id=model_id, model_name=model_name, timestamp=ts, prompt="p", status=status,
            input_tokens=input_tokens, output_tokens=output_tokens, total_latency_ms=1000.0, tps=50.0,
            category=category,
        ))
        db.commit()


def _price_change_dataset(factory):
    """A: $1/$5 seed, then $2/$10 from CHANGE_AT. One probe on each side, plus unpriced/error/hidden rows."""
    _price(factory, A[0], 1.0, 5.0, EPOCH, status="seed")
    _price(factory, A[0], 2.0, 10.0, CHANGE_AT)
    _price(factory, HIDDEN[0], 2.75, 16.5, EPOCH, status="seed")
    _probe(factory, A, HOUR + timedelta(minutes=10), 100_000, 100_000)       # old price: 0.6
    _probe(factory, A, CHANGE_AT + timedelta(hours=1, minutes=10), 100_000, 100_000)  # new price: 1.2
    _probe(factory, A, CHANGE_AT + timedelta(minutes=20), None, None, status="error")
    _probe(factory, UNKNOWN, HOUR + timedelta(minutes=15), 1_000, 2_000)
    _probe(factory, HIDDEN, HOUR + timedelta(minutes=15), 1_000_000, 1_000_000)


def test_summary_sums_each_probe_at_its_own_price(env):
    _, factory, client = env
    _price_change_dataset(factory)
    body = client.get("/api/cost/summary?window=24h").json()
    rows = {r["model_id"]: r for r in body["rows"]}
    assert set(rows) == {A[0], UNKNOWN[0]}  # error rows filtered, (1P) hidden
    assert rows[A[0]]["samples"] == 2
    assert rows[A[0]]["input_tokens"] == 200_000
    assert rows[A[0]]["cost_usd"] == pytest.approx(0.6 + 1.2)
    assert rows[A[0]]["avg_cost_per_call_usd"] == pytest.approx(0.9)
    assert rows[UNKNOWN[0]]["cost_usd"] is None  # no price row -> NULL, shown as "-"
    assert rows[UNKNOWN[0]]["avg_cost_per_call_usd"] is None
    assert body["total_cost_usd"] == pytest.approx(1.8)
    assert body["total_input_tokens"] == 201_000  # unpriced tokens still count
    assert body["total_output_tokens"] == 202_000
    assert [r["model_id"] for r in body["rows"]] == [A[0], UNKNOWN[0]]


def test_channel_compare_adds_unpriced_models_as_zero(env):
    _, factory, client = env
    _price_change_dataset(factory)
    channels = {c["channel"]: c for c in client.get("/api/cost/channel-compare?window=24h").json()["channels"]}
    assert set(channels) == {"Bedrock Global", "Other"}
    assert channels["Bedrock Global"]["cost_usd"] == pytest.approx(1.8)
    assert channels["Bedrock Global"]["samples"] == 2
    assert channels["Other"]["cost_usd"] == 0.0
    assert channels["Other"]["input_tokens"] == 1_000


def test_trend_buckets_per_row_cost(env):
    _, factory, client = env
    _price_change_dataset(factory)
    body = client.get("/api/cost/trend?window=24h").json()
    assert body["bucket_minutes"] == 60
    points = [(p["bucket"], p["model_name"], p["cost_usd"]) for p in body["points"]]
    assert points == [
        (HOUR.isoformat(), A[1], pytest.approx(0.6)),
        ((HOUR + timedelta(hours=2)).isoformat(), A[1], pytest.approx(1.2)),
    ]  # unpriced model has no points, error and hidden rows are filtered


def test_efficiency_averages_priced_success_rows_only(env):
    _, factory, client = env
    _price_change_dataset(factory)
    got = {m["model_id"]: m for m in client.get("/api/efficiency/score?window=24h").json()["models"]}
    assert set(got) == {A[0], UNKNOWN[0]}
    assert got[A[0]]["samples"] == 3  # the error row counts as a sample, not as a cost
    assert got[A[0]]["success_rate"] == pytest.approx(0.6667)
    assert got[A[0]]["avg_cost_usd"] == pytest.approx(0.9)
    assert got[UNKNOWN[0]]["avg_cost_usd"] is None
    assert got[UNKNOWN[0]]["components"]["cost"] is None


def test_efficiency_category_filter_still_applies(env):
    _, factory, client = env
    _price(factory, A[0], 1.0, 5.0, EPOCH, status="seed")
    _probe(factory, A, HOUR, 100_000, 100_000, category="reasoning")
    _probe(factory, A, HOUR, 200_000, 200_000, category="translate")
    got = client.get("/api/efficiency/score?window=24h&category=reasoning").json()["models"]
    assert [(m["model_id"], m["samples"], m["avg_cost_usd"]) for m in got] == [(A[0], 1, pytest.approx(0.6))]


def test_seeded_costs_match_v2291_on_unchanged_channels_and_fix_the_11_corrected_ones(env):
    engine, factory, client = env
    active = {mid: price_identity(mid) for mid in ACTIVE_IDS}
    assert len(active) == 55 and all(active.values()), [m for m, i in active.items() if i is None]
    assert len(UNCHANGED) == 44 and len(CORRECTED) == 11
    pricing_seed.ensure_seed(engine, active)
    in_tok, out_tok = 12_345, 6_789
    for mid in ACTIVE_IDS:
        _probe(factory, (mid, f"label {mid}"), NOW - timedelta(hours=1), in_tok, out_tok)

    rows = {r["model_id"]: r["cost_usd"] for r in client.get("/api/cost/summary?window=24h").json()["rows"]}
    assert set(rows) == set(ACTIVE_IDS)
    for mid in UNCHANGED:
        assert type(rows[mid]) is float, mid
        assert rows[mid] == pytest.approx(legacy.estimate_cost_usd(mid, in_tok, out_tok), rel=1e-12), mid
    for mid, (inp, out) in CORRECTED.items():
        assert rows[mid] == pytest.approx((in_tok * inp + out_tok * out) / 1_000_000.0, rel=1e-12), mid
        assert rows[mid] != pytest.approx(legacy.estimate_cost_usd(mid, in_tok, out_tok), rel=1e-6), mid
```

#### `t06-tests` — `@scratch/patches/t06-tests.patch`

<!-- plan-block id=t06-tests path=@scratch/patches/t06-tests.patch sha256=5433a7a059a805278b2eb318f1561f2066657ca0e6b2639a0adedd6e2f70c979 -->
```diff
diff --git a/backend/tests/test_fable51_catalog.py b/backend/tests/test_fable51_catalog.py
index cbc0627..4fab417 100644
--- a/backend/tests/test_fable51_catalog.py
+++ b/backend/tests/test_fable51_catalog.py
@@ -1,8 +1,11 @@
 """Claude Fable 5.1 카탈로그 편입 (v2.22.0) — 3채널 등록·단가·substring 충돌·패리티 스위치 검증."""
 
-import pricing
+import pytest
+
+import pricing_seed
 import prober
 from parity.catalog import is_applicable, is_reasoning_capable, supports_forced_tool_choice
+from pricing_sources import ANTHROPIC_SOURCE_ID, price_identity
 from routers.reliability import _LABEL_RE
 
 
@@ -32,9 +35,14 @@ def test_discovery_substring_does_not_mislabel_fable51_as_fable5():
 
 
 def test_pricing_all_three_channels():
-    expected = {"input": 10.0, "output": 50.0}
+    # v2.30.0: per-model_id seed rows (ADR-030). Global and CP are $10/$50, Bedrock US is Global x1.1.
     for mid in ("global.anthropic.claude-fable-5-1", "us.anthropic.claude-fable-5-1", "anthropic:claude-fable-5-1"):
-        assert pricing.get_pricing(mid) == expected, mid
+        assert price_identity(mid).family_key == "claude-fable-5-1", mid
+    assert pricing_seed.SEED["global.anthropic.claude-fable-5-1"][:2] == pytest.approx((10.0, 50.0))
+    assert pricing_seed.SEED["us.anthropic.claude-fable-5-1"][:2] == pytest.approx((11.0, 55.0))
+    assert pricing_seed.CP_SEED["claude-fable-5-1"] == (10.0, 50.0, ANTHROPIC_SOURCE_ID)
+    # substring prefix collision (fable-5 ⊂ fable-5-1) must not reach the price identity either
+    assert price_identity("anthropic:claude-fable-5").family_key == "claude-fable-5"
 
 
 def test_reasoning_and_parity_flags():
diff --git a/backend/tests/test_openai_pricing.py b/backend/tests/test_openai_pricing.py
index 7f0dd17..144820b 100644
--- a/backend/tests/test_openai_pricing.py
+++ b/backend/tests/test_openai_pricing.py
@@ -1,88 +1,77 @@
-"""OpenAI pricing normalization + cost estimation."""
-import pricing
+"""OpenAI channel price identity + seed prices + cost channel split.
+
+v2.30.0 (ADR-030): backend/pricing.py (PRICE_TABLE, _normalize_key prefix fallback, estimate_cost_usd) is gone.
+Prices are stored per model_id in price_history, so every channel needs its own classification
+(pricing_sources.price_identity) and its own seed row (pricing_seed.SEED). Per-row cost math is covered by
+test_price_history.py and test_cost_time_effective.py.
+"""
+import pytest
+
+import pricing_seed
+from pricing_sources import active_channels, price_identity
 from routers.cost import _channel
 
 
-def test_normalize_openai_key():
-    assert pricing._normalize_key("openai:us-east-1:openai.gpt-5.4") == "gpt-5.4"
-    assert pricing._normalize_key("openai:us-east-2:openai.gpt-5.5") == "gpt-5.5"
+def _seed(model_id):
+    return pytest.approx(pricing_seed.SEED[model_id][:2])
 
 
-def test_normalize_openai_global_key():
-    # Bedrock global CRIS는 in-region과 단가가 달라 "-global" suffix 키로 분리 (v2.20.0).
-    assert pricing._normalize_key("openai:global:global.openai.gpt-5.6-sol") == "gpt-5.6-sol-global"
-    assert pricing._normalize_key("openai:us-east-1:openai.gpt-5.6-sol") == "gpt-5.6-sol"
-    # Claude의 global. 프로파일은 종전대로 base 키로 collapse (suffix 미부여).
-    assert pricing._normalize_key("global.anthropic.claude-opus-5") == "claude-opus-5"
+def test_openai_channels_classify_per_channel():
+    assert price_identity("openai:us-east-1:openai.gpt-5.4").channel == "inregion:us-east-1"
+    assert price_identity("openai:us-east-2:openai.gpt-5.5").channel == "inregion:us-east-2"
+    assert price_identity("openai:global:global.openai.gpt-5.6-sol").channel == "global"
+    assert price_identity("openai:us:us.openai.gpt-6-astra").channel == "us"
+    assert price_identity("openai:us-west-2:openai.gpt-6-astra").channel == "inregion:us-west-2"
+    # Global/US CRIS and in-region share one family (one table row), never a "-global" key.
+    assert {price_identity(m).family_key for m in (
+        "openai:global:global.openai.gpt-5.6-sol", "openai:us-east-1:openai.gpt-5.6-sol",
+    )} == {"gpt-5.6-sol"}
+    assert price_identity("openai:global:global.openai.gpt-5.6-sol").source_ref == "openai.gpt-5.6-sol"
 
 
-def test_normalize_openai_us_cris_key():
-    # US CRIS(pseudo-region "us")도 채널 단가 분리 대상 — "-us" suffix (v2.25.0).
-    assert pricing._normalize_key("openai:us:us.openai.gpt-6-astra") == "gpt-6-astra-us"
-    assert pricing._normalize_key("openai:global:global.openai.gpt-6-astra") == "gpt-6-astra-global"
-    assert pricing._normalize_key("openai:us-west-2:openai.gpt-6-astra") == "gpt-6-astra"
-    # in-region, 1P 키는 suffix 없음 — 회귀 방지.
-    assert pricing._normalize_key("openai:us-east-1:openai.gpt-5.6-sol") == "gpt-5.6-sol"
-    assert pricing._normalize_key("openai:1p:gpt-5.4") == "gpt-5.4"
+def test_dormant_1p_channel_is_not_priced():
+    # 1P direct is hidden and dormant (v2.19.1); it must not borrow the in-region price any more.
+    assert "openai:1p:gpt-5.4" not in pricing_seed.SEED
+    assert active_channels({"openai:1p:gpt-5.4": "OpenAI GPT 5.4 (1P)"}, ["(1P)"]) == {}
 
 
 def test_gpt6_astra_official_pricing_per_channel():
-    """GPT 6 Astra — v2.25.0 미확정(None) → v2.27.0 AWS 공식 모델 카드 단가 (Standard, ≤272K).
+    """In-Region, Geo CRIS(US) = OpenAI list +10% ($11/$55), Global CRIS = list ($10/$50)."""
+    assert _seed("openai:us-west-2:openai.gpt-6-astra") == (11.0, 55.0)
+    assert _seed("openai:us:us.openai.gpt-6-astra") == (11.0, 55.0)
+    assert _seed("openai:global:global.openai.gpt-6-astra") == (10.0, 50.0)
 
-    In-Region·Geo CRIS(US)는 OpenAI 정가 +10%($11/$55), Global CRIS는 정가($10/$50).
-    """
-    assert pricing.get_pricing("openai:us-west-2:openai.gpt-6-astra") == {"input": 11.0, "output": 55.0}
-    assert pricing.get_pricing("openai:us:us.openai.gpt-6-astra") == {"input": 11.0, "output": 55.0}
-    assert pricing.get_pricing("openai:global:global.openai.gpt-6-astra") == {"input": 10.0, "output": 50.0}
-    # 1M in + 1M out = $11 + $55
-    assert pricing.estimate_cost_usd("openai:us-west-2:openai.gpt-6-astra", 1_000_000, 1_000_000) == 66.0
 
-
-def test_normalize_gpt6_sol_luna_keys():
-    # GPT 6 Sol/Luna도 Astra와 같은 3키 규칙 — Global/US CRIS는 suffix, Mantle 인리전은 base 키.
+def test_gpt6_sol_luna_seed_per_channel():
     for fam in ("sol", "luna"):
-        assert pricing._normalize_key(f"openai:us-east-1:openai.gpt-6-{fam}") == f"gpt-6-{fam}"
-        assert pricing._normalize_key(f"openai:us:us.openai.gpt-6-{fam}") == f"gpt-6-{fam}-us"
-        assert pricing._normalize_key(f"openai:global:global.openai.gpt-6-{fam}") == f"gpt-6-{fam}-global"
-        # 정규화된 키가 PRICE_TABLE에 정확히 존재해야 prefix fallback을 타지 않는다.
-        for suffix in ("", "-us", "-global"):
-            assert f"gpt-6-{fam}{suffix}" in pricing.PRICE_TABLE
-
-
-def test_estimate_cost_gpt6_sol_luna():
-    # Sol us-east-1: 1M in @2.20 + 1M out @11.00 = 13.20
-    assert abs(pricing.estimate_cost_usd("openai:us-east-1:openai.gpt-6-sol", 1_000_000, 1_000_000) - 13.20) < 1e-9
-    # Luna Global: 2M in @0.10 + 500K out @0.50 = 0.20 + 0.25 = 0.45
-    assert abs(pricing.estimate_cost_usd("openai:global:global.openai.gpt-6-luna", 2_000_000, 500_000) - 0.45) < 1e-9
-
-
-def test_get_pricing_openai():
-    assert pricing.get_pricing("openai:us-east-1:openai.gpt-5.4") == {"input": 2.75, "output": 16.5}
-    assert pricing.get_pricing("openai:us-east-2:openai.gpt-5.5") == {"input": 5.5, "output": 33.0}
-
-
-def test_get_pricing_gpt56_global_vs_in_region():
-    # 공식 모델 카드 (Standard tier, short context) — global CRIS가 in-region보다 저렴.
-    # in-region은 2026-07-30 인하 반영 (Luna -80%, Terra -20%, Sol 불변).
-    # v2.28.1: GPT-5.6 Sol 프로모션 단가 (AWS 카드 + agreement offers, 최소 2026-11-21까지)
-    assert pricing.get_pricing("openai:global:global.openai.gpt-5.6-sol") == {"input": 4.0, "output": 20.0}
-    assert pricing.get_pricing("openai:us-east-1:openai.gpt-5.6-sol") == {"input": 4.4, "output": 22.0}
-    assert pricing.get_pricing("openai:global:global.openai.gpt-5.6-terra") == {"input": 2.0, "output": 12.0}
-    assert pricing.get_pricing("openai:us-east-2:openai.gpt-5.6-terra") == {"input": 2.2, "output": 13.2}
-    assert pricing.get_pricing("openai:global:global.openai.gpt-5.6-luna") == {"input": 0.2, "output": 1.2}
-    assert pricing.get_pricing("openai:us-west-2:openai.gpt-5.6-luna") == {"input": 0.22, "output": 1.32}
-
-
-def test_estimate_cost_openai():
-    # 1M input @2.75 + 1M output @16.5 = 19.25
-    assert pricing.estimate_cost_usd("openai:us-east-1:openai.gpt-5.4", 1_000_000, 1_000_000) == 19.25
-
-
-def test_existing_pricing_unbroken():
-    assert pricing.get_pricing("us.anthropic.claude-fable-5") == {"input": 10.0, "output": 50.0}
-    # Opus 4.8은 $5/$25 — 2026-07-24 공식 가격 확인 (기존 $15/$75는 Opus 4.1 단가로 오기재였음)
-    assert pricing.get_pricing("anthropic:claude-opus-4-8") == {"input": 5.0, "output": 25.0}
-    assert pricing.get_pricing("global.anthropic.claude-opus-5") == {"input": 5.0, "output": 25.0}
+        for mid in (f"openai:us-east-1:openai.gpt-6-{fam}", f"openai:us:us.openai.gpt-6-{fam}",
+                    f"openai:global:global.openai.gpt-6-{fam}"):
+            assert price_identity(mid).family_key == f"gpt-6-{fam}", mid
+            assert mid in pricing_seed.SEED, mid
+
+
+def test_seed_openai_gpt54_gpt55():
+    assert _seed("openai:us-east-1:openai.gpt-5.4") == (2.75, 16.5)
+    assert _seed("openai:us-east-2:openai.gpt-5.5") == (5.5, 33.0)
+
+
+def test_seed_gpt56_global_vs_in_region():
+    # Global CRIS is cheaper than in-region; GPT-5.6 Sol carries the promotional price (v2.28.1).
+    assert _seed("openai:global:global.openai.gpt-5.6-sol") == (4.0, 20.0)
+    assert _seed("openai:us-east-1:openai.gpt-5.6-sol") == (4.4, 22.0)
+    assert _seed("openai:global:global.openai.gpt-5.6-terra") == (2.0, 12.0)
+    assert _seed("openai:us-east-2:openai.gpt-5.6-terra") == (2.2, 13.2)
+    assert _seed("openai:global:global.openai.gpt-5.6-luna") == (0.2, 1.2)
+    assert _seed("openai:us-west-2:openai.gpt-5.6-luna") == (0.22, 1.32)
+
+
+def test_existing_claude_seed_unbroken():
+    # Bedrock US is Global x1.1 since v2.30.0 (the old table collapsed us. onto global.).
+    assert _seed("us.anthropic.claude-fable-5") == (11.0, 55.0)
+    assert _seed("global.anthropic.claude-opus-5") == (5.0, 25.0)
+    # Opus 4.8 is $5/$25 (2026-07-24 official check; $15/$75 was the Opus 4.1 price).
+    assert pricing_seed.CP_SEED["claude-opus-4-8"][:2] == pytest.approx((5.0, 25.0))
+    assert price_identity("anthropic:claude-opus-4-8").family_key == "claude-opus-4-8"
 
 
 def test_channel_openai():
diff --git a/backend/tests/test_opus55_gpt6_catalog.py b/backend/tests/test_opus55_gpt6_catalog.py
index 5644536..614bae4 100644
--- a/backend/tests/test_opus55_gpt6_catalog.py
+++ b/backend/tests/test_opus55_gpt6_catalog.py
@@ -10,9 +10,12 @@
   In-Region, US CRIS는 Sol $2.20/$11, Luna $0.11/$0.55, Global CRIS는 Sol $2/$10, Luna $0.10/$0.50.
 """
 
-import pricing
+import pytest
+
+import pricing_seed
 import prober
 from parity.catalog import is_reasoning_capable, supports_forced_tool_choice
+from pricing_sources import price_identity
 from routers.reliability import _LABEL_RE
 
 # 2026-09-23 CP on AWS /v1/models 실측 순서 그대로 — 점 버전이 base 버전보다 먼저 온다.
@@ -79,11 +82,15 @@ def test_date_suffix_is_not_a_point_release():
 
 
 def test_opus55_pricing_all_three_channels_not_opus5_fallback():
-    expected = {"input": 4.0, "output": 20.0}
+    # v2.30.0: exact per-model_id seed rows, no prefix fallback (ADR-030). Bedrock US is Global x1.1.
     for mid in ("global.anthropic.claude-opus-5-5", "us.anthropic.claude-opus-5-5", "anthropic:claude-opus-5-5"):
-        assert pricing.get_pricing(mid) == expected, mid
-    # Opus 5는 불변
-    assert pricing.get_pricing("anthropic:claude-opus-5") == {"input": 5.0, "output": 25.0}
+        assert price_identity(mid).family_key == "claude-opus-5-5", mid
+    assert pricing_seed.SEED["global.anthropic.claude-opus-5-5"][:2] == pytest.approx((4.0, 20.0))
+    assert pricing_seed.SEED["us.anthropic.claude-opus-5-5"][:2] == pytest.approx((4.4, 22.0))
+    assert pricing_seed.CP_SEED["claude-opus-5-5"][:2] == pytest.approx((4.0, 20.0))
+    # Opus 5는 불변 — CP id claude-opus-5는 Opus 5.5가 아니라 Opus 5로 분류된다
+    assert price_identity("anthropic:claude-opus-5").family_key == "claude-opus-5"
+    assert pricing_seed.CP_SEED["claude-opus-5"][:2] == pytest.approx((5.0, 25.0))
 
 
 def test_opus55_reasoning_and_forced_tool_choice_flags():
@@ -143,17 +150,18 @@ def test_gpt6_sol_luna_pricing_per_channel_and_never_matches_astra():
     }
     assert sorted(expected) == sorted(_GPT6_SOL_LUNA_KEYS)
     astra_prices = [
-        pricing.get_pricing(mid)
+        pricing_seed.SEED[mid][:2]
         for mid in (
             "openai:global:global.openai.gpt-6-astra",
             "openai:us:us.openai.gpt-6-astra",
             "openai:us-west-2:openai.gpt-6-astra",
         )
     ]
-    assert all(p is not None for p in astra_prices)
     for mid, price in expected.items():
-        assert pricing.get_pricing(mid) == price, mid
-        assert pricing.get_pricing(mid) not in astra_prices, mid
+        seeded = pricing_seed.SEED[mid][:2]
+        assert seeded == pytest.approx((price["input"], price["output"])), mid
+        assert seeded not in astra_prices, mid
+        assert price_identity(mid).family_key != "gpt-6-astra", mid
 
 
 def test_gpt6_openai_reasoning_markers_stay_excluded():
```

#### `t06-routers` — `@scratch/patches/t06-routers.patch`

<!-- plan-block id=t06-routers path=@scratch/patches/t06-routers.patch sha256=e94489d1ae39fdd536889a7b03933b6239cc9f5a32eb04745975e650325a544d -->
```diff
diff --git a/backend/routers/cost.py b/backend/routers/cost.py
index 4034c37..96f1339 100644
--- a/backend/routers/cost.py
+++ b/backend/routers/cost.py
@@ -1,5 +1,8 @@
 """Cost Dashboard router - 토큰 단가 × 입출력 적산으로 비용 통계.
 
+v2.30.0 (ADR-030): 단가는 price_history에서 각 프로브 시각에 유효했던 값을 행 단위로 조인한다
+(price_history.with_row_cost). 단가 행이 없는 모델은 비용 NULL, 토큰 합계에는 포함.
+
 Endpoints:
   GET /api/cost/summary?window=24h     - 모델별 비용 합계 + total
   GET /api/cost/channel-compare?window=24h - Bedrock vs Anthropic CP on AWS 채널 비교
@@ -21,7 +24,7 @@ from fastapi import Depends
 from database import get_db
 from models import ProbeResult
 from visibility import hidden_patterns
-from pricing import estimate_cost_usd
+from price_history import as_utc, with_row_cost
 
 logger = logging.getLogger(__name__)
 router = APIRouter(prefix="/api/cost", tags=["cost"])
@@ -80,7 +83,7 @@ def get_cost_summary(
 ):
     """모델별 비용 합계."""
     since = datetime.now(timezone.utc) - _parse_window(window)
-    rows = (
+    query, row_cost = with_row_cost(
         db.query(
             ProbeResult.model_id,
             ProbeResult.model_name,
@@ -88,6 +91,12 @@ def get_cost_summary(
             func.coalesce(func.sum(ProbeResult.input_tokens), 0).label("in_tok"),
             func.coalesce(func.sum(ProbeResult.output_tokens), 0).label("out_tok"),
         )
+    )
+    rows = (
+        query.add_columns(
+            func.sum(row_cost).label("cost"),
+            func.count(row_cost).label("priced"),
+        )
         .filter(ProbeResult.timestamp >= since)
         .filter(ProbeResult.status == "success")
         .filter(*[~ProbeResult.model_name.contains(p) for p in hidden_patterns()])
@@ -100,7 +109,7 @@ def get_cost_summary(
     total_in = 0
     total_out = 0
     for r in rows:
-        cost = estimate_cost_usd(r.model_id, int(r.in_tok), int(r.out_tok))
+        cost = float(r.cost) if r.priced else None
         avg = (cost / r.samples) if cost is not None and r.samples > 0 else None
         if cost is not None:
             total_cost += cost
@@ -148,13 +157,19 @@ def get_channel_compare(
 ):
     """채널별 (Bedrock Global / US / Nova / Anthropic CP) 합계."""
     since = datetime.now(timezone.utc) - _parse_window(window)
-    rows = (
+    query, row_cost = with_row_cost(
         db.query(
             ProbeResult.model_id,
             func.count(ProbeResult.id).label("samples"),
             func.coalesce(func.sum(ProbeResult.input_tokens), 0).label("in_tok"),
             func.coalesce(func.sum(ProbeResult.output_tokens), 0).label("out_tok"),
         )
+    )
+    rows = (
+        query.add_columns(
+            func.sum(row_cost).label("cost"),
+            func.count(row_cost).label("priced"),
+        )
         .filter(ProbeResult.timestamp >= since)
         .filter(ProbeResult.status == "success")
         .filter(*[~ProbeResult.model_name.contains(p) for p in hidden_patterns()])
@@ -169,9 +184,8 @@ def get_channel_compare(
         slot["samples"] += int(r.samples)
         slot["input_tokens"] += int(r.in_tok)
         slot["output_tokens"] += int(r.out_tok)
-        cost = estimate_cost_usd(r.model_id, int(r.in_tok), int(r.out_tok))
-        if cost is not None:
-            slot["cost_usd"] += cost
+        if r.priced:  # 단가 없는 모델은 0으로 더한다 (현행 유지)
+            slot["cost_usd"] += float(r.cost)
 
     channels = [
         ChannelRow(
@@ -210,15 +224,15 @@ def get_cost_trend(
     since = datetime.now(timezone.utc) - delta
     bucket_min = 60 if delta >= timedelta(hours=12) else 5
 
-    # date_trunc를 사용하지 않고 Python으로 bucket 계산 (DB-portable).
-    rows = (
+    # date_trunc를 사용하지 않고 Python으로 bucket 계산 (DB-portable). 비용은 행 단위 시점 단가.
+    query, row_cost = with_row_cost(
         db.query(
-            ProbeResult.model_id,
             ProbeResult.model_name,
             ProbeResult.timestamp,
-            ProbeResult.input_tokens,
-            ProbeResult.output_tokens,
         )
+    )
+    rows = (
+        query.add_columns(row_cost.label("cost"))
         .filter(ProbeResult.timestamp >= since)
         .filter(ProbeResult.status == "success")
         .filter(*[~ProbeResult.model_name.contains(p) for p in hidden_patterns()])
@@ -228,11 +242,11 @@ def get_cost_trend(
     bucket_seconds = bucket_min * 60
     points_map: dict[tuple[str, str], float] = {}
     for r in rows:
-        cost = estimate_cost_usd(r.model_id, r.input_tokens or 0, r.output_tokens or 0)
-        if cost is None:
+        if r.cost is None:
             continue
-        # bucket start: floor timestamp to bucket_min
-        ts = r.timestamp.replace(microsecond=0)
+        cost = float(r.cost)
+        # bucket start: floor timestamp to bucket_min (SQLite는 naive로 돌려주므로 UTC로 고정)
+        ts = as_utc(r.timestamp).replace(microsecond=0)
         epoch = int(ts.timestamp())
         bucket_epoch = (epoch // bucket_seconds) * bucket_seconds
         bucket_iso = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc).isoformat()
diff --git a/backend/routers/efficiency.py b/backend/routers/efficiency.py
index dc0e24e..4b90c43 100644
--- a/backend/routers/efficiency.py
+++ b/backend/routers/efficiency.py
@@ -24,7 +24,7 @@ from sqlalchemy.orm import Session
 from database import get_db
 from models import ProbeResult
 from visibility import visible_only
-from pricing import estimate_cost_usd
+from price_history import with_row_cost
 
 logger = logging.getLogger(__name__)
 router = APIRouter(prefix="/api/efficiency", tags=["efficiency"])
@@ -109,15 +109,15 @@ def get_efficiency_score(
     category 미지정 시 전체. 지정 시 그 카테고리만 (공정 비교 권장: 같은 prompt 기준).
     """
     since = datetime.now(timezone.utc) - _parse_window(window)
-    q = visible_only(db.query(ProbeResult), ProbeResult.model_name).filter(
-        ProbeResult.timestamp >= since)
+    q, row_cost = with_row_cost(visible_only(db.query(ProbeResult), ProbeResult.model_name))
+    q = q.add_columns(row_cost.label("row_cost")).filter(ProbeResult.timestamp >= since)
     if category:
         q = q.filter(ProbeResult.category == category)
     rows = q.all()
 
-    # Aggregate per model
+    # Aggregate per model — 비용은 각 프로브 시각의 단가(row_cost, 단가 없으면 None)
     agg: dict[str, dict] = {}
-    for r in rows:
+    for r, cost in rows:
         a = agg.setdefault(
             r.model_id,
             {
@@ -143,9 +143,8 @@ def get_efficiency_score(
                 a["latency"].append(float(r.total_latency_ms))
             if r.tps is not None:
                 a["tps"].append(float(r.tps))
-            cost = estimate_cost_usd(r.model_id, r.input_tokens or 0, r.output_tokens or 0)
             if cost is not None:
-                a["costs"].append(cost)
+                a["costs"].append(float(cost))
 
     # 모델별 평균 계산
     per_model: list[dict] = []
```

### Task 7 blocks

#### `t07-dataset` — `backend/tests/_pricing_dataset.py`

<!-- plan-block id=t07-dataset path=backend/tests/_pricing_dataset.py sha256=e4210ee2735de9d973971084b2d85cea8a03b82588f56b03abf958e29f0127a7 -->
```python
"""Shared golden dataset for the pricing payload and export tests (v2.30.0).

load() writes a small price_history/price_sync_runs set; EXPECTED_PAYLOAD is the exact build_pricing_payload
result for it with OFFICIAL_PAGES and PRICE_NOTES pinned to the copies below. Offer ids other than the
spec's examples are fictional.
"""

from datetime import datetime, timedelta, timezone

import models
from pricing_sources import EPOCH, price_identity

NOW = datetime(2026, 9, 25, 16, 0, tzinfo=timezone.utc)
RUN1 = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
RUN2 = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)

OPUS = "offer:offer-7sp77cpl4rveu"
NOVA = "pricelist:USE1-Nova2.0Lite-input-tokens"
SOL = "offer:offer-gnqokrqqvdbgw"
TERRA = "offer:offer-terra0example"
G55 = "offer:offer-gpt55example"
G54 = "offer:offer-5l5a5izq5fbec"

ACTIVE_IDS = [
    "anthropic:claude-opus-5-5",
    "global.anthropic.claude-opus-5-5",
    "us.anthropic.claude-opus-5-5",
    "us.amazon.nova-2-lite-v1:0",
    "openai:global:global.openai.gpt-6-luna",
    "openai:global:global.openai.gpt-5.6-sol",
    "openai:us-east-1:openai.gpt-5.6-sol",
    "openai:global:global.openai.gpt-5.6-terra",
    "openai:us-east-1:openai.gpt-5.6-terra",
    "openai:us-east-2:openai.gpt-5.6-terra",
    "openai:us-west-2:openai.gpt-5.6-terra",
    "openai:us-east-1:openai.gpt-5.5",
    "openai:us-west-2:openai.gpt-5.4",
    "openai:us-east-1:openai.gpt-5.4",
    "openai:us-east-2:openai.gpt-5.4",
]

OFFICIAL_PAGES = [
    {"slug": "bedrock-pricing", "title_en": "Amazon Bedrock pricing", "title_ko": "Amazon Bedrock 요금",
     "url": "https://aws.amazon.com/bedrock/pricing/"},
    {"slug": "model-card-openai-gpt-54", "title_en": "Amazon Bedrock model card, OpenAI GPT 5.4",
     "title_ko": "Amazon Bedrock 모델 카드, OpenAI GPT 5.4",
     "url": "https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html"},
]

SOL_NOTE = {
    "family_key": "gpt-5.6-sol", "kind": "promo", "min_until": "2026-11-21",
    "prior_price": {"in_region": {"input": 5.5, "output": 33}, "global": {"input": 5, "output": 30}},
    "text_ko": "프로모션 단가, 최소 2026-11-21까지",
    "text_en": "Promotional price, at least until 2026-11-21",
    "source": "manual_note",
}


def active():
    return {mid: price_identity(mid) for mid in ACTIVE_IDS}


def add_price(db, model_id, inp, out, *, effective_from=EPOCH, status="seed", observed_at=None, source_id):
    ident = price_identity(model_id)
    row = models.PriceHistory(
        model_id=model_id, family_key=ident.family_key if ident else "unknown",
        channel=ident.channel if ident else "global", input_per_mtok=inp, output_per_mtok=out,
        effective_from=effective_from, source_id=source_id, status=status, observed_at=observed_at,
    )
    db.add(row)
    db.flush()
    return row


def load(db):
    """Runs 1 and 2 finished; run 3 is still running and must be ignored. GPT 6 Luna has no price rows."""
    db.add(models.PriceSyncRun(id=1, started_at=RUN1, finished_at=RUN1 + timedelta(seconds=31), status="completed"))
    db.add(models.PriceSyncRun(id=2, started_at=RUN2, finished_at=RUN2 + timedelta(seconds=31), status="completed"))
    db.add(models.PriceSyncRun(id=3, started_at=NOW, finished_at=None, status="running"))
    add_price(db, "anthropic:claude-opus-5-5", 4.0, 20.0, observed_at=RUN2, source_id="anthropic-pricing")
    add_price(db, "global.anthropic.claude-opus-5-5", 4.0, 20.0, observed_at=RUN2, source_id=OPUS)
    add_price(db, "us.anthropic.claude-opus-5-5", 4.4, 22.0, observed_at=RUN2, source_id=OPUS)
    # Price List failed in run 2: Nova was last confirmed in run 1 -> stale.
    add_price(db, "us.amazon.nova-2-lite-v1:0", 0.33, 2.75, observed_at=RUN1,
              source_id=NOVA)
    add_price(db, "openai:global:global.openai.gpt-5.6-sol", 4.0, 20.0, observed_at=RUN2, source_id=SOL)
    add_price(db, "openai:global:global.openai.gpt-5.6-sol", 9.0, 45.0, effective_from=RUN2,
              status="pending_review", observed_at=RUN2, source_id=SOL)
    add_price(db, "openai:us-east-1:openai.gpt-5.6-sol", 4.4, 22.0, source_id=SOL)  # seed never confirmed
    add_price(db, "openai:global:global.openai.gpt-5.6-terra", 2.0, 12.0, observed_at=RUN2, source_id=TERRA)
    add_price(db, "openai:us-east-1:openai.gpt-5.6-terra", 2.2, 13.2, observed_at=RUN2, source_id=TERRA)
    add_price(db, "openai:us-east-2:openai.gpt-5.6-terra", 2.2, 13.2, observed_at=RUN2, source_id=TERRA)
    add_price(db, "openai:us-west-2:openai.gpt-5.6-terra", 2.2, 13.2, observed_at=RUN1, source_id=TERRA)
    add_price(db, "openai:us-west-2:openai.gpt-5.6-terra", 2.4, 14.4, effective_from=RUN2, status="verified",
              observed_at=RUN2, source_id=TERRA)
    add_price(db, "openai:us-east-1:openai.gpt-5.5", 5.5, 33.0, source_id=G55)
    for region in ("us-west-2", "us-east-2", "us-east-1"):
        add_price(db, f"openai:{region}:openai.gpt-5.4", 2.75, 16.5, observed_at=RUN2, source_id=G54)
    # Not in the active set: never shown.
    add_price(db, "us.anthropic.claude-opus-4-6-v1", 5.5, 27.5, observed_at=RUN2, source_id="offer:offer-hidden")
    add_price(db, "openai:us-east-2:openai.gpt-5.5", 5.5, 33.0, effective_from=RUN2, status="pending_review",
              observed_at=RUN2, source_id=G55)
    db.commit()


# ----------------------------------------------------------------- golden /api/pricing body for load()

OFFER_URL = "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html"
PRICE_LIST_URL = "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html"
ANTHROPIC_URL = "https://platform.claude.com/docs/en/about-claude/pricing#model-pricing"
R1 = "2026-09-24T15:00:00Z"
R2 = "2026-09-25T15:00:00Z"


def _cell(inp, out, model_ids, source_ids, footnotes, verification, observed_at, pending=None, regions=None):
    cell = {"regions": regions} if regions is not None else {}
    cell.update({
        "input": inp, "output": out, "model_ids": model_ids, "source_ids": source_ids, "footnotes": footnotes,
        "verification": verification, "observed_at": observed_at, "pending": pending,
    })
    return cell


def _family(family_key, family, provider, cp=None, global_=None, us=None, in_region=(), notes=()):
    return {"family_key": family_key, "family": family, "provider": provider,
            "tiers": {"cp": cp, "global": global_, "us": us, "in_region": list(in_region)}, "notes": list(notes)}


def _ref(n, rid, kind, title_en, title_ko, url, as_of):
    return {"n": n, "id": rid, "kind": kind, "title_en": title_en, "title_ko": title_ko, "url": url, "as_of": as_of}


EXPECTED_PAYLOAD = {
    "currency": "USD",
    "unit": "per_1m_tokens",
    "generated_at": "2026-09-25T16:00:00Z",
    "last_sync": {"id": 2, "started_at": R2, "finished_at": "2026-09-25T15:00:31Z", "status": "completed"},
    "pending_review": 1,  # the gpt-5.5 us-east-2 pending row is not in the active set
    "families": [
        _family("claude-opus-5-5", "Claude Opus 5.5", "anthropic",
                cp=_cell(4, 20, ["anthropic:claude-opus-5-5"], ["anthropic-pricing"], [1], "verified", R2),
                global_=_cell(4, 20, ["global.anthropic.claude-opus-5-5"], [OPUS], [2], "verified", R2),
                us=_cell(4.4, 22, ["us.anthropic.claude-opus-5-5"], [OPUS], [2], "verified", R2)),
        _family("nova-2-lite", "Nova 2.0 Lite", "amazon",
                us=_cell(0.33, 2.75, ["us.amazon.nova-2-lite-v1:0"], [NOVA], [3], "stale", R1)),
        _family("gpt-6-luna", "GPT 6 Luna", "openai"),
        _family("gpt-5.6-sol", "GPT 5.6 Sol", "openai",
                global_=_cell(4, 20, ["openai:global:global.openai.gpt-5.6-sol"], [SOL], [4], "verified", R2,
                              pending={"id": 6, "input": 9, "output": 45, "observed_at": R2}),
                in_region=[_cell(4.4, 22, ["openai:us-east-1:openai.gpt-5.6-sol"], [SOL], [4], "seed_only", None,
                                 regions=["us-east-1"])],
                notes=[SOL_NOTE]),
        _family("gpt-5.6-terra", "GPT 5.6 Terra", "openai",
                global_=_cell(2, 12, ["openai:global:global.openai.gpt-5.6-terra"], [TERRA], [5], "verified", R2),
                in_region=[
                    _cell(2.2, 13.2, ["openai:us-east-1:openai.gpt-5.6-terra", "openai:us-east-2:openai.gpt-5.6-terra"],
                          [TERRA], [5], "verified", R2, regions=["us-east-1", "us-east-2"]),
                    _cell(2.4, 14.4, ["openai:us-west-2:openai.gpt-5.6-terra"], [TERRA], [5], "verified", R2,
                          regions=["us-west-2"]),
                ]),
        _family("gpt-5.5", "GPT 5.5", "openai",
                in_region=[_cell(5.5, 33, ["openai:us-east-1:openai.gpt-5.5"], [G55], [6], "seed_only", None,
                                 regions=["us-east-1"])]),
        _family("gpt-5.4", "GPT 5.4", "openai",
                in_region=[_cell(2.75, 16.5, ["openai:us-east-1:openai.gpt-5.4", "openai:us-east-2:openai.gpt-5.4",
                                              "openai:us-west-2:openai.gpt-5.4"],
                                 [G54], [7], "verified", R2, regions=["us-east-1", "us-east-2", "us-west-2"])]),
    ],
    "models": {
        "anthropic:claude-opus-5-5": {"input": 4, "output": 20, "verification": "verified"},
        "global.anthropic.claude-opus-5-5": {"input": 4, "output": 20, "verification": "verified"},
        "openai:global:global.openai.gpt-5.6-sol": {"input": 4, "output": 20, "verification": "verified"},
        "openai:global:global.openai.gpt-5.6-terra": {"input": 2, "output": 12, "verification": "verified"},
        "openai:us-east-1:openai.gpt-5.4": {"input": 2.75, "output": 16.5, "verification": "verified"},
        "openai:us-east-1:openai.gpt-5.5": {"input": 5.5, "output": 33, "verification": "seed_only"},
        "openai:us-east-1:openai.gpt-5.6-sol": {"input": 4.4, "output": 22, "verification": "seed_only"},
        "openai:us-east-1:openai.gpt-5.6-terra": {"input": 2.2, "output": 13.2, "verification": "verified"},
        "openai:us-east-2:openai.gpt-5.4": {"input": 2.75, "output": 16.5, "verification": "verified"},
        "openai:us-east-2:openai.gpt-5.6-terra": {"input": 2.2, "output": 13.2, "verification": "verified"},
        "openai:us-west-2:openai.gpt-5.4": {"input": 2.75, "output": 16.5, "verification": "verified"},
        "openai:us-west-2:openai.gpt-5.6-terra": {"input": 2.4, "output": 14.4, "verification": "verified"},
        "us.amazon.nova-2-lite-v1:0": {"input": 0.33, "output": 2.75, "verification": "stale"},
        "us.anthropic.claude-opus-5-5": {"input": 4.4, "output": 22, "verification": "verified"},
    },
    "references": [
        _ref(1, "anthropic-pricing", "anthropic_doc",
             "Anthropic API pricing (Claude Platform on AWS uses standard pricing)",
             "Anthropic API 요금 (Claude Platform on AWS는 표준 요금)", ANTHROPIC_URL, "2026-09-25"),
        _ref(2, OPUS, "agreement_offer",
             "Amazon Bedrock agreement offer rate card, offer-7sp77cpl4rveu (Claude Opus 5.5)",
             "Amazon Bedrock 약정 오퍼 요금표, offer-7sp77cpl4rveu (Claude Opus 5.5)", OFFER_URL, "2026-09-25"),
        _ref(3, NOVA, "price_list",
             "AWS Price List API, AmazonBedrock usage type USE1-Nova2.0Lite-input-tokens (Nova 2.0 Lite)",
             "AWS Price List API, AmazonBedrock 사용 유형 USE1-Nova2.0Lite-input-tokens (Nova 2.0 Lite)",
             PRICE_LIST_URL, "2026-09-24"),
        _ref(4, SOL, "agreement_offer",
             "Amazon Bedrock agreement offer rate card, offer-gnqokrqqvdbgw (GPT 5.6 Sol)",
             "Amazon Bedrock 약정 오퍼 요금표, offer-gnqokrqqvdbgw (GPT 5.6 Sol)", OFFER_URL, "2026-09-25"),
        _ref(5, TERRA, "agreement_offer",
             "Amazon Bedrock agreement offer rate card, offer-terra0example (GPT 5.6 Terra)",
             "Amazon Bedrock 약정 오퍼 요금표, offer-terra0example (GPT 5.6 Terra)", OFFER_URL, "2026-09-25"),
        # only seed rows (observed_at NULL) cite it -> the seed check date
        _ref(6, G55, "agreement_offer",
             "Amazon Bedrock agreement offer rate card, offer-gpt55example (GPT 5.5)",
             "Amazon Bedrock 약정 오퍼 요금표, offer-gpt55example (GPT 5.5)", OFFER_URL, "2026-09-26"),
        _ref(7, G54, "agreement_offer",
             "Amazon Bedrock agreement offer rate card, offer-5l5a5izq5fbec (GPT 5.4)",
             "Amazon Bedrock 약정 오퍼 요금표, offer-5l5a5izq5fbec (GPT 5.4)", OFFER_URL, "2026-09-25"),
        _ref(8, "official:bedrock-pricing", "official_page", "Amazon Bedrock pricing", "Amazon Bedrock 요금",
             "https://aws.amazon.com/bedrock/pricing/", None),
        _ref(9, "official:model-card-openai-gpt-54", "official_page", "Amazon Bedrock model card, OpenAI GPT 5.4",
             "Amazon Bedrock 모델 카드, OpenAI GPT 5.4",
             "https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html", None),
        _ref(10, "note:gpt-5.6-sol", "manual_note", "Promotional price, at least until 2026-11-21",
             "프로모션 단가, 최소 2026-11-21까지", None, None),
    ],
    "disclaimer": {
        "en": "This price list is compiled automatically from public sources for reference only and is not an "
              "official AWS statement. Always confirm final prices on the official pricing pages.",
        "ko": "이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. "
              "최종 가격은 반드시 공식 사이트에서 확인하세요.",
    },
}
```

#### `t07-test-payload` — `backend/tests/test_pricing_payload.py`

<!-- plan-block id=t07-test-payload path=backend/tests/test_pricing_payload.py sha256=01125610c3978c2affcfc4718e10391f3e5d27b491adbb30b82a7adfd26c6c1b -->
```python
"""pricing_payload.build_pricing_payload — exact /api/pricing JSON on a small golden dataset (v2.30.0).

Dataset (tests/_pricing_dataset.py): Claude Opus 5.5 on three channels, a stale Nova row, GPT 6 Luna with no
price rows, GPT 5.6 Sol with a pending row and a seed-only in-region row, GPT 5.6 Terra whose us-west-2 price
differs from us-east-1/us-east-2, GPT 5.5 seed-only, GPT 5.4 on three equal regions, and rows for inactive
model_ids that must never appear. OFFICIAL_PAGES and PRICE_NOTES are pinned to test copies so the golden does
not depend on their production wording; DISCLAIMER is the spec text.
"""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import pricing_sources
from pricing_payload import build_pricing_payload, price_number, price_text
from tests import _pricing_dataset as ds
from tests._pricing_dataset import EXPECTED_PAYLOAD, OPUS, SOL


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setattr(pricing_sources, "OFFICIAL_PAGES", ds.OFFICIAL_PAGES)
    monkeypatch.setattr(pricing_sources, "PRICE_NOTES", [ds.SOL_NOTE])
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    ds.load(session)
    yield session
    session.close()
    engine.dispose()


def test_payload_matches_the_golden_exactly(db):
    assert build_pricing_payload(db, ds.active(), now=ds.NOW) == EXPECTED_PAYLOAD


def test_every_footnote_resolves_to_the_cited_source(db):
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    refs = {r["n"]: r["id"] for r in payload["references"]}
    assert sorted(refs) == list(range(1, len(refs) + 1))
    for family in payload["families"]:
        cells = [c for c in (family["tiers"][t] for t in ("cp", "global", "us")) if c] + family["tiers"]["in_region"]
        for cell in cells:
            assert [refs[n] for n in cell["footnotes"]] == cell["source_ids"]


def test_numbers_serialize_without_trailing_zeros():
    assert price_number(4.0) == 4 and isinstance(price_number(4.0), int)
    assert price_number(4.40) == 4.4
    assert price_number(4.0 * 1.1) == 4.4  # 4.4000000000000004
    assert price_number(0.1234567) == 0.123457
    assert price_text(4.4) == "4.4"
    assert price_text(0.11) == "0.11"
    assert price_text(20.0) == "20"
    assert price_text(0.00001) == "0.00001"


def test_promo_note_drops_once_the_prior_price_is_observed(db):
    ds.add_price(db, "openai:us-east-1:openai.gpt-5.6-sol", 5.5, 33.0, effective_from=ds.RUN2, status="verified",
                 observed_at=ds.RUN2, source_id=SOL)
    db.commit()
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    sol = next(f for f in payload["families"] if f["family_key"] == "gpt-5.6-sol")
    assert sol["notes"] == []
    assert [r["kind"] for r in payload["references"]].count("manual_note") == 0


def test_price_rows_effective_after_now_are_not_current_yet(db):
    ds.add_price(db, "us.anthropic.claude-opus-5-5", 5.0, 25.0, effective_from=ds.NOW + timedelta(hours=1),
                 status="verified", observed_at=ds.NOW, source_id=OPUS)
    db.commit()
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    assert payload["models"]["us.anthropic.claude-opus-5-5"]["input"] == 4.4


def test_empty_active_set_still_returns_the_fixed_sections(db):
    payload = build_pricing_payload(db, {}, now=ds.NOW)
    assert payload["families"] == [] and payload["models"] == {} and payload["pending_review"] == 0
    assert [r["kind"] for r in payload["references"]] == ["official_page", "official_page"]


def test_production_official_pages_and_note_are_listed_after_the_cited_sources(db, monkeypatch):
    monkeypatch.undo()  # production OFFICIAL_PAGES and PRICE_NOTES
    payload = build_pricing_payload(db, ds.active(), now=ds.NOW)
    kinds = [r["kind"] for r in payload["references"]]
    cited = kinds.count("agreement_offer") + kinds.count("price_list") + kinds.count("anthropic_doc")
    assert kinds[cited:] == ["official_page"] * 9 + ["manual_note"]
    assert {r["url"] for r in payload["references"] if r["kind"] == "official_page"} == {
        "https://aws.amazon.com/bedrock/pricing/",
        *(f"https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-{slug}.html" for slug in (
            "gpt-54", "gpt-55", "gpt-56-sol", "gpt-56-terra", "gpt-56-luna", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna")),
    }
    note = next(r for r in payload["references"] if r["kind"] == "manual_note")
    assert note["id"] == "note:gpt-5.6-sol" and note["url"] is None
```

#### `t07-test-export` — `backend/tests/test_pricing_export.py`

<!-- plan-block id=t07-test-export path=backend/tests/test_pricing_export.py sha256=9c03444ff81b396bc956c75f41e54d2a8bc19f03ec9669e60b49cccbc2b830d8 -->
```python
"""pricing_export — golden CSV, Markdown and JSON for the golden payload (v2.30.0).

The exports are pure functions of the /api/pricing payload: same order, same footnote numbers, disclaimer
first (and last in Markdown). tests/_pricing_dataset.EXPECTED_PAYLOAD is the input; its correctness against
the database is pinned by test_pricing_payload.py.
"""

import csv
import io
import json
from datetime import date

import pytest

from pricing_export import BOM, export_filename, to_csv, to_json, to_markdown
from tests._pricing_dataset import EXPECTED_PAYLOAD

GOLDEN_MD_KO = """> 이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요.

# 비용 단가

- 통화와 단위: USD, 1M 토큰당, 입력 / 출력
- 생성 시각: 2026-09-25T16:00:00Z
- 마지막 자동 확인: 2026-09-25T15:00:31Z (completed)
- 검토 대기: 1

## Anthropic Claude

| 모델 | Claude Platform on AWS | Global | US | In-Region |
|---|---|---|---|---|
| Claude Opus 5.5 | 4 / 20[^1] | 4 / 20[^2] | 4.4 / 22[^2] | — |

## Amazon Nova

| 모델 | Claude Platform on AWS | Global | US | In-Region |
|---|---|---|---|---|
| Nova 2.0 Lite | — | — | 0.33 / 2.75 (자동 확인 안 됨)[^3] | — |

## OpenAI

| 모델 | Claude Platform on AWS | Global | US | In-Region |
|---|---|---|---|---|
| GPT 6 Luna | — | — | — | — |
| GPT 5.6 Sol | — | 4 / 20 (검토 대기 9 / 45)[^4] | — | 4.4 / 22 us-east-1 (자동 확인 안 됨)[^4] |
| GPT 5.6 Terra | — | 2 / 12[^5] | — | 2.2 / 13.2 us-east-1, us-east-2[^5]<br>2.4 / 14.4 us-west-2[^5] |
| GPT 5.5 | — | — | — | 5.5 / 33 us-east-1 (자동 확인 안 됨)[^6] |
| GPT 5.4 | — | — | — | 2.75 / 16.5 us-east-1, us-east-2, us-west-2[^7] |

## 참고 사항

1. 단가는 USD, 1M 토큰당, Standard 등급 입력과 출력 기준이다.
2. Global 채널 단가는 같은 모델의 US, In-Region 채널과 다를 수 있다.
3. OpenAI는 입력 272K 이하 기준이다.
4. 캐시, batch, long-context, priority 단가는 포함하지 않는다.
5. 비용 화면은 각 프로브 시각의 단가로 계산한다.
6. 최종 가격은 공식 요금 페이지에서 확인한다[^8][^9].
7. GPT 5.6 Sol: 프로모션 단가, 최소 2026-11-21까지[^10]

## 참고 자료

[^1]: Anthropic API 요금 (Claude Platform on AWS는 표준 요금), https://platform.claude.com/docs/en/about-claude/pricing#model-pricing, 확인일 2026-09-25
[^2]: Amazon Bedrock 약정 오퍼 요금표, offer-7sp77cpl4rveu (Claude Opus 5.5), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, 확인일 2026-09-25
[^3]: AWS Price List API, AmazonBedrock 사용 유형 USE1-Nova2.0Lite-input-tokens (Nova 2.0 Lite), https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html, 확인일 2026-09-24
[^4]: Amazon Bedrock 약정 오퍼 요금표, offer-gnqokrqqvdbgw (GPT 5.6 Sol), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, 확인일 2026-09-25
[^5]: Amazon Bedrock 약정 오퍼 요금표, offer-terra0example (GPT 5.6 Terra), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, 확인일 2026-09-25
[^6]: Amazon Bedrock 약정 오퍼 요금표, offer-gpt55example (GPT 5.5), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, 확인일 2026-09-26
[^7]: Amazon Bedrock 약정 오퍼 요금표, offer-5l5a5izq5fbec (GPT 5.4), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, 확인일 2026-09-25
[^8]: Amazon Bedrock 요금, https://aws.amazon.com/bedrock/pricing/
[^9]: Amazon Bedrock 모델 카드, OpenAI GPT 5.4, https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html
[^10]: 수동 메모: 프로모션 단가, 최소 2026-11-21까지

> 이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요.
"""

GOLDEN_MD_EN = """> This price list is compiled automatically from public sources for reference only and is not an official AWS statement. Always confirm final prices on the official pricing pages.

# Unit prices

- Currency and unit: USD per 1M tokens, input / output
- Generated: 2026-09-25T16:00:00Z
- Last automatic check: 2026-09-25T15:00:31Z (completed)
- Pending review: 1

## Anthropic Claude

| Model | Claude Platform on AWS | Global | US | In-Region |
|---|---|---|---|---|
| Claude Opus 5.5 | 4 / 20[^1] | 4 / 20[^2] | 4.4 / 22[^2] | — |

## Amazon Nova

| Model | Claude Platform on AWS | Global | US | In-Region |
|---|---|---|---|---|
| Nova 2.0 Lite | — | — | 0.33 / 2.75 (not verified automatically)[^3] | — |

## OpenAI

| Model | Claude Platform on AWS | Global | US | In-Region |
|---|---|---|---|---|
| GPT 6 Luna | — | — | — | — |
| GPT 5.6 Sol | — | 4 / 20 (Pending review 9 / 45)[^4] | — | 4.4 / 22 us-east-1 (not verified automatically)[^4] |
| GPT 5.6 Terra | — | 2 / 12[^5] | — | 2.2 / 13.2 us-east-1, us-east-2[^5]<br>2.4 / 14.4 us-west-2[^5] |
| GPT 5.5 | — | — | — | 5.5 / 33 us-east-1 (not verified automatically)[^6] |
| GPT 5.4 | — | — | — | 2.75 / 16.5 us-east-1, us-east-2, us-west-2[^7] |

## Notes

1. Prices are in USD per 1M tokens, Standard tier input and output.
2. Global channel prices can differ from the US and In-Region channels of the same model.
3. OpenAI prices apply to inputs of 272K tokens or fewer.
4. Cache, batch, long-context and priority prices are not included.
5. The cost pages use the price in effect at each probe's time.
6. Confirm final prices on the official pricing pages[^8][^9].
7. GPT 5.6 Sol: Promotional price, at least until 2026-11-21[^10]

## References

[^1]: Anthropic API pricing (Claude Platform on AWS uses standard pricing), https://platform.claude.com/docs/en/about-claude/pricing#model-pricing, checked 2026-09-25
[^2]: Amazon Bedrock agreement offer rate card, offer-7sp77cpl4rveu (Claude Opus 5.5), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, checked 2026-09-25
[^3]: AWS Price List API, AmazonBedrock usage type USE1-Nova2.0Lite-input-tokens (Nova 2.0 Lite), https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html, checked 2026-09-24
[^4]: Amazon Bedrock agreement offer rate card, offer-gnqokrqqvdbgw (GPT 5.6 Sol), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, checked 2026-09-25
[^5]: Amazon Bedrock agreement offer rate card, offer-terra0example (GPT 5.6 Terra), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, checked 2026-09-25
[^6]: Amazon Bedrock agreement offer rate card, offer-gpt55example (GPT 5.5), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, checked 2026-09-26
[^7]: Amazon Bedrock agreement offer rate card, offer-5l5a5izq5fbec (GPT 5.4), https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html, checked 2026-09-25
[^8]: Amazon Bedrock pricing, https://aws.amazon.com/bedrock/pricing/
[^9]: Amazon Bedrock model card, OpenAI GPT 5.4, https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html
[^10]: Manual note: Promotional price, at least until 2026-11-21

> This price list is compiled automatically from public sources for reference only and is not an official AWS statement. Always confirm final prices on the official pricing pages.
"""

GOLDEN_CSV_KO = BOM + """# 이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요.
provider,family,channel,regions,model_ids,input_usd_per_1m,output_usd_per_1m,verification,observed_at,footnotes,source_ids
anthropic,Claude Opus 5.5,cp,,anthropic:claude-opus-5-5,4,20,verified,2026-09-25T15:00:00Z,1,anthropic-pricing
anthropic,Claude Opus 5.5,global,,global.anthropic.claude-opus-5-5,4,20,verified,2026-09-25T15:00:00Z,2,offer:offer-7sp77cpl4rveu
anthropic,Claude Opus 5.5,us,,us.anthropic.claude-opus-5-5,4.4,22,verified,2026-09-25T15:00:00Z,2,offer:offer-7sp77cpl4rveu
amazon,Nova 2.0 Lite,us,,us.amazon.nova-2-lite-v1:0,0.33,2.75,stale,2026-09-24T15:00:00Z,3,pricelist:USE1-Nova2.0Lite-input-tokens
openai,GPT 5.6 Sol,global,,openai:global:global.openai.gpt-5.6-sol,4,20,verified,2026-09-25T15:00:00Z,4,offer:offer-gnqokrqqvdbgw
openai,GPT 5.6 Sol,in_region,us-east-1,openai:us-east-1:openai.gpt-5.6-sol,4.4,22,seed_only,,4,offer:offer-gnqokrqqvdbgw
openai,GPT 5.6 Terra,global,,openai:global:global.openai.gpt-5.6-terra,2,12,verified,2026-09-25T15:00:00Z,5,offer:offer-terra0example
openai,GPT 5.6 Terra,in_region,us-east-1 us-east-2,openai:us-east-1:openai.gpt-5.6-terra openai:us-east-2:openai.gpt-5.6-terra,2.2,13.2,verified,2026-09-25T15:00:00Z,5,offer:offer-terra0example
openai,GPT 5.6 Terra,in_region,us-west-2,openai:us-west-2:openai.gpt-5.6-terra,2.4,14.4,verified,2026-09-25T15:00:00Z,5,offer:offer-terra0example
openai,GPT 5.5,in_region,us-east-1,openai:us-east-1:openai.gpt-5.5,5.5,33,seed_only,,6,offer:offer-gpt55example
openai,GPT 5.4,in_region,us-east-1 us-east-2 us-west-2,openai:us-east-1:openai.gpt-5.4 openai:us-east-2:openai.gpt-5.4 openai:us-west-2:openai.gpt-5.4,2.75,16.5,verified,2026-09-25T15:00:00Z,7,offer:offer-5l5a5izq5fbec

reference_n,reference_id,kind,title,url,as_of
1,anthropic-pricing,anthropic_doc,Anthropic API 요금 (Claude Platform on AWS는 표준 요금),https://platform.claude.com/docs/en/about-claude/pricing#model-pricing,2026-09-25
2,offer:offer-7sp77cpl4rveu,agreement_offer,"Amazon Bedrock 약정 오퍼 요금표, offer-7sp77cpl4rveu (Claude Opus 5.5)",https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html,2026-09-25
3,pricelist:USE1-Nova2.0Lite-input-tokens,price_list,"AWS Price List API, AmazonBedrock 사용 유형 USE1-Nova2.0Lite-input-tokens (Nova 2.0 Lite)",https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html,2026-09-24
4,offer:offer-gnqokrqqvdbgw,agreement_offer,"Amazon Bedrock 약정 오퍼 요금표, offer-gnqokrqqvdbgw (GPT 5.6 Sol)",https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html,2026-09-25
5,offer:offer-terra0example,agreement_offer,"Amazon Bedrock 약정 오퍼 요금표, offer-terra0example (GPT 5.6 Terra)",https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html,2026-09-25
6,offer:offer-gpt55example,agreement_offer,"Amazon Bedrock 약정 오퍼 요금표, offer-gpt55example (GPT 5.5)",https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html,2026-09-26
7,offer:offer-5l5a5izq5fbec,agreement_offer,"Amazon Bedrock 약정 오퍼 요금표, offer-5l5a5izq5fbec (GPT 5.4)",https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html,2026-09-25
8,official:bedrock-pricing,official_page,Amazon Bedrock 요금,https://aws.amazon.com/bedrock/pricing/,
9,official:model-card-openai-gpt-54,official_page,"Amazon Bedrock 모델 카드, OpenAI GPT 5.4",https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html,
10,note:gpt-5.6-sol,manual_note,"프로모션 단가, 최소 2026-11-21까지",,
"""


def test_markdown_golden_ko():
    assert to_markdown(EXPECTED_PAYLOAD, "ko") == GOLDEN_MD_KO


def test_markdown_golden_en():
    assert to_markdown(EXPECTED_PAYLOAD, "en") == GOLDEN_MD_EN


def test_csv_golden_ko():
    assert to_csv(EXPECTED_PAYLOAD, "ko") == GOLDEN_CSV_KO


def test_csv_en_changes_only_the_disclaimer_and_reference_titles():
    en = to_csv(EXPECTED_PAYLOAD, "en")
    first, rest = en.split("\n", 1)
    assert first == BOM + "# " + EXPECTED_PAYLOAD["disclaimer"]["en"]
    assert '2,offer:offer-7sp77cpl4rveu,agreement_offer,"Amazon Bedrock agreement offer rate card, ' in rest
    assert rest.split("\n\n")[0] == GOLDEN_CSV_KO.split("\n", 1)[1].split("\n\n")[0]  # price rows are language-neutral


def test_csv_parses_back_into_two_tables():
    text = to_csv(EXPECTED_PAYLOAD, "ko")
    lines = text.lstrip(BOM).split("\n")
    assert lines[0].startswith("# ")
    prices, references = "\n".join(lines[1:]).split("\n\n")
    rows = list(csv.DictReader(io.StringIO(prices)))
    assert len(rows) == 11  # one row per cell (tier element), empty cells have no row
    terra = [r for r in rows if r["family"] == "GPT 5.6 Terra" and r["channel"] == "in_region"]
    assert [(r["regions"], r["input_usd_per_1m"]) for r in terra] == [("us-east-1 us-east-2", "2.2"), ("us-west-2", "2.4")]
    refs = list(csv.DictReader(io.StringIO(references)))
    assert [int(r["reference_n"]) for r in refs] == list(range(1, 11))


def test_json_is_the_payload():
    text = to_json(EXPECTED_PAYLOAD)
    assert json.loads(text) == EXPECTED_PAYLOAD
    assert "이 가격표는" in text  # ensure_ascii=False keeps Korean readable
    assert text.endswith("}\n")


def test_filenames():
    assert export_filename("csv", date(2026, 9, 26)) == "llm-monitor-unit-prices-2026-09-26.csv"
    assert export_filename("md", date(2026, 9, 26)) == "llm-monitor-unit-prices-2026-09-26.md"
    assert export_filename("json", date(2026, 9, 26)) == "llm-monitor-unit-prices-2026-09-26.json"
    with pytest.raises(ValueError):
        export_filename("xlsx", date(2026, 9, 26))


def test_unknown_lang_is_rejected():
    with pytest.raises(ValueError):
        to_markdown(EXPECTED_PAYLOAD, "ja")
    with pytest.raises(ValueError):
        to_csv(EXPECTED_PAYLOAD, "ja")


def test_no_last_sync_and_no_pending_lines():
    payload = dict(EXPECTED_PAYLOAD, last_sync=None, pending_review=0)
    md = to_markdown(payload, "ko")
    assert "- 마지막 자동 확인: 없음\n" in md
    assert "- 검토 대기:" not in md
```

#### `t07-payload` — `backend/pricing_payload.py`

<!-- plan-block id=t07-payload path=backend/pricing_payload.py sha256=ab74e042e4a99473d00e6a3676910d12a71b6b688c01c6297cb513fc865b6e3f -->
```python
"""GET /api/pricing payload builder (v2.30.0, ADR-030) — pure function over price_history.

The backend decides every order and number; the frontend and the three export formats reuse them as-is:
- families: PROVIDER_ORDER (Anthropic Claude, Amazon Nova, OpenAI), then FAMILY_ORDER.
- tiers: always the four keys cp, global, us (object or null) and in_region (always a list). Channels of one
  tier with equal values (price, verification, pending value) form one element; in_region elements are
  ordered by region name.
- footnotes: walking the cells in display order, each source_id gets the next number the first time it is
  cited; the fixed official pages follow, and manual notes come last.
"""

from datetime import datetime
from decimal import Decimal
from typing import Mapping, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

import pricing_sources
from models import PriceHistory
from price_history import as_utc, current_rows, last_finished_run, pending_rows, verification_of
from pricing_seed import SEED_SOURCE_DATE
from pricing_sources import (
    ANTHROPIC_REFERENCE_URL, ANTHROPIC_SOURCE_ID, FAMILY_ORDER, OFFER_REFERENCE_URL, PRICELIST_REFERENCE_URL,
    PROVIDER_ORDER, PriceIdentity, note_source_id, official_source_id, region_of, tier_of,
)

ANTHROPIC_TITLE_EN = "Anthropic API pricing (Claude Platform on AWS uses standard pricing)"
ANTHROPIC_TITLE_KO = "Anthropic API 요금 (Claude Platform on AWS는 표준 요금)"

SINGLE_TIERS = ("cp", "global", "us")
_VERIFICATION_RANK = {"verified": 0, "stale": 1, "seed_only": 2, "none": 3}


def price_number(v: float):
    """At most 6 decimals, trailing zeros removed: 4.0 -> 4, 4.40 -> 4.4, 4.4000000000000004 -> 4.4."""
    d = Decimal(str(round(float(v), 6))).normalize()
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def price_text(v: float) -> str:
    """price_number as text for CSV/Markdown (never scientific notation): 4.4 -> "4.4", 1e-05 -> "0.00001"."""
    n = price_number(v)
    if isinstance(n, int):
        return str(n)
    return format(Decimal(str(n)), "f")


def iso_z(value: Optional[datetime]) -> Optional[str]:
    """UTC ISO-8601 with a Z suffix and whole seconds (2026-09-26T15:00:00Z)."""
    if value is None:
        return None
    return as_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _same_price(row: PriceHistory, prior: Mapping) -> bool:
    return (price_number(row.input_per_mtok), price_number(row.output_per_mtok)) == (
        price_number(prior["input"]), price_number(prior["output"]))


def _source_reference(source_id: str, families: list[str]) -> dict:
    names = ", ".join(families)
    if source_id.startswith("offer:"):
        offer_id = source_id[len("offer:"):]
        return {
            "kind": "agreement_offer",
            "title_en": f"Amazon Bedrock agreement offer rate card, {offer_id} ({names})",
            "title_ko": f"Amazon Bedrock 약정 오퍼 요금표, {offer_id} ({names})",
            "url": OFFER_REFERENCE_URL,
        }
    if source_id.startswith("pricelist:"):
        usagetype = source_id[len("pricelist:"):]
        return {
            "kind": "price_list",
            "title_en": f"AWS Price List API, AmazonBedrock usage type {usagetype} ({names})",
            "title_ko": f"AWS Price List API, AmazonBedrock 사용 유형 {usagetype} ({names})",
            "url": PRICELIST_REFERENCE_URL,
        }
    if source_id == ANTHROPIC_SOURCE_ID:
        return {"kind": "anthropic_doc", "title_en": ANTHROPIC_TITLE_EN, "title_ko": ANTHROPIC_TITLE_KO,
                "url": ANTHROPIC_REFERENCE_URL}
    # Unknown format: still listed so the footnote resolves, without a link.
    return {"kind": "official_page", "title_en": source_id, "title_ko": source_id, "url": None}


def build_pricing_payload(db: Session, active: Mapping[str, PriceIdentity], *, now: datetime) -> dict:
    """The exact /api/pricing body for the active channel set (model_id -> PriceIdentity)."""
    now = as_utc(now)
    ids = sorted(active)
    current = current_rows(db, ids, now=now)
    pending = pending_rows(db, ids)
    last_run = last_finished_run(db)
    pending_count = 0
    if ids:
        pending_count = (
            db.query(func.count(PriceHistory.id))
            .filter(PriceHistory.model_id.in_(ids), PriceHistory.status == "pending_review")
            .scalar()
        ) or 0

    by_family: dict[str, list[str]] = {}
    for mid in ids:
        by_family.setdefault(active[mid].family_key, []).append(mid)

    def family_order(family_key: str):
        ident = active[by_family[family_key][0]]
        provider_rank = PROVIDER_ORDER.index(ident.provider) if ident.provider in PROVIDER_ORDER else len(PROVIDER_ORDER)
        family_rank = FAMILY_ORDER.index(ident.family) if ident.family in FAMILY_ORDER else len(FAMILY_ORDER)
        return provider_rank, family_rank, family_key

    numbers: dict[str, int] = {}
    cited_by: dict[str, list[str]] = {}

    def cite(source_ids: list[str], family: str) -> list[int]:
        out = []
        for sid in source_ids:
            if sid not in numbers:
                numbers[sid] = len(numbers) + 1
                cited_by[sid] = []
            if family not in cited_by[sid]:
                cited_by[sid].append(family)
            out.append(numbers[sid])
        return out

    def group_key(mid: str):
        row = current[mid]
        p = pending.get(mid)
        return (
            price_number(row.input_per_mtok), price_number(row.output_per_mtok), verification_of(row, last_run),
            None if p is None else (price_number(p.input_per_mtok), price_number(p.output_per_mtok)),
        )

    def groups(mids: list[str]) -> list[list[str]]:
        grouped: dict[tuple, list[str]] = {}
        for mid in mids:
            grouped.setdefault(group_key(mid), []).append(mid)
        return list(grouped.values())

    def cell(mids: list[str], family: str) -> dict:
        rows = [current[m] for m in mids]
        first = rows[0]
        source_ids: list[str] = []
        for r in rows:
            if r.source_id not in source_ids:
                source_ids.append(r.source_id)
        observed = [as_utc(r.observed_at) for r in rows if r.observed_at is not None]
        p = pending.get(mids[0])
        return {
            "input": price_number(first.input_per_mtok),
            "output": price_number(first.output_per_mtok),
            "model_ids": list(mids),
            "source_ids": source_ids,
            "footnotes": cite(source_ids, family),
            "verification": verification_of(first, last_run),
            "observed_at": iso_z(min(observed)) if observed else None,
            "pending": None if p is None else {
                "id": p.id,
                "input": price_number(p.input_per_mtok),
                "output": price_number(p.output_per_mtok),
                "observed_at": iso_z(p.observed_at),
            },
        }

    families = []
    for family_key in sorted(by_family, key=family_order):
        mids = by_family[family_key]
        ident = active[mids[0]]
        priced = [m for m in mids if m in current]
        tiers: dict = {}
        for tier in SINGLE_TIERS:
            options = groups(sorted(m for m in priced if tier_of(active[m].channel) == tier))
            if not options:
                tiers[tier] = None
                continue
            best = min(options, key=lambda g: (_VERIFICATION_RANK[verification_of(current[g[0]], last_run)], g[0]))
            tiers[tier] = cell(best, ident.family)
        regional = sorted(
            (m for m in priced if tier_of(active[m].channel) == "in_region"),
            key=lambda m: (region_of(active[m].channel), m),
        )
        tiers["in_region"] = [
            {"regions": [region_of(active[m].channel) for m in g], **cell(g, ident.family)}
            for g in groups(regional)
        ]
        notes = [dict(note) for note in pricing_sources.PRICE_NOTES
                 if note["family_key"] == family_key and not _note_resolved(note, mids, active, current)]
        families.append({
            "family_key": family_key,
            "family": ident.family,
            "provider": ident.provider,
            "tiers": tiers,
            "notes": notes,
        })

    references = []
    for sid, n in sorted(numbers.items(), key=lambda kv: kv[1]):
        observed = [as_utc(r.observed_at) for r in current.values() if r.source_id == sid and r.observed_at is not None]
        as_of = max(observed).date().isoformat() if observed else SEED_SOURCE_DATE.isoformat()
        references.append({"n": n, "id": sid, **_source_reference(sid, cited_by[sid]), "as_of": as_of})
    for page in pricing_sources.OFFICIAL_PAGES:
        references.append({
            "n": len(references) + 1, "id": official_source_id(page["slug"]), "kind": "official_page",
            "title_en": page["title_en"], "title_ko": page["title_ko"], "url": page["url"], "as_of": None,
        })
    for fam in families:
        for note in fam["notes"]:
            references.append({
                "n": len(references) + 1, "id": note_source_id(note["family_key"]), "kind": "manual_note",
                "title_en": note["text_en"], "title_ko": note["text_ko"], "url": None, "as_of": None,
            })

    return {
        "currency": "USD",
        "unit": "per_1m_tokens",
        "generated_at": iso_z(now),
        "last_sync": None if last_run is None else {
            "id": last_run.id,
            "started_at": iso_z(last_run.started_at),
            "finished_at": iso_z(last_run.finished_at),
            "status": last_run.status,
        },
        "pending_review": int(pending_count),
        "families": families,
        "models": {
            mid: {
                "input": price_number(current[mid].input_per_mtok),
                "output": price_number(current[mid].output_per_mtok),
                "verification": verification_of(current[mid], last_run),
            }
            for mid in ids if mid in current
        },
        "references": references,
        "disclaimer": {"en": pricing_sources.DISCLAIMER["en"], "ko": pricing_sources.DISCLAIMER["ko"]},
    }


def _note_resolved(note: Mapping, mids: list[str], active: Mapping[str, PriceIdentity],
                   current: Mapping[str, PriceHistory]) -> bool:
    """A promo note drops out once a sync has observed the pre-promotion price on one of its tiers."""
    for tier, prior in note["prior_price"].items():
        for mid in mids:
            row = current.get(mid)
            if (row is not None and row.observed_at is not None
                    and tier_of(active[mid].channel) == tier and _same_price(row, prior)):
                return True
    return False
```

#### `t07-export` — `backend/pricing_export.py`

<!-- plan-block id=t07-export path=backend/pricing_export.py sha256=cb963237c90238355f53b30f1f69cf17228f5b5e939349865363dd921dcccf19 -->
```python
"""CSV, Markdown and JSON downloads of the /api/pricing payload (v2.30.0) — pure functions.

Every format keeps the payload's order and footnote numbers (never re-sorted or renumbered) and carries
the disclaimer. Markdown and CSV prices use pricing_payload.price_text (at most 6 decimals, trailing zeros
removed); only the web screen fixes two decimals.
"""

import csv
import io
import json
from datetime import date

from pricing_payload import price_text
from pricing_sources import note_source_id

EXPORT_FORMATS = ("csv", "md", "json")
BOM = chr(0xFEFF)  # UTF-8 BOM so Excel opens the Korean CSV correctly
LANGS = ("ko", "en")

PROVIDER_TITLES = {"anthropic": "Anthropic Claude", "amazon": "Amazon Nova", "openai": "OpenAI"}
TIER_KEYS = ("cp", "global", "us", "in_region")

CSV_HEADER = ["provider", "family", "channel", "regions", "model_ids", "input_usd_per_1m", "output_usd_per_1m",
              "verification", "observed_at", "footnotes", "source_ids"]
CSV_REFERENCE_HEADER = ["reference_n", "reference_id", "kind", "title", "url", "as_of"]

_TEXT = {
    "ko": {
        "title": "비용 단가",
        "unit": "통화와 단위: USD, 1M 토큰당, 입력 / 출력",
        "generated": "생성 시각",
        "last_sync": "마지막 자동 확인",
        "never": "없음",
        "pending": "검토 대기",
        "columns": ["모델", "Claude Platform on AWS", "Global", "US", "In-Region"],
        "unverified": "자동 확인 안 됨",
        "notes": "참고 사항",
        "official": "최종 가격은 공식 요금 페이지에서 확인한다",
        "references": "참고 자료",
        "checked": "확인일",
        "manual": "수동 메모",
        "fixed_notes": [
            "단가는 USD, 1M 토큰당, Standard 등급 입력과 출력 기준이다.",
            "Global 채널 단가는 같은 모델의 US, In-Region 채널과 다를 수 있다.",
            "OpenAI는 입력 272K 이하 기준이다.",
            "캐시, batch, long-context, priority 단가는 포함하지 않는다.",
            "비용 화면은 각 프로브 시각의 단가로 계산한다.",
        ],
    },
    "en": {
        "title": "Unit prices",
        "unit": "Currency and unit: USD per 1M tokens, input / output",
        "generated": "Generated",
        "last_sync": "Last automatic check",
        "never": "none",
        "pending": "Pending review",
        "columns": ["Model", "Claude Platform on AWS", "Global", "US", "In-Region"],
        "unverified": "not verified automatically",
        "notes": "Notes",
        "official": "Confirm final prices on the official pricing pages",
        "references": "References",
        "checked": "checked",
        "manual": "Manual note",
        "fixed_notes": [
            "Prices are in USD per 1M tokens, Standard tier input and output.",
            "Global channel prices can differ from the US and In-Region channels of the same model.",
            "OpenAI prices apply to inputs of 272K tokens or fewer.",
            "Cache, batch, long-context and priority prices are not included.",
            "The cost pages use the price in effect at each probe's time.",
        ],
    },
}


def _lang(lang: str) -> str:
    if lang not in LANGS:
        raise ValueError(f"unsupported lang: {lang!r}")
    return lang


def export_filename(fmt: str, today: date) -> str:
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"unsupported export format: {fmt!r}")
    return f"llm-monitor-unit-prices-{today.isoformat()}.{fmt}"


def _cells(family: dict):
    """(tier key, cell) in display order: cp, global, us, then each in_region element."""
    for tier in TIER_KEYS[:3]:
        if family["tiers"][tier] is not None:
            yield tier, family["tiers"][tier]
    for element in family["tiers"]["in_region"]:
        yield "in_region", element


def to_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _md_cell(cell: dict, t: dict) -> str:
    text = f"{price_text(cell['input'])} / {price_text(cell['output'])}"
    if cell.get("regions"):
        text += " " + ", ".join(cell["regions"])
    if cell["verification"] in ("stale", "seed_only"):
        text += f" ({t['unverified']})"
    if cell["pending"] is not None:
        text += f" ({t['pending']} {price_text(cell['pending']['input'])} / {price_text(cell['pending']['output'])})"
    return text + "".join(f"[^{n}]" for n in cell["footnotes"])


def to_markdown(payload: dict, lang: str) -> str:
    t = _TEXT[_lang(lang)]
    disclaimer = payload["disclaimer"][lang]
    title_key = f"title_{lang}"
    lines = [f"> {disclaimer}", "", f"# {t['title']}", "", f"- {t['unit']}", f"- {t['generated']}: {payload['generated_at']}"]
    sync = payload["last_sync"]
    lines.append(f"- {t['last_sync']}: " + (f"{sync['finished_at']} ({sync['status']})" if sync else t["never"]))
    if payload["pending_review"] > 0:
        lines.append(f"- {t['pending']}: {payload['pending_review']}")

    provider = None
    for family in payload["families"]:
        if family["provider"] != provider:
            provider = family["provider"]
            lines += ["", f"## {PROVIDER_TITLES.get(provider, provider)}", "",
                      "| " + " | ".join(t["columns"]) + " |", "|---|---|---|---|---|"]
        tiers = family["tiers"]
        row = [family["family"]]
        for tier in TIER_KEYS[:3]:
            row.append(_md_cell(tiers[tier], t) if tiers[tier] is not None else "—")
        row.append("<br>".join(_md_cell(e, t) for e in tiers["in_region"]) or "—")
        lines.append("| " + " | ".join(row) + " |")

    official = [r for r in payload["references"] if r["kind"] == "official_page"]
    notes = [(family, note) for family in payload["families"] for note in family["notes"]]
    note_n = {r["id"]: r["n"] for r in payload["references"] if r["kind"] == "manual_note"}
    lines += ["", f"## {t['notes']}", ""]
    items = list(t["fixed_notes"])
    if official:
        # Referenced before the manual notes so Markdown renderers number footnotes in payload order.
        items.append(t["official"] + "".join(f"[^{r['n']}]" for r in official) + ".")
    for family, note in notes:
        items.append(f"{family['family']}: {note[f'text_{lang}']}[^{note_n[note_source_id(note['family_key'])]}]")
    lines += [f"{i}. {item}" for i, item in enumerate(items, start=1)]

    lines += ["", f"## {t['references']}", ""]
    for ref in payload["references"]:
        parts = [ref[title_key] if ref["kind"] != "manual_note" else f"{t['manual']}: {ref[title_key]}"]
        if ref["url"]:
            parts.append(ref["url"])
        if ref["as_of"]:
            parts.append(f"{t['checked']} {ref['as_of']}")
        lines.append(f"[^{ref['n']}]: " + ", ".join(parts))
    lines += ["", f"> {disclaimer}", ""]
    return "\n".join(lines)


def to_csv(payload: dict, lang: str) -> str:
    """UTF-8 BOM (Excel), a raw "# <disclaimer>" first line, the price rows, a blank line, the references."""
    _lang(lang)
    buf = io.StringIO()
    buf.write(BOM + "# " + payload["disclaimer"][lang] + "\n")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for family in payload["families"]:
        for tier, cell in _cells(family):
            writer.writerow([
                family["provider"], family["family"], tier, " ".join(cell.get("regions", [])),
                " ".join(cell["model_ids"]), price_text(cell["input"]), price_text(cell["output"]),
                cell["verification"], cell["observed_at"] or "", " ".join(str(n) for n in cell["footnotes"]),
                " ".join(cell["source_ids"]),
            ])
    writer.writerow([])
    writer.writerow(CSV_REFERENCE_HEADER)
    for ref in payload["references"]:
        writer.writerow([ref["n"], ref["id"], ref["kind"], ref[f"title_{lang}"], ref["url"] or "", ref["as_of"] or ""])
    return buf.getvalue()
```

### Task 8 blocks

#### `t08-test` — `backend/tests/test_pricing_router.py`

<!-- plan-block id=t08-test path=backend/tests/test_pricing_router.py sha256=b866e16ae8891484b7ee0744105a2f1a7dba51d9e5d8fc6350177d8f3db2a701 -->
```python
"""routers/pricing.py — /api/pricing, /api/pricing/export, /api/admin/pricing/* (v2.30.0, ADR-030).

In-memory SQLite, FastAPI TestClient, no network. prober.AVAILABLE_MODELS is replaced per test so the
active set is deterministic; the 60 s cache is cleared around every test.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import prober
from auth import create_access_token
from database import get_db
from price_history import as_utc
from pricing_export import BOM
from pricing_sources import DISCLAIMER, EPOCH
from routers import pricing as pricing_router
from tests._pricing_dataset import add_price

MODELS = {
    "global.anthropic.claude-opus-5-5": "Bedrock Claude Opus 5.5 (Global)",
    "us.anthropic.claude-opus-5-5": "Bedrock Claude Opus 5.5 (US)",
    "openai:us-east-1:openai.gpt-5.4": "OpenAI GPT 5.4 (us-east-1)",
    "openai:us-east-2:openai.gpt-5.4": "OpenAI GPT 5.4 (us-east-2)",
    "openai:1p:gpt-5.4": "OpenAI GPT 5.4 (1P)",  # hidden by HIDDEN_MODEL_PATTERNS
}
OPUS_OFFER = "offer:offer-7sp77cpl4rveu"
G54_OFFER = "offer:offer-5l5a5izq5fbec"


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(MODELS))
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P)")
    now = datetime.now(timezone.utc)
    with factory() as db:
        db.add(models.User(username="admin", password_hash="x", approved=1))
        db.add(models.User(username="viewer@example.com", password_hash="x", approved=1))
        db.add(models.PriceSyncRun(started_at=now - timedelta(hours=1), finished_at=now - timedelta(minutes=59),
                                   status="completed"))
        add_price(db, "global.anthropic.claude-opus-5-5", 4.0, 20.0, observed_at=now - timedelta(hours=1),
                  source_id=OPUS_OFFER)
        add_price(db, "us.anthropic.claude-opus-5-5", 4.4, 22.0, observed_at=now - timedelta(hours=1),
                  source_id=OPUS_OFFER)
        for region in ("us-east-1", "us-east-2"):
            add_price(db, f"openai:{region}:openai.gpt-5.4", 2.75, 16.5, observed_at=now - timedelta(hours=1),
                      source_id=G54_OFFER)
        add_price(db, "openai:1p:gpt-5.4", 2.75, 16.5, source_id=G54_OFFER)
        db.commit()

    app = FastAPI()
    app.include_router(pricing_router.router)
    app.include_router(pricing_router.admin_router)

    def db_override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    pricing_router.invalidate_cache()
    with TestClient(app) as client:
        yield factory, client, now
    pricing_router.invalidate_cache()
    engine.dispose()


def _auth(username):
    return {"Authorization": f"Bearer {create_access_token(username)}"}


def _pending(factory, model_id, inp, out, *, effective_from, observed_at):
    with factory() as db:
        row = add_price(db, model_id, inp, out, effective_from=effective_from, status="pending_review",
                        observed_at=observed_at, source_id=OPUS_OFFER)
        db.commit()
        return row.id


def test_pricing_shape_and_active_set(env):
    _, client, _ = env
    body = client.get("/api/pricing").json()
    assert body["currency"] == "USD" and body["unit"] == "per_1m_tokens"
    assert body["disclaimer"] == {"en": DISCLAIMER["en"], "ko": DISCLAIMER["ko"]}
    assert [f["family_key"] for f in body["families"]] == ["claude-opus-5-5", "gpt-5.4"]
    for family in body["families"]:
        assert set(family["tiers"]) == {"cp", "global", "us", "in_region"}
        assert isinstance(family["tiers"]["in_region"], list)
    gpt54 = body["families"][1]["tiers"]["in_region"]
    assert [(e["regions"], e["input"], e["output"]) for e in gpt54] == [(["us-east-1", "us-east-2"], 2.75, 16.5)]
    assert "openai:1p:gpt-5.4" not in body["models"]  # hidden channel never appears
    assert body["models"]["us.anthropic.claude-opus-5-5"] == {"input": 4.4, "output": 22, "verification": "verified"}
    refs = {r["n"]: r["id"] for r in body["references"]}
    for family in body["families"]:
        for tier in ("cp", "global", "us"):
            cell = family["tiers"][tier]
            if cell:
                assert [refs[n] for n in cell["footnotes"]] == cell["source_ids"]


def test_cp_ids_observed_in_the_last_30_days_stay_in_the_table_when_discovery_failed(env):
    factory, client, now = env
    with factory() as db:
        add_price(db, "anthropic:claude-opus-5-5", 4.0, 20.0, observed_at=now - timedelta(days=2),
                  source_id="anthropic-pricing")
        add_price(db, "anthropic:claude-opus-4-7", 5.0, 25.0, observed_at=now - timedelta(days=31),
                  source_id="anthropic-pricing")
        db.commit()
    body = client.get("/api/pricing").json()
    assert body["families"][0]["tiers"]["cp"]["model_ids"] == ["anthropic:claude-opus-5-5"]
    assert "anthropic:claude-opus-4-7" not in body["models"]  # older than 30 days


def test_payload_is_cached_for_60_seconds(env, monkeypatch):
    factory, client, now = env
    clock = [1000.0]
    monkeypatch.setattr(pricing_router, "_monotonic", lambda: clock[0])
    assert client.get("/api/pricing").json()["pending_review"] == 0
    _pending(factory, "us.anthropic.claude-opus-5-5", 9.0, 45.0, effective_from=now, observed_at=now)
    clock[0] += 59.0
    assert client.get("/api/pricing").json()["pending_review"] == 0  # still cached
    clock[0] += 1.0
    assert client.get("/api/pricing").json()["pending_review"] == 1  # 60 s elapsed


def test_approve_keeps_effective_from_clears_cache_and_warns_about_later_rows(env):
    factory, client, now = env
    change_at = now - timedelta(minutes=30)
    row_id = _pending(factory, "us.anthropic.claude-opus-5-5", 9.0, 45.0, effective_from=change_at,
                      observed_at=change_at)
    with factory() as db:
        add_price(db, "us.anthropic.claude-opus-5-5", 5.0, 25.0, effective_from=now - timedelta(minutes=10),
                  status="verified", observed_at=now - timedelta(minutes=10), source_id=OPUS_OFFER)
        db.commit()
    before = client.get("/api/pricing").json()
    assert before["pending_review"] == 1
    assert before["families"][0]["tiers"]["us"]["pending"]["id"] == row_id

    res = client.post(f"/api/admin/pricing/pending/{row_id}/approve", headers=_auth("admin"))
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True and body["status"] == "verified"
    assert body["effective_from"] == change_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert len(body["warnings"]) == 1 and re.search(r"5 / 25", body["warnings"][0])
    with factory() as db:
        row = db.get(models.PriceHistory, row_id)
        assert row.status == "verified"
        assert as_utc(row.effective_from) == change_at

    after = client.get("/api/pricing").json()  # cache cleared by approve
    assert after["pending_review"] == 0
    assert after["families"][0]["tiers"]["us"]["pending"] is None
    assert after["models"]["us.anthropic.claude-opus-5-5"]["input"] == 5  # later verified row still wins now


def test_approve_no_baseline_row_applies_from_1970(env):
    factory, client, now = env
    row_id = _pending(factory, "openai:us-east-1:openai.gpt-5.4", 3.0, 18.0, effective_from=EPOCH, observed_at=now)
    listed = client.get("/api/admin/pricing/pending", headers=_auth("admin")).json()["pending"]
    assert [(p["id"], p["reason"]) for p in listed] == [(row_id, "no_baseline")]
    res = client.post(f"/api/admin/pricing/pending/{row_id}/approve", headers=_auth("admin")).json()
    assert res["effective_from"] == "1970-01-01T00:00:00Z"
    assert res["warnings"] == []


def test_reject_marks_rejected_and_clears_cache(env):
    factory, client, now = env
    row_id = _pending(factory, "us.anthropic.claude-opus-5-5", 9.0, 45.0, effective_from=now, observed_at=now)
    assert client.get("/api/pricing").json()["pending_review"] == 1
    res = client.post(f"/api/admin/pricing/pending/{row_id}/reject", headers=_auth("admin"))
    assert res.status_code == 200 and res.json()["status"] == "rejected"
    assert client.get("/api/pricing").json()["pending_review"] == 0
    again = client.post(f"/api/admin/pricing/pending/{row_id}/approve", headers=_auth("admin"))
    assert again.status_code == 409  # only pending_review rows can be decided
    assert client.post("/api/admin/pricing/pending/99999/reject", headers=_auth("admin")).status_code == 404


def test_pending_list_reports_current_value_and_change_ratio(env):
    factory, client, now = env
    row_id = _pending(factory, "us.anthropic.claude-opus-5-5", 6.6, 44.0, effective_from=now, observed_at=now)
    listed = client.get("/api/admin/pricing/pending", headers=_auth("admin")).json()["pending"]
    assert listed == [{
        "id": row_id, "model_id": "us.anthropic.claude-opus-5-5", "family_key": "claude-opus-5-5", "channel": "us",
        "reason": "changed", "current": {"input": 4.4, "output": 22.0}, "new": {"input": 6.6, "output": 44.0},
        "change": {"input": 0.5, "output": 1.0}, "source_id": OPUS_OFFER,
        "effective_from": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }]


@pytest.mark.parametrize("method,path", [
    ("get", "/api/admin/pricing/pending"),
    ("post", "/api/admin/pricing/pending/1/approve"),
    ("post", "/api/admin/pricing/pending/1/reject"),
])
def test_admin_endpoints_require_the_admin_account(env, method, path):
    _, client, _ = env
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers=_auth("viewer@example.com")).status_code == 403


@pytest.mark.parametrize("fmt,content_type,ext", [
    ("csv", "text/csv; charset=utf-8", "csv"),
    ("md", "text/markdown; charset=utf-8", "md"),
    ("json", "application/json", "json"),
])
def test_export_headers_and_bodies(env, fmt, content_type, ext):
    _, client, _ = env
    res = client.get(f"/api/pricing/export?format={fmt}&lang=en")
    assert res.status_code == 200
    assert res.headers["content-type"] == content_type
    today = datetime.now(timezone.utc).date().isoformat()
    assert res.headers["content-disposition"] == f'attachment; filename="llm-monitor-unit-prices-{today}.{ext}"'
    text = res.content.decode("utf-8")
    if fmt == "csv":
        assert text.startswith(BOM + "# " + DISCLAIMER["en"] + "\n")
    elif fmt == "md":
        assert text.startswith("> " + DISCLAIMER["en"] + "\n")
        assert text.rstrip("\n").endswith("> " + DISCLAIMER["en"])
    else:
        assert res.json() == client.get("/api/pricing").json()


def test_export_lang_defaults_to_korean(env):
    _, client, _ = env
    text = client.get("/api/pricing/export?format=md").content.decode("utf-8")
    assert text.startswith("> " + DISCLAIMER["ko"] + "\n")


@pytest.mark.parametrize("query", ["format=xlsx", "format=csv&lang=ja", ""])
def test_export_rejects_unknown_format_or_lang(env, query):
    _, client, _ = env
    assert client.get(f"/api/pricing/export?{query}").status_code == 422


def test_main_registers_both_pricing_routers():
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "from routers import pricing as pricing_router" in src
    assert "app.include_router(pricing_router.router)" in src
    assert "app.include_router(pricing_router.admin_router)" in src


def test_hidden_model_patterns_drop_classifiable_channels(env, monkeypatch):
    _, client, _ = env
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P),(us-east-2)")
    body = client.get("/api/pricing").json()
    assert "openai:us-east-2:openai.gpt-5.4" not in body["models"]
    assert "openai:us-east-1:openai.gpt-5.4" in body["models"]
```

#### `t08-router` — `backend/routers/pricing.py`

<!-- plan-block id=t08-router path=backend/routers/pricing.py sha256=15ade51e3d33e943cd8546f5f20f65db7e1a8da3463874becd5a1328b5e5906b -->
```python
"""Unit price menu API (v2.30.0, ADR-030).

Public:
  GET /api/pricing                                   - price table payload (pricing_payload.build_pricing_payload)
  GET /api/pricing/export?format=csv|md|json&lang=ko|en - the same table as a download (attachment)
Admin (JWT, username == "admin"):
  GET  /api/admin/pricing/pending                    - pending_review rows with current value and change ratio
  POST /api/admin/pricing/pending/{row_id}/approve   - status -> verified (effective_from unchanged)
  POST /api/admin/pricing/pending/{row_id}/reject    - status -> rejected

CloudFront does not cache /api/*, so the payload is cached in-process for 60 s (no lang in the key: the
body carries both languages). Approve/reject clear this process's cache at once; other backend tasks catch
up within 60 s.
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

import prober
from auth import get_current_user
from database import get_db
from models import PriceHistory, User
from price_history import as_utc, current_rows
from pricing_export import export_filename, to_csv, to_json, to_markdown
from pricing_payload import build_pricing_payload, iso_z, price_number
from pricing_sources import EPOCH, active_channels, price_identity
from routers.admin import _ensure_admin
from visibility import hidden_patterns

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pricing", tags=["pricing"])
admin_router = APIRouter(prefix="/api/admin/pricing", tags=["admin"])

CACHE_TTL_S = 60.0
CP_RECENT_DAYS = 30
_EXPORT_MEDIA_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "json": "application/json",
}

_cache_lock = threading.Lock()
_cache: dict = {"at": 0.0, "payload": None}
_monotonic = time.monotonic  # patched by tests


def invalidate_cache() -> None:
    with _cache_lock:
        _cache["payload"] = None
        _cache["at"] = 0.0


def _active(db: Session, now: datetime) -> dict:
    """Active channels = AVAILABLE_MODELS + CP ids observed in the last 30 days (CP discovery may have failed
    at this backend's startup), hidden labels removed, classified by price_identity."""
    models = dict(prober.AVAILABLE_MODELS)
    since = now - timedelta(days=CP_RECENT_DAYS)
    recent = (
        db.query(PriceHistory.model_id)
        .filter(PriceHistory.channel == "cp", PriceHistory.observed_at >= since)
        .distinct()
        .all()
    )
    for (model_id,) in recent:
        ident = price_identity(model_id)
        if model_id not in models and ident is not None and ident.channel == "cp":
            models[model_id] = f"Anthropic {ident.family} (US)"  # prober's CP label format
    return active_channels(models, hidden_patterns())


def _payload(db: Session) -> dict:
    with _cache_lock:
        cached = _cache["payload"]
        if cached is not None and _monotonic() - _cache["at"] < CACHE_TTL_S:
            return cached
    now = datetime.now(timezone.utc)
    payload = build_pricing_payload(db, _active(db, now), now=now)
    with _cache_lock:
        _cache["payload"] = payload
        _cache["at"] = _monotonic()
    return payload


@router.get("")
def get_pricing_table(db: Session = Depends(get_db)):
    """Unit price table: families in display order, per-cell footnotes, references, disclaimer (ko + en)."""
    return _payload(db)


@router.get("/export")
def export_pricing_table(
    fmt: str = Query(..., alias="format", pattern="^(csv|md|json)$"),
    lang: str = Query("ko", pattern="^(ko|en)$"),
    db: Session = Depends(get_db),
):
    """Download the price table as CSV (UTF-8 BOM), Markdown or JSON."""
    payload = _payload(db)
    if fmt == "csv":
        body = to_csv(payload, lang)
    elif fmt == "md":
        body = to_markdown(payload, lang)
    else:
        body = to_json(payload)
    filename = export_filename(fmt, datetime.now(timezone.utc).date())
    return Response(
        content=body.encode("utf-8"),
        media_type=_EXPORT_MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class PriceValue(BaseModel):
    input: float
    output: float


class PendingPrice(BaseModel):
    id: int
    model_id: str
    family_key: str
    channel: str
    reason: str  # changed | no_baseline
    current: Optional[PriceValue]
    new: PriceValue
    change: Optional[PriceValue]  # |new - old| / old per side; null without a baseline
    source_id: str
    effective_from: str
    observed_at: Optional[str]


class PendingList(BaseModel):
    pending: list[PendingPrice]


class PendingAction(BaseModel):
    ok: bool
    id: int
    status: str
    effective_from: str
    warnings: list[str]


def _ratio(new: float, old: float) -> Optional[float]:
    return round(abs(new - old) / old, 6) if old else None


@admin_router.get("/pending", response_model=PendingList)
def list_pending_prices(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """All pending_review rows, oldest first, with the currently effective value and the change ratio."""
    _ensure_admin(user)
    rows = db.query(PriceHistory).filter(PriceHistory.status == "pending_review").order_by(PriceHistory.id).all()
    current = current_rows(db, [r.model_id for r in rows])
    out = []
    for r in rows:
        cur = current.get(r.model_id)
        change = None
        if cur is not None:
            ci, co = _ratio(r.input_per_mtok, cur.input_per_mtok), _ratio(r.output_per_mtok, cur.output_per_mtok)
            change = PriceValue(input=ci, output=co) if ci is not None and co is not None else None
        out.append(PendingPrice(
            id=r.id, model_id=r.model_id, family_key=r.family_key, channel=r.channel,
            reason="no_baseline" if as_utc(r.effective_from) == EPOCH else "changed",
            current=None if cur is None else PriceValue(
                input=price_number(cur.input_per_mtok), output=price_number(cur.output_per_mtok)),
            new=PriceValue(input=price_number(r.input_per_mtok), output=price_number(r.output_per_mtok)),
            change=change, source_id=r.source_id,
            effective_from=iso_z(r.effective_from), observed_at=iso_z(r.observed_at),
        ))
    return PendingList(pending=out)


def _pending_or_404(db: Session, row_id: int) -> PriceHistory:
    row = db.get(PriceHistory, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"price row {row_id} not found")
    if row.status != "pending_review":
        raise HTTPException(status_code=409, detail=f"price row {row_id}는 검토 대기 상태가 아닙니다 (현재: {row.status})")
    return row


@admin_router.post("/pending/{row_id}/approve", response_model=PendingAction)
def approve_pending_price(row_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """pending_review -> verified. effective_from stays the insert-time value (the observing run's start, or
    1970 for no_baseline). A verified row that already starts later keeps winning from its own start."""
    _ensure_admin(user)
    row = _pending_or_404(db, row_id)
    later = (
        db.query(PriceHistory)
        .filter(PriceHistory.model_id == row.model_id, PriceHistory.status == "verified",
                PriceHistory.effective_from > row.effective_from, PriceHistory.id != row.id)
        .order_by(PriceHistory.effective_from, PriceHistory.id)
        .all()
    )
    warnings = [
        f"id {v.id}의 단가 {price_number(v.input_per_mtok)} / {price_number(v.output_per_mtok)}가 "
        f"{iso_z(v.effective_from)}부터 적용되므로, 승인한 단가는 그 시각 전까지만 적용됩니다."
        for v in later
    ]
    row.status = "verified"
    db.commit()
    invalidate_cache()
    logger.info("admin '%s' approved price row %d (%s)", user.username, row.id, row.model_id)
    return PendingAction(ok=True, id=row.id, status=row.status, effective_from=iso_z(row.effective_from),
                         warnings=warnings)


@admin_router.post("/pending/{row_id}/reject", response_model=PendingAction)
def reject_pending_price(row_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """pending_review -> rejected. The sync keeps it rejected until the observed value changes."""
    _ensure_admin(user)
    row = _pending_or_404(db, row_id)
    row.status = "rejected"
    db.commit()
    invalidate_cache()
    logger.info("admin '%s' rejected price row %d (%s)", user.username, row.id, row.model_id)
    return PendingAction(ok=True, id=row.id, status=row.status, effective_from=iso_z(row.effective_from),
                         warnings=[])
```

### Task 9 blocks

#### `t09-test` — `frontend/src/lib/pricingTable.test.ts`

<!-- plan-block id=t09-test path=frontend/src/lib/pricingTable.test.ts sha256=a450aced8b5fe63735485d2150789f31e2f60fe8841f5d2959b21bcbf3fffe57 -->
```ts
/**
 * 비용 단가 표 순수 로직 (v2.30.0) — 화면 포맷(소수 둘째 자리 고정), 배지 판정, `costFromPrices`.
 *
 * 정렬과 각주 번호는 백엔드가 정하므로 여기서는 검사하지 않는다. 배지 규칙은 설계서 UI 절:
 * stale, seed_only → "자동 확인 안 됨", pending → "검토 대기", 수동 메모 → 프로모션(날짜가 지나면 확인 필요).
 */
import { afterEach, describe, expect, test, vi } from "vitest";
import { fetchPricing, pricingExportUrl } from "./api";
import type { PricingModelPrice, PricingNote, PricingTier } from "./types";
import {
  costFromPrices, formatPricePair, formatUnitPrice, notesForTier, tierBadges, utcDate,
} from "./pricingTable";

afterEach(() => {
  vi.unstubAllGlobals();
});

function tier(overrides: Partial<PricingTier> = {}): PricingTier {
  return {
    input: 4.4, output: 22, model_ids: ["openai:us-east-1:openai.gpt-5.6-sol"],
    source_ids: ["offer:offer-e2esol56"], footnotes: [6],
    verification: "verified", observed_at: "2026-09-26T15:00:00Z", pending: null,
    ...overrides,
  };
}

const SOL_PROMO: PricingNote = {
  family_key: "gpt-5.6-sol", kind: "promo", min_until: "2026-11-21",
  prior_price: { in_region: { input: 5.5, output: 33 }, global: { input: 5, output: 30 } },
  text_ko: "2026-09-23 AWS 모델 카드 기재(현재 미게재), CHANGELOG v2.28.1",
  text_en: "Listed on the AWS model card on 2026-09-23 (no longer shown), CHANGELOG v2.28.1",
  source: "manual_note",
};

const SEPT_26 = new Date("2026-09-26T12:00:00Z");

describe("formatUnitPrice / formatPricePair — 화면은 소수 둘째 자리 고정", () => {
  test.each([
    [0.06, "$0.06"], [4, "$4.00"], [4.4, "$4.40"], [0.1, "$0.10"], [16.5, "$16.50"], [2.75, "$2.75"], [0.33, "$0.33"],
  ])("%s → %s", (value, expected) => {
    expect(formatUnitPrice(value)).toBe(expected);
  });

  test("입력 / 출력 쌍", () => {
    expect(formatPricePair({ input: 4, output: 20 })).toBe("$4.00 / $20.00");
    expect(formatPricePair(tier())).toBe("$4.40 / $22.00");
  });
});

describe("utcDate", () => {
  test("UTC 날짜만 남긴다, 오프셋 없는 값은 UTC로 읽는다", () => {
    expect(utcDate("2026-09-26T15:00:00Z")).toBe("2026-09-26");
    expect(utcDate("2026-09-26T23:30:00")).toBe("2026-09-26");
    expect(utcDate(null)).toBeNull();
    expect(utcDate("not a date")).toBeNull();
  });
});

describe("tierBadges", () => {
  test("verified이고 검토 대기와 메모가 없으면 배지가 없다", () => {
    expect(tierBadges(tier(), [], "ko", SEPT_26)).toEqual([]);
  });

  test("stale → 자동 확인 안 됨, 툴팁은 마지막 확인일", () => {
    const stale = tier({ verification: "stale", observed_at: "2026-09-20T03:00:00Z" });
    expect(tierBadges(stale, [], "ko", SEPT_26)).toEqual([
      { kind: "unverified", label: "자동 확인 안 됨", title: "마지막 확인 2026-09-20" },
    ]);
    expect(tierBadges(stale, [], "en", SEPT_26)).toEqual([
      { kind: "unverified", label: "Not auto-verified", title: "Last verified 2026-09-20" },
    ]);
  });

  test("seed_only → 자동 확인 안 됨, 툴팁은 초기값", () => {
    const seed = tier({ verification: "seed_only", observed_at: null });
    expect(tierBadges(seed, [], "ko", SEPT_26)).toEqual([{ kind: "unverified", label: "자동 확인 안 됨", title: "초기값" }]);
    expect(tierBadges(seed, [], "en", SEPT_26)[0].title).toBe("Initial value");
  });

  test("none은 배지를 만들지 않는다", () => {
    expect(tierBadges(tier({ verification: "none" }), [], "ko", SEPT_26)).toEqual([]);
  });

  test("pending → 검토 대기, 툴팁은 새 값", () => {
    const pending = tier({ pending: { id: 91, input: 3, output: 18, observed_at: "2026-09-26T15:00:00Z" } });
    expect(tierBadges(pending, [], "ko", SEPT_26)).toEqual([{ kind: "pending", label: "검토 대기", title: "새 값 $3.00 / $18.00" }]);
    expect(tierBadges(pending, [], "en", SEPT_26)).toEqual([{ kind: "pending", label: "Pending review", title: "New value $3.00 / $18.00" }]);
  });

  test("수동 메모 → 프로모션 배지, 툴팁은 프로모션 이전 단가와 메모 근거", () => {
    const [badge] = tierBadges(tier(), notesForTier([SOL_PROMO], "in_region"), "ko", SEPT_26);
    expect(badge.kind).toBe("promo");
    expect(badge.label).toBe("프로모션(최소 2026-11-21까지, 수동 메모)");
    expect(badge.title).toBe("프로모션 이전 단가 $5.50 / $33.00\n2026-09-23 AWS 모델 카드 기재(현재 미게재), CHANGELOG v2.28.1");
    const [en] = tierBadges(tier(), notesForTier([SOL_PROMO], "global"), "en", SEPT_26);
    expect(en.label).toBe("Promotion (until at least 2026-11-21, manual note)");
    expect(en.title).toBe("Price before the promotion $5.00 / $30.00\nListed on the AWS model card on 2026-09-23 (no longer shown), CHANGELOG v2.28.1");
  });

  test("티어를 좁히지 않은 메모는 티어 이름과 함께 모든 이전 단가를 보여 준다", () => {
    const [badge] = tierBadges(tier(), [SOL_PROMO], "ko", SEPT_26);
    expect(badge.title.split("\n")[0]).toBe("프로모션 이전 단가 In-Region $5.50 / $33.00, Global $5.00 / $30.00");
  });

  test("min_until 당일(UTC)까지는 프로모션, 다음 날부터 종료 여부 확인 필요", () => {
    const notes = notesForTier([SOL_PROMO], "in_region");
    expect(tierBadges(tier(), notes, "ko", new Date("2026-11-21T23:59:59Z"))[0].kind).toBe("promo");
    const [passed] = tierBadges(tier(), notes, "ko", new Date("2026-11-22T00:00:00Z"));
    expect(passed.kind).toBe("promo_check");
    expect(passed.label).toBe("프로모션 종료 여부 확인 필요");
    expect(passed.title).toContain("$5.50 / $33.00");
    expect(tierBadges(tier(), notes, "en", new Date("2026-12-01T00:00:00Z"))[0].label).toBe("Check whether the promotion has ended");
  });

  test("배지 순서: 자동 확인 안 됨 → 검토 대기 → 프로모션", () => {
    const all = tier({
      verification: "stale", observed_at: "2026-09-20T03:00:00Z",
      pending: { id: 7, input: 5.5, output: 33, observed_at: "2026-09-26T15:00:00Z" },
    });
    expect(tierBadges(all, notesForTier([SOL_PROMO], "in_region"), "ko", SEPT_26).map((b) => b.kind))
      .toEqual(["unverified", "pending", "promo"]);
  });
});

describe("notesForTier", () => {
  test("그 티어의 이전 단가가 있는 메모만 남기고 이전 단가를 그 티어로 좁힌다", () => {
    expect(notesForTier([SOL_PROMO], "us")).toEqual([]);
    expect(notesForTier([SOL_PROMO], "cp")).toEqual([]);
    const [global] = notesForTier([SOL_PROMO], "global");
    expect(global.prior_price).toEqual({ global: { input: 5, output: 30 } });
    expect(SOL_PROMO.prior_price).toHaveProperty("in_region"); // 원본은 바꾸지 않는다
  });
});

describe("costFromPrices", () => {
  const models: Record<string, PricingModelPrice> = {
    "openai:us-east-1:openai.gpt-6-sol": { input: 2.2, output: 11, verification: "verified" },
    "openai:global:global.openai.gpt-6-luna": { input: 0.1, output: 0.5, verification: "stale" },
    "us.amazon.nova-2-lite-v1:0": { input: 0.33, output: 2.75, verification: "seed_only" },
  };

  test("USD per 1M 토큰 산술", () => {
    expect(costFromPrices(models, "openai:us-east-1:openai.gpt-6-sol", 1_000_000, 1_000_000)).toBeCloseTo(13.2, 9);
    expect(costFromPrices(models, "openai:global:global.openai.gpt-6-luna", 2_000_000, 500_000)).toBeCloseTo(0.45, 9);
    expect(costFromPrices(models, "us.amazon.nova-2-lite-v1:0", 32, 128)).toBeCloseTo((32 * 0.33 + 128 * 2.75) / 1e6, 12);
  });

  test("단가가 없으면 null — prefix fallback 없음", () => {
    expect(costFromPrices(models, "openai:us:us.openai.gpt-6-sol", 100, 100)).toBeNull();
    expect(costFromPrices(models, "openai:us-east-1:openai.gpt-6", 100, 100)).toBeNull();
    expect(costFromPrices(models, "toString", 100, 100)).toBeNull();
    expect(costFromPrices(null, "openai:us-east-1:openai.gpt-6-sol", 100, 100)).toBeNull();
    expect(costFromPrices(undefined, "openai:us-east-1:openai.gpt-6-sol", 100, 100)).toBeNull();
  });

  test("토큰 수가 없으면 0으로 센다 (백엔드 COALESCE와 같음)", () => {
    expect(costFromPrices(models, "openai:us-east-1:openai.gpt-6-sol", null, 1000)).toBeCloseTo(0.011, 12);
    expect(costFromPrices(models, "openai:us-east-1:openai.gpt-6-sol", undefined, undefined)).toBe(0);
  });
});

describe("pricing API client", () => {
  test("pricingExportUrl — format과 lang을 쿼리로 싣는 같은 출처 경로", () => {
    expect(pricingExportUrl("csv", "ko")).toBe("/api/pricing/export?format=csv&lang=ko");
    expect(pricingExportUrl("md", "en")).toBe("/api/pricing/export?format=md&lang=en");
    expect(pricingExportUrl("json", "ko")).toBe("/api/pricing/export?format=json&lang=ko");
  });

  test("fetchPricing — 인증 없는 GET /api/pricing", async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify({ currency: "USD", families: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(fetchPricing()).resolves.toMatchObject({ currency: "USD", families: [] });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/pricing");
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).has("Authorization")).toBe(false);
  });
});
```

#### `t09-types-api` — `@scratch/patches/t09-types-api.patch`

<!-- plan-block id=t09-types-api path=@scratch/patches/t09-types-api.patch sha256=43f2196a34bf4952bc9239c651d457d85bc288deeaf165baebf4d87a890e422d -->
```diff
diff --git a/frontend/src/lib/api.ts b/frontend/src/lib/api.ts
index 0d5b35b..7d6a25f 100644
--- a/frontend/src/lib/api.ts
+++ b/frontend/src/lib/api.ts
@@ -10,6 +10,7 @@ import {
   ChatStreamEvents,
   Insight,
   AutoProbeAnomalies,
+  PricingResponse,
 } from "./types";
 import { ApiError, fetchJson } from "./http";
 import type {
@@ -889,3 +890,16 @@ export async function fetchFeaturesEvidence(q: { run_id: number; feature: string
 export async function triggerFeaturesRun(): Promise<{ triggered: boolean; message: string }> {
   return authenticatedJson(`${BASE}/api/features/trigger`, { method: "POST" });
 }
+
+// ── Unit prices (v2.30.0) ───────────────────────────────────────────────
+
+/** Public price table, backend single source (official sources refreshed every 12 hours). */
+export async function fetchPricing(signal?: AbortSignal): Promise<PricingResponse> {
+  return fetchJson(`${BASE}/api/pricing`, { signal });
+}
+
+/** Same-origin download link; the backend sets Content-Disposition with the dated file name. */
+export function pricingExportUrl(format: "csv" | "md" | "json", lang: "ko" | "en"): string {
+  const sp = new URLSearchParams({ format, lang });
+  return `${BASE}/api/pricing/export?${sp.toString()}`;
+}
diff --git a/frontend/src/lib/types.ts b/frontend/src/lib/types.ts
index 20c775c..1a681f3 100644
--- a/frontend/src/lib/types.ts
+++ b/frontend/src/lib/types.ts
@@ -162,3 +162,82 @@ export interface Insight {
   model_breakdown: Record<string, unknown> | null;
   created_at: string;
 }
+
+// ---------------------------------------------------------------------------
+// Unit prices (v2.30.0) — GET /api/pricing. The backend owns ordering and footnote numbers.
+// ---------------------------------------------------------------------------
+
+export type PriceVerification = "verified" | "stale" | "seed_only" | "none";
+
+export interface PricingPending {
+  id: number;
+  input: number;
+  output: number;
+  observed_at: string;
+}
+
+export interface PricingTier {
+  input: number;
+  output: number;
+  model_ids: string[];
+  source_ids: string[];
+  footnotes: number[];
+  verification: PriceVerification;
+  observed_at: string | null;
+  pending: PricingPending | null;
+}
+
+export interface PricingInRegionTier extends PricingTier {
+  regions: string[];
+}
+
+export interface PricingNote {
+  family_key: string;
+  kind: "promo";
+  min_until: string;
+  prior_price: Record<string, { input: number; output: number }>;
+  text_ko: string;
+  text_en: string;
+  source: "manual_note";
+}
+
+export interface PricingFamily {
+  family_key: string;
+  family: string;
+  provider: "anthropic" | "amazon" | "openai";
+  tiers: {
+    cp: PricingTier | null;
+    global: PricingTier | null;
+    us: PricingTier | null;
+    in_region: PricingInRegionTier[];
+  };
+  notes: PricingNote[];
+}
+
+export interface PricingReference {
+  n: number;
+  id: string;
+  kind: "agreement_offer" | "price_list" | "anthropic_doc" | "official_page" | "manual_note";
+  title_en: string;
+  title_ko: string;
+  url: string | null;
+  as_of: string | null;
+}
+
+export interface PricingModelPrice {
+  input: number;
+  output: number;
+  verification: PriceVerification;
+}
+
+export interface PricingResponse {
+  currency: "USD";
+  unit: "per_1m_tokens";
+  generated_at: string;
+  last_sync: { id: number; started_at: string; finished_at: string | null; status: string } | null;
+  pending_review: number;
+  families: PricingFamily[];
+  models: Record<string, PricingModelPrice>;
+  references: PricingReference[];
+  disclaimer: { en: string; ko: string };
+}
```

#### `t09-pricing-table` — `frontend/src/lib/pricingTable.ts`

<!-- plan-block id=t09-pricing-table path=frontend/src/lib/pricingTable.ts sha256=c7b2e4051a01e7e1e4dec0fb3b29376efa05f98140f282a023877931affb2357 -->
```ts
// 비용 단가 표(/pricing) 순수 로직 (v2.30.0) — 셀 포맷, 배지 판정, /api/pricing `models`로 비용 계산.
// 정렬과 각주 번호는 백엔드(GET /api/pricing)가 정한다. 여기서는 다시 정렬하거나 번호를 매기지 않는다.

import { parseTimestamp } from "./format";
import type { PricingModelPrice, PricingNote, PricingTier } from "./types";

export type PricingTierKey = "cp" | "global" | "us" | "in_region";

export const TIER_LABELS: Record<PricingTierKey, string> = {
  cp: "Claude Platform on AWS",
  global: "Global",
  us: "US",
  in_region: "In-Region",
};

/** "$4.00" — the screen always shows two decimals; exports keep the backend's own number. */
export function formatUnitPrice(v: number): string {
  return `$${v.toFixed(2)}`;
}

/** "$4.00 / $20.00" (input / output). */
export function formatPricePair(t: { input: number; output: number }): string {
  return `${formatUnitPrice(t.input)} / ${formatUnitPrice(t.output)}`;
}

/** UTC calendar date "YYYY-MM-DD" of an API timestamp (offset-less values are UTC), or null. */
export function utcDate(value: string | null | undefined): string | null {
  const timestamp = parseTimestamp(value);
  return timestamp === null ? null : new Date(timestamp).toISOString().slice(0, 10);
}

export type PricingBadge = { kind: "unverified" | "pending" | "promo" | "promo_check"; label: string; title: string };

/** Notes that name a prior price for this tier, narrowed to that tier's prior price only. */
export function notesForTier(notes: PricingNote[], tier: PricingTierKey): PricingNote[] {
  return notes
    .filter((note) => Object.prototype.hasOwnProperty.call(note.prior_price, tier))
    .map((note) => ({ ...note, prior_price: { [tier]: note.prior_price[tier] } }));
}

function priorPriceText(note: PricingNote): string {
  const entries = Object.entries(note.prior_price);
  if (entries.length === 1) return formatPricePair(entries[0][1]);
  return entries
    .map(([tier, price]) => `${TIER_LABELS[tier as PricingTierKey] ?? tier} ${formatPricePair(price)}`)
    .join(", ");
}

/**
 * Badges for one price cell, in display order: not auto-verified, pending review, promotion.
 * A promotion whose `min_until` date (UTC) has passed turns into a "check whether it ended" badge.
 */
export function tierBadges(tier: PricingTier, notes: PricingNote[], lang: "ko" | "en", today: Date): PricingBadge[] {
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const badges: PricingBadge[] = [];
  if (tier.verification === "stale" || tier.verification === "seed_only") {
    const checked = tier.verification === "stale" ? utcDate(tier.observed_at) : null;
    badges.push({
      kind: "unverified",
      label: L("Not auto-verified", "자동 확인 안 됨"),
      title: checked ? L(`Last verified ${checked}`, `마지막 확인 ${checked}`) : L("Initial value", "초기값"),
    });
  }
  if (tier.pending) {
    const next = formatPricePair(tier.pending);
    badges.push({ kind: "pending", label: L("Pending review", "검토 대기"), title: L(`New value ${next}`, `새 값 ${next}`) });
  }
  const todayUtc = today.toISOString().slice(0, 10);
  for (const note of notes) {
    if (note.kind !== "promo") continue;
    const title = `${L("Price before the promotion", "프로모션 이전 단가")} ${priorPriceText(note)}\n${lang === "en" ? note.text_en : note.text_ko}`;
    badges.push(todayUtc > note.min_until
      ? { kind: "promo_check", label: L("Check whether the promotion has ended", "프로모션 종료 여부 확인 필요"), title }
      : {
        kind: "promo",
        label: L(`Promotion (until at least ${note.min_until}, manual note)`, `프로모션(최소 ${note.min_until}까지, 수동 메모)`),
        title,
      });
  }
  return badges;
}

/** USD for one call at the current price of `modelId`; null when the model has no price (shown as "—"). */
export function costFromPrices(
  models: Record<string, PricingModelPrice> | null | undefined,
  modelId: string,
  inputTokens: number | null | undefined,
  outputTokens: number | null | undefined,
): number | null {
  if (!models || !Object.prototype.hasOwnProperty.call(models, modelId)) return null;
  const price = models[modelId];
  // Missing token counts count as zero, like the backend's COALESCE(tokens, 0) row cost.
  return ((inputTokens ?? 0) * price.input + (outputTokens ?? 0) * price.output) / 1_000_000;
}
```

### Task 10 blocks

#### `t10-test` — `frontend/src/components/PricingPanel.test.tsx`

<!-- plan-block id=t10-test path=frontend/src/components/PricingPanel.test.tsx sha256=b19498cf4a50097081482ba48242440012b4c3ddb4170c1369714b4844757178 -->
```tsx
/** 비용 단가 화면 정적 렌더 (v2.30.0) — 응답 순서 그대로의 제공사 섹션, #ref-n 각주, In-Region 여러 줄 셀,
 * 빈 셀 "—", 다운로드 링크, 참고 사항 5개, 면책 문구 두 번. 브라우저 동작은 e2e/pricing.spec.ts가 맡는다.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import type { PricingResponse } from "@/lib/types";
import { pricingFixture } from "../../e2e/fixtures";
import { PricingContent, providerSections } from "./PricingPanel";

function render(lang: "ko" | "en", highlight: number | null = null, data: PricingResponse = pricingFixture): string {
  return renderToStaticMarkup(
    <PricingContent data={data} lang={lang} today={new Date("2026-09-26T12:00:00Z")} highlight={highlight} onFootnote={() => {}} />,
  );
}

const count = (html: string, needle: string) => html.split(needle).length - 1;

/** Markup of one tier cell in a family row, up to its closing </td>. */
function cell(html: string, family: string, tier: string): string {
  const row = html.slice(html.indexOf(`data-family="${family}"`));
  const start = row.indexOf(`data-tier="${tier}"`);
  return row.slice(start, row.indexOf("</td>", start));
}

describe("providerSections", () => {
  test("응답 순서 그대로 연속한 제공사끼리 묶는다 (다시 정렬하지 않는다)", () => {
    expect(providerSections(pricingFixture.families).map((s) => [s.provider, s.families.length]))
      .toEqual([["anthropic", 2], ["amazon", 1], ["openai", 3]]);
    const [fable, , nova, astra] = pricingFixture.families;
    expect(providerSections([astra, fable, nova, astra]).map((s) => s.provider)).toEqual(["openai", "anthropic", "amazon", "openai"]);
  });
});

describe("PricingContent", () => {
  test("제공사 섹션 순서, 고정 열, 소수 둘째 자리 셀, 빈 셀", () => {
    const html = render("ko");
    expect(html.indexOf(">Anthropic Claude</h2>")).toBeLessThan(html.indexOf(">Amazon Nova</h2>"));
    expect(html.indexOf(">Amazon Nova</h2>")).toBeLessThan(html.indexOf(">OpenAI</h2>"));
    expect(count(html, ">Claude Platform on AWS</th>")).toBe(3);
    expect(cell(html, "claude-opus-5-5", "us")).toContain("$4.40 / $22.00");
    expect(cell(html, "nova-2-lite", "cp")).toContain("—");
    expect(cell(html, "nova-2-lite", "cp")).toContain("단가 없음");
  });

  test("In-Region 원소마다 한 줄 (가격, 리전)", () => {
    const inRegion = cell(render("ko"), "gpt-5.4", "in_region");
    expect(count(inRegion, "data-price-line")).toBe(2);
    expect(inRegion).toMatch(/\$2\.75 \/ \$16\.50<\/span> <span[^>]*>us-east-1, us-east-2<\/span>/);
    expect(inRegion).toMatch(/\$2\.50 \/ \$15\.00<\/span> <span[^>]*>us-west-2<\/span>/);
  });

  test("각주는 #ref-n 링크, 참고 자료가 같은 id, 강조는 하나", () => {
    const html = render("ko", 7);
    expect(html).toContain('href="#ref-7"');
    expect(html).toContain('aria-label="참고 자료 7"');
    for (const ref of pricingFixture.references) expect(html).toContain(`id="ref-${ref.n}"`);
    expect(count(html, 'data-highlighted="true"')).toBe(1);
    expect(html).toMatch(/id="ref-7"[^>]*data-highlighted="true"/);
    expect(html).toMatch(/id="ref-10"[^>]*data-kind="manual_note"[^>]*>.*?수동 메모/);
  });

  test("다운로드 링크는 현재 언어의 export download 링크", () => {
    for (const format of ["csv", "md", "json"]) {
      expect(render("ko")).toContain(`href="/api/pricing/export?format=${format}&amp;lang=ko" download=""`);
    }
    expect(render("en")).toContain('href="/api/pricing/export?format=csv&amp;lang=en" download=""');
  });

  test("면책 문구 두 번, 참고 사항 5개, 동기화 상태와 검토 대기 수", () => {
    const html = render("ko");
    expect(count(html, pricingFixture.disclaimer.ko)).toBe(2);
    expect(count(render("en"), pricingFixture.disclaimer.en)).toBe(2);
    expect(count(html.slice(html.indexOf("pricing-notes-title")), "<li>")).toBeGreaterThanOrEqual(5);
    expect(html).toContain("<li>OpenAI는 입력 272K 이하 기준이다</li>");
    expect(html).toContain("완료");
    expect(html).toContain("검토 대기 1건");
    expect(render("en", null, { ...pricingFixture, last_sync: null, pending_review: 0 })).toContain("No automatic check has run yet");
  });

  test("면책 상자의 Anthropic 요금 링크, 참고 자료 확인일, 검토 대기 0건이면 숨김", () => {
    const html = render("ko");
    expect(html).toContain('href="https://platform.claude.com/docs/en/about-claude/pricing"');
    expect(html).toContain("확인일 2026-09-26");
    const none = render("en", null, { ...pricingFixture, pending_review: 0 });
    expect(none).not.toContain("data-pending-count");
    expect(none).not.toContain("pending review");
  });
});
```

#### `t10-fixtures` — `@scratch/patches/t10-fixtures.patch`

<!-- plan-block id=t10-fixtures path=@scratch/patches/t10-fixtures.patch sha256=33647759839739bed6e6076105c669221625529c63416f6e7c0c19bcbfdab054 -->
```diff
diff --git a/frontend/e2e/fixtures.ts b/frontend/e2e/fixtures.ts
index b6bdba1..d2b0a5a 100644
--- a/frontend/e2e/fixtures.ts
+++ b/frontend/e2e/fixtures.ts
@@ -1,4 +1,7 @@
 import type { Page } from "@playwright/test";
+import type {
+  PricingFamily, PricingModelPrice, PricingReference, PricingResponse, PricingTier,
+} from "../src/lib/types";
 
 export const modelCatalog = [
   { id: "anthropic-fable", name: "Anthropic Claude Fable 5.1 (US)" },
@@ -51,6 +54,173 @@ export const categories = [
   { id: "translate", label_ko: "번역", label_en: "Translate" },
 ];
 
+// ── GET /api/pricing (v2.30.0) ─────────────────────────────────────────────
+// Offer ids other than the three real ones quoted in the design (Opus 5.5, GPT 6 Astra, GPT 5.4) are
+// synthetic. Offer tokens, legal-term links and presigned URLs never belong in a fixture.
+
+const OFFER_API = "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html";
+const PRICE_LIST_API = "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html";
+
+function priceTier(input: number, output: number, model_ids: string[], source_id: string, footnote: number,
+  overrides: Partial<PricingTier> = {}): PricingTier {
+  return {
+    input, output, model_ids, source_ids: [source_id], footnotes: [footnote],
+    verification: "verified", observed_at: "2026-09-26T15:00:00Z", pending: null, ...overrides,
+  };
+}
+
+const pricingFamilies: PricingFamily[] = [
+  {
+    family_key: "claude-fable-5-1", family: "Claude Fable 5.1", provider: "anthropic",
+    tiers: {
+      cp: priceTier(10, 50, ["anthropic:claude-fable-5-1"], "anthropic-pricing", 1),
+      global: priceTier(10, 50, ["global.anthropic.claude-fable-5-1"], "offer:offer-e2efable51", 2),
+      us: priceTier(11, 55, ["us.anthropic.claude-fable-5-1"], "offer:offer-e2efable51", 2,
+        { verification: "stale", observed_at: "2026-09-20T03:00:00Z" }),
+      in_region: [],
+    },
+    notes: [],
+  },
+  {
+    family_key: "claude-opus-5-5", family: "Claude Opus 5.5", provider: "anthropic",
+    tiers: {
+      cp: priceTier(4, 20, ["anthropic:claude-opus-5-5"], "anthropic-pricing", 1),
+      global: priceTier(4, 20, ["global.anthropic.claude-opus-5-5"], "offer:offer-7sp77cpl4rveu", 3),
+      us: priceTier(4.4, 22, ["us.anthropic.claude-opus-5-5"], "offer:offer-7sp77cpl4rveu", 3),
+      in_region: [],
+    },
+    notes: [],
+  },
+  {
+    family_key: "nova-2-lite", family: "Nova 2.0 Lite", provider: "amazon",
+    tiers: {
+      cp: null, global: null,
+      us: priceTier(0.33, 2.75, ["us.amazon.nova-2-lite-v1:0"], "pricelist:USE1-Nova2.0Lite-input-tokens", 4,
+        { verification: "seed_only", observed_at: null }),
+      in_region: [],
+    },
+    notes: [],
+  },
+  {
+    family_key: "gpt-6-astra", family: "GPT 6 Astra", provider: "openai",
+    tiers: {
+      cp: null,
+      global: priceTier(10, 50, ["openai:global:global.openai.gpt-6-astra"], "offer:offer-7epta7rbw5aws", 5),
+      us: priceTier(11, 55, ["openai:us:us.openai.gpt-6-astra"], "offer:offer-7epta7rbw5aws", 5),
+      in_region: [{ regions: ["us-west-2"], ...priceTier(11, 55, ["openai:us-west-2:openai.gpt-6-astra"], "offer:offer-7epta7rbw5aws", 5) }],
+    },
+    notes: [],
+  },
+  {
+    family_key: "gpt-5.6-sol", family: "GPT 5.6 Sol", provider: "openai",
+    tiers: {
+      cp: null,
+      global: priceTier(4, 20, ["openai:global:global.openai.gpt-5.6-sol"], "offer:offer-e2esol56", 6),
+      us: null,
+      in_region: [{
+        regions: ["us-east-1", "us-east-2"],
+        ...priceTier(4.4, 22, ["openai:us-east-1:openai.gpt-5.6-sol", "openai:us-east-2:openai.gpt-5.6-sol"], "offer:offer-e2esol56", 6),
+      }],
+    },
+    notes: [{
+      family_key: "gpt-5.6-sol", kind: "promo", min_until: "2026-11-21",
+      prior_price: { in_region: { input: 5.5, output: 33 }, global: { input: 5, output: 30 } },
+      text_ko: "2026-09-23 AWS 모델 카드 기재(현재 미게재), CHANGELOG v2.28.1",
+      text_en: "Listed on the AWS model card on 2026-09-23 (no longer shown), CHANGELOG v2.28.1",
+      source: "manual_note",
+    }],
+  },
+  {
+    // Production has one price for all three GPT 5.4 regions; the us-west-2 split is synthetic so the
+    // e2e suite exercises a multi-line In-Region cell.
+    family_key: "gpt-5.4", family: "GPT 5.4", provider: "openai",
+    tiers: {
+      cp: null, global: null, us: null,
+      in_region: [
+        {
+          regions: ["us-east-1", "us-east-2"],
+          ...priceTier(2.75, 16.5, ["openai:us-east-1:openai.gpt-5.4", "openai:us-east-2:openai.gpt-5.4"], "offer:offer-5l5a5izq5fbec", 7,
+            { pending: { id: 91, input: 3, output: 18, observed_at: "2026-09-26T15:00:00Z" } }),
+        },
+        { regions: ["us-west-2"], ...priceTier(2.5, 15, ["openai:us-west-2:openai.gpt-5.4"], "offer:offer-5l5a5izq5fbec", 7) },
+      ],
+    },
+    notes: [],
+  },
+];
+
+function offerReference(n: number, offerId: string, model: string, as_of: string): PricingReference {
+  return {
+    n, id: `offer:${offerId}`, kind: "agreement_offer",
+    title_en: `Amazon Bedrock agreement offer ${offerId}, ${model}`,
+    title_ko: `Amazon Bedrock 계약 오퍼 ${offerId}, ${model}`,
+    url: OFFER_API, as_of,
+  };
+}
+
+const pricingReferences: PricingReference[] = [
+  {
+    n: 1, id: "anthropic-pricing", kind: "anthropic_doc",
+    title_en: "Anthropic API pricing (Claude Platform on AWS uses standard pricing)",
+    title_ko: "Anthropic API 요금 (Claude Platform on AWS는 표준 요금)",
+    url: "https://platform.claude.com/docs/en/about-claude/pricing#model-pricing", as_of: "2026-09-26",
+  },
+  offerReference(2, "offer-e2efable51", "Claude Fable 5.1", "2026-09-20"),
+  offerReference(3, "offer-7sp77cpl4rveu", "Claude Opus 5.5", "2026-09-26"),
+  {
+    n: 4, id: "pricelist:USE1-Nova2.0Lite-input-tokens", kind: "price_list",
+    title_en: "AWS Price List, USE1-Nova2.0Lite-input-tokens",
+    title_ko: "AWS Price List, USE1-Nova2.0Lite-input-tokens",
+    url: PRICE_LIST_API, as_of: "2026-09-26",
+  },
+  offerReference(5, "offer-7epta7rbw5aws", "GPT 6 Astra", "2026-09-26"),
+  offerReference(6, "offer-e2esol56", "GPT 5.6 Sol", "2026-09-26"),
+  offerReference(7, "offer-5l5a5izq5fbec", "GPT 5.4", "2026-09-26"),
+  {
+    n: 8, id: "official:bedrock-pricing", kind: "official_page",
+    title_en: "Amazon Bedrock pricing", title_ko: "Amazon Bedrock 요금",
+    url: "https://aws.amazon.com/bedrock/pricing/", as_of: null,
+  },
+  {
+    n: 9, id: "official:model-card-openai-gpt-6-astra", kind: "official_page",
+    title_en: "Amazon Bedrock model card, OpenAI GPT 6 Astra", title_ko: "Amazon Bedrock 모델 카드, OpenAI GPT 6 Astra",
+    url: "https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-astra.html", as_of: null,
+  },
+  {
+    n: 10, id: "note:gpt-5.6-sol", kind: "manual_note",
+    title_en: "GPT 5.6 Sol promotion until at least 2026-11-21, listed on the AWS model card on 2026-09-23 (no longer shown), CHANGELOG v2.28.1",
+    title_ko: "GPT 5.6 Sol 프로모션 최소 2026-11-21까지, 2026-09-23 AWS 모델 카드 기재(현재 미게재), CHANGELOG v2.28.1",
+    url: null, as_of: null,
+  },
+];
+
+function pricingModels(families: PricingFamily[]): Record<string, PricingModelPrice> {
+  const models: Record<string, PricingModelPrice> = {};
+  for (const family of families) {
+    const { cp, global, us, in_region } = family.tiers;
+    for (const tier of [cp, global, us, ...in_region]) {
+      if (!tier) continue;
+      for (const id of tier.model_ids) models[id] = { input: tier.input, output: tier.output, verification: tier.verification };
+    }
+  }
+  return models;
+}
+
+export const pricingFixture: PricingResponse = {
+  currency: "USD",
+  unit: "per_1m_tokens",
+  generated_at: "2026-09-26T16:00:00Z",
+  last_sync: { id: 12, started_at: "2026-09-26T15:00:00Z", finished_at: "2026-09-26T15:00:31Z", status: "completed" },
+  pending_review: 1,
+  families: pricingFamilies,
+  models: pricingModels(pricingFamilies),
+  references: pricingReferences,
+  disclaimer: {
+    ko: "이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요.",
+    en: "This price list is compiled automatically from public sources for reference only and is not an official AWS statement. Always confirm final prices on the official pricing pages.",
+  },
+};
+
 /** All API traffic stays in fixtures, including unexpected mutations. */
 export async function mockApi(page: Page) {
   const data = monitoringData();
@@ -65,6 +235,7 @@ export async function mockApi(page: Page) {
       "/api/auto-probe/anomalies": data.anomalies,
       "/api/auto-probe/categories": categories,
       "/api/insights/latest": null,
+
     };
     const body = values[url.pathname];
     await route.fulfill({
```

#### `t10-panel` — `frontend/src/components/PricingPanel.tsx`

<!-- plan-block id=t10-panel path=frontend/src/components/PricingPanel.tsx sha256=288904110b0e3b4df95dbad243d4099df5992ced725de277d334cc41fa0a580f -->
```tsx
"use client";

// 비용 단가 (v2.30.0) — GET /api/pricing 단일 출처. 제공사 섹션, 행 순서, 각주 번호는 응답 그대로 쓴다.
// 공식 단가는 12시간마다 자동 확인되고, 면책 문구는 상단 안내 상자와 참고 자료 끝에 두 번 표기한다.

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchPricing, pricingExportUrl } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useLang } from "@/lib/i18n-context";
import {
  TIER_LABELS, formatPricePair, notesForTier, tierBadges,
  type PricingBadge, type PricingTierKey,
} from "@/lib/pricingTable";
import type {
  PricingFamily, PricingInRegionTier, PricingReference, PricingResponse, PricingTier,
} from "@/lib/types";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { DataEmpty, DataError, DataLoading } from "./DataState";
import RefreshControls from "./RefreshControls";

type Lang = "ko" | "en";

const HIGHLIGHT_MS = 1500;
const TIER_KEYS: PricingTierKey[] = ["cp", "global", "us", "in_region"];
const PROVIDER_LABELS: Record<PricingFamily["provider"], string> = {
  anthropic: "Anthropic Claude",
  amazon: "Amazon Nova",
  openai: "OpenAI",
};
const EXPORTS: { format: "csv" | "md" | "json"; label: string }[] = [
  { format: "csv", label: "CSV" },
  { format: "md", label: "Markdown" },
  { format: "json", label: "JSON" },
];
const OFFICIAL_LINKS: { url: string; en: string; ko: string }[] = [
  { url: "https://aws.amazon.com/bedrock/pricing/", en: "Amazon Bedrock pricing", ko: "Amazon Bedrock 요금" },
  { url: "https://platform.claude.com/docs/en/about-claude/pricing", en: "Anthropic pricing", ko: "Anthropic 요금" },
];
const SYNC_STATUS: Record<string, { en: string; ko: string }> = {
  completed: { en: "completed", ko: "완료" },
  partial: { en: "partial, some sources failed", ko: "일부 출처 실패" },
  failed: { en: "failed", ko: "실패" },
  running: { en: "running", ko: "진행 중" },
};
const NOTES: { en: string; ko: string }[] = [
  { en: "Prices are in USD per 1M tokens, Standard tier input and output", ko: "단가는 USD, 1M 토큰당, Standard 등급 입력과 출력 기준이다" },
  { en: "Global channel prices can differ from the same model's US and In-Region channels", ko: "Global 채널 단가는 같은 모델의 US, In-Region 채널과 다를 수 있다" },
  { en: "OpenAI prices apply to inputs of 272K tokens or less", ko: "OpenAI는 입력 272K 이하 기준이다" },
  { en: "Cache, batch, long-context and priority prices are not included", ko: "캐시, batch, long-context, priority 단가는 포함하지 않는다" },
  { en: "The cost pages use the price in effect at each probe's time", ko: "비용 화면은 각 프로브 시각의 단가로 계산한다" },
];
const CELL = "border-b border-gray-800/60 px-2 py-2.5 align-top";
const STICKY = "sticky left-0 z-10 bg-gray-900";
const BADGE_CLASS: Record<PricingBadge["kind"], string> = {
  unverified: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  pending: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  promo: "border-purple-500/40 bg-purple-500/10 text-purple-300",
  promo_check: "border-rose-500/40 bg-rose-500/10 text-rose-300",
};

/** Consecutive runs of the same provider, in response order (the backend already sorted them). */
export function providerSections(families: PricingFamily[]): { provider: PricingFamily["provider"]; families: PricingFamily[] }[] {
  const sections: { provider: PricingFamily["provider"]; families: PricingFamily[] }[] = [];
  for (const family of families) {
    const last = sections[sections.length - 1];
    if (last && last.provider === family.provider) last.families.push(family);
    else sections.push({ provider: family.provider, families: [family] });
  }
  return sections;
}

function Footnotes({ numbers, lang, onFootnote }: { numbers: number[]; lang: Lang; onFootnote: (n: number) => void }) {
  return (
    <>
      {numbers.map((n) => (
        <sup key={n} className="ml-0.5">
          <a
            href={`#ref-${n}`}
            onClick={() => onFootnote(n)}
            aria-label={lang === "en" ? `Reference ${n}` : `참고 자료 ${n}`}
            className="text-[10px] font-medium text-blue-400 hover:underline"
          >
            [{n}]
          </a>
        </sup>
      ))}
    </>
  );
}

function Badges({ badges }: { badges: PricingBadge[] }) {
  if (badges.length === 0) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {badges.map((badge) => (
        <span
          key={badge.kind}
          data-badge={badge.kind}
          title={badge.title}
          className={`rounded border px-1.5 py-0.5 text-[10px] font-medium leading-tight ${BADGE_CLASS[badge.kind]}`}
        >
          {badge.label}
          <span className="sr-only">, {badge.title}</span>
        </span>
      ))}
    </div>
  );
}

function TierCell({ family, tierKey, lang, today, onFootnote }: {
  family: PricingFamily;
  tierKey: PricingTierKey;
  lang: Lang;
  today: Date;
  onFootnote: (n: number) => void;
}) {
  const single = tierKey === "in_region" ? null : family.tiers[tierKey];
  const entries: (PricingTier | PricingInRegionTier)[] = tierKey === "in_region"
    ? family.tiers.in_region
    : single ? [single] : [];
  if (entries.length === 0) {
    return (
      <td data-tier={tierKey} className={CELL}>
        <span aria-hidden="true" className="text-gray-600">—</span>
        <span className="sr-only">{lang === "en" ? "No price" : "단가 없음"}</span>
      </td>
    );
  }
  const notes = notesForTier(family.notes, tierKey);
  return (
    <td data-tier={tierKey} className={CELL}>
      <div className="space-y-2">
        {entries.map((entry) => (
          <div key={entry.model_ids.join(" ")} data-price-line>
            <span className="whitespace-nowrap tabular-nums text-gray-100" title={entry.model_ids.join("\n")}>
              {formatPricePair(entry)}
            </span>
            {"regions" in entry && <>{" "}<span className="text-gray-400">{entry.regions.join(", ")}</span></>}
            <Footnotes numbers={entry.footnotes} lang={lang} onFootnote={onFootnote} />
            <Badges badges={tierBadges(entry, notes, lang, today)} />
          </div>
        ))}
      </div>
    </td>
  );
}

function ReferenceItem({ reference, lang, highlighted }: { reference: PricingReference; lang: Lang; highlighted: boolean }) {
  const title = lang === "en" ? reference.title_en : reference.title_ko;
  return (
    <li
      id={`ref-${reference.n}`}
      data-kind={reference.kind}
      data-highlighted={highlighted ? "true" : "false"}
      className={`scroll-mt-36 rounded-lg px-2 py-1.5 transition-colors ${highlighted ? "bg-blue-500/15 ring-1 ring-blue-500/40" : ""}`}
    >
      <span className="mr-1.5 tabular-nums text-gray-500">[{reference.n}]</span>
      {reference.kind === "manual_note" && (
        <span className="mr-1.5 rounded border border-purple-500/40 bg-purple-500/10 px-1.5 py-0.5 text-[10px] font-medium text-purple-300">
          {lang === "en" ? "Manual note" : "수동 메모"}
        </span>
      )}
      {reference.url ? (
        <a href={reference.url} target="_blank" rel="noopener noreferrer" className="break-words text-blue-400 hover:underline">
          {title}<span aria-hidden="true"> ↗</span>
        </a>
      ) : (
        <span className="break-words text-gray-300">{title}</span>
      )}
      {reference.as_of && (
        <span className="text-gray-500">, {lang === "en" ? "checked" : "확인일"} {reference.as_of}</span>
      )}
    </li>
  );
}

/** Everything below the page heading once /api/pricing has answered — pure, so vitest renders it statically. */
export function PricingContent({ data, lang, today, highlight, onFootnote }: {
  data: PricingResponse;
  lang: Lang;
  today: Date;
  highlight: number | null;
  onFootnote: (n: number) => void;
}) {
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const sync = data.last_sync;
  const syncStatus = sync ? SYNC_STATUS[sync.status] ?? { en: sync.status, ko: sync.status } : null;
  return (
    <>
      <div
        role="note"
        aria-label={L("Disclaimer", "면책 안내")}
        data-disclaimer="top"
        className="rounded-xl border border-amber-500/50 bg-amber-500/10 p-4 text-sm leading-relaxed text-amber-200"
      >
        <p>{data.disclaimer[lang]}</p>
        <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {OFFICIAL_LINKS.map((link) => (
            <a key={link.url} href={link.url} target="_blank" rel="noopener noreferrer" className="font-medium underline hover:no-underline">
              {L(link.en, link.ko)}<span aria-hidden="true"> ↗</span>
            </a>
          ))}
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-gray-400" data-last-sync>
          {sync && syncStatus ? (
            <>
              {L("Last automatic check", "마지막 자동 확인")}:{" "}
              {sync.finished_at ? (
                <time dateTime={sync.finished_at} className="tabular-nums text-gray-300">{formatDateTime(sync.finished_at, lang)}</time>
              ) : (
                <span className="text-gray-300">{L("in progress", "진행 중")}</span>
              )}
              , {L(syncStatus.en, syncStatus.ko)}
            </>
          ) : (
            L("No automatic check has run yet, initial values are shown.", "자동 확인 기록이 아직 없어 초기값을 표시합니다.")
          )}
          {data.pending_review > 0 && (
            <span data-pending-count className="ml-3 rounded border border-sky-500/40 bg-sky-500/10 px-1.5 py-0.5 text-sky-300">
              {L(`${data.pending_review} pending review`, `검토 대기 ${data.pending_review}건`)}
            </span>
          )}
        </p>
        <div role="group" aria-label={L("Download price list", "가격표 내려받기")} className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-gray-400">{L("Download", "내려받기")}</span>
          {EXPORTS.map((item) => (
            <a key={item.format} href={pricingExportUrl(item.format, lang)} download className="ui-button">
              {item.label}
            </a>
          ))}
        </div>
      </div>

      {data.families.length === 0 && (
        <DataEmpty
          title={L("No unit prices yet.", "표시할 단가가 없습니다.")}
          description={L("No active channel has a price yet. Refresh after the next automatic check.", "활성 채널의 단가가 아직 없습니다. 다음 자동 확인 뒤 새로고침하세요.")}
        />
      )}

      {providerSections(data.families).map((section) => {
        const label = PROVIDER_LABELS[section.provider];
        return (
          <section key={section.provider} aria-labelledby={`pricing-${section.provider}`} className="min-w-0 rounded-xl border border-gray-800 bg-gray-900 p-4">
            <h2 id={`pricing-${section.provider}`} className="mb-3 text-sm font-semibold text-gray-200">{label}</h2>
            {/* relative: sr-only 텍스트(absolute)가 스크롤 영역 밖으로 빠져 페이지 가로 스크롤을 만들지 않게 한다. */}
            <div role="region" aria-label={L(`${label} price table`, `${label} 단가 표`)} tabIndex={0} data-pricing-scroll className="relative overflow-x-auto">
              <table className="w-full min-w-[760px] border-separate border-spacing-0 text-xs">
                <thead>
                  <tr className="text-gray-500">
                    <th scope="col" className={`${STICKY} border-b border-gray-800 py-2 pr-3 text-left font-medium`}>{L("Model", "모델")}</th>
                    {TIER_KEYS.map((key) => (
                      <th key={key} scope="col" className="border-b border-gray-800 px-2 py-2 text-left font-medium">{TIER_LABELS[key]}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {section.families.map((family) => (
                    <tr key={family.family_key} data-family={family.family_key}>
                      <th scope="row" className={`${STICKY} ${CELL} whitespace-nowrap pl-0 pr-3 text-left font-semibold text-gray-200`}>
                        {family.family}
                      </th>
                      {TIER_KEYS.map((key) => (
                        <TierCell key={key} family={family} tierKey={key} lang={lang} today={today} onFootnote={onFootnote} />
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}

      <section aria-labelledby="pricing-notes-title" className="rounded-xl border border-gray-800 bg-gray-900/50 p-4">
        <h2 id="pricing-notes-title" className="mb-2 text-sm font-semibold text-gray-200">{L("Notes", "참고 사항")}</h2>
        <ol className="list-decimal space-y-1 pl-5 text-xs leading-relaxed text-gray-400">
          {NOTES.map((note) => <li key={note.en}>{L(note.en, note.ko)}</li>)}
        </ol>
      </section>

      <section aria-labelledby="pricing-references-title" className="rounded-xl border border-gray-800 bg-gray-900/50 p-4">
        <h2 id="pricing-references-title" className="mb-2 text-sm font-semibold text-gray-200">{L("References", "참고 자료")}</h2>
        <ol className="space-y-0.5 text-xs leading-relaxed">
          {data.references.map((reference) => (
            <ReferenceItem key={reference.id} reference={reference} lang={lang} highlighted={highlight === reference.n} />
          ))}
        </ol>
        <p data-disclaimer="bottom" className="mt-4 border-t border-gray-800 pt-3 text-xs leading-relaxed text-amber-300">
          {data.disclaimer[lang]}
        </p>
      </section>
    </>
  );
}

export default function PricingPanel() {
  const { lang } = useLang();
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const resource = useAsyncResource<PricingResponse>("pricing", fetchPricing);
  const [highlight, setHighlight] = useState<number | null>(null);
  const highlightTimer = useRef<number | undefined>(undefined);

  // The anchor's own hash navigation scrolls to #ref-n; this only adds the 1.5 s highlight.
  const onFootnote = useCallback((n: number) => {
    window.clearTimeout(highlightTimer.current);
    setHighlight(n);
    highlightTimer.current = window.setTimeout(() => setHighlight(null), HIGHLIGHT_MS);
  }, []);
  useEffect(() => () => window.clearTimeout(highlightTimer.current), []);

  return (
    <div className="min-w-0 p-4 sm:p-6 space-y-4 sm:space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-gray-100">{L("Unit Prices", "비용 단가")}</h1>
          <p className="text-sm text-gray-500 mt-1">
            {L(
              "Per-model token prices (USD per 1M tokens), checked against official sources every 12 hours.",
              "모델별 토큰 단가(USD, 1M 토큰당)를 공식 출처에서 12시간마다 자동으로 확인해 보여 줍니다.",
            )}
          </p>
        </div>
        <RefreshControls refreshing={resource.refreshing} onRefresh={() => void resource.refresh()} updatedAt={resource.updatedAt} />
      </div>

      <DataError error={resource.error} resource={L("unit prices", "비용 단가")} onRetry={() => void resource.refresh()} hasData={resource.data !== null} />
      {resource.loading && <DataLoading />}
      {resource.data && (
        <PricingContent data={resource.data} lang={lang} today={new Date()} highlight={highlight} onFootnote={onFootnote} />
      )}
    </div>
  );
}
```

### Task 11 blocks

#### `t11-test-pricing` — `frontend/src/lib/pricing.test.ts`

<!-- plan-block id=t11-test-pricing path=frontend/src/lib/pricing.test.ts sha256=118adeeb5ab81b2477f14b86177deb0dc2f46357820e26e8210a8ce60216c019 -->
```ts
/**
 * 비용 표시 포맷 회귀 (v2.30.0).
 *
 * 프런트 단가 미러(PRICE_TABLE, getPricing, estimateCost)는 없어졌다. 단가는 GET /api/pricing이
 * 단일 출처이고, 호출 비용은 `costFromPrices`(lib/pricingTable.ts)가 그 `models`로 계산한다.
 */
import { describe, expect, test } from "vitest";
import * as pricing from "./pricing";
import { formatCost } from "./pricing";
import { costFromPrices } from "./pricingTable";

describe("formatCost", () => {
  test("null은 대시", () => {
    expect(formatCost(null)).toBe("—");
  });

  test("$0.001 미만은 milli-dollar, $1 미만은 cent, 그 이상은 소수 넷째 자리", () => {
    expect(formatCost(0)).toBe("$0.00m");
    expect(formatCost(0.0005)).toBe("$0.50m");
    expect(formatCost(0.0132)).toBe("$1.32¢");
    expect(formatCost(13.2)).toBe("$13.2000");
    expect(formatCost(168)).toBe("$168.0000");
  });
});

describe("pricing 모듈 — 단가 미러 제거", () => {
  test("formatCost만 export한다", () => {
    expect(Object.keys(pricing).sort()).toEqual(["formatCost"]);
  });
});

describe("costFromPrices + formatCost", () => {
  const models = {
    "openai:us-east-1:openai.gpt-6-sol": { input: 2.2, output: 11, verification: "verified" as const },
  };

  test("API 단가로 계산한 비용을 포맷한다", () => {
    expect(formatCost(costFromPrices(models, "openai:us-east-1:openai.gpt-6-sol", 1_000_000, 1_000_000))).toBe("$13.2000");
    expect(formatCost(costFromPrices(models, "openai:us-east-1:openai.gpt-6-sol", 1000, 100))).toBe("$0.33¢");
  });

  test("단가가 없는 모델은 대시", () => {
    expect(formatCost(costFromPrices(models, "global.anthropic.claude-opus-5-5", 1000, 100))).toBe("—");
  });
});
```

#### `t11-test-compare` — `frontend/src/components/ComparePanel.test.ts`

<!-- plan-block id=t11-test-compare path=frontend/src/components/ComparePanel.test.ts sha256=9aa5c5aeb503db84785766ae5009dfdddbe5506f8ba4fe681c4076dc9a722f3e -->
```ts
/** Comparison Lab 비교 매트릭스 (v2.30.0) — 비용은 /api/pricing `models`의 현재 단가로 계산한다.
 *
 * 단가가 없는 모델은 비용 null("—")이고 최저 비용 강조에서 빠진다. 프런트 단가 미러의 prefix fallback
 * (예: GPT 6 Sol US CRIS가 in-region 단가로 조용히 매칭)은 더 이상 일어나지 않는다.
 */
import { describe, expect, test } from "vitest";
import type { CompareResult } from "@/lib/api";
import type { PricingModelPrice } from "@/lib/types";
import { compareMatrix, type RunningState } from "./ComparePanel";

function run(model_id: string, result: Partial<CompareResult> | null, error?: string): RunningState {
  return {
    model_id, model_name: model_id, text: "",
    result: result === null ? undefined : {
      model_id, model_name: model_id, status: "success", ttft_ms: 500, total_latency_ms: 2000,
      server_latency_ms: null, tps: 50, input_tokens: 1000, output_tokens: 1000, output_text: "", ...result,
    },
    error,
  };
}

const prices: Record<string, PricingModelPrice> = {
  "openai:us-east-1:openai.gpt-6-sol": { input: 2.2, output: 11, verification: "verified" },
  "openai:global:global.openai.gpt-6-luna": { input: 0.1, output: 0.5, verification: "verified" },
};

describe("compareMatrix", () => {
  test("비용은 API 단가로 계산하고 최저 비용은 단가가 있는 모델 중에서 고른다", () => {
    const matrix = compareMatrix([
      run("openai:us-east-1:openai.gpt-6-sol", {}),
      run("openai:global:global.openai.gpt-6-luna", {}),
      run("openai:us:us.openai.gpt-6-sol", {}),
    ], prices)!;
    const cost = Object.fromEntries(matrix.list.map((row) => [row.model_id, row.cost]));
    expect(cost["openai:us-east-1:openai.gpt-6-sol"]).toBeCloseTo(0.0132, 12);
    expect(cost["openai:global:global.openai.gpt-6-luna"]).toBeCloseTo(0.0006, 12);
    expect(cost["openai:us:us.openai.gpt-6-sol"]).toBeNull();
    expect(matrix.bestCost).toBeCloseTo(0.0006, 12);
  });

  test("단가를 못 받았으면 모든 비용이 null이고 최저 비용도 null", () => {
    const matrix = compareMatrix([run("openai:us-east-1:openai.gpt-6-sol", {})], null)!;
    expect(matrix.list[0].cost).toBeNull();
    expect(matrix.bestCost).toBeNull();
  });

  test("성공한 모델만 매트릭스에 들어가고, 하나도 없으면 null", () => {
    const matrix = compareMatrix([
      run("openai:us-east-1:openai.gpt-6-sol", { ttft_ms: 300, tps: 80 }),
      run("openai:global:global.openai.gpt-6-luna", { status: "error" }),
      run("openai:us:us.openai.gpt-6-sol", null, "throttled"),
    ], prices)!;
    expect(matrix.list.map((row) => row.model_id)).toEqual(["openai:us-east-1:openai.gpt-6-sol"]);
    expect(matrix.bestTtft).toBe(300);
    expect(matrix.bestTps).toBe(80);
    expect(compareMatrix([run("openai:us:us.openai.gpt-6-sol", null, "throttled")], prices)).toBeNull();
  });
});
```

#### `t11-components` — `@scratch/patches/t11-components.patch`

<!-- plan-block id=t11-components path=@scratch/patches/t11-components.patch sha256=1e3aafa79fbfb584337eec55de0cacdad0e1be34d5955e82feae69b6f67743fd -->
```diff
diff --git a/frontend/src/components/ComparePanel.tsx b/frontend/src/components/ComparePanel.tsx
index 5f51956..4572a42 100644
--- a/frontend/src/components/ComparePanel.tsx
+++ b/frontend/src/components/ComparePanel.tsx
@@ -1,11 +1,12 @@
 "use client";
 
 import { useEffect, useMemo, useState } from "react";
-import { ModelInfo, AuthUser } from "@/lib/types";
-import { compareStream, CompareResult, fetchModels } from "@/lib/api";
+import { ModelInfo, AuthUser, PricingModelPrice } from "@/lib/types";
+import { compareStream, CompareResult, fetchModels, fetchPricing } from "@/lib/api";
 import { useLang } from "@/lib/i18n-context";
 import { groupByFamily, sortResults } from "@/lib/sortModels";
-import { estimateCost, formatCost } from "@/lib/pricing";
+import { formatCost } from "@/lib/pricing";
+import { costFromPrices } from "@/lib/pricingTable";
 import MessageMarkdown from "./chat/MessageMarkdown";
 
 interface Props {
@@ -120,7 +121,7 @@ const SUGGESTED_COMPARE_PROMPTS_EN: { label: string; prompt: string }[] = [
   },
 ];
 
-interface RunningState {
+export interface RunningState {
   model_id: string;
   model_name: string;
   text: string;
@@ -129,6 +130,40 @@ interface RunningState {
   error?: string;
 }
 
+/**
+ * 비교 매트릭스 — 성공한 모델만, 최단 TTFT / 최단 latency / 최고 TPS / 최저 비용.
+ * 비용은 /api/pricing `models`의 현재 단가(v2.30.0). 단가가 없는 모델은 비용 null("—")이고
+ * 최저 비용 강조 후보에서 빠진다.
+ */
+export function compareMatrix(runs: RunningState[], prices: Record<string, PricingModelPrice> | null) {
+  const list = runs
+    .filter((r) => r.result?.status === "success")
+    .map((r) => ({
+      ...r,
+      cost: costFromPrices(prices, r.model_id, r.result!.input_tokens, r.result!.output_tokens),
+    }));
+  if (list.length === 0) return null;
+  const min = (sel: (x: (typeof list)[0]) => number | null): number | null =>
+    list.reduce<number | null>((acc, x) => {
+      const v = sel(x);
+      if (v === null) return acc;
+      return acc === null || v < acc ? v : acc;
+    }, null);
+  const max = (sel: (x: (typeof list)[0]) => number | null): number | null =>
+    list.reduce<number | null>((acc, x) => {
+      const v = sel(x);
+      if (v === null) return acc;
+      return acc === null || v > acc ? v : acc;
+    }, null);
+  return {
+    list,
+    bestTtft: min((x) => x.result!.ttft_ms),
+    bestLatency: min((x) => x.result!.total_latency_ms),
+    bestTps: max((x) => x.result!.tps),
+    bestCost: min((x) => x.cost),
+  };
+}
+
 export default function ComparePanel({ user, onLoginClick }: Props) {
   const { lang } = useLang();
 
@@ -141,9 +176,12 @@ export default function ComparePanel({ user, onLoginClick }: Props) {
   const [runs, setRuns] = useState<Map<string, RunningState>>(new Map());
   const [error, setError] = useState<string | null>(null);
   const [controller, setController] = useState<AbortController | null>(null);
+  const [prices, setPrices] = useState<Record<string, PricingModelPrice> | null>(null);
 
   useEffect(() => {
     fetchModels().then(setModels).catch((e) => console.error(e));
+    // 단가를 못 받으면 비용 열만 "—"로 두고 비교는 계속한다.
+    fetchPricing().then((pricing) => setPrices(pricing.models)).catch((e) => console.error(e));
   }, []);
 
   const sortedModels = useMemo(
@@ -239,34 +277,7 @@ export default function ComparePanel({ user, onLoginClick }: Props) {
   const runArray = Array.from(runs.values()).sort((a, b) => a.model_name.localeCompare(b.model_name));
 
   // 비교 매트릭스 - 최단 TTFT / 최단 latency / 최고 TPS / 최저 비용 강조.
-  const matrix = useMemo(() => {
-    const list = runArray
-      .filter((r) => r.result?.status === "success")
-      .map((r) => {
-        const cost = estimateCost(r.model_id, r.result!.input_tokens, r.result!.output_tokens);
-        return { ...r, cost };
-      });
-    if (list.length === 0) return null;
-    const min = (sel: (x: (typeof list)[0]) => number | null): number | null =>
-      list.reduce<number | null>((acc, x) => {
-        const v = sel(x);
-        if (v === null) return acc;
-        return acc === null || v < acc ? v : acc;
-      }, null);
-    const max = (sel: (x: (typeof list)[0]) => number | null): number | null =>
-      list.reduce<number | null>((acc, x) => {
-        const v = sel(x);
-        if (v === null) return acc;
-        return acc === null || v > acc ? v : acc;
-      }, null);
-    return {
-      list,
-      bestTtft: min((x) => x.result!.ttft_ms),
-      bestLatency: min((x) => x.result!.total_latency_ms),
-      bestTps: max((x) => x.result!.tps),
-      bestCost: min((x) => x.cost),
-    };
-  }, [runArray]);
+  const matrix = useMemo(() => compareMatrix(runArray, prices), [runArray, prices]);
 
   return (
     <div className="p-6 space-y-6 max-w-7xl mx-auto">
@@ -465,8 +476,8 @@ export default function ComparePanel({ user, onLoginClick }: Props) {
           </table>
           <p className="text-[10px] text-gray-600 mt-2">
             {lang === "en"
-              ? "Best value per column shown in green. Cost is estimated from public Bedrock/Anthropic pricing."
-              : "각 컬럼의 최적 값을 녹색으로 강조. 비용은 Bedrock/Anthropic 공개 단가 기반 추정치입니다."}
+              ? "Best value per column shown in green. Cost is estimated from the current prices on the Unit Prices page."
+              : "각 컬럼의 최적 값을 녹색으로 강조. 비용은 비용 단가 메뉴의 현재 단가로 계산한 추정치입니다."}
           </p>
         </div>
       )}
diff --git a/frontend/src/components/CostDashboardPanel.tsx b/frontend/src/components/CostDashboardPanel.tsx
index de71dc5..eb123ac 100644
--- a/frontend/src/components/CostDashboardPanel.tsx
+++ b/frontend/src/components/CostDashboardPanel.tsx
@@ -1,6 +1,7 @@
 "use client";
 
 import { useCallback, useEffect, useState } from "react";
+import Link from "next/link";
 import {
   fetchCostSummary,
   fetchChannelCompare,
@@ -252,18 +253,22 @@ export default function CostDashboardPanel() {
             cost = input_tokens × input_price/1M + output_tokens × output_price/1M
           </code>
         </p>
-        <p>
+        <p data-cost-methodology>
           {lang === "en"
-            ? "Token counts come from each model's response usage object (per-call). Public unit prices are stored in `pricing.py` (backend) and `lib/pricing.ts` (frontend) and must be updated together when AWS/Anthropic publishes new tiers."
-            : "토큰 수는 모델 응답의 usage 객체에서 호출별로 수집합니다. 공개 단가는 `pricing.py`(backend) + `lib/pricing.ts`(frontend)에 정의되어 있고 AWS/Anthropic의 단가 변경 시 함께 업데이트해야 합니다."}
+            ? "Token counts come from each model's response usage object (per call). Unit prices are refreshed from official sources every 12 hours, and each probe is costed at the price in effect at its time. See "
+            : "토큰 수는 모델 응답의 usage 객체에서 호출별로 수집합니다. 단가는 공식 출처에서 12시간마다 자동 갱신되며 각 프로브 시각의 단가로 계산합니다. 모델별 단가와 출처는 "}
+          <Link href="/pricing" className="text-blue-400 hover:underline">{lang === "en" ? "Unit Prices" : "비용 단가"}</Link>
+          {lang === "en" ? " for per-model prices and sources." : " 메뉴를 참고하세요."}
         </p>
         <p>
           <span className="text-gray-300 font-semibold">
             {lang === "en" ? "Channel comparison" : "채널 비교"}:
           </span>{" "}
           {lang === "en"
-            ? "Bedrock Global / US use cross-region inference profiles; Anthropic (CP on AWS) uses the vendor's external endpoint (aws-external-anthropic.*.api.aws). Unit prices may differ slightly across channels — this dashboard reports the actual numbers, not assumptions."
-            : "Bedrock Global / US는 cross-region inference profile, Anthropic CP on AWS는 vendor external endpoint(aws-external-anthropic.*.api.aws)를 사용합니다. 채널별 단가가 다를 수 있으며 본 대시보드는 실측 수치 그대로를 보여줍니다."}
+            ? "Bedrock Global / US use cross-region inference profiles; Anthropic (CP on AWS) uses the vendor's external endpoint (aws-external-anthropic.*.api.aws). Unit prices are refreshed from official sources every 12 hours and each probe is costed at the price in effect at its time, see "
+            : "Bedrock Global / US는 cross-region inference profile, Anthropic CP on AWS는 vendor external endpoint(aws-external-anthropic.*.api.aws)를 사용합니다. 단가는 공식 출처에서 12시간마다 자동 갱신되며 각 프로브 시각의 단가로 계산합니다. 채널별 단가는 "}
+          <Link href="/pricing" className="text-blue-400 hover:underline">{lang === "en" ? "Unit Prices" : "비용 단가"}</Link>
+          {lang === "en" ? "." : " 메뉴를 참고하세요."}
         </p>
         <p>
           <span className="text-gray-300 font-semibold">
diff --git a/frontend/src/components/ModelExplorer.tsx b/frontend/src/components/ModelExplorer.tsx
index dbef93b..1e33a60 100644
--- a/frontend/src/components/ModelExplorer.tsx
+++ b/frontend/src/components/ModelExplorer.tsx
@@ -3,12 +3,13 @@
 // Model Explorer (v2.9.0) — 모니터링 중인 전체 모델 카드 그리드 + 상세 모달.
 // 참조 UX: aws-samples Bedrock Central의 Explore Models (검색/필터 + 카드 + 상세).
 // 데이터는 /api/models(공개)에서 — 모델 추가 시 자동 반영, 하드코딩 없음.
+// 단가는 /api/pricing `models`를 페이지에서 한 번 받아 카드와 상세에 내려준다 (v2.30.0).
 
 import { useId, useMemo, useRef, useState } from "react";
-import { ModelInfo } from "@/lib/types";
-import { fetchModels } from "@/lib/api";
+import { ModelInfo, PricingModelPrice, PricingResponse } from "@/lib/types";
+import { fetchModels, fetchPricing } from "@/lib/api";
 import { useLang, useT } from "@/lib/i18n-context";
-import { getPricing } from "@/lib/pricing";
+import { formatUnitPrice, formatPricePair } from "@/lib/pricingTable";
 import { sortResults, isExcludedModel } from "@/lib/sortModels";
 import { useAsyncResource } from "@/hooks/useAsyncResource";
 import { DataEmpty, DataError, DataLoading } from "@/components/DataState";
@@ -73,10 +74,13 @@ function CopyButton({ text, label }: { text: string; label: string }) {
   );
 }
 
-function DetailModal({ model, onClose }: { model: ModelInfo; onClose: () => void }) {
+function DetailModal({ model, price, onClose }: {
+  model: ModelInfo;
+  price: PricingModelPrice | null;
+  onClose: () => void;
+}) {
   const { lang } = useLang();
   const ch = channelOf(model.id);
-  const price = getPricing(model.id);
   const examples = codeExamples(model.id, lang === "en" ? "en" : "ko");
   const links = modelLinks(model.id, model.name, lang === "en" ? "en" : "ko");
   const [tab, setTab] = useState(0);
@@ -112,8 +116,8 @@ function DetailModal({ model, onClose }: { model: ModelInfo; onClose: () => void
             <div className="text-gray-500">{lang === "en" ? "Pricing (per 1M tokens)" : "토큰 단가 (1M 기준)"}</div>
             {price ? (
               <div className="text-gray-200 tabular-nums">
-                Input <span className="font-semibold">${price.input}</span> / Output{" "}
-                <span className="font-semibold">${price.output}</span>
+                {lang === "en" ? "Input" : "입력"} <span className="font-semibold">{formatUnitPrice(price.input)}</span>
+                {" / "}{lang === "en" ? "Output" : "출력"} <span className="font-semibold">{formatUnitPrice(price.output)}</span>
               </div>
             ) : (
               <div className="text-gray-500">{lang === "en" ? "Pricing unavailable" : "단가 정보 없음"}</div>
@@ -194,6 +198,10 @@ export default function ModelExplorer() {
   const { lang } = useLang();
   const t = useT();
   const resource = useAsyncResource<ModelInfo[]>("model-catalog", fetchModels);
+  const pricing = useAsyncResource<PricingResponse>("pricing", fetchPricing);
+  const prices = pricing.data?.models ?? null;
+  const priceOf = (id: string): PricingModelPrice | null =>
+    prices && Object.prototype.hasOwnProperty.call(prices, id) ? prices[id] : null;
   const [search, setSearch] = useState("");
   const [channel, setChannel] = useState<ChannelType | "all">("all");
   const [selected, setSelected] = useState<ModelInfo | null>(null);
@@ -226,7 +234,11 @@ export default function ModelExplorer() {
               : "모델을 선택하면 호출 ID·코드 예제·연결 링크를 볼 수 있습니다."}
           </p>
         </div>
-        <RefreshControls refreshing={resource.refreshing} onRefresh={resource.refresh} updatedAt={resource.updatedAt} />
+        <RefreshControls
+          refreshing={resource.refreshing || pricing.refreshing}
+          onRefresh={() => { void resource.refresh(); void pricing.refresh(); }}
+          updatedAt={resource.updatedAt}
+        />
       </div>
 
       {/* 검색 + 채널 필터 */}
@@ -266,6 +278,8 @@ export default function ModelExplorer() {
 
       <DataError error={resource.error} resource={lang === "en" ? "model catalog" : "모델 카탈로그"}
                  onRetry={resource.refresh} hasData={models.length > 0} />
+      <DataError error={pricing.error} resource={lang === "en" ? "unit prices" : "비용 단가"}
+                 onRetry={pricing.refresh} hasData={prices !== null} />
       {resource.loading && <DataLoading />}
       {!resource.error && resource.data !== null && models.length === 0 && (
         <DataEmpty title={lang === "en" ? "No models available." : "등록된 모델이 없습니다."}
@@ -280,7 +294,7 @@ export default function ModelExplorer() {
       <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
         {filtered.map((m) => {
           const ch = channelOf(m.id);
-          const price = getPricing(m.id);
+          const price = priceOf(m.id);
           return (
             <button
               key={m.id}
@@ -301,14 +315,17 @@ export default function ModelExplorer() {
               </div>
               <code className="block text-[11px] text-gray-500 break-all mt-1.5">{m.id}</code>
               <div className="text-[11px] text-gray-500 mt-2 tabular-nums">
-                {price ? `$${price.input} / $${price.output} (1M in/out)` : (lang === "en" ? "Pricing unavailable" : "단가 정보 없음")}
+                {price
+                  ? `${formatPricePair(price)} ${lang === "en" ? "(per 1M tokens, in/out)" : "(1M 토큰당 입력/출력)"}`
+                  : pricing.loading ? (lang === "en" ? "Loading prices…" : "단가 불러오는 중…")
+                    : (lang === "en" ? "Pricing unavailable" : "단가 정보 없음")}
               </div>
             </button>
           );
         })}
       </div>
 
-      {selected && <DetailModal key={selected.id} model={selected} onClose={() => setSelected(null)} />}
+      {selected && <DetailModal key={selected.id} model={selected} price={priceOf(selected.id)} onClose={() => setSelected(null)} />}
     </div>
   );
 }
```

### Task 12 blocks

#### `t12-spec` — `frontend/e2e/pricing.spec.ts`

<!-- plan-block id=t12-spec path=frontend/e2e/pricing.spec.ts sha256=af1a497988eebe34895a9b9656a3a4d8bed705950b28ddebb0a52356d994d2df -->
```ts
import { expect, test } from "@playwright/test";
import { mockApi, pricingFixture } from "./fixtures";

const DISCLAIMER_KO = pricingFixture.disclaimer.ko;
const EXPORT_EXT = { csv: "csv", md: "md", json: "json" } as const;

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  // The promotion badge depends on today's date (min_until 2026-11-21); timers keep running.
  await page.clock.setFixedTime(new Date("2026-09-26T12:00:00Z"));
});

test("unit prices render the backend table, badges and both disclaimers", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/pricing");
  await expect(page.getByRole("heading", { name: "비용 단가", level: 1, exact: true })).toBeVisible();
  await expect(page).toHaveTitle("비용 단가 | LLM Monitor");

  const nav = page.getByRole("navigation", { name: "주요 메뉴" });
  await expect(nav.getByRole("link", { name: "비용 단가", exact: true })).toHaveAttribute("aria-current", "page");
  const labels = await nav.getByRole("link").allTextContents();
  expect(labels.indexOf("비용 단가")).toBe(labels.indexOf("비용") + 1);

  await expect(page.getByRole("note", { name: "면책 안내" })).toContainText(DISCLAIMER_KO);
  await expect(page.getByRole("note", { name: "면책 안내" }).getByRole("link", { name: "Amazon Bedrock 요금" }))
    .toHaveAttribute("href", "https://aws.amazon.com/bedrock/pricing/");
  await expect(page.locator('[data-disclaimer="bottom"]')).toHaveText(DISCLAIMER_KO);
  await expect(page.locator("[data-last-sync]")).toContainText("마지막 자동 확인");
  await expect(page.locator("[data-last-sync]")).toContainText("완료");
  await expect(page.locator("[data-pending-count]")).toHaveText("검토 대기 1건");

  await expect(page.getByRole("main").getByRole("heading", { level: 2 }))
    .toHaveText(["Anthropic Claude", "Amazon Nova", "OpenAI", "참고 사항", "참고 자료"]);
  await expect(page.getByRole("region", { name: "OpenAI 단가 표" }).getByRole("rowheader"))
    .toHaveText(["GPT 6 Astra", "GPT 5.6 Sol", "GPT 5.4"]);
  await expect(page.getByRole("region", { name: "Anthropic Claude 단가 표" }).getByRole("columnheader"))
    .toHaveText(["모델", "Claude Platform on AWS", "Global", "US", "In-Region"]);

  const opus = page.locator('tr[data-family="claude-opus-5-5"]');
  await expect(opus.locator('td[data-tier="cp"]')).toContainText("$4.00 / $20.00");
  await expect(opus.locator('td[data-tier="us"]')).toContainText("$4.40 / $22.00");
  await expect(opus.locator('td[data-tier="in_region"]')).toHaveText("—단가 없음");

  const gpt54 = page.locator('tr[data-family="gpt-5.4"] td[data-tier="in_region"] [data-price-line]');
  await expect(gpt54).toHaveCount(2);
  await expect(gpt54.nth(0)).toContainText("$2.75 / $16.50 us-east-1, us-east-2");
  await expect(gpt54.nth(1)).toContainText("$2.50 / $15.00 us-west-2");
  await expect(gpt54.nth(0).locator('[data-badge="pending"]')).toHaveAttribute("title", "새 값 $3.00 / $18.00");

  const fableUs = page.locator('tr[data-family="claude-fable-5-1"] td[data-tier="us"] [data-badge="unverified"]');
  await expect(fableUs).toContainText("자동 확인 안 됨");
  await expect(fableUs).toHaveAttribute("title", "마지막 확인 2026-09-20");
  await expect(page.locator('tr[data-family="nova-2-lite"] [data-badge="unverified"]')).toHaveAttribute("title", "초기값");
  const promo = page.locator('tr[data-family="gpt-5.6-sol"] [data-badge="promo"]');
  await expect(promo).toHaveCount(2);
  await expect(promo.first()).toContainText("프로모션(최소 2026-11-21까지, 수동 메모)");
  await expect(page.locator('tr[data-family="gpt-5.6-sol"] td[data-tier="in_region"] [data-badge="promo"]'))
    .toHaveAttribute("title", /^프로모션 이전 단가 \$5\.50 \/ \$33\.00\n2026-09-23/);

  const notes = page.getByRole("region", { name: "참고 사항" }).getByRole("listitem");
  await expect(notes).toHaveText([
    "단가는 USD, 1M 토큰당, Standard 등급 입력과 출력 기준이다",
    "Global 채널 단가는 같은 모델의 US, In-Region 채널과 다를 수 있다",
    "OpenAI는 입력 272K 이하 기준이다",
    "캐시, batch, long-context, priority 단가는 포함하지 않는다",
    "비용 화면은 각 프로브 시각의 단가로 계산한다",
  ]);
  const references = page.getByRole("region", { name: "참고 자료" }).getByRole("listitem");
  await expect(references).toHaveCount(pricingFixture.references.length);
  await expect(page.locator("#ref-1").getByRole("link")).toHaveAttribute("rel", "noopener noreferrer");
  await expect(page.locator("#ref-10")).toContainText("수동 메모");
  await expect(page.locator("#ref-10").getByRole("link")).toHaveCount(0);
});

test("a promotion past its minimum date asks to check whether it ended", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-11-22T00:00:00Z"));
  await page.goto("/pricing");
  const sol = page.locator('tr[data-family="gpt-5.6-sol"]');
  await expect(sol.locator('[data-badge="promo_check"]')).toHaveCount(2);
  await expect(sol.locator('[data-badge="promo_check"]').first()).toContainText("프로모션 종료 여부 확인 필요");
  await expect(sol.locator('[data-badge="promo"]')).toHaveCount(0);
});

test("a footnote jumps to its reference and highlights it for 1.5 seconds", async ({ page }) => {
  await page.goto("/pricing");
  await page.locator('tr[data-family="gpt-5.4"]').getByRole("link", { name: "참고 자료 7" }).first().click();
  await expect(page).toHaveURL(/#ref-7$/);
  const reference = page.locator("#ref-7");
  await expect(reference).toHaveAttribute("data-highlighted", "true");
  await expect(reference).toBeInViewport();
  const header = (await page.locator("header").boundingBox())!;
  expect((await reference.boundingBox())!.y).toBeGreaterThanOrEqual(header.y + header.height);
  await expect(reference).toHaveAttribute("data-highlighted", "false", { timeout: 3000 });
});

test("download links point at the export endpoint in the current language", async ({ page }) => {
  // Chromium sends <a download> requests from the download manager, outside Playwright routing
  // (checked on the dev host), so the test fetches each link's href through the intercepted route.
  const requested: string[] = [];
  await page.route("**/api/pricing/export?*", (route) => {
    const url = new URL(route.request().url());
    requested.push(`${url.searchParams.get("format")}:${url.searchParams.get("lang")}`);
    const ext = EXPORT_EXT[url.searchParams.get("format") as keyof typeof EXPORT_EXT];
    return route.fulfill({
      status: 200,
      contentType: "text/plain; charset=utf-8",
      headers: { "Content-Disposition": `attachment; filename="llm-monitor-unit-prices-2026-09-26.${ext}"` },
      body: DISCLAIMER_KO,
    });
  });
  await page.goto("/pricing");
  const group = page.getByRole("group", { name: "가격표 내려받기" });
  for (const [label, format] of [["CSV", "csv"], ["Markdown", "md"], ["JSON", "json"]] as const) {
    const link = group.getByRole("link", { name: label, exact: true });
    await expect(link).toHaveAttribute("href", `/api/pricing/export?format=${format}&lang=ko`);
    await expect(link).toHaveAttribute("download", "");
    const disposition = await link.evaluate(async (element) => {
      const response = await fetch((element as HTMLAnchorElement).href);
      return response.headers.get("content-disposition");
    });
    expect(disposition).toBe(`attachment; filename="llm-monitor-unit-prices-2026-09-26.${EXPORT_EXT[format]}"`);
  }
  expect(requested).toEqual(["csv:ko", "md:ko", "json:ko"]);

  await page.locator('header button[lang="en"]:visible').click();
  const english = page.getByRole("group", { name: "Download price list" });
  await expect(english.getByRole("link", { name: "CSV", exact: true })).toHaveAttribute("href", "/api/pricing/export?format=csv&lang=en");
  await expect(page.getByRole("note", { name: "Disclaimer" })).toContainText(pricingFixture.disclaimer.en);
});

test("a 375px phone scrolls only the price table, with the model column pinned", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/pricing");
  const table = page.getByRole("region", { name: "OpenAI 단가 표" });
  await expect(table.getByRole("rowheader").first()).toBeVisible();
  for (const theme of ["dark", "light"]) {
    await page.evaluate((value) => document.documentElement.classList.toggle("light", value === "light"), theme);
    await expect.poll(() => page.evaluate(() => {
      const root = document.scrollingElement!;
      return root.scrollWidth <= root.clientWidth;
    })).toBe(true);
  }
  expect(await table.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
  await table.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
  const box = (await table.boundingBox())!;
  const model = (await table.getByRole("rowheader").first().boundingBox())!;
  expect(Math.abs(model.x - box.x)).toBeLessThan(2);

  await page.locator("header button[aria-controls]").click();
  await expect(page.getByRole("navigation", { name: "모바일 메뉴" }).getByRole("link", { name: "비용 단가", exact: true }))
    .toHaveAttribute("aria-current", "page");
});

test("a failed price request offers a retry and is not shown as an empty table", async ({ page }) => {
  let fail = true;
  await page.route("**/api/pricing", (route) => fail
    ? route.fulfill({ status: 503, json: { detail: "Unavailable" } })
    : route.fallback());
  await page.goto("/pricing");
  const error = page.getByRole("alert").filter({ hasText: "비용 단가" });
  await expect(error).toBeVisible();
  await expect(page.getByText("표시할 단가가 없습니다.", { exact: true })).toHaveCount(0);
  fail = false;
  await error.getByRole("button", { name: "다시 시도" }).click();
  await expect(page.locator('tr[data-family="claude-opus-5-5"]')).toBeVisible();
});

test("Model Explorer cards and details use prices from /api/pricing", async ({ page }) => {
  await page.route("**/api/models", (route) => route.fulfill({ json: [
    { id: "global.anthropic.claude-fable-5-1", name: "Bedrock Claude Fable 5.1 (Global)" },
    { id: "openai:us:us.openai.gpt-6-sol", name: "OpenAI GPT 6 Sol (US)" },
  ] }));
  await page.route("**/api/pricing", (route) => route.fulfill({ json: {
    ...pricingFixture,
    models: { "global.anthropic.claude-fable-5-1": { input: 12.34, output: 56.78, verification: "verified" } },
  } }));
  await page.goto("/models");
  const fable = page.getByRole("button", { name: "Bedrock Claude Fable 5.1 (Global)", exact: true });
  await expect(fable).toContainText("$12.34 / $56.78 (1M 토큰당 입력/출력)");
  await expect(page.getByRole("button", { name: "OpenAI GPT 6 Sol (US)", exact: true })).toContainText("단가 정보 없음");
  await fable.click();
  await expect(page.getByRole("dialog", { name: "Bedrock Claude Fable 5.1 (Global)" })).toContainText("입력 $12.34 / 출력 $56.78");
});

test("the cost methodology links to the unit price page", async ({ page }) => {
  await page.goto("/cost");
  const link = page.locator("[data-cost-methodology]").getByRole("link", { name: "비용 단가", exact: true });
  await expect(link).toHaveAttribute("href", "/pricing");
  await link.click();
  await expect(page).toHaveURL(/\/pricing$/);
  await expect(page.getByRole("heading", { name: "비용 단가", level: 1, exact: true })).toBeVisible();
});
```

### Task 13 blocks

#### `t13-tests` — `@scratch/patches/t13-tests.patch`

<!-- plan-block id=t13-tests path=@scratch/patches/t13-tests.patch sha256=59960137ae7e53e6e70ef4844b1ced1d4142e34cd48e9578019a1e3ec3656db2 -->
```diff
diff --git a/cdk/test/image-pinning.test.ts b/cdk/test/image-pinning.test.ts
index d35f7ea..4b6049e 100644
--- a/cdk/test/image-pinning.test.ts
+++ b/cdk/test/image-pinning.test.ts
@@ -101,12 +101,13 @@ describe("context 이미지 주입 (backendImage/frontendImage)", () => {
     }));
   });
 
-  it("scheduler의 autoprober/insights/parity/gptbench/features task definition도 backend digest URI를 사용한다", () => {
+  it("scheduler의 autoprober/insights/parity/gptbench/features/pricingsync task definition도 backend digest URI를 사용한다", () => {
     const tds = schedTemplate.findResources("AWS::ECS::TaskDefinition");
     const images = Object.values(tds).map(
       (td) => (td as any).Properties.ContainerDefinitions[0].Image,
     );
-    expect(images).toHaveLength(5); // autoprober + insights + parityrun (v2.11.0) + gptbench (v2.18.0) + featuresverify (v2.23.0)
+    // autoprober + insights + parityrun (v2.11.0) + gptbench (v2.18.0) + featuresverify (v2.23.0) + pricingsync (v2.30.0)
+    expect(images).toHaveLength(6);
     for (const img of images) {
       expect(img).toBe(BE_URI);
     }
diff --git a/cdk/test/scheduler-stack.test.ts b/cdk/test/scheduler-stack.test.ts
index df12030..a67e961 100644
--- a/cdk/test/scheduler-stack.test.ts
+++ b/cdk/test/scheduler-stack.test.ts
@@ -37,8 +37,8 @@ describe("SchedulerStack", () => {
     template = Template.fromStack(scheduler);
   });
 
-  it("Schedule이 5개 생성된다 (AutoProber + Insights + ParityRun + GptBench + FeaturesVerify)", () => {
-    template.resourceCountIs("AWS::Scheduler::Schedule", 5);
+  it("Schedule이 6개 생성된다 (AutoProber + Insights + ParityRun + GptBench + FeaturesVerify + PricingSync)", () => {
+    template.resourceCountIs("AWS::Scheduler::Schedule", 6);
   });
 
   it("AutoProber는 rate(5 minutes) 스케줄을 사용한다", () => {
@@ -76,8 +76,8 @@ describe("SchedulerStack", () => {
     }));
   });
 
-  it("TaskDefinition이 5개 생성된다", () => {
-    template.resourceCountIs("AWS::ECS::TaskDefinition", 5);
+  it("TaskDefinition이 6개 생성된다 (PricingSync 포함, v2.30.0)", () => {
+    template.resourceCountIs("AWS::ECS::TaskDefinition", 6);
   });
 
   it("Task는 Fargate, awsvpc, X86_64로 설정된다", () => {
@@ -205,6 +205,95 @@ describe("SchedulerStack", () => {
     }));
   });
 
+  describe("PricingSync (v2.30.0, ADR-030)", () => {
+    const PRICING_COMMAND = ["python", "-m", "pricing_sync_runner", "--once"];
+    type Container = { Command: string[]; Environment?: { Name: string; Value: string }[]; Secrets?: { Name: string }[] };
+    type CfnResource = ReturnType<Template["findResources"]>[string];
+
+    const taskDefByCommand = (command: string[]): [string, CfnResource] => {
+      const found = Object.entries(template.findResources("AWS::ECS::TaskDefinition")).filter(([, resource]) =>
+        (resource.Properties.ContainerDefinitions as Container[]).some(
+          (container) => container.Command.join(" ") === command.join(" ")));
+      expect(found).toHaveLength(1);
+      return found[0]!;
+    };
+    const containerOf = (taskDef: CfnResource): Container => taskDef.Properties.ContainerDefinitions[0];
+    const pricingRoleLogicalId = (): string => {
+      const [, taskDef] = taskDefByCommand(PRICING_COMMAND);
+      return taskDef.Properties.TaskRoleArn["Fn::GetAtt"][0];
+    };
+    const schedulerStatement = (sid: string): { Resource: unknown[] } => {
+      const statements = Object.entries(template.findResources("AWS::IAM::Policy"))
+        .filter(([logicalId]) => logicalId.startsWith("SchedulerInvokeRoleDefaultPolicy"))
+        .flatMap(([, policy]) => policy.Properties.PolicyDocument.Statement)
+        .filter((statement: { Sid?: string }) => statement.Sid === sid);
+      expect(statements).toHaveLength(1);
+      return statements[0];
+    };
+
+    it("컨테이너 CMD는 pricing_sync_runner --once, 로그 그룹 /ecs/pricingsync 14일, 0.5 vCPU / 1 GB", () => {
+      const [, taskDef] = taskDefByCommand(PRICING_COMMAND);
+      expect(taskDef.Properties.Cpu).toBe("512");
+      expect(taskDef.Properties.Memory).toBe("1024");
+      const logGroupRef = containerOf(taskDef) as unknown as { LogConfiguration: { Options: { "awslogs-group": { Ref: string } } } };
+      const logGroupId = logGroupRef.LogConfiguration.Options["awslogs-group"].Ref;
+      const logGroups = template.findResources("AWS::Logs::LogGroup");
+      expect(logGroups[logGroupId]?.Properties).toEqual({ LogGroupName: "/ecs/pricingsync", RetentionInDays: 14 });
+    });
+
+    it("rate(12 hours) 스케줄이 PricingSync task def를 실행한다 (ParityRun과 별개의 12시간 스케줄)", () => {
+      const [taskDefId] = taskDefByCommand(PRICING_COMMAND);
+      const targeting = Object.values(template.findResources("AWS::Scheduler::Schedule"))
+        .filter((schedule) => schedule.Properties.Target.EcsParameters.TaskDefinitionArn.Ref === taskDefId);
+      expect(targeting).toHaveLength(1);
+      expect(targeting[0]!.Properties.ScheduleExpression).toBe("rate(12 hours)");
+      expect(targeting[0]!.Properties.Description).toMatch(/every 12 hours/);
+      const twelveHour = Object.values(template.findResources("AWS::Scheduler::Schedule"))
+        .filter((schedule) => schedule.Properties.ScheduleExpression === "rate(12 hours)");
+      expect(twelveHour).toHaveLength(2);
+    });
+
+    it("AutoProber와 같은 env/secret을 받는다 (CP 디스커버리, OpenAI 등록용) — CP 주기 노브만 빠진다", () => {
+      const pricing = containerOf(taskDefByCommand(PRICING_COMMAND)[1]);
+      const autoProber = containerOf(taskDefByCommand(["python", "-m", "auto_prober_runner", "--once"])[1]);
+      expect(pricing.Environment).toEqual(
+        (autoProber.Environment ?? []).filter((variable) => variable.Name !== "ANTHROPIC_CP_PROBE_INTERVAL_S"));
+      expect((pricing.Secrets ?? []).map((secret) => secret.Name).sort())
+        .toEqual((autoProber.Secrets ?? []).map((secret) => secret.Name).sort());
+      expect((pricing.Secrets ?? []).map((secret) => secret.Name)).toEqual(
+        expect.arrayContaining(["ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "OPENAI_API_KEY", "DB_HOST", "DB_PASSWORD"]));
+    });
+
+    it("전용 task role은 가격 읽기 액션 2개만 갖는다 — bedrock:Invoke* 없음, 다른 정책 없음", () => {
+      const roleId = pricingRoleLogicalId();
+      const role = template.findResources("AWS::IAM::Role")[roleId];
+      expect(role).toBeDefined();
+      expect(role!.Properties.ManagedPolicyArns).toBeUndefined();
+      const statements = (role!.Properties.Policies as { PolicyDocument: { Statement: { Action: string | string[]; Resource: unknown }[] } }[])
+        .flatMap((policy) => policy.PolicyDocument.Statement);
+      const actions = statements.flatMap((statement) => [statement.Action].flat()).sort();
+      expect(actions).toEqual(["bedrock:ListFoundationModelAgreementOffers", "pricing:GetProducts"]);
+      expect(statements.map((statement) => statement.Resource)).toEqual(["*"]);
+      expect(actions.some((action) => action.startsWith("bedrock:Invoke"))).toBe(false);
+      // 이 역할에 붙는 AWS::IAM::Policy(DefaultPolicy 등)가 없어야 한다.
+      const attached = Object.values(template.findResources("AWS::IAM::Policy"))
+        .filter((policy) => JSON.stringify(policy.Properties.Roles ?? []).includes(roleId));
+      expect(attached).toEqual([]);
+    });
+
+    it("Scheduler 역할: RunTask family ':*'와 명시 PassRole 목록에 PricingSync가 들어간다 (ADR-011)", () => {
+      const [, taskDef] = taskDefByCommand(PRICING_COMMAND);
+      const family = taskDef.Properties.Family as string;
+      expect(schedulerStatement("RunTaskFamilyWildcard").Resource).toContain(
+        `arn:aws:ecs:us-east-1:111111111111:task-definition/${family}:*`);
+      expect(schedulerStatement("PassTaskRoles").Resource).toContainEqual({ "Fn::GetAtt": [pricingRoleLogicalId(), "Arn"] });
+    });
+
+    it("스케줄 이름을 PricingSyncScheduleName output으로 내보낸다 (런북 수동 run-task용)", () => {
+      expect(Object.keys(template.findOutputs("PricingSyncScheduleName"))).toEqual(["PricingSyncScheduleName"]);
+    });
+  });
+
   it("autoprober task def에 GPT-6 Sol/Luna model id가 주입된다 (v2.27.0)", () => {
     template.hasResourceProperties("AWS::ECS::TaskDefinition", Match.objectLike({
       ContainerDefinitions: Match.arrayWith([Match.objectLike({
```

#### `t13-stack` — `@scratch/patches/t13-stack.patch`

<!-- plan-block id=t13-stack path=@scratch/patches/t13-stack.patch sha256=1e8f1cbc03480de183458803ec827ad6ab41b2a5e72c2a40264a9be024fe35f1 -->
```diff
diff --git a/cdk/lib/stacks/scheduler-stack.ts b/cdk/lib/stacks/scheduler-stack.ts
index c449a7a..c36fb5e 100644
--- a/cdk/lib/stacks/scheduler-stack.ts
+++ b/cdk/lib/stacks/scheduler-stack.ts
@@ -10,6 +10,8 @@
 //   - rate(15 minutes) → GptBench Fargate Task (gptbench_runner --once)
 //   - cron(30 17 * * ? *) Etc/UTC → FeaturesVerify Fargate Task (features_runner --once)
 //     (v2.29.0: 매일 17:30 UTC = 02:30 KST 고정 1회. 이전 rate(24 hours)는 스케줄 생성 시각 기준이라 시각이 고정되지 않았다)
+//   - rate(12 hours) → PricingSync Fargate Task (pricing_sync_runner --once)
+//     (v2.30.0: 공식 단가 동기화 — Bedrock agreement offers, AWS Price List, Anthropic pricing.md. 모델 호출 권한 없음, ADR-030)
 //   - 각 TaskDefinition은 backend ECR 이미지를 재사용하고 CMD만 override.
 //   - 모든 task는 RDS:5432 egress + Bedrock/Mantle 액세스 필요 → 별도 SG + RDS SG에 ingress(standalone) 추가.
 import * as cdk from "aws-cdk-lib";
@@ -133,6 +135,27 @@ export class SchedulerStack extends cdk.Stack {
     // Insights는 향후 AgentCore Memory를 인사이트 컨텍스트로 활용할 가능성 있음 - 정책 attach.
     insightsTaskRole.addManagedPolicy(props.agentCoreMemoryAccessPolicy);
 
+    // PricingSync (v2.30.0, ADR-030) — 공식 단가 읽기 전용 호출 2개만. 모델 호출(bedrock:Invoke*)은 주지 않는다.
+    // DB는 다른 태스크와 같다(schedulerTaskSg → RDS 5432, DB secret은 실행 역할이 주입).
+    // CP/OpenAI 채널 등록(_discover_anthropic_models, _register_openai_models)은 API 키 secret과 env만 쓰므로 IAM이 필요 없다.
+    const pricingSyncTaskRole = new iam.Role(this, "PricingSyncTaskRole", {
+      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
+      description: "PricingSync task role - official price reads (agreement offers, Price List) + DB, no model invocation",
+      inlinePolicies: {
+        pricing: new iam.PolicyDocument({
+          statements: [
+            new iam.PolicyStatement({
+              sid: "OfficialPriceReads",
+              effect: iam.Effect.ALLOW,
+              actions: ["bedrock:ListFoundationModelAgreementOffers", "pricing:GetProducts"],
+              // 두 API 모두 리소스 ARN이 없는 읽기 전용 카탈로그 호출이라 Resource는 *.
+              resources: ["*"],
+            }),
+          ],
+        }),
+      },
+    });
+
     // Claude Platform on AWS (Path 3 External) - vendor endpoint.
     // AppServicesStack과 동일하게 사전 생성된 SSM SecureString을 import.
     const anthropicApiKeyParam = ssm.StringParameter.fromSecureStringParameterAttributes(
@@ -316,6 +339,16 @@ export class SchedulerStack extends cdk.Stack {
       "/ecs/features",
     );
 
+    // 공식 단가 동기화 (v2.30.0, ADR-030) — 12시간마다 활성 55채널의 Standard 입력/출력 단가를 공식 출처에서 읽어
+    // price_history에 기록한다(50% 초과 변화는 검토 대기). 같은 env/secret(buildTaskDef 기본값)으로 CP 디스커버리와
+    // OpenAI 채널 등록을 AutoProber와 똑같이 해야 활성 채널 집합이 맞는다. extraEnvironment 없음.
+    const pricingSyncTaskDef = buildTaskDef(
+      "PricingSyncTaskDef",
+      pricingSyncTaskRole,
+      ["python", "-m", "pricing_sync_runner", "--once"],
+      "/ecs/pricingsync",
+    );
+
     // ---------------------------------------------------------------------
     // 4-1) Scheduler invoke role (ADR-011).
     //    L2 EcsRunFargateTask가 자동 생성하는 role은 ecs:RunTask Resource를 task def의
@@ -344,6 +377,7 @@ export class SchedulerStack extends cdk.Stack {
           // bump되는 순간 스케줄이 silent fail (ADR-011과 동일 시나리오).
           `arn:aws:ecs:${this.region}:${this.account}:task-definition/${gptBenchTaskDef.family}:*`,
           `arn:aws:ecs:${this.region}:${this.account}:task-definition/${featuresTaskDef.family}:*`,
+          `arn:aws:ecs:${this.region}:${this.account}:task-definition/${pricingSyncTaskDef.family}:*`,
         ],
       }),
     );
@@ -355,6 +389,8 @@ export class SchedulerStack extends cdk.Stack {
         resources: [
           autoProberTaskRole.roleArn,
           insightsTaskRole.roleArn,
+          // PricingSync 역할도 명시 목록에 둔다 — L2 target이 붙이는 revision 고정 문에 기대지 않는다(ADR-011).
+          pricingSyncTaskRole.roleArn,
           executionRole.roleArn,
         ],
         conditions: {
@@ -427,6 +463,21 @@ export class SchedulerStack extends cdk.Stack {
       }),
     });
 
+    const pricingSyncSchedule = new scheduler.Schedule(this, "PricingSyncSchedule", {
+      // 12시간 주기 (v2.30.0, 사용자 결정 2026-09-26) — offers FM 18개 순차 약 25초 + Price List 1회 + Anthropic 문서 1회.
+      //   런 전체 상한 300초(SYNC_DEADLINE_S), pg_advisory_lock(917350004)로 수동 실행과 겹치지 않는다.
+      schedule: scheduler.ScheduleExpression.rate(cdk.Duration.hours(12)),
+      description: "Official unit-price sync (Bedrock agreement offers, AWS Price List, Anthropic pricing doc) every 12 hours",
+      target: new schedulerTargets.EcsRunFargateTask(props.cluster, {
+        taskDefinition: pricingSyncTaskDef,
+        vpcSubnets: props.appSubnets,
+        securityGroups: [schedulerTaskSg],
+        assignPublicIp: false,
+        platformVersion: ecs.FargatePlatformVersion.LATEST,
+        role: schedulerInvokeRole,
+      }),
+    });
+
     this.insightsSchedule = new scheduler.Schedule(this, "InsightsSchedule", {
       schedule: scheduler.ScheduleExpression.rate(cdk.Duration.minutes(5)),
       description: "Insights every 5 minutes (Sonnet 4.6)",
@@ -473,6 +524,19 @@ export class SchedulerStack extends cdk.Stack {
       },
     ]);
 
+    NagSuppressions.addResourceSuppressions(
+      pricingSyncTaskRole,
+      [
+        {
+          id: "AwsSolutions-IAM5",
+          reason:
+            "ADR-030: bedrock:ListFoundationModelAgreementOffers와 pricing:GetProducts는 리소스 ARN이 없는 읽기 전용 카탈로그 호출이라 Resource *. 모델 호출 권한은 없다.",
+          appliesTo: ["Resource::*"],
+        },
+      ],
+      true,
+    );
+
     NagSuppressions.addResourceSuppressions(
       schedulerInvokeRole,
       [
@@ -494,6 +558,9 @@ export class SchedulerStack extends cdk.Stack {
     new cdk.CfnOutput(this, "InsightsScheduleName", {
       value: this.insightsSchedule.scheduleName,
     });
+    new cdk.CfnOutput(this, "PricingSyncScheduleName", {
+      value: pricingSyncSchedule.scheduleName,
+    });
     new cdk.CfnOutput(this, "SchedulerTaskSgId", {
       value: schedulerTaskSg.securityGroupId,
     });
```

### Task 14 blocks

#### `t14-doccheck` — `@scratch/e2_doccheck.py`

<!-- plan-block id=t14-doccheck path=@scratch/e2_doccheck.py sha256=0873a6b390e853250840785b38d2a2bd1d2384e1c7541af1a6f580171b235c32 -->
````python
"""v2.30.0 docs/release consistency check (not committed). Run from the repo root before committing E2."""
import json, re, subprocess, sys
from pathlib import Path

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)

def read(p):
    return Path(p).read_text(encoding="utf-8")

# 1. version strings (6 places)
check('APP_VERSION = "v2.30.0"' in read("frontend/src/lib/version.ts"), "version.ts not v2.30.0")
check('version="2.30.0"' in read("backend/main.py"), "backend/main.py FastAPI version not 2.30.0")
check(json.loads(read("frontend/package.json"))["version"] == "2.30.0", "frontend/package.json version")
lock = json.loads(read("frontend/package-lock.json"))
check(lock["version"] == "2.30.0" and lock["packages"][""]["version"] == "2.30.0", "package-lock.json versions")
check("version-2.30.0-blue" in read("README.md"), "README badge")
check("(v2.30.0 — 현재 버전은" in read("CLAUDE.md"), "CLAUDE.md overview")
check(read("CHANGELOG.md").split("\n## ", 2)[1].startswith("v2.30.0 — "), "CHANGELOG top entry is not v2.30.0")

# 2. ADR-030 + follow-ups
adr = Path("docs/decisions/ADR-030-pricing-auto-sync-time-effective-cost.md")
check(adr.exists() and "Supersedes" in read(adr) and "us.amazon.nova-2-lite-v1:0" in read(adr), "ADR-030 missing or incomplete")
check("## 후속 (v2.30.0, 2026-09-26)" in read("docs/decisions/ADR-025-openai-global-cris-channels.md"), "ADR-025 follow-up")
check("## 후속 (v2.30.0, 2026-09-26)" in read("docs/decisions/ADR-028-claude-opus-5-5-and-gpt-6-sol-luna.md"), "ADR-028 follow-up")

# 3. README bilingual parity
readme = read("README.md")
en, ko = readme.split('<a id="korean"></a>')
for token in ["/pricing", "pricing_sync_runner.py", "/api/pricing/export", "ADR-030", "price_history.py"]:
    check(token in en and token in ko and en.count(token) == ko.count(token), f"README EN/KO parity for {token}")
check("Eleven analytical pages" in en and "11개 분석 페이지" in ko, "README page count")
check("pricing.py                # " not in readme, "README tree still lists backend/pricing.py")

# 4. architecture: identical Mermaid blocks, PricingSync in both full diagrams
arch = read("docs/architecture.md")
blocks = re.findall(r"```mermaid\n(.*?)```", arch, re.S)
check(len(blocks) == 8 and blocks[:4] == blocks[4:], "architecture EN/KO Mermaid blocks differ")
check(all('prc["PricingSync task: 12 h"]' in b for b in (blocks[0], blocks[4])), "PricingSync node missing")
check("6 EventBridge schedules and 6 task definitions" in arch and "EventBridge 스케줄 6개, 태스크 정의 6개" in arch, "CDK stack row")
check(arch.count("`PricingSyncSchedule`") == 2 and arch.count("| 030 |") == 2, "schedule table or ADR row")

# 5. api-reference, runbooks, CLAUDE files
api = read("docs/api-reference.md")
check("### GET /api/pricing\n" in api and "### GET /api/pricing/export" in api and "/api/admin/pricing/pending" in api, "api-reference pricing sections")
check("re-prices past rows" not in api, "api-reference still describes query-time re-pricing")
check("### 5-4. v2.30.0" in read("docs/runbooks/deploy.md"), "deploy.md §5-4")
tr = read("docs/runbooks/troubleshooting.md")
check("## 비용 단가 동기화 실패" in tr and "## 검토 대기 단가 승인" in tr and "## GPT-5.6 Sol 프로모션 종료 확인" in tr, "troubleshooting sections")
check("6 schedules" in read("cdk/CLAUDE.md") and "85 tests" in read("cdk/CLAUDE.md"), "cdk/CLAUDE.md")
check("pricing_sync_runner.py" in read("backend/CLAUDE.md") and "(18 router modules)" in read("backend/CLAUDE.md"), "backend/CLAUDE.md")
check("`pricing.py` — `router` `/api/pricing`" in read("backend/routers/CLAUDE.md"), "routers/CLAUDE.md")
check("`pricingTable.ts`" in read("frontend/src/lib/CLAUDE.md") and "must change together" not in read("frontend/src/lib/CLAUDE.md"), "lib/CLAUDE.md")
check("`PricingPanel.tsx`" in read("frontend/src/components/CLAUDE.md"), "components/CLAUDE.md")
root = read("CLAUDE.md")
check("**단가 (v2.30.0, ADR-030)**" in root and "pricing_seed.py" in root and "├── /pricing" in root, "root CLAUDE.md pricing notes")
check("prefix fallback이 나머지 채널을 오매칭" not in root and "모델 카드가 게재되면 재대조" not in root, "root CLAUDE.md stale pricing guidance")

check("6개 스케줄에 적용한다" in read("docs/runbooks/rollback.md"), "rollback.md schedule count")
check("**Unit Prices** (`/pricing`, v2.30.0)" in read("docs/onboarding.md"), "onboarding.md Unit Prices concept")
check("`pricing/` (v2.30.0, `PricingPanel`)" in read("frontend/src/app/CLAUDE.md"), "app/CLAUDE.md pages")
check("`/pricing` 비용 단가 (v2.30.0" in read("frontend/CLAUDE.md"), "frontend/CLAUDE.md pages")
check("all six scheduled task definitions" in read("AGENTS.md") and "6개 스케줄을" in read("AGENTS.md"), "AGENTS.md schedule count")

# 6. Korean middle dots: no file may gain a '·'
changed = subprocess.run(["git", "diff", "--name-only", "HEAD"], capture_output=True, text=True, check=True).stdout.split()
new_files = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", "docs", ":(exclude)docs/superpowers"], capture_output=True, text=True, check=True).stdout.split()
for f in changed + new_files:
    if not Path(f).exists() or not f.endswith((".md", ".ts", ".py", ".json")):
        continue
    after = read(f).count("·")
    before = subprocess.run(["git", "show", f"HEAD:{f}"], capture_output=True, text=True).stdout.count("·")
    check(after <= before, f"{f}: middle dots {before} -> {after}")

print("\n".join(fails) if fails else "DOCCHECK OK")
sys.exit(1 if fails else 0)
````

#### `t14-mermaid-check` — `@scratch/mermaid-check.cjs`

<!-- plan-block id=t14-mermaid-check path=@scratch/mermaid-check.cjs sha256=12d21832c936ca7d918e2aa021aea19b885faae0ccbfbbc69f8eb8c4b6125cfe -->
````js
const fs = require("fs");
const { chromium } = require(process.cwd() + "/frontend/node_modules/playwright");
const files = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.setContent('<html><body></body></html>');
  await page.addScriptTag({ url: "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js" });
  await page.evaluate(() => window.mermaid.initialize({ startOnLoad: false }));
  let bad = 0;
  for (const f of files) {
    const blocks = [...fs.readFileSync(f, "utf8").matchAll(/```mermaid\n([\s\S]*?)```/g)].map((m) => m[1]);
    for (const [i, code] of blocks.entries()) {
      const r = await page.evaluate(async ({ code, i }) => {
        try { await window.mermaid.render("m" + i + Math.random().toString(36).slice(2), code); return "ok"; } catch (e) { return String(e.message || e); }
      }, { code, i });
      if (r !== "ok") bad++;
      console.log(f, "block", i, r.slice(0, 200));
    }
  }
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
````

#### `t14-adr` — `docs/decisions/ADR-030-pricing-auto-sync-time-effective-cost.md`

<!-- plan-block id=t14-adr path=docs/decisions/ADR-030-pricing-auto-sync-time-effective-cost.md sha256=250d2f71afbfd6aa2cccba4f6c794a2560e7ae23ecba8ca9645112e3b4129198 -->
```markdown
# ADR-030: 공식 단가 12시간 자동 동기화 + 프로브 시각 단가로 비용 계산 — model_id 단위 단가 이력, 50% 안전장치와 관리자 승인

- **Status**: Accepted
- **Date**: 2026-09-26
- **Supersedes**: ADR-025의 "비용은 조회 시점 계산이라 단가를 바꾸면 과거 행도 소급 재계산된다" 정책(ADR-027, ADR-028이 같은 정책을 인용한 문장 포함)
- **Related**: ADR-011 (Scheduler IAM family `:*`), ADR-018 (digest 고정 배포), ADR-019, ADR-020 (OpenAI Mantle, 1P), ADR-025 (채널별 단가), ADR-027, ADR-028 (agreement offer 단가 출처), v2.30.0, 설계 문서 `docs/superpowers/specs/2026-09-26-pricing-menu-design.md`
- **Code**: `backend/pricing_sources.py`, `backend/pricing_seed.py`, `backend/pricing_parsers.py`, `backend/pricing_sync.py`, `backend/pricing_sync_runner.py`, `backend/price_history.py`, `backend/pricing_payload.py`, `backend/pricing_export.py`, `backend/routers/pricing.py`, `backend/models.py`(`PriceHistory`, `PriceSyncRun`), `backend/routers/cost.py`, `backend/routers/efficiency.py`, `frontend/src/components/PricingPanel.tsx`, `frontend/src/lib/pricingTable.ts`, `cdk/lib/stacks/scheduler-stack.ts`(`PricingSync*`)

## Context

v2.29.1까지 모델 단가는 `backend/pricing.py` `PRICE_TABLE`에 코드로 고정돼 있었고, `frontend/src/lib/pricing.ts`가 같은 표를
복사해 들고 있었다. 비용 화면과 효율성 점수는 조회할 때마다 그 표로 계산했다(ADR-025의 소급 정책). 그 결과 세 가지 문제가
있었다.

1. 단가가 바뀌면 사람이 모델 카드를 보고 두 파일을 함께 고쳐야 했다. 두 표를 비교하는 테스트는 없었다.
2. 키 정규화(`_normalize_key`)와 prefix fallback 때문에 정확한 키가 빠지면 형제 모델의 단가가 조용히 붙었다. Opus 5.5 키가
   없으면 Opus 5의 $5 / $25가 붙었고, GPT-6은 "3키를 항상 함께 둔다"는 규칙으로 막아야 했다.
3. 단가를 고치면 과거 전체가 새 단가로 다시 계산됐다. 2026-07-30 GPT-5.6 Luna −80%, Terra −20% 인하와 2026-09-23 Sol 프로모션
   반영 때 그 이전 프로브도 새 단가로 보였다.

2026-09-26 스파이크(읽기 전용, 설계 검토에서 재검증)에서 공식 출처 3개를 조합하면 활성 55채널 전부의 Standard 단가를
기계적으로 읽을 수 있음을 확인했다. 같은 조사에서 코드 단가 오류 11채널을 찾았다(Decision 2의 표).

| 출처 | 대상 채널 | 호출 |
|------|-----------|------|
| Bedrock agreement offer rate card | Bedrock Claude 20 + OpenAI 25 (파운데이션 모델 18개 = Claude 10 + OpenAI 8) | `bedrock.list_foundation_model_agreement_offers(modelId=<FM id>, offerType="PUBLIC")`, 리전 무관(us-east-1과 ap-northeast-2가 같은 offerId, rateCard), 18개 합계 약 25초 |
| AWS Price List API | Nova 2.0 Lite | `pricing.get_products(ServiceCode="AmazonBedrock")`, usagetype 정확 일치 `USE1-Nova2.0Lite-input-tokens` / `USE1-Nova2.0Lite-output-tokens`, 단위 `1K tokens` → ×1000 |
| Anthropic 공식 단가 문서 | Claude Platform on AWS 9 | `GET https://platform.claude.com/docs/en/about-claude/pricing.md`, "## Model pricing" 첫 표. 문서가 Claude Platform on AWS는 Claude API와 같은 표준 단가라고 명시 |

`amazon.nova-2-lite-v1:0`은 agreement offer가 `ValidationException: Agreement not supported for this model`이라 Price List로 읽는다.

사용자 요청(2026-09-26): 모델별 단가를 한 화면에서 보는 새 메뉴 `/pricing`("비용 단가" / "Unit Prices"), 공식 출처에서
12시간마다 자동 갱신, CSV, Markdown, JSON 다운로드, 출처 각주, "참고용이며 AWS 공식 입장이 아님" 면책 문구, 비용은 각 프로브
시각에 유효했던 단가로 계산.

## 검토한 선택지

| 결정 | 선택지 | 판단 |
|------|--------|------|
| 단가 원천 | **A. 백엔드 단일 출처 `GET /api/pricing`, 프런트 미러 삭제** | 채택(사용자 결정). 두 표 불일치가 구조적으로 사라진다 |
| | B. 프런트 미러 유지, 동기화 결과만 백엔드 반영 | 기각. 두 표를 맞추는 수작업과 불일치 위험이 그대로다 |
| 비용 시점 | A. 조회 시점 소급 계산(ADR-025) | 기각. 단가가 바뀔 때마다 과거 비용이 바뀐다 |
| | **B. 시점 단가(각 프로브 시각에 유효했던 단가)** | 채택(사용자 결정). 단가 이력을 보존한다 |
| v2.30.0 이전 변경 | **A. 재구성하지 않음, seed가 과거 전체에 적용** | 채택(설계 검토 권장안 A, 사용자 결정). 결과가 기존 소급 계산과 같다 |
| | B. 알려진 변경(2026-07-30 Luna, Terra 인하, Sol 프로모션 시작)을 이력으로 재구성 | 기각. 공식 출처가 이력과 정확한 시작 시각을 주지 않아 추정이 섞인다 |
| 코드 단가 오류 11채널 | **A. 과거까지 교정** | 채택(사용자 결정). 단가 변경이 아니라 처음부터 틀린 값이다 |
| | B. 첫 동기화부터만 교정 | 기각. 틀린 값이 과거 비용에 남는다 |
| 변경 적용 | A. 관측한 값을 모두 자동 적용 | 기각. 단위 오류(1000배)나 파서 오류가 비용에 그대로 들어간다 |
| | **B. 변화율 50% 이하 자동 적용, 초과는 관리자 승인** | 채택 |
| | C. 모든 변경을 관리자 승인 | 기각. 12시간마다 사람이 봐야 해 자동 갱신의 의미가 없다 |
| 저장 단위 | A. 패밀리 키(`claude-opus-5-5`, `gpt-6-sol-global`) 단위 | 기각. prefix fallback과 키 정규화 오류(US = Global 오류의 원인)가 남는다 |
| | **B. `model_id` 단위**(`probe_results.model_id`와 같은 값) | 채택. 비용 조인이 정확 일치라 prefix fallback이 구조적으로 사라진다 |

## Decision

### 1. 단가 이력 — `price_history`, `price_sync_runs`

- 두 테이블은 `backend/models.py` ORM(`PriceHistory`, `PriceSyncRun`)과 `create_all`로 만든다. lifespan ALTER 블록에는 넣지 않는다.
- `price_history` 행 하나는 `model_id`, `family_key`, `channel`(`cp`, `global`, `us`, `inregion:<region>`), `input_per_mtok`,
  `output_per_mtok`(USD per 1M tokens), `effective_from`, `source_id`, `status`(`seed`, `verified`, `pending_review`, `rejected`),
  `observed_at`(출처에서 마지막으로 확인한 시각, seed는 NULL), `run_id`다. 인덱스 `ix_price_history_model_eff(model_id, effective_from)`.
- **유효 행**은 같은 `model_id`에서 `status`가 `seed` 또는 `verified`이고 `effective_from <= t`인 행 중 `(effective_from, id)`가 가장
  늦은 행이다.
- 저장과 비용 계산은 float다. 동기화 비교에만 `Decimal(str(round(v, 6)))`를 쓴다(PostgreSQL `numeric`이 `Decimal`로 돌아와
  float 누적에서 `TypeError`가 나는 문제를 피한다).
- 모든 시각은 timezone-aware datetime을 ORM/Core 바인드 파라미터로 넣는다(SQLite는 DateTime을 문자열로 비교한다).
- `pricing_sources.price_identity(model_id)`가 활성 채널을 모두 분류한다(`family_key`, `family`, `provider`, `channel`,
  `source_kind`, `source_ref`). 분류할 수 없는 id는 예외가 아니라 `None`이고 그 채널은 단가 없음("-")이 된다. Claude Platform on AWS
  id는 런타임 디스커버리로 정해지고 날짜 접미사가 붙을 수 있어 prober `_ANTHROPIC_TARGETS`와 같은 substring 규칙과
  `_is_point_release_of`로 분류한다. `family` 문자열은 프런트 `lib/sortModels.ts` `FAMILY_ORDER`와 바이트 단위로 같고, pytest가
  두 목록의 동등성을 고정한다.

### 2. seed와 과거 교정

- `pricing_seed.SEED`는 활성 55채널 중 CP를 뺀 46채널의 공식 단가를 `model_id` 단위로, `CP_SEED`는 CP 9패밀리를 `family_key`
  단위로 둔다(CP id가 바뀔 수 있으므로 `ensure_seed`가 현재 활성 CP model_id로 풀어 넣는다).
- `ensure_seed(engine, active)`는 **model_id 단위 멱등 삽입**이다. 그 model_id 행이 하나도 없을 때만 `effective_from`
  1970-01-01T00:00:00Z, `status='seed'`, `observed_at` NULL로 넣는다. 마이그레이션과 분리된 자체 트랜잭션에서
  `pg_advisory_xact_lock(917350003)` 아래 실행한다(SQLite는 잠금 생략). 호출 위치는 backend lifespan(모델 등록 다음, 실패해도 기동
  계속)과 `pricing_sync_runner`(모델 등록 → seed → 동기화)다. 그래서 동기화가 먼저 돌아도 seed가 빠지지 않는다.
- seed가 1970년부터 유효하므로 첫 동기화 이전 구간은 seed로 계산한다. 44채널은 v2.29.1 코드 값과 같아 비용이 변하지 않고,
  아래 11채널만 과거 전체가 교정된다.

| 채널 | model_id | v2.29.1 코드 (입력 / 출력) | 공식 = seed (입력 / 출력) |
|------|----------|----------------------------|---------------------------|
| Bedrock Claude Fable 5.1 (US) | `us.anthropic.claude-fable-5-1` | $10 / $50 | $11 / $55 |
| Bedrock Claude Fable 5 (US) | `us.anthropic.claude-fable-5` | $10 / $50 | $11 / $55 |
| Bedrock Claude Opus 5.5 (US) | `us.anthropic.claude-opus-5-5` | $4 / $20 | $4.40 / $22 |
| Bedrock Claude Opus 5 (US) | `us.anthropic.claude-opus-5` | $5 / $25 | $5.50 / $27.50 |
| Bedrock Claude Opus 4.8 (US) | `us.anthropic.claude-opus-4-8` | $5 / $25 | $5.50 / $27.50 |
| Bedrock Claude Opus 4.7 (US) | `us.anthropic.claude-opus-4-7` | $5 / $25 | $5.50 / $27.50 |
| Bedrock Claude Opus 4.6 (US) | `us.anthropic.claude-opus-4-6-v1` | $5 / $25 | $5.50 / $27.50 |
| Bedrock Claude Sonnet 5 (US) | `us.anthropic.claude-sonnet-5` | $2 / $10 | $2.20 / $11 |
| Bedrock Claude Sonnet 4.6 (US) | `us.anthropic.claude-sonnet-4-6` | $3 / $15 | $3.30 / $16.50 |
| Bedrock Claude Haiku 4.5 (US) | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | $1 / $5 | $1.10 / $5.50 |
| Bedrock Nova 2.0 Lite (US) | `us.amazon.nova-2-lite-v1:0` | $0.06 / $0.24 | $0.33 / $2.75 |

- Bedrock Claude US 10채널: `_normalize_key`가 `us.`와 `global.`을 같은 키로 합쳐 Global 단가가 붙었다. 오퍼 rate card의 US(Geo)
  단가는 Global × 1.1이므로 약 9.1% 과소 산정이었다.
- Nova 2.0 Lite: 1세대 Nova Lite 단가가 들어가 있었다. 입력 5.5배, 출력 11.5배 과소 산정이었다.

### 3. 12시간 동기화 (`pricing_sync.py`, `pricing_sync_runner.py`)

1. 러너는 `create_tables()` → `prober._discover_anthropic_models()`, `prober._register_openai_models()`(AutoProber와 같은 env,
   secret) → `ensure_seed` 순서로 준비한다. 활성 채널은 `AVAILABLE_MODELS`에서 숨김 라벨(`HIDDEN_MODEL_PATTERNS`, 기본 `(1P)`)을
   빼고 `price_identity`로 분류한 것이다. CP 디스커버리가 실패하면 CP 9채널은 변경 없음, 런은 `partial`이다.
2. 런 전체를 `pg_advisory_lock(917350004)`로 직렬화한다. 잠금을 못 잡으면 경고 로그를 남기고 exit 1로 끝낸다(런 행 없음). `ensure_seed`가
   실패해도 동기화하지 않고 exit 1이다 — seed 없이 돌면 `no_baseline` 행이 생기고, model_id 단위 멱등 규칙 때문에 그 채널의 seed가
   영구히 빠진다.
3. 출처별로 한 번씩, Anthropic 문서 → Price List → offers 순서로 가져온다(느린 offers가 싼 출처를 `skipped:deadline`으로 밀어내지
   않게). offers는 FM 18개를 중복 없이 순차 호출하고, 각 호출은 `ThrottlingException` 계열, 5xx, HTTP 429, 연결 오류에 1초, 2초,
   4초 간격으로 최대 3회 재시도한다(botocore 자체 재시도는 끈다). 300초 상한은 호출 직전에만 검사하고 진행 중인 호출은 끊지 않는다. 오퍼 응답의 `offerToken`과 `legalTerm.url`(presigned URL)은 저장하거나 로그에 남기지 않는다.
4. 오퍼 차원 이름은 허용 목록 정규식에 **완전 일치**할 때만 후보다.
   `^(?:(?P<rc>APN2|USE1|USE2|USW2)_)?(?:(?P<io>input|output)_tokens(?P<g>_global)?_standard|(?P<IO>Input|Output)TokenCount(?P<G>_Global)?)$`
   그래서 batch, flex, priority, long-context, cache, reserved, GovCloud, 그 밖의 리전 접두는 후보가 되지 않는다. 오퍼가 정확히
   1개가 아니면 그 FM의 채널은 변경 없음이다. 채널별 선택 순서는 `global`이 `APN2_*_global_standard` → `USE1_*_global_standard` →
   평면 `*_global_standard` → 레거시 `APN2_*TokenCount_Global` → `USE1_*TokenCount_Global`, `us`가 `USE1_*_standard` → 평면
   `*_standard` → 레거시 `USE1_*TokenCount`, `inregion:<region>`이 리전 접두 → 평면 `*_standard`다. 단위는 USD per 1M tokens로
   해석하고 GPT-6 Astra 카드 값(standard 11 / 55, global 10 / 50)으로 fixture에서 고정한다.
5. Anthropic 문서는 헤더 이름("Model", "Base input tokens", "Output tokens")으로 열을 찾고, 모델명과 값 셀에서 `<sup>…</sup>`를
   지우고, 모델명 끝 괄호 그룹(마크다운 링크 포함)을 지운 뒤 매핑 표와 **정확 일치**로만 연결한다. 표에서 "Claude Opus 5.5"가
   "Claude Opus 5"보다, "Claude Fable 5.1"이 "Claude Fable 5"보다 먼저 나오므로 접두 일치는 금지다(prober `_is_point_release_of`
   실사고와 같은 유형).
6. 채널별 판정. 변화율은 입력과 출력 각각 `|new − old| / old`(`Decimal`)다.

| 결과 | 조건 | 기록 |
|------|------|------|
| `unchanged` | 새 값 = 현재 유효 값 | 유효 행의 `observed_at`, `run_id`, `source_id`만 갱신(offerId가 재발급돼도 참고 자료가 현재 오퍼를 가리킨다) |
| `changed` | 다르고 두 변화율 모두 0.5 이하(경계 포함) | 새 행 `verified`, `effective_from = observed_at =` 런 시작 시각 |
| `pending` | 어느 쪽이든 0.5 초과 | 같은 값의 `pending_review` 또는 `rejected` 행이 있으면 그 행의 `observed_at`만 갱신(거부한 값은 값이 달라질 때까지 다시 올라오지 않는다), 없으면 새 행 `pending_review`, `effective_from = observed_at =` 런 시작 시각 |
| `no_baseline` | 유효 행이 없음(seed에도 없는 새 model_id) | 같은 값의 `pending_review` 또는 `rejected` 행이 있으면 그 행의 `observed_at`만 갱신, 없으면 새 행 `pending_review`, `effective_from` 1970-01-01, `observed_at` 런 시작 시각 |
| `rejected` | `pending` 또는 `no_baseline` 조건이지만 같은 값의 `rejected` 행이 있음 | 그 행의 `observed_at`만 갱신(관측 성공이며 검토 대기 수에 넣지 않는다) |
| `skipped:<reason>` | 공식 값을 구하지 못함(출처 실패, 오퍼 수 ≠ 1, 필수 차원 없음, 매핑 없음, 파싱 실패, `deadline`) | 변경 없음 |

7. 런 행은 시작할 때 `running`으로 넣고 커밋한다. 끝날 때 공식 값을 얻은 채널이 하나도 없으면(모든 출처 실패, 첫 호출 전 상한 초과
   포함) `failed`, `skipped:<reason>` 채널이 하나라도 있거나 활성 채널이 없는 출처가 있으면(CP 디스커버리 실패 →
   `anthropic_doc: no active channels`) `partial`(상한을 넘긴 뒤 남은 채널은 `skipped:deadline`), 그 밖에는 `completed`다.
   `summary`에는 출처별 호출, ok, failed 수와 채널별 결과, 오류(최대 50개)를 싣고, `changes`는 새 verified 행 수, `pending`은 런 뒤
   검토 대기 중인 채널 수다. 러너는 `completed`, `partial`이면 exit 0, `failed`면 exit 1이고 `os._exit`로 끝난다.

### 4. 검토 대기 승인 (관리자)

- `GET /api/admin/pricing/pending`은 대기 행마다 현재 유효 값, 새 값, 변화율, 출처, 사유(`changed`, `no_baseline`)를 준다.
- `POST /api/admin/pricing/pending/{id}/approve`는 `status`만 `verified`로 바꾼다. `effective_from`은 삽입 때 값(관측 런의 시작
  시각, `no_baseline`이면 1970-01-01) 그대로이며, 그보다 늦은 verified 행이 이미 있으면 응답 `warnings`에 싣는다.
  `POST …/reject`는 `rejected`로 바꾼다. 없는 id는 404, `pending_review`가 아닌 행은 409다.
- 모두 admin 전용(`username == "admin"`)이다. 처리한 backend 태스크는 `/api/pricing` 캐시를 바로 비우고, 다른 backend 태스크는
  최대 60초 늦을 수 있다.

### 5. 비용 계산

- `price_history.effective_prices_subquery()`는 `seed`, `verified` 행에 `effective_to = LEAD(effective_from) OVER (PARTITION BY
  model_id ORDER BY effective_from, id)`를 붙인다. `with_row_cost(query)`는 `probe_results`를 `model_id` 일치와 `timestamp >=
  effective_from AND (effective_to IS NULL OR timestamp < effective_to)`로 **LEFT JOIN**하고
  `row_cost = (COALESCE(input_tokens, 0) × input_per_mtok + COALESCE(output_tokens, 0) × output_per_mtok) / 1,000,000`(float
  캐스트)을 만든다. 단가 행이 없으면 NULL이다.
- `/api/cost/summary`, `/api/cost/channel-compare`는 `row_cost`를 모델(또는 채널)별로 합산한다. 단가가 없는 모델은 비용 NULL
  (화면 "-")이고 토큰은 합계에 들어가며, 채널 비교는 NULL을 0으로 더하던 동작을 유지한다. `/api/cost/trend`와
  `/api/efficiency/score`는 기존 Python 순회에 행 단위 `row_cost`를 쓴다(efficiency는 단가가 있는 success 행만 평균). 필터와
  응답 형태는 그대로다.
- v2.29.1 `PRICE_TABLE`, `estimate_cost_usd` 고정 사본을 테스트에 두고, 단가 변경이 없는 구간에서 새 계산이 사본 계산과
  같음(교정 11채널 제외)과 반환형이 float임을 고정한다.

### 6. 표시와 다운로드

- `GET /api/pricing`(공개, 60초 인메모리 캐시)이 표 전체를 내려준다. 표시 순서(`PROVIDER_ORDER` Anthropic Claude → Amazon Nova →
  OpenAI, 그 안은 `FAMILY_ORDER`)와 각주 번호는 백엔드가 정하고, 프런트와 export 3형식은 받은 순서와 번호를 그대로 쓴다.
- 셀별 계산 상태 `verification`: `seed_only`(유효 행이 seed이고 한 번도 확인되지 않음), `verified`(유효 행의 `observed_at`이 가장
  최근에 끝난 런의 시작 시각 이후 — 런 상태 무관), `stale`(그 밖). 한 출처가 계속 실패하면 그 채널은 곧 `stale`이 되어 "자동 확인
  안 됨" 배지로 드러난다.
- 면책 문구는 `pricing_sources.DISCLAIMER` 한 곳에만 둔다. KO "이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며,
  AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요.", EN "This price list is compiled automatically from
  public sources for reference only and is not an official AWS statement. Always confirm final prices on the official pricing
  pages." 화면 상단 안내 상자, 참고 자료 끝, CSV 첫 줄, Markdown 처음과 끝, JSON 본문에 모두 들어간다.
- GPT-5.6 Sol 프로모션(In-Region, Geo $4.40 / $22, Global $4 / $20)의 "최소 2026-11-21까지"는 현재 공식 출처 어디에도 없다.
  그래서 공식 출처가 아닌 **수동 메모**(`PRICE_NOTES`, 근거는 2026-09-23 AWS 모델 카드 기재와 CHANGELOG v2.28.1)로 두고 참고
  자료에 `manual_note`로 구분해 싣는다. 동기화가 이전 단가(`prior_price`)를 관측하면 메모는 응답에서 빠진다.
- 범위: USD, Standard 입력과 출력만(캐시, batch, long-context, priority, flex 제외), 휴면 1P와 숨김 채널 제외.

### 7. 인프라

- `cdk/lib/stacks/scheduler-stack.ts`: `PricingSyncTaskRole`(인라인 정책 `bedrock:ListFoundationModelAgreementOffers`,
  `pricing:GetProducts`, Resource `*`만 — 모델 호출 권한 없음), 공용 `buildTaskDef`로 만든 `PricingSyncTaskDef`(AutoProber와 같은
  env, secret, 0.5 vCPU / 1 GB, 로그 그룹 `/ecs/pricingsync` 14일), `PricingSyncSchedule` `rate(12 hours)`. Scheduler 역할의
  `RunTaskFamilyWildcard`에 새 family `:*`, `PassTaskRoles`에 새 역할을 넣는다(ADR-011).
- 공식 출처 호출은 App 서브넷 NAT egress로 나간다(us-east-1 Bedrock control plane과 Price List API, `platform.claude.com`).

## Consequences

- (+) 단가가 코드 수정 없이 12시간마다 공식 출처를 따라간다. 두 표를 맞추는 수작업과 prefix fallback 오매칭이 사라졌다.
- (+) 과거 비용이 단가 변경에 흔들리지 않는다. 첫 동기화 이후의 인하, 인상은 관측한 런의 시작 시각부터 적용된다.
- (+) 코드 단가 오류 11채널이 과거까지 교정됐다. Bedrock Claude US 채널 비용이 약 10% 늘고 Nova 2.0 Lite 비용이 크게 는다.
- (+) 형식 드리프트(차원 스킴, 문서 구조, 단위)는 허용 목록과 fail-closed로 잘못된 값 적용을 막고 "자동 확인 안 됨"으로 드러난다.
  50% 안전장치가 단위 오류(1000배)를 막는다.
- (−) **v2.30.0 이전 구간의 알려진 단가 변경은 재구성하지 않았다.** 2026-07-30 GPT-5.6 Luna, Terra 인하 이전과 GPT-5.6 Sol
  프로모션 이전의 프로브도 현재 seed 단가로 계산된다(기존 소급 계산과 같은 결과).
- (−) **정상적인 대폭 변경도 승인이 필요하다.** 2026-07-30 Luna −80% 같은 인하는 `pending_review`로 가며, 관리자가 승인하면
  관측한 런의 시작 시각부터 적용된다. 반대로 Sol 프로모션이 끝나 이전 단가로 돌아가면 입력 +25%, 출력 +50%(22 → 33, 20 → 30)라
  경계 포함 규칙으로 자동 적용된다.
- (−) 승인 직후 다른 backend 태스크는 최대 60초 동안 이전 표를 줄 수 있다.
- (−) 오퍼 rate card에는 단위 스케일 정보가 없어 "USD per 1M tokens" 해석을 fixture 대조로 고정한다. AWS가 스킴을 바꾸면 파서와
  fixture를 고쳐야 한다.
- (−) 새 모델을 추가할 때 `pricing_sources.py` 매핑과 `pricing_seed.py`도 고쳐야 한다. "활성 채널 전부가 분류되고 seed 단가가 있다"
  테스트가 CI에서 누락을 잡고, 운영에서는 `no_baseline` 검토 대기로 드러난다.
- (−) 1P direct 채널(휴면)은 분류 대상이 아니다. 재노출하려면 1P 정가 출처와 분류, seed를 새로 설계해야 한다.
- ADR-025, ADR-027, ADR-028의 "비용은 조회 시점 계산이라 소급 재계산된다" 문장은 당시 기록으로 남기고, ADR-025에 이 ADR을 가리키는
  후속 절을 붙였다.
```

#### `t14-docs` — `@scratch/patches/t14-docs.patch`

<!-- plan-block id=t14-docs path=@scratch/patches/t14-docs.patch sha256=28cc9d2f258f6f1fbdb228b4c97885d0ff1079e1ec96238dbb9f00e39cab8ba3 -->
````diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 563ff86..db1920a 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -7,6 +7,40 @@
 - 카테고리: `Added` / `Changed` / `Fixed` / `Removed` / `Security` / `Infra` / `Docs`
 - 매 commit 시 PR 또는 작업 종료 시 한 항목 추가.
 
+## v2.30.0 — 2026-09-26
+
+### Added
+- **Unit Prices page (`/pricing`, "비용 단가")** (user request 2026-09-26). One row per model family and one column per channel (Claude Platform on AWS, Global, US, In-Region) show the Standard input and output price per 1M tokens (`$4.00 / $20.00`). Every price carries a numbered footnote that jumps to its entry in the reference list, and the page downloads as CSV, Markdown or JSON (`/api/pricing/export?format=csv|md|json&lang=ko|en`, file `llm-monitor-unit-prices-YYYY-MM-DD.<ext>`). An amber box at the top and a line after the references say "This price list is compiled automatically from public sources for reference only and is not an official AWS statement. Always confirm final prices on the official pricing pages.", and every download carries the same text. Cells get a "Not auto-verified" badge when the latest finished sync did not observe them, "Pending review" when a large change waits for approval, and GPT-5.6 Sol gets a manual promotion note (at least until 2026-11-21) that turns into "check whether the promotion ended" after that date. The menu item sits right after Cost. The table covers the 19 families of the 55 active channels; dormant 1P and hidden channels are excluded.
+- **비용 단가 페이지(`/pricing`, "Unit Prices")**(2026-09-26 사용자 요청). 모델 패밀리마다 한 행, 채널(Claude Platform on AWS, Global, US, In-Region)마다 한 열로 1M 토큰당 Standard 입력, 출력 단가(`$4.00 / $20.00`)를 보여 준다. 단가마다 번호 각주가 붙고 누르면 참고 자료 목록의 해당 항목으로 이동하며, CSV, Markdown, JSON으로 내려받는다(`/api/pricing/export?format=csv|md|json&lang=ko|en`, 파일 `llm-monitor-unit-prices-YYYY-MM-DD.<ext>`). 상단 호박색 안내 상자와 참고 자료 끝에 "이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요."를 표시하고, 모든 다운로드 파일에도 같은 문구를 넣는다. 가장 최근에 끝난 동기화가 확인하지 못한 셀에는 "자동 확인 안 됨", 큰 변경이 승인을 기다리는 셀에는 "검토 대기" 배지가 붙는다. GPT-5.6 Sol에는 수동 메모인 프로모션 배지(최소 2026-11-21까지)가 붙고, 그 날짜가 지나면 "프로모션 종료 여부 확인 필요"로 바뀐다. 메뉴는 "비용" 바로 뒤다. 표는 활성 55채널의 패밀리 19개를 담고, 휴면 1P와 숨김 채널은 뺀다.
+- **Official prices synced every 12 hours.** A new scheduled PricingSync task (`python -m pricing_sync_runner --once`, `rate(12 hours)`) reads three official sources: the Bedrock agreement-offer rate card (`ListFoundationModelAgreementOffers`, 18 foundation models covering the 20 Bedrock Claude and 25 OpenAI channels), the AWS Price List API (`GetProducts`, Nova 2.0 Lite, 1K-token prices × 1000) and Anthropic's `pricing.md` (the 9 Claude Platform on AWS channels at standard pricing). Offer dimensions must fully match an allow-list regex, so batch, flex, priority, long-context, cache, reserved, GovCloud and other region prefixes never count; the Anthropic table is read by header names with exact model-name matching, so "Claude Opus 5.5" never lands on Opus 5. A change of at most 50% on both input and output (50% included) applies from the start of the run that observed it; above that it waits as `pending_review` for an admin (`GET /api/admin/pricing/pending`, `POST /api/admin/pricing/pending/{id}/approve`, `POST …/reject`). A channel whose official value cannot be read keeps its price and shows as not auto-verified. Runs are serialized with `pg_advisory_lock(917350004)`, capped at 300 s, and never store or log `offerToken` or the presigned `legalTerm.url`.
+- **공식 단가를 12시간마다 동기화한다.** 새 스케줄 태스크 PricingSync(`python -m pricing_sync_runner --once`, `rate(12 hours)`)가 공식 출처 3개를 읽는다. Bedrock agreement offer rate card(`ListFoundationModelAgreementOffers`, 파운데이션 모델 18개로 Bedrock Claude 20채널과 OpenAI 25채널), AWS Price List API(`GetProducts`, Nova 2.0 Lite, 1K 토큰 단가 × 1000), Anthropic `pricing.md`(Claude Platform on AWS 9채널, 표준 단가)다. 오퍼 차원 이름은 허용 목록 정규식에 완전히 일치해야 하므로 batch, flex, priority, long-context, cache, reserved, GovCloud, 그 밖의 리전 접두는 후보가 되지 않는다. Anthropic 표는 헤더 이름으로 열을 찾고 모델명을 정확 일치로만 연결하므로 "Claude Opus 5.5"가 Opus 5에 붙지 않는다. 입력과 출력 모두 50% 이하로 바뀌면(50% 포함) 관측한 런의 시작 시각부터 적용하고, 그보다 크면 `pending_review`로 두고 관리자 승인을 기다린다(`GET /api/admin/pricing/pending`, `POST /api/admin/pricing/pending/{id}/approve`, `POST …/reject`). 공식 값을 읽지 못한 채널은 기존 단가를 유지하고 자동 확인 안 됨으로 표시된다. 런은 `pg_advisory_lock(917350004)`로 직렬화하고 300초 상한을 두며, `offerToken`과 presigned `legalTerm.url`은 저장하거나 로그에 남기지 않는다.
+- **`GET /api/pricing`** (public, 60 s in-process cache) returns the families in display order with `tiers` `cp`, `global`, `us` and `in_region` (always an array; regions with the same price are grouped), `models` (model_id → current price), `references` with the footnote numbers assigned by the backend, `last_sync`, `pending_review` and the disclaimer in both languages. The export's JSON is the same body.
+- **`GET /api/pricing`**(공개, 60초 인메모리 캐시)는 패밀리를 표시 순서대로 내려주며 `tiers`는 `cp`, `global`, `us`, `in_region`(항상 배열, 같은 단가의 리전은 한 원소로 묶음)이다. `models`(model_id → 현재 단가), 백엔드가 번호를 매긴 `references`, `last_sync`, `pending_review`, 두 언어 면책 문구를 함께 싣는다. 다운로드 JSON은 같은 본문이다.
+
+### Changed
+- **Costs use the unit price in effect at each probe's time** (ADR-030; supersedes the ADR-025 rule that re-priced every past row at query time). Prices are stored per `model_id` in the new `price_history` table (`effective_from`, status `seed`, `verified`, `pending_review` or `rejected`), and `/api/cost/summary`, `/api/cost/channel-compare`, `/api/cost/trend` and `/api/efficiency/score` price every row through a range join on an exact `model_id` match (`LEAD(effective_from)`), so the prefix fallback is gone by construction. Response shapes are unchanged and a model without a price still shows "-". History starts with the first sync: the seed (the current official prices, effective from 1970-01-01) covers all earlier time, so price changes made before v2.30.0 (the 2026-07-30 GPT-5.6 Luna and Terra cuts, the GPT-5.6 Sol promotion) are not reconstructed and those rows read the same as before.
+- **비용은 각 프로브 시각에 유효했던 단가로 계산한다**(ADR-030, 과거 행 전체를 조회 시점 단가로 다시 계산하던 ADR-025 규칙을 대체). 단가는 새 `price_history` 테이블에 `model_id` 단위로 저장하고(`effective_from`, 상태 `seed`, `verified`, `pending_review`, `rejected`), `/api/cost/summary`, `/api/cost/channel-compare`, `/api/cost/trend`, `/api/efficiency/score`는 행마다 `model_id` 정확 일치와 시각 범위 조인(`LEAD(effective_from)`)으로 단가를 붙인다. 그래서 prefix fallback이 구조적으로 사라졌다. 응답 형태는 그대로이고 단가가 없는 모델은 여전히 "-"다. 이력은 첫 동기화부터 시작한다. seed(현재 공식 단가, 1970-01-01부터 유효)가 그 이전 구간 전체에 적용되므로 v2.30.0 이전의 단가 변경(2026-07-30 GPT-5.6 Luna, Terra 인하, GPT-5.6 Sol 프로모션)은 재구성하지 않고 그 행들은 이전과 같은 값으로 보인다.
+- **Model Explorer and Comparison Lab read prices from `/api/pricing` `models`**, formatted like the price table, and "1M in/out" is translated in KO and EN. Comparison Lab shows "—" for a model without a price and leaves it out of the cheapest highlight. The Cost page methodology text now says prices are refreshed from official sources every 12 hours and applied at each probe's time, with a link to Unit Prices.
+- **모델 탐색과 Comparison Lab은 `/api/pricing` `models`에서 단가를 읽는다.** 표기는 단가 표와 같은 포맷터를 쓰고 "1M in/out"은 KO, EN 모두 번역했다. Comparison Lab은 단가가 없는 모델을 "—"로 표시하고 최저 비용 강조에서 뺀다. 비용 화면 방법론 문단은 "단가는 공식 출처에서 12시간마다 자동 갱신되며 각 프로브 시각의 단가로 계산한다"로 바꾸고 비용 단가 메뉴 링크를 달았다.
+
+### Fixed
+- **11 channels were priced wrong in code; corrected for all history** (user decision 2026-09-26: a wrong value from the start, not a price change). Bedrock Claude **US** (`us.anthropic.*`, 10 channels) carried the Global price because `_normalize_key` mapped `us.` and `global.` to the same key, about 9.1% under; the official US (Geo) price is Global × 1.1: Fable 5.1 and Fable 5 $11 / $55, Opus 5.5 $4.40 / $22, Opus 5, 4.8, 4.7 and 4.6 $5.50 / $27.50, Sonnet 5 $2.20 / $11, Sonnet 4.6 $3.30 / $16.50, Haiku 4.5 $1.10 / $5.50. **Nova 2.0 Lite** (`us.amazon.nova-2-lite-v1:0`) used the first-generation Nova Lite price $0.06 / $0.24; the official price is $0.33 / $2.75 (5.5× on input, 11.5× on output). The other 44 active channels already matched the official values.
+- **코드 단가 오류 11채널을 과거까지 교정했다**(2026-09-26 사용자 결정, 단가 변경이 아니라 처음부터 틀린 값). Bedrock Claude **US**(`us.anthropic.*`, 10채널)는 `_normalize_key`가 `us.`와 `global.`을 같은 키로 합쳐 Global 단가가 붙어 약 9.1% 과소 산정됐다. 공식 US(Geo) 단가는 Global × 1.1이다. Fable 5.1, Fable 5 $11 / $55, Opus 5.5 $4.40 / $22, Opus 5, 4.8, 4.7, 4.6 $5.50 / $27.50, Sonnet 5 $2.20 / $11, Sonnet 4.6 $3.30 / $16.50, Haiku 4.5 $1.10 / $5.50. **Nova 2.0 Lite**(`us.amazon.nova-2-lite-v1:0`)는 1세대 Nova Lite 단가 $0.06 / $0.24를 쓰고 있었고 공식 단가는 $0.33 / $2.75다(입력 5.5배, 출력 11.5배 과소). 나머지 활성 44채널은 공식 값과 같았다.
+
+### Removed
+- `backend/pricing.py` (`PRICE_TABLE`, `get_pricing`, `_normalize_key`, `estimate_cost_usd`) and the frontend mirror in `frontend/src/lib/pricing.ts` (`PRICE_TABLE`, `getPricing`, `estimateCost`; only `formatCost` remains). There is no compatibility module.
+- `backend/pricing.py`(`PRICE_TABLE`, `get_pricing`, `_normalize_key`, `estimate_cost_usd`)와 `frontend/src/lib/pricing.ts`의 프런트 미러(`PRICE_TABLE`, `getPricing`, `estimateCost`, `formatCost`만 남김)를 삭제했다. 호환 모듈은 없다.
+
+### Infra
+- CDK `BedrockMonitor-Scheduler`: new `PricingSyncTaskRole` (inline policy `bedrock:ListFoundationModelAgreementOffers` and `pricing:GetProducts` on `*` only, no model invocation), `PricingSyncTaskDef` from the shared `buildTaskDef` (the AutoProber env and secrets for Claude Platform on AWS discovery and OpenAI registration, 0.5 vCPU / 1 GB, log group `/ecs/pricingsync` kept 14 days), `PricingSyncSchedule` `rate(12 hours)`, the new family in the scheduler role's `RunTaskFamilyWildcard` and the new role in `PassTaskRoles` (ADR-011), and the output `PricingSyncScheduleName`. CDK tests pin 6 schedules, 6 task definitions, the command, the two IAM actions and the scheduler grants (85 tests). No new env. The tables `price_history` and `price_sync_runs` come from `create_all`, and backend startup inserts the seed under `pg_advisory_xact_lock(917350003)`. Deploy with the digest-pinned CDK path (`--exclusively BedrockMonitor-AppServices BedrockMonitor-Scheduler`); the image-only path cannot create the new task definition. After the deploy, run PricingSync once by hand (`docs/runbooks/deploy.md` §5-4).
+- CDK `BedrockMonitor-Scheduler`: `PricingSyncTaskRole`(인라인 정책 `bedrock:ListFoundationModelAgreementOffers`, `pricing:GetProducts`, Resource `*`만, 모델 호출 권한 없음), 공용 `buildTaskDef`로 만든 `PricingSyncTaskDef`(Claude Platform on AWS 디스커버리와 OpenAI 등록을 위해 AutoProber와 같은 env와 secret, 0.5 vCPU / 1 GB, 로그 그룹 `/ecs/pricingsync` 14일 보존), `PricingSyncSchedule` `rate(12 hours)`, Scheduler 역할 `RunTaskFamilyWildcard`의 새 family와 `PassTaskRoles`의 새 역할(ADR-011), output `PricingSyncScheduleName`을 추가했다. CDK 테스트가 스케줄 6개, 태스크 정의 6개, 명령, IAM 액션 2개, Scheduler 권한을 고정한다(85건). 신규 env는 없다. `price_history`, `price_sync_runs` 테이블은 `create_all`이 만들고 backend 기동이 `pg_advisory_xact_lock(917350003)` 아래 seed를 넣는다. digest 고정 CDK 경로(`--exclusively BedrockMonitor-AppServices BedrockMonitor-Scheduler`)로 배포한다. 이미지-only 경로는 새 태스크 정의를 만들지 못한다. 배포 뒤 PricingSync를 한 번 수동으로 실행한다(`docs/runbooks/deploy.md` §5-4).
+
+### Docs
+- New **ADR-030** (official price sources, per-`model_id` price history, the seed and the 11 corrected channels, the 50% guard and admin approval, time-effective costs, no reconstruction before v2.30.0, the manual Sol promotion note, infra). ADR-025 gains a v2.30.0 follow-up that points to it, and ADR-028 records that the GPT-6 Sol and Luna model cards are now published and match the offers. Updated: `README.md` (EN/KO features, eleven pages, usage, project tree, API table), `docs/architecture.md` (six scheduled tasks in both Mermaid diagrams, the unit price path, tables, ADR 030), `docs/api-reference.md` (`/api/pricing`, `/api/pricing/export`, admin approval, cost semantics), `CLAUDE.md`, `backend/CLAUDE.md`, `backend/routers/CLAUDE.md`, `backend/tests/CLAUDE.md`, `frontend/src/lib/CLAUDE.md`, `frontend/src/components/CLAUDE.md`, `cdk/CLAUDE.md`, and the runbooks (`deploy.md` §5-4 PricingSync manual run and checks; `troubleshooting.md` sync failures, pending approval, the GPT-5.6 Sol promotion check after 2026-11-21).
+- **ADR-030**을 신설했다(공식 단가 출처, `model_id` 단위 단가 이력, seed와 교정 11채널, 50% 안전장치와 관리자 승인, 시점 단가 비용, v2.30.0 이전 비재구성, Sol 프로모션 수동 메모, 인프라). ADR-025에는 이 ADR을 가리키는 v2.30.0 후속 절을, ADR-028에는 GPT-6 Sol, Luna 모델 카드가 게시돼 오퍼 값과 일치한다는 기록을 덧붙였다. `README.md`(두 언어의 기능, 11개 페이지, 사용법, 프로젝트 트리, API 표), `docs/architecture.md`(두 Mermaid 다이어그램의 스케줄 태스크 6개, 단가 경로, 표, ADR 030), `docs/api-reference.md`(`/api/pricing`, `/api/pricing/export`, 관리자 승인, 비용 의미), `CLAUDE.md`, `backend/CLAUDE.md`, `backend/routers/CLAUDE.md`, `backend/tests/CLAUDE.md`, `frontend/src/lib/CLAUDE.md`, `frontend/src/components/CLAUDE.md`, `cdk/CLAUDE.md`, 런북(`deploy.md` §5-4 PricingSync 수동 실행과 확인, `troubleshooting.md` 동기화 실패, 검토 대기 승인, 2026-11-21 이후 GPT-5.6 Sol 프로모션 확인)을 갱신했다.
+- Version bumped to **v2.30.0** (`frontend/src/lib/version.ts`, `frontend/package.json` + `package-lock.json`, `backend/main.py` FastAPI version, `README.md` badge, `CLAUDE.md` overview).
+- 버전을 **v2.30.0**으로 범프했다(`frontend/src/lib/version.ts`, `frontend/package.json` + `package-lock.json`, `backend/main.py` FastAPI version, `README.md` 배지, `CLAUDE.md` 개요).
+
 ## v2.29.1 — 2026-09-26
 
 ### Changed
diff --git a/CLAUDE.md b/CLAUDE.md
index 0b16aec..40b087a 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -2,7 +2,7 @@
 
 ## Project Overview / 프로젝트 개요
 
-**Amazon Bedrock LLM Monitor** (v2.29.1 — 현재 버전은 `frontend/src/lib/version.ts`가 source of truth) — A real-time dashboard for response speed, throughput, reliability, cost, and output-quality monitoring of AWS Bedrock + Anthropic CP on AWS + OpenAI (Mantle/1P) LLM channels.
+**Amazon Bedrock LLM Monitor** (v2.30.0 — 현재 버전은 `frontend/src/lib/version.ts`가 source of truth) — A real-time dashboard for response speed, throughput, reliability, cost, and output-quality monitoring of AWS Bedrock + Anthropic CP on AWS + OpenAI (Mantle/1P) LLM channels.
 
 **Amazon Bedrock LLM 모니터** — Bedrock + Anthropic CP on AWS 채널의 응답 속도·처리량·신뢰성·비용·출력 품질을 실시간으로 모니터링하는 대시보드.
 
@@ -12,7 +12,7 @@
 - **Frontend**: Next.js 16 standalone + React + Tailwind + Recharts + react-markdown + FloatingChat + PWA(iPhone/iPad 홈 화면 설치 — manifest.ts·앱 아이콘·safe-area, v2.21.0)
 - **Infra**: CDK v2 TypeScript / 8 stacks (Network, Data, Cluster, AgentCore, AppServices, Edge, Scheduler, Observability)
 - **Edge**: CloudFront VPC Origin → Internal ALB → ECS Fargate × 2 (backend, frontend). VPC Origin → ALB는 현재 VPC 내부 HTTP:80(`edge-stack.ts` `HTTP_ONLY`, 운영 cert 정착 전 임시 — ALB는 internal + private subnet + VPC CIDR SG), ALB에는 HTTPS:443 리스너도 있음
-- **Scheduling**: EventBridge Scheduler → AutoProber + Insights (`rate(5 minutes)`, Claude Platform on AWS 채널도 매 사이클 — v2.29.1에서 v2.29.0의 10분 주기를 되돌림) + ParityRun (12시간 주기) + GptBench (`rate(15 minutes)`) + FeaturesVerify (매일 17:30 UTC) Fargate Tasks — `cdk/lib/stacks/scheduler-stack.ts`
+- **Scheduling**: EventBridge Scheduler → AutoProber + Insights (`rate(5 minutes)`, Claude Platform on AWS 채널도 매 사이클 — v2.29.1에서 v2.29.0의 10분 주기를 되돌림) + ParityRun (12시간 주기) + GptBench (`rate(15 minutes)`) + FeaturesVerify (매일 17:30 UTC) + PricingSync (`rate(12 hours)`, 공식 단가 동기화 — v2.30.0) Fargate Tasks — `cdk/lib/stacks/scheduler-stack.ts`
 - **AI**: Claude Sonnet 4.6 챗봇 (4 tools) + Haiku 4.5 dynamic followups + Sonnet 4.6 인사이트 잡 (KO·EN 요약) — 모델 ID는 `backend/agent/bedrock.py` `CHAT_MODEL_ID`/`INSIGHTS_MODEL_ID`, followups는 `backend/routers/chat.py` `_generate_followups`가 source of truth
 
 자세한 v2 설계는 [`docs/architecture.md`](./docs/architecture.md) / [`docs/decisions/ADR-*.md`](./docs/decisions/) / [`.kiro/specs/v2-upgrade/`](./.kiro/specs/v2-upgrade/) (v2.0.0 당시 설계 기록 — 9개 모델, 인사이트 30분 주기 기준이라 현행과 다름).
@@ -31,7 +31,8 @@ Internal ALB
                 ├── /?view=manual — 수동 프로브 (ProbeConfigPanel + StreamingView, 결과/차트/비교 탭, auth)
                 ├── /chat         — 챗봇 팝업 창 진입점 (Firefox/Safari, FloatingChat이 연다)
                 ├── /prompts      — Prompt CRUD + Bedrock OptimizePrompt (auth)
-                ├── /cost         — 30-day projection + per-model + channel compare
+                ├── /cost         — 30-day projection + per-model + channel compare (프로브 시각의 단가로 계산, v2.30.0)
+                ├── /pricing      — 비용 단가 (모델 패밀리 × 채널 Standard 입력/출력 단가 + 번호 각주 출처 + CSV/Markdown/JSON 다운로드 + 면책 문구, 12시간 자동 갱신, v2.30.0)
                 ├── /reliability  — Family/channel success rate + error buckets
                 ├── /efficiency   — 0-100 Token Efficiency Score (weighted)
                 ├── /analysis     — Stop reason 분포 + Output length 분포
@@ -46,7 +47,8 @@ EventBridge Scheduler (rate 5 min)
   ├── Insights Fargate Task    → Sonnet 4.6 KO+EN summary (`INSIGHTS_MODEL_ID`), save Insight row
   ├── ParityRun Fargate Task   → 12시간 주기 모델×surface×피처 실행-증거 스윕 (v2.12.0)
   ├── GptBench Fargate Task    → 15분 주기 GPT 18채널(Mantle 인리전 11 + Global/US CRIS 7) × 10회 TTFB/TTFT 벤치 (v2.18.0; Terra Global CRIS 포함 v2.20.1, GPT-6 Astra 3채널 v2.25.1, GPT-6 Sol/Luna 6채널 v2.28.0)
-  └── FeaturesVerify Fargate Task → 일 1회(cron 17:30 UTC = 02:30 KST 고정, v2.29.0) Claude API Features 39행(= 문서 피처 33 + 코어 4 + Models API 1 + strict_tool_use 분할 1) × 5 surface × 대표 5모델 = 975셀 실행-증거 스윕 (v2.23.0; Opus 5.5 편입 v2.28.0)
+  ├── FeaturesVerify Fargate Task → 일 1회(cron 17:30 UTC = 02:30 KST 고정, v2.29.0) Claude API Features 39행(= 문서 피처 33 + 코어 4 + Models API 1 + strict_tool_use 분할 1) × 5 surface × 대표 5모델 = 975셀 실행-증거 스윕 (v2.23.0; Opus 5.5 편입 v2.28.0)
+  └── PricingSync Fargate Task → 12시간 주기(rate(12 hours)) 공식 단가 동기화 — Bedrock agreement offer rate card + AWS Price List + Anthropic pricing.md → price_history (50% 초과 변경은 관리자 승인 대기, v2.30.0, ADR-030)
 
 Backend ↔ Bedrock (Seoul region inference profiles us.*, global.*) + Anthropic CP on AWS + OpenAI (Bedrock Mantle + 1P direct api.openai.com)
                                   (aws-external-anthropic.us-east-2.api.aws, workspace-id header)
@@ -72,7 +74,14 @@ model-monitoring/
 │   ├── visibility.py        # 조회 노출 필터 — HIDDEN_MODEL_PATTERNS (기본 `(1P)`) (v2.19.1)
 │   ├── tests/               # pytest (python3.12)
 │   ├── prober.py            # Probe logic (Bedrock + Anthropic CP + OpenAI Mantle/Global/US/1P), AVAILABLE_MODELS (55개 활성 + 1P 5개 휴면), retry, stop_reason capture
-│   ├── pricing.py           # 모델별 token 단가 + estimate_cost_usd
+│   ├── pricing_sources.py   # 단가 순수 데이터 — price_identity(model_id → family/채널/출처), 오퍼 FM id, Anthropic 문서 모델명, Price List usagetype 매핑, PROVIDER_ORDER, FAMILY_ORDER(프런트와 동일, pytest 고정), DISCLAIMER, OFFICIAL_PAGES, PRICE_NOTES (v2.30.0)
+│   ├── pricing_seed.py      # 활성 55채널 공식 단가 seed(SEED, CP는 CP_SEED family_key 단위) + ensure_seed(model_id 단위 멱등, pg_advisory_xact_lock(917350003))
+│   ├── pricing_parsers.py   # 출처별 순수 파서 — offers rateCard(DIMENSION_RE 허용 목록), Price List(1K → 1M), Anthropic markdown(헤더 이름, <sup> 제거, 정확 일치)
+│   ├── pricing_sync.py      # 12시간 동기화 — 가져오기, 비교(CHANGE_THRESHOLD 0.5 경계 포함), pending_review, price_sync_runs 기록, 상한 300초
+│   ├── pricing_sync_runner.py # CLI entry: `python -m pricing_sync_runner --once` (PricingSync Fargate task) — create_tables → CP/OpenAI 등록 → ensure_seed → run_sync(pg_advisory_lock(917350004)) → os._exit
+│   ├── price_history.py     # 유효 단가 조회, 행 단위 비용 서브쿼리(with_row_cost — /api/cost/*, /api/efficiency/score), verification(seed_only/verified/stale)
+│   ├── pricing_payload.py   # /api/pricing 응답 조립(표시 순서, 각주 번호, 참고 자료) + 숫자 직렬화
+│   ├── pricing_export.py    # CSV(BOM + 면책 첫 줄), Markdown, JSON 내보내기 순수 함수
 │   ├── auth.py              # JWT + bcrypt + ADMIN_EMAIL=whchoi98@gmail.com
 │   ├── models.py            # ProbeResult.stop_reason, .category 컬럼 포함
 │   ├── schemas.py           # Pydantic; ProbeResultResponse.stop_reason Optional
@@ -97,7 +106,8 @@ model-monitoring/
 │       ├── prompts.py       # /api/prompts/* — prompt set CRUD + Bedrock OptimizePrompt (auth)
 │       ├── chat.py          # /api/chat/stream — Sonnet 4.6 + 4 tools + dynamic followups
 │       ├── insights.py      # /api/insights/* — list/latest/stream-regenerate
-│       ├── cost.py          # /api/cost/* — summary, channel-compare, trend
+│       ├── cost.py          # /api/cost/* — summary, channel-compare, trend (행 단위 시점 단가, v2.30.0)
+│       ├── pricing.py       # /api/pricing(60초 캐시), /api/pricing/export(csv|md|json) 공개 + admin_router /api/admin/pricing/pending, approve, reject (v2.30.0)
 │       ├── reliability.py   # /api/reliability/multi-channel — family/channel grouped
 │       ├── efficiency.py    # /api/efficiency/score — 0-100 weighted score per category
 │       ├── analysis.py      # /api/analysis/* — stop-reasons, output-length (v2.1.0)
@@ -116,6 +126,7 @@ model-monitoring/
 │   │   │   ├── chat/page.tsx      # 챗봇 팝업 창 (ChatPanel variant="popup")
 │   │   │   ├── prompts/page.tsx   # login-gate + PromptsPanel
 │   │   │   ├── cost/page.tsx
+│   │   │   ├── pricing/page.tsx   # 비용 단가 (v2.30.0)
 │   │   │   ├── reliability/page.tsx
 │   │   │   ├── efficiency/page.tsx
 │   │   │   └── analysis/page.tsx  # v2.1.0
@@ -132,7 +143,8 @@ model-monitoring/
 │   │   │   ├── AutoDashboard.tsx        # workload category filter + multi-select model
 │   │   │   ├── ModelStatusGrid.tsx      # family-grouped 55 cards (Bedrock prefix) + 지표 값 등급 색(양호 파랑/경고 호박 ▲/위험 장미 ◆, data-grade, 범례 + 접이식 기준표 — lib/metricGrade.ts, ADR-029, v2.28.0)
 │   │   │   ├── TrendChart.tsx           # MODEL_COLORS 라벨 (21 Bedrock + 9 Anthropic CP + 25 OpenAI Mantle/Global/US 활성; 1P 5개는 휴면)
-│   │   │   ├── CostDashboardPanel.tsx
+│   │   │   ├── CostDashboardPanel.tsx   # 방법론 문단이 /pricing으로 연결 (v2.30.0)
+│   │   │   ├── PricingPanel.tsx         # 비용 단가 표(제공사 섹션, 채널 4열, 각주 → #ref-n) + 면책 상자 + 마지막 자동 확인 + 다운로드 3종 + 참고 자료 (v2.30.0)
 │   │   │   ├── ReliabilityPanel.tsx
 │   │   │   ├── EfficiencyPanel.tsx
 │   │   │   ├── AnalysisPanel.tsx        # v2.1.0
@@ -149,7 +161,8 @@ model-monitoring/
 │   │       ├── monitoring.ts / trendSelection.ts / pivotTrend.ts / costProjection.ts  # 카드 건강·신선도, 트렌드 선택·URL 상태, 트렌드 피벗, 비용 외삽
 │   │       ├── i18n.ts + i18n-context.tsx  # KO/EN
 │   │       ├── sortModels.ts            # FAMILY_ORDER, groupByFamily, channelRank, EXCLUDED_FAMILIES/isExcludedModel
-│   │       ├── pricing.ts               # backend/pricing.py mirror
+│   │       ├── pricing.ts               # formatCost만 (v2.30.0부터 단가 표는 backend /api/pricing — 프런트 미러 없음)
+│   │       ├── pricingTable.ts          # /pricing 순수 함수 — formatUnitPrice, formatPricePair, tierBadges, costFromPrices (정렬과 번호 매기기 없음, v2.30.0)
 │   │       ├── theme.ts + chartTheme.ts # 다크/화이트 테마 (v2.8.0)
 │   │       ├── modelExplorer.ts         # 채널/네이티브ID/코드예제/링크 유도 (lang 파라미터로 KO/EN, v2.16.2)
 │   │       ├── claudeFeatures.ts        # Claude API Features 매트릭스 순수 로직 — 셀 집계·그룹 구성(modelKey, modelOrder)·surfaceSummary/surfaceFindings·labelMaps·지연시간 헬퍼 (v2.24.0)
@@ -159,7 +172,7 @@ model-monitoring/
 ├── cdk/                                  # lib/stacks/ 8 stacks + lib/constructs/{fargate-service,pinned-image}.ts (TypeScript)
 └── docs/
     ├── architecture.md, api-reference.md
-    ├── decisions/ADR-001~029.md
+    ├── decisions/ADR-001~030.md
     └── runbooks/deploy.md, rollback.md, troubleshooting.md
 ```
 
@@ -241,14 +254,14 @@ curl -X POST "https://d36s7ml54xwemr.cloudfront.net/api/admin/users/<username>/a
 | GPT 5.4 | — | — | ✅ | ✅ | ✅ | ✅ (v2.6.0) |
 
 - **Mantle (Path 4)** model_id 키: `openai:<region>:openai.gpt-5.x`. 라벨: `OpenAI GPT 5.x (<region>)`. OpenAI-compatible `/openai/v1` + Bedrock bearer 토큰(`OPENAI_API_KEY`, `ABSK-…`). 자세히는 ADR-019.
-- **Global CRIS (v2.20.0, 2026-08-18)**: GPT-5.6 세대(Sol/Terra/Luna) 이상만 Bedrock global cross-region inference profile 지원 (2026-08-17 AWS 발표, GPT-6 Astra는 v2.25.0, GPT-6 Sol/Luna는 v2.27.0에서 합류 — ADR-027, ADR-028). 키: `openai:global:global.openai.gpt-5.6-*` (pseudo-region `global`, 프로파일 id는 in-region id에 `global.` 접두사를 prober가 파생 — 별도 model-id env 없음). 라벨: `OpenAI GPT 5.6 * (Global)`. **global 프로파일은 bedrock-mantle 호스트 미지원** — `OPENAI_GLOBAL_BASE_URL=https://bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1`(Seoul bedrock-runtime OpenAI-compat, 기존 `OPENAI_API_KEY` bearer 재사용)로만 호출. **단가가 in-region보다 저렴**해 pricing은 `-global` suffix 키로 채널 분리 (ADR-025). gptbench(`_BENCH_SPECS`)에는 GPT-5.6 세대 중 Terra Global만 포함(v2.20.1, 5.6 Sol/Luna Global 미포함)이며 GPT-6 Astra Global은 v2.25.1, GPT-6 Sol/Luna Global은 v2.28.0에서 포함 — 벤치 18채널 = Mantle 인리전 11 + CRIS 7(Global 4 + US 3).
-- **GPT-6 Astra (v2.25.0, 2026-09-09)**: 채널 3개. 1. Global CRIS `openai:global:global.openai.gpt-6-astra`, 라벨 `OpenAI GPT 6 Astra (Global)`, 기존 `OPENAI_GLOBAL_BASE_URL`(Seoul bedrock-runtime) 재사용. 2. **US CRIS — 유사 리전 `us`** `openai:us:us.openai.gpt-6-astra`, 라벨 `OpenAI GPT 6 Astra (US)`, env `OPENAI_US_BASE_URL=https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1`. 3. Mantle 인리전 `openai:us-west-2:openai.gpt-6-astra`, 라벨 `OpenAI GPT 6 Astra (us-west-2)`. Responses API 전용(5.4/5.5/5.6과 동일). env: `BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID=openai.gpt-6-astra` 하나만 주입하고 Global/US 프로파일 id는 prober가 `global.`/`us.` 접두로 파생한다. **실측(2026-09-09, 운영 Bedrock 장기 키 + Responses API)**: `bedrock-mantle.us-east-1`, `bedrock-mantle.us-east-2`는 404 `not_found_error`("The model does not exist") — Bedrock 모델 액세스는 전 리전 AVAILABLE/AUTHORIZED이므로 엔티틀먼트가 아니라 Mantle 호스트 온보딩 미완이며, 404 리전을 스펙에 넣으면 프로브가 전부 오류 행이 되므로 두 리전은 제외했다 — **2026-09-23 사용자 결정으로 "현재 미지원 — 제외" 확정**(정기 재확인 대상 아님, AWS가 지원을 발표하면 스펙 튜플에 리전만 추가, ADR-027 v2.28.0 후속). 접두사 없는 평문 id(`openai.gpt-6-astra`)는 온디맨드 호출 불가(추론 프로파일 필요). **단가 (v2.27.0에서 반영 — AWS 공식 모델 카드, Standard, 입력 272K 이하)**: `gpt-6-astra`(인리전 us-west-2) $11/$55, `gpt-6-astra-us`(US CRIS) $11/$55, `gpt-6-astra-global` $10/$50 per MTok — 3키는 항상 함께 둔다(하나만 있으면 prefix fallback이 나머지 채널을 오매칭). 비용은 조회 시점 계산이라 단가를 바꾸면 과거 행에도 소급된다. 2026-09-23 재측정에서도 Mantle us-east-1/us-east-2는 404(위 사용자 결정의 근거). gptbench `_BENCH_SPECS` 포함(v2.25.1 — Global, US CRIS, us-west-2 3채널로 벤치 9 → 12채널, v2.28.0 Sol/Luna 합류로 18채널), 1P 스펙 미추가. 자세히는 ADR-027. **패리티 `_REASONING_MARKERS`에 `gpt-6` 미포함**: Responses `reasoning.effort`/chat `reasoning_effort`를 수락하지만 `reasoning_tokens`를 0으로 보고해(2026-09-09 라이브) `reasoning`/`reasoning_effort` 12셀은 skipped 유지 — 판단 근거는 ADR-027.
-- **GPT-6 Sol / GPT-6 Luna (v2.27.0, 2026-09-23)**: 2026-09-22 출시(AWS 모델 카드 미게재 — `model-cards-openai.html`에는 Astra만). 모델마다 채널 3개: Global CRIS `openai:global:global.openai.gpt-6-{sol,luna}`(라벨 `OpenAI GPT 6 {Sol,Luna} (Global)`), US CRIS `openai:us:us.openai.gpt-6-{sol,luna}`(`(US)`), Mantle 인리전 `openai:us-east-1:openai.gpt-6-{sol,luna}`(`(us-east-1)`). env: `BEDROCK_OPENAI_GPT_6_{SOL,LUNA}_MODEL_ID` 하나씩, Global/US 프로파일 id는 prober가 파생. **실측(2026-09-23)**: Mantle us-east-2/us-west-2는 404 `not_found_error`("The model 'openai.gpt-6-sol' does not exist")라 제외 — Astra(Mantle us-west-2 단독)와 정반대. **2026-09-23 사용자 결정(v2.28.1): "현재 미지원 — 제외"**, 정기 재확인 대상 아님(AWS가 지원을 발표하면 스펙 튜플에 리전만 추가). Mantle us-east-1 첫 호출은 401 "Your subscription to the model is being set up"(Marketplace 구독 개시) → 수 분 뒤 200. 서울 기준 단건: Sol Global TTFB 559/TTFT 856ms, US 927/2059ms · Luna Global 591/857ms, US 919/1064ms. **단가 (v2.28.0에서 반영 — 출처: Bedrock `ListFoundationModelAgreementOffers` rate card, 모델 카드는 아직 미게재)**: `gpt-6-sol`(인리전 us-east-1)·`gpt-6-sol-us` $2.20/$11, `gpt-6-sol-global` $2/$10, `gpt-6-luna`·`gpt-6-luna-us` $0.11/$0.55, `gpt-6-luna-global` $0.10/$0.50 per MTok. offer: Sol `offer-pycji3sz5gpcc`, Luna `offer-gmo53nkzc5or6` — `*_standard` = In-Region + Geo CRIS, `*_global_standard` = Global CRIS. 같은 API의 Astra offer(`offer-7epta7rbw5aws`)가 Astra 공식 카드와 정확히 일치함을 교차 검증했고, 값은 OpenAI 정가 + In-Region/Geo 10%와도 같다. 모델 카드가 게재되면 재대조. 3키는 항상 함께 둔다. **패리티 `_REASONING_MARKERS`에 `gpt-6` 미포함**: 패리티 프로브(effort low, "17 x 23은?")에서 `reasoning_tokens=0`(effort high에서만 13/18) → 넣으면 미지원 오판. gptbench `_BENCH_SPECS`에는 v2.28.0에서 6채널 모두 편입(목록 끝 — 데드라인 컷이 신규 채널에 먼저 떨어짐, 벤치 요청 형태 라이브 200, Sol `reasoning_tokens` 0, Luna 34~47), 1P 스펙 미추가. 자세히는 ADR-028(+ v2.28.0 후속).
-- **1P direct (Path 5, v2.6.0 — v2.19.1부터 휴면/비노출)** model_id 키: `openai:1p:gpt-5.x`. 라벨: `OpenAI GPT 5.x (1P)`. `https://api.openai.com/v1` 직접 호출 + **OpenAI platform 키**(`OPENAI_1P_API_KEY`, `sk-proj-…` — Mantle bearer와 호환 불가). native id(`gpt-5.x`, 접두사 없음). 리전 개념 없음(글로벌 라우팅). env: `OPENAI_1P_API_KEY`(SSM `/bedrock-monitor/openai-1p-api-key`), `OPENAI_1P_GPT_54/55_MODEL_ID`, `OPENAI_1P_BASE_URL`(선택). 자세히는 ADR-020. **2026-07-31 사용자 결정으로 비교에서 제외(비노출)**: 코드·DB 행은 보존, CDK `ENABLE_OPENAI_1P=false`로 env 미주입(등록 skip) + backend `visibility.py` `(1P)` 라벨 조회 필터 + frontend `EXCLUDED_FAMILIES` 하드필터. 재노출 = CDK 플래그 true + 유효 키 SSM 저장 + `HIDDEN_MODEL_PATTERNS=""` env + EXCLUDED_FAMILIES에서 제거 + **pricing 1P 단가 분리 선행** (base 키 `gpt-5.6-*`는 in-region 단가라 1P 정가와 다르다 — Terra/Luna는 +10% 과대, Sol은 v2.28.1 프로모션 단가($4.40/$22)가 1P 정가($5/$30)보다 낮아 오히려 **과소** 산정 — ADR-025, v2.28.1).
-- **GPT-5.6 세대 (v2.17.0, 2026-07-14)**: Sol(최상위)/Terra(균형)/Luna(저비용) — Mantle native id `openai.gpt-5.6-{sol,terra,luna}`, 1P native id `gpt-5.6-{sol,terra,luna}`. **Sol은 us-west-2 미제공**. Responses API 전용(5.4/5.5와 동일). env: `BEDROCK_OPENAI_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID` + `OPENAI_1P_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID`. **현행 단가 (v2.20.0에서 교정 — 2026-07-30 AWS 인하 Luna -80%·Terra -20% 반영, 공식 모델 카드 Standard tier 기준)**: in-region/Geo Sol $4.40/$22(**v2.28.1 프로모션 단가, 최소 2026-11-21까지 — 종료 후 카드 재확인, 구 $5.50/$33**), Terra $2.20/$13.20, Luna $0.22/$1.32 · Global CRIS Sol $4/$20(프로모션, 구 $5/$30), Terra $2/$12, Luna $0.20/$1.20 per MTok.
+- **Global CRIS (v2.20.0, 2026-08-18)**: GPT-5.6 세대(Sol/Terra/Luna) 이상만 Bedrock global cross-region inference profile 지원 (2026-08-17 AWS 발표, GPT-6 Astra는 v2.25.0, GPT-6 Sol/Luna는 v2.27.0에서 합류 — ADR-027, ADR-028). 키: `openai:global:global.openai.gpt-5.6-*` (pseudo-region `global`, 프로파일 id는 in-region id에 `global.` 접두사를 prober가 파생 — 별도 model-id env 없음). 라벨: `OpenAI GPT 5.6 * (Global)`. **global 프로파일은 bedrock-mantle 호스트 미지원** — `OPENAI_GLOBAL_BASE_URL=https://bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1`(Seoul bedrock-runtime OpenAI-compat, 기존 `OPENAI_API_KEY` bearer 재사용)로만 호출. **단가가 in-region보다 저렴**해 채널마다 단가 행이 따로 있다(v2.30.0부터 `price_history`의 model_id 단위 행, ADR-030 — 이전의 `-global` suffix 키는 ADR-025). gptbench(`_BENCH_SPECS`)에는 GPT-5.6 세대 중 Terra Global만 포함(v2.20.1, 5.6 Sol/Luna Global 미포함)이며 GPT-6 Astra Global은 v2.25.1, GPT-6 Sol/Luna Global은 v2.28.0에서 포함 — 벤치 18채널 = Mantle 인리전 11 + CRIS 7(Global 4 + US 3).
+- **GPT-6 Astra (v2.25.0, 2026-09-09)**: 채널 3개. 1. Global CRIS `openai:global:global.openai.gpt-6-astra`, 라벨 `OpenAI GPT 6 Astra (Global)`, 기존 `OPENAI_GLOBAL_BASE_URL`(Seoul bedrock-runtime) 재사용. 2. **US CRIS — 유사 리전 `us`** `openai:us:us.openai.gpt-6-astra`, 라벨 `OpenAI GPT 6 Astra (US)`, env `OPENAI_US_BASE_URL=https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1`. 3. Mantle 인리전 `openai:us-west-2:openai.gpt-6-astra`, 라벨 `OpenAI GPT 6 Astra (us-west-2)`. Responses API 전용(5.4/5.5/5.6과 동일). env: `BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID=openai.gpt-6-astra` 하나만 주입하고 Global/US 프로파일 id는 prober가 `global.`/`us.` 접두로 파생한다. **실측(2026-09-09, 운영 Bedrock 장기 키 + Responses API)**: `bedrock-mantle.us-east-1`, `bedrock-mantle.us-east-2`는 404 `not_found_error`("The model does not exist") — Bedrock 모델 액세스는 전 리전 AVAILABLE/AUTHORIZED이므로 엔티틀먼트가 아니라 Mantle 호스트 온보딩 미완이며, 404 리전을 스펙에 넣으면 프로브가 전부 오류 행이 되므로 두 리전은 제외했다 — **2026-09-23 사용자 결정으로 "현재 미지원 — 제외" 확정**(정기 재확인 대상 아님, AWS가 지원을 발표하면 스펙 튜플에 리전만 추가, ADR-027 v2.28.0 후속). 접두사 없는 평문 id(`openai.gpt-6-astra`)는 온디맨드 호출 불가(추론 프로파일 필요). **단가 (v2.27.0에서 반영 — AWS 공식 모델 카드, Standard, 입력 272K 이하)**: `gpt-6-astra`(인리전 us-west-2) $11/$55, `gpt-6-astra-us`(US CRIS) $11/$55, `gpt-6-astra-global` $10/$50 per MTok — v2.30.0부터 `pricing_seed.SEED`에 model_id 단위로 두고 12시간마다 agreement offer로 확인한다(정확 일치라 prefix fallback 없음, ADR-030). 2026-09-23 재측정에서도 Mantle us-east-1/us-east-2는 404(위 사용자 결정의 근거). gptbench `_BENCH_SPECS` 포함(v2.25.1 — Global, US CRIS, us-west-2 3채널로 벤치 9 → 12채널, v2.28.0 Sol/Luna 합류로 18채널), 1P 스펙 미추가. 자세히는 ADR-027. **패리티 `_REASONING_MARKERS`에 `gpt-6` 미포함**: Responses `reasoning.effort`/chat `reasoning_effort`를 수락하지만 `reasoning_tokens`를 0으로 보고해(2026-09-09 라이브) `reasoning`/`reasoning_effort` 12셀은 skipped 유지 — 판단 근거는 ADR-027.
+- **GPT-6 Sol / GPT-6 Luna (v2.27.0, 2026-09-23)**: 2026-09-22 출시(출시 당시 AWS 모델 카드 미게재 — 2026-09-26 게시 확인, 값은 오퍼와 일치). 모델마다 채널 3개: Global CRIS `openai:global:global.openai.gpt-6-{sol,luna}`(라벨 `OpenAI GPT 6 {Sol,Luna} (Global)`), US CRIS `openai:us:us.openai.gpt-6-{sol,luna}`(`(US)`), Mantle 인리전 `openai:us-east-1:openai.gpt-6-{sol,luna}`(`(us-east-1)`). env: `BEDROCK_OPENAI_GPT_6_{SOL,LUNA}_MODEL_ID` 하나씩, Global/US 프로파일 id는 prober가 파생. **실측(2026-09-23)**: Mantle us-east-2/us-west-2는 404 `not_found_error`("The model 'openai.gpt-6-sol' does not exist")라 제외 — Astra(Mantle us-west-2 단독)와 정반대. **2026-09-23 사용자 결정(v2.28.1): "현재 미지원 — 제외"**, 정기 재확인 대상 아님(AWS가 지원을 발표하면 스펙 튜플에 리전만 추가). Mantle us-east-1 첫 호출은 401 "Your subscription to the model is being set up"(Marketplace 구독 개시) → 수 분 뒤 200. 서울 기준 단건: Sol Global TTFB 559/TTFT 856ms, US 927/2059ms · Luna Global 591/857ms, US 919/1064ms. **단가 (v2.28.0에서 반영 — 출처: Bedrock `ListFoundationModelAgreementOffers` rate card, v2.30.0부터 PricingSync가 12시간마다 같은 API로 확인)**: `gpt-6-sol`(인리전 us-east-1)·`gpt-6-sol-us` $2.20/$11, `gpt-6-sol-global` $2/$10, `gpt-6-luna`·`gpt-6-luna-us` $0.11/$0.55, `gpt-6-luna-global` $0.10/$0.50 per MTok. offer: Sol `offer-pycji3sz5gpcc`, Luna `offer-gmo53nkzc5or6` — `*_standard` = In-Region + Geo CRIS, `*_global_standard` = Global CRIS. 같은 API의 Astra offer(`offer-7epta7rbw5aws`)가 Astra 공식 카드와 정확히 일치함을 교차 검증했고, 값은 OpenAI 정가 + In-Region/Geo 10%와도 같다. 모델 카드 게시 후 재대조 완료(2026-09-26, 일치 — ADR-028 후속). **패리티 `_REASONING_MARKERS`에 `gpt-6` 미포함**: 패리티 프로브(effort low, "17 x 23은?")에서 `reasoning_tokens=0`(effort high에서만 13/18) → 넣으면 미지원 오판. gptbench `_BENCH_SPECS`에는 v2.28.0에서 6채널 모두 편입(목록 끝 — 데드라인 컷이 신규 채널에 먼저 떨어짐, 벤치 요청 형태 라이브 200, Sol `reasoning_tokens` 0, Luna 34~47), 1P 스펙 미추가. 자세히는 ADR-028(+ v2.28.0 후속).
+- **1P direct (Path 5, v2.6.0 — v2.19.1부터 휴면/비노출)** model_id 키: `openai:1p:gpt-5.x`. 라벨: `OpenAI GPT 5.x (1P)`. `https://api.openai.com/v1` 직접 호출 + **OpenAI platform 키**(`OPENAI_1P_API_KEY`, `sk-proj-…` — Mantle bearer와 호환 불가). native id(`gpt-5.x`, 접두사 없음). 리전 개념 없음(글로벌 라우팅). env: `OPENAI_1P_API_KEY`(SSM `/bedrock-monitor/openai-1p-api-key`), `OPENAI_1P_GPT_54/55_MODEL_ID`, `OPENAI_1P_BASE_URL`(선택). 자세히는 ADR-020. **2026-07-31 사용자 결정으로 비교에서 제외(비노출)**: 코드·DB 행은 보존, CDK `ENABLE_OPENAI_1P=false`로 env 미주입(등록 skip) + backend `visibility.py` `(1P)` 라벨 조회 필터 + frontend `EXCLUDED_FAMILIES` 하드필터. 재노출 = CDK 플래그 true + 유효 키 SSM 저장 + `HIDDEN_MODEL_PATTERNS=""` env + EXCLUDED_FAMILIES에서 제거 + **1P 단가 출처 설계 선행** (v2.30.0부터 단가는 `price_history` model_id 단위이고 `pricing_sources.price_identity`가 1P id를 분류하지 않아 1P 비용은 "-"다. 재노출하려면 `pricing_sources.py` 분류, `pricing_seed.py` 1P 정가 seed, 1P 공식 출처 동기화를 함께 추가한다 — 1P 정가는 in-region 단가와 다르다: Terra/Luna는 in-region이 10% 높고 Sol은 in-region 프로모션 단가($4.40/$22)가 1P 정가($5/$30)보다 낮다, ADR-020, ADR-030).
+- **GPT-5.6 세대 (v2.17.0, 2026-07-14)**: Sol(최상위)/Terra(균형)/Luna(저비용) — Mantle native id `openai.gpt-5.6-{sol,terra,luna}`, 1P native id `gpt-5.6-{sol,terra,luna}`. **Sol은 us-west-2 미제공**. Responses API 전용(5.4/5.5와 동일). env: `BEDROCK_OPENAI_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID` + `OPENAI_1P_GPT_56_{SOL,TERRA,LUNA}_MODEL_ID`. **현행 단가 (v2.20.0에서 교정 — 2026-07-30 AWS 인하 Luna -80%·Terra -20% 반영, 공식 모델 카드 Standard tier 기준)**: in-region/Geo Sol $4.40/$22(**v2.28.1 프로모션 단가 — 공식 출처에는 종료일이 없고 "최소 2026-11-21까지"는 `pricing_sources.PRICE_NOTES` 수동 메모, 구 $5.50/$33. 종료로 구 단가에 돌아오면 +25%/+50%라 50% 경계 포함으로 자동 적용**), Terra $2.20/$13.20, Luna $0.22/$1.32 · Global CRIS Sol $4/$20(프로모션, 구 $5/$30), Terra $2/$12, Luna $0.20/$1.20 per MTok.
 
-- **Claude Fable 5.1 (v2.22.0, 2026-09-01)**: 2026-08-31 출시. Bedrock 프로파일 `global.`/`us.anthropic.claude-fable-5-1` (Seoul·us-east-1 모두 ACTIVE, 라이브 converse 검증). Fable 5와 동일 Covered Model 제약(provider_data_share 리전 opt-in 기존 적용) + 동일 단가 $10/$50. **forced `tool_choice`(type tool/any)는 400 거부** → 패리티 `tool_use` 프로브는 `parity/catalog.py` `supports_forced_tool_choice()`로 `auto`+프롬프트 지시로 대체. CP 채널은 `_ANTHROPIC_TARGETS` 선등록(`fable-5-1`) — `fable-5` substring 접두 충돌은 `_match_anthropic_model()`이 처리.
-- **Claude Opus 5.5 (v2.27.0, 2026-09-23)**: 2026-09-22 출시([AWS 모델 카드](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5-5.html)). Bedrock `global.anthropic.claude-opus-5-5`(Seoul — Seoul은 Global CRIS만, Geo 없음) + `us.anthropic.claude-opus-5-5`(us-east-1) + CP `anthropic:claude-opus-5-5`(타깃 `opus-5-5`를 `opus-5` 앞에). 라이브 converse_stream 200(TTFT 약 2.8s), CP 200. **temperature 400 + forced `tool_choice` 400** → `_REASONING_MODEL_PATTERNS`의 `"opus-5"`가 substring으로 포함, 패리티 `_NO_FORCED_TOOL_CHOICE_MARKERS`에 `"opus-5-5"` 추가(Opus 5는 forced 유지). 단가 $4/$20 — 정확 키 `claude-opus-5-5` 필수(없으면 prefix fallback이 Opus 5 $5/$25). **CP 오등록 실사고(2026-09-23)**: CP `/v1/models`가 `claude-opus-5-5`를 `claude-opus-5`보다 먼저 반환해 구 코드가 5.5 id를 `Anthropic Claude Opus 5 (US)`로 프로빙(실제 Opus 5 CP 미측정) → 타깃 추가 + `_is_point_release_of()` 가드(substring 뒤 `-<1~2자리 숫자>`가 오는 id는 자기 타깃 없으면 제외, 8자리 날짜 서픽스는 매칭 유지)로 **다음 점 버전(예: sonnet-5-5)도 fail-closed**. 저장 행은 backend 기동 시 `label_repair.py`가 정정. v2.28.0부터 `/claude-features` 5번째 대표 모델(ADR-026 부록). 자세히는 ADR-028.
+- **Claude Fable 5.1 (v2.22.0, 2026-09-01)**: 2026-08-31 출시. Bedrock 프로파일 `global.`/`us.anthropic.claude-fable-5-1` (Seoul·us-east-1 모두 ACTIVE, 라이브 converse 검증). Fable 5와 동일 Covered Model 제약(provider_data_share 리전 opt-in 기존 적용) + 동일 단가 $10/$50(US $11/$55 — v2.30.0 교정). **forced `tool_choice`(type tool/any)는 400 거부** → 패리티 `tool_use` 프로브는 `parity/catalog.py` `supports_forced_tool_choice()`로 `auto`+프롬프트 지시로 대체. CP 채널은 `_ANTHROPIC_TARGETS` 선등록(`fable-5-1`) — `fable-5` substring 접두 충돌은 `_match_anthropic_model()`이 처리.
+- **Claude Opus 5.5 (v2.27.0, 2026-09-23)**: 2026-09-22 출시([AWS 모델 카드](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5-5.html)). Bedrock `global.anthropic.claude-opus-5-5`(Seoul — Seoul은 Global CRIS만, Geo 없음) + `us.anthropic.claude-opus-5-5`(us-east-1) + CP `anthropic:claude-opus-5-5`(타깃 `opus-5-5`를 `opus-5` 앞에). 라이브 converse_stream 200(TTFT 약 2.8s), CP 200. **temperature 400 + forced `tool_choice` 400** → `_REASONING_MODEL_PATTERNS`의 `"opus-5"`가 substring으로 포함, 패리티 `_NO_FORCED_TOOL_CHOICE_MARKERS`에 `"opus-5-5"` 추가(Opus 5는 forced 유지). 단가 $4/$20(US $4.40/$22 — v2.30.0 교정). v2.30.0부터 model_id 정확 일치라 prefix fallback이 없고, Anthropic 문서 표도 "Claude Opus 5.5"가 "Claude Opus 5"보다 먼저 나오므로 CP 매핑은 정확 일치만 쓴다(ADR-030). **CP 오등록 실사고(2026-09-23)**: CP `/v1/models`가 `claude-opus-5-5`를 `claude-opus-5`보다 먼저 반환해 구 코드가 5.5 id를 `Anthropic Claude Opus 5 (US)`로 프로빙(실제 Opus 5 CP 미측정) → 타깃 추가 + `_is_point_release_of()` 가드(substring 뒤 `-<1~2자리 숫자>`가 오는 id는 자기 타깃 없으면 제외, 8자리 날짜 서픽스는 매칭 유지)로 **다음 점 버전(예: sonnet-5-5)도 fail-closed**. 저장 행은 backend 기동 시 `label_repair.py`가 정정. v2.28.0부터 `/claude-features` 5번째 대표 모델(ADR-026 부록). 자세히는 ADR-028.
 
 **제외 모델 (2026-05-20부터)**: Opus 4.5, Sonnet 4.5 — 사용자 요청으로 모니터링 대상에서 제외. Frontend hard-filter(`lib/sortModels.ts` `EXCLUDED_FAMILIES`/`isExcludedModel` — AutoDashboard, ModelExplorer, `lib/monitoring.ts`가 사용)도 적용해서 backend silent bug 대비.
 
@@ -256,6 +269,8 @@ curl -X POST "https://d36s7ml54xwemr.cloudfront.net/api/admin/users/<username>/a
 
 **라벨 정책**: DB의 `model_name`은 항상 `"Bedrock <family> (<channel>)"` 또는 `"Anthropic <family> (<channel>)"` prefix. OpenAI 라벨은 `"OpenAI <family> (<region>)"`(Mantle 인리전) / `"OpenAI <family> (Global)"`(Global CRIS, v2.20.0) / `"OpenAI <family> (US)"`(US CRIS, v2.25.0) / `"OpenAI <family> (1P)"`(1P direct) prefix. Frontend `MODEL_COLORS`/`FAMILY_ORDER`는 이 prefix를 expected. 정렬 순서: **Anthropic → Global(Bedrock·OpenAI 공통, `(Global)` 서픽스) → US(Bedrock US·OpenAI US CRIS, `(US)` 서픽스) → OpenAI 리전** (`channelRank` 함수). OpenAI US CRIS는 `channelRank`에서 리전 채널보다 앞선 US 티어로 분기한다(v2.25.0) — 이 분기가 없으면 ICU `localeCompare`가 `(us-west-2)`를 `(US)`보다 앞에 놓으므로 `sortModels.ts`의 분기 순서를 바꾸지 말 것.
 
+**단가 (v2.30.0, ADR-030)**: 단가의 단일 출처는 backend `price_history` 테이블이다(`backend/pricing.py`와 `frontend/src/lib/pricing.ts`의 `PRICE_TABLE`, `get_pricing`, `estimate_cost_usd`, `getPricing`, `estimateCost`는 삭제 — 프런트 미러 없음). PricingSync 태스크가 12시간마다 공식 출처 3개(Bedrock agreement offer rate card — Bedrock Claude 20 + OpenAI 25, AWS Price List — Nova 2.0 Lite, Anthropic `pricing.md` — Claude Platform on AWS 9)에서 Standard 입력/출력 단가를 읽어 model_id 단위로 기록한다. 입력이나 출력 변화율이 0.5를 넘으면(0.5는 자동 적용) `pending_review`로 두고 관리자 승인(`POST /api/admin/pricing/pending/{id}/approve`)을 기다린다. 비용(`/api/cost/*`, `/api/efficiency/score`)은 각 프로브 시각에 유효했던 단가로 계산한다 — ADR-025의 "조회 시점 소급 계산"은 폐기됐다. 첫 동기화 이전 구간은 seed(`pricing_seed.py`, effective_from 1970-01-01)로 계산하고 v2.30.0 이전 단가 변경은 재구성하지 않았다. 코드 단가 오류 11채널(Bedrock Claude US 10 = Global × 1.1, Nova 2.0 Lite $0.33/$2.75)은 seed로 과거까지 교정했다. **모델을 추가하면** `pricing_sources.py`(`price_identity` 분류, 오퍼 FM id 또는 Anthropic 문서 모델명 매핑, 새 패밀리면 `FAMILY_ORDER`)와 `pricing_seed.py`(`SEED`, CP는 `CP_SEED`)를 함께 고친다 — "활성 채널 전부가 분류되고 seed 단가가 있다" 테스트가 누락을 잡고, 운영에서는 `no_baseline` 검토 대기로 드러난다. 새 패밀리는 프런트 `lib/sortModels.ts` `FAMILY_ORDER`와 백엔드 `pricing_sources.FAMILY_ORDER`가 바이트 단위로 같아야 한다(pytest 고정). 화면 `/pricing`, API `GET /api/pricing`(태스크마다 60초 캐시), `GET /api/pricing/export?format=csv|md|json&lang=ko|en`.
+
 ---
 
 ## Workload Preset (6 categories, round-robin) / 워크로드 프리셋
@@ -298,9 +313,9 @@ Claude Platform on AWS 채널(anthropic:*)도 기본값에서는 매 사이클 
 - **Register**: `username`은 **EmailStr** 검증 강제 (v2.1.0). approved=0 → admin SES → approved=1 → login
 - **Admin email**: `whchoi98@gmail.com` (`backend/auth.py:ADMIN_EMAIL`)
   - SES region: `us-east-1`. **Sandbox 모드 시 sender/recipient 둘 다 verified identity 필요**
-- **Public**: `/api/health`, `/api/auth/{login,register,approve}`, 모든 조회 GET — `/api/auto-probe/*`, `/api/results/*`, `/api/models`, `/api/cost/*`, `/api/reliability/*`, `/api/efficiency/*`, `/api/analysis/*`, `/api/parity/{catalog,latest,evidence}`, `/api/features/{catalog,latest,evidence}`, `/api/gptbench/*`, `/api/insights`·`/latest`, `GET /api/prompts`, `GET /api/probes/{run_id}`
+- **Public**: `/api/health`, `/api/auth/{login,register,approve}`, 모든 조회 GET — `/api/auto-probe/*`, `/api/results/*`, `/api/models`, `/api/cost/*`, `/api/reliability/*`, `/api/efficiency/*`, `/api/analysis/*`, `/api/parity/{catalog,latest,evidence}`, `/api/features/{catalog,latest,evidence}`, `/api/gptbench/*`, `/api/pricing`, `/api/pricing/export`, `/api/insights`·`/latest`, `GET /api/prompts`, `GET /api/probes/{run_id}`
 - **Auth required** (`Depends(get_current_user)`): `/api/auth/me`, `/api/auto-probe/trigger` (202 accepted / 409 active reservation), `/api/probes/run`, `/api/compare/run`, `/api/parity/trigger`, `/api/features/trigger`, `/api/prompts` (POST/DELETE, `/optimize`), `/api/insights/regenerate`·`/stream-regenerate`, `/api/chat/*`
-- **Admin only**: `/api/admin/*` (username == "admin"). admin 비밀번호는 `SEED_ADMIN_PASSWORD` env var (8자 이상)
+- **Admin only**: `/api/admin/*` (username == "admin") — `/api/admin/pricing/*` 검토 대기 단가 승인/거부 포함 (v2.30.0). admin 비밀번호는 `SEED_ADMIN_PASSWORD` env var (8자 이상)
 
 ---
 
@@ -361,6 +376,7 @@ Scheduler role의 `ecs:RunTask` Resource는 **task def family `:*` wildcard** 
 - 모든 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
 - 예: `probe_results.stop_reason TEXT`
 - 기동 마이그레이션이 ~130s 걸릴 수 있어 backend 헬스체크 유예는 300s (`app-services-stack.ts` `healthCheckGracePeriod`, 2026-09-06 서킷 브레이커 롤백 실사고)
+- 새 테이블(`price_history`, `price_sync_runs`, v2.30.0)은 `models.py` ORM + `create_all`로 만든다 — lifespan ALTER 블록에 넣지 않는다. seed(`pricing_seed.ensure_seed`)는 마이그레이션 트랜잭션과 분리된 자체 트랜잭션에서 `pg_advisory_xact_lock(917350003)`, 동기화 런은 `pg_advisory_lock(917350004)`. 모든 시각은 timezone-aware datetime 바인드 파라미터로 넣는다(SQLite는 DateTime을 문자열로 비교하므로 raw 시각 리터럴 금지)
 
 ### Auto-Prober는 daemon thread 아님
 - v1: backend 프로세스 안의 thread. v2: **별도 Fargate Task** (EventBridge Scheduler가 5분마다 RunTask). backend의 `auto_prober.py`는 `run_cycle()` 함수만 export, daemon 로직 없음. `auto_prober_runner.py`가 CLI entrypoint.
diff --git a/README.md b/README.md
index 60f55b5..d471170 100644
--- a/README.md
+++ b/README.md
@@ -1,7 +1,7 @@
 # Amazon Bedrock LLM Monitor
 
 ![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
-[![Version](https://img.shields.io/badge/version-2.29.1-blue.svg)](CHANGELOG.md)
+[![Version](https://img.shields.io/badge/version-2.30.0-blue.svg)](CHANGELOG.md)
 [![Build](https://img.shields.io/badge/build-CDK%20%7C%20Docker-success)](docs/runbooks/deploy.md)
 <a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
 <a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>
@@ -18,9 +18,9 @@ Amazon Bedrock, Anthropic CP on AWS, OpenAI GPT on Bedrock LLM 채널의 응답
 
 ## Overview
 
-Amazon Bedrock LLM Monitor is a production-grade observability platform that continuously probes 55 LLM channels (21 Bedrock, 9 Anthropic CP on AWS, 25 OpenAI GPT on Bedrock) across Bedrock Global / US inference profiles (including Claude Opus 5.5, v2.27.0), Anthropic CP on AWS, and OpenAI GPT via Bedrock Mantle in-region endpoints (Path 4) plus Bedrock Global cross-region profiles for GPT-5.6 and GPT-6 Astra, Sol and Luna and US cross-region profiles for GPT-6 Astra, Sol and Luna (v2.20.0, v2.25.0, v2.27.0). (An OpenAI 1P direct path — Path 5 — exists in code but is dormant/hidden as of v2.19.1.) It surfaces latency (TTFT, total, server), throughput (TPS), output token distribution, stop-reason patterns, multi-channel reliability, and 30-day cost projections — all behind a Next.js dashboard with ten monitoring views.
+Amazon Bedrock LLM Monitor is a production-grade observability platform that continuously probes 55 LLM channels (21 Bedrock, 9 Anthropic CP on AWS, 25 OpenAI GPT on Bedrock) across Bedrock Global / US inference profiles (including Claude Opus 5.5, v2.27.0), Anthropic CP on AWS, and OpenAI GPT via Bedrock Mantle in-region endpoints (Path 4) plus Bedrock Global cross-region profiles for GPT-5.6 and GPT-6 Astra, Sol and Luna and US cross-region profiles for GPT-6 Astra, Sol and Luna (v2.20.0, v2.25.0, v2.27.0). (An OpenAI 1P direct path — Path 5 — exists in code but is dormant/hidden as of v2.19.1.) It surfaces latency (TTFT, total, server), throughput (TPS), output token distribution, stop-reason patterns, multi-channel reliability, 30-day cost projections, and official unit prices synced every 12 hours — all behind a Next.js dashboard with eleven monitoring views.
 
-The system runs on AWS ECS Fargate (CDK-managed, 8 stacks), with EventBridge Scheduler driving 5-minute round-robin workload probes across six prompt categories. A built-in chatbot (Claude Sonnet 4.6 with four Bedrock tools) lets you query the time-series data conversationally.
+The system runs on AWS ECS Fargate (CDK-managed, 8 stacks), with EventBridge Scheduler driving 5-minute round-robin workload probes across six prompt categories and a 12-hourly sync of official unit prices. A built-in chatbot (Claude Sonnet 4.6 with four Bedrock tools) lets you query the time-series data conversationally.
 
 ![Dashboard overview: channel counts, per-model status strip, collection cadence](docs/images/ui/dashboard-en.png)
 
@@ -28,7 +28,8 @@ The system runs on AWS ECS Fargate (CDK-managed, 8 stacks), with EventBridge Sch
 
 - **Installable on iPhone/iPad (PWA)** — open the dashboard in Safari, Share → "Add to Home Screen" for a full-screen standalone app (v2.21.0).
 - **Real-time auto-probing** — EventBridge Scheduler fires a Fargate task every 5 minutes that round-robins six workload categories (chat-short, reasoning, code-gen, summarize, structured, translate) across all 55 monitored channels. The 9 Claude Platform on AWS channels are probed every cycle with the same category as every other channel (v2.29.1 reverted the v2.29.0 10-minute cadence); setting `ANTHROPIC_CP_PROBE_INTERVAL_S=600` switches them to every other cycle with their own category rotation, an operational lever if the monthly usage cap returns.
-- **Ten analytical pages** — Dashboard (latency / TPS trends), Model Explorer (per-model cards with Converse/InvokeModel/Messages/Responses code examples), Parity Run (model × API-surface × feature evidence matrix), Cost (30-day projection + channel comparison), Reliability (success rate per family/channel + error buckets), Efficiency (weighted 0-100 score), Analysis (stop-reason distribution + output-length histograms), Prompts (set CRUD + Bedrock OptimizePrompt), GPT on AWS (18-channel TTFB/TTFT bench over Bedrock Mantle in-region and cross-region profiles — GPT 5.4/5.5/5.6 Terra and GPT-6 Astra/Sol/Luna, 15-min cycles), Claude API Features (documented feature × endpoint × model evidence matrix with doc-drift detection).
+- **Eleven analytical pages** — Dashboard (latency / TPS trends), Model Explorer (per-model cards with Converse/InvokeModel/Messages/Responses code examples), Parity Run (model × API-surface × feature evidence matrix), Cost (30-day projection + channel comparison, each probe priced at the unit price in effect at its time), Unit Prices (Standard input/output price per model family and channel with numbered source footnotes and CSV / Markdown / JSON download, v2.30.0), Reliability (success rate per family/channel + error buckets), Efficiency (weighted 0-100 score), Analysis (stop-reason distribution + output-length histograms), Prompts (set CRUD + Bedrock OptimizePrompt), GPT on AWS (18-channel TTFB/TTFT bench over Bedrock Mantle in-region and cross-region profiles — GPT 5.4/5.5/5.6 Terra and GPT-6 Astra/Sol/Luna, 15-min cycles), Claude API Features (documented feature × endpoint × model evidence matrix with doc-drift detection).
+- **Unit prices from official sources** — the Unit Prices page (`/pricing`) lists the Standard input and output price per 1M tokens of every active model family across the Claude Platform on AWS, Global, US and In-Region channels. Each price carries a numbered footnote to its source, and the page links the reference list and downloads as CSV, Markdown or JSON. A scheduled PricingSync task reads the Bedrock agreement-offer rate cards, the AWS Price List API and Anthropic's pricing page every 12 hours; a change above 50% on input or output waits for admin approval. Cost and efficiency figures use the price in effect at each probe's time. The page and every download state that the list is reference information compiled from public sources, not an official AWS statement (v2.30.0, ADR-030).
 - **Graded model-card metrics** — on the dashboard, each card's TTFT, total latency and TPS value turns blue (normal), amber ▲ (warning) or rose ◆ (critical) against per-workload-category thresholds derived from 48 h of production p90/p99 (TPS is graded only on the low side); a legend expands into the full threshold table, and values carry a `data-grade` attribute and screen-reader descriptions (v2.28.0, ADR-029).
 - **12-hourly parity sweep** — a scheduled Fargate task probes every model × API surface × feature cell (6 surfaces × 19 features) with execution evidence (tool-canary round-trip, JSON validity, cached-token counts, stream deltas) — HTTP 200 alone never counts as supported.
 - **Daily Claude API Features sweep** — a scheduled Fargate task (daily at 17:30 UTC, 02:30 KST, v2.29.0) runs the 39-row catalog (= 33 documented features + 4 core Messages + Models API 1 + strict_tool_use split 1) against Claude Platform on AWS, Bedrock Mantle `/anthropic`, and Bedrock runtime (Messages API + InvokeModel + Converse) for 5 representative models (Claude Fable 5.1, Fable 5, Opus 5.5, Opus 5, Sonnet 5 — 975 cells per run, v2.28.0), surfacing a documentation-drift banner when observed behavior disagrees with the documented availability.
@@ -169,6 +170,10 @@ curl https://<your-cloudfront-domain>/api/auto-probe/latest
 # Filter by workload category
 curl "https://<your-cloudfront-domain>/api/auto-probe/latest?category=code-gen"
 
+# Unit prices (official sources, synced every 12 hours) and a CSV download
+curl -s https://<your-cloudfront-domain>/api/pricing | jq '{last_sync, pending_review, families: (.families | length)}'
+curl -OJ "https://<your-cloudfront-domain>/api/pricing/export?format=csv&lang=en"
+
 # Authenticate and run a manual probe (SSE stream)
 TOKEN=$(curl -sX POST https://<your-cloudfront-domain>/api/auth/login \
   -H 'Content-Type: application/json' \
@@ -229,16 +234,23 @@ model-monitoring/
 │   ├── prober.py                 # 55 active (+5 dormant 1P) AVAILABLE_MODELS, retry, Bedrock + Anthropic CP + OpenAI Mantle/Global/US/1P
 │   ├── auto_prober.py            # run_cycle() invoked by EventBridge Fargate task
 │   ├── gptbench.py               # GPT on AWS bench cycle (18 channels × 10 runs, TTFB/TTFT)
-│   ├── pricing.py                # token unit price table
+│   ├── pricing_sources.py        # price identity per channel, source maps, disclaimer, reference pages (v2.30.0)
+│   ├── pricing_seed.py           # official seed prices for the 55 active channels + ensure_seed
+│   ├── pricing_parsers.py        # agreement-offer, Price List and Anthropic pricing.md parsers
+│   ├── pricing_sync.py           # 12-hourly sync: fetch, compare, 50% guard, record
+│   ├── pricing_sync_runner.py    # PricingSync task entry: python -m pricing_sync_runner --once
+│   ├── price_history.py          # effective prices, per-row cost subquery, verification state
+│   ├── pricing_payload.py        # /api/pricing payload (order, footnotes, references)
+│   ├── pricing_export.py         # CSV, Markdown and JSON export
 │   ├── agent/                    # chatbot core: Bedrock model ids, 4 tools, AgentCore Memory, streaming
 │   ├── parity/                   # parity run engine: catalog (6 surfaces × 19 features), engine, probes, runner
 │   ├── claude_features/          # catalog (39 rows × 5 surfaces × 5 models), transports, probes, engine, runner (v2.23.0)
-│   ├── routers/                  # 17 router modules (auth, admin, analysis, cost, gptbench, features, …)
+│   ├── routers/                  # 18 router modules (auth, admin, analysis, cost, pricing, gptbench, features, …)
 │   └── tests/                    # pytest suite
-├── frontend/                     # Next.js 16 standalone + 11 routes (installable PWA)
-│   ├── src/app/                  # /, /models, /parity, /gpt-on-aws, /claude-features, /chat, /prompts, /cost, /reliability, /efficiency, /analysis + manifest.ts / PWA icons
+├── frontend/                     # Next.js 16 standalone + 12 routes (installable PWA)
+│   ├── src/app/                  # /, /models, /parity, /gpt-on-aws, /claude-features, /chat, /prompts, /cost, /pricing, /reliability, /efficiency, /analysis + manifest.ts / PWA icons
 │   ├── src/components/           # 30+ React components (dashboard, panels, chat)
-│   ├── src/lib/                  # api client, i18n, sortModels, pricing mirror, version + vitest unit tests
+│   ├── src/lib/                  # api client, i18n, sortModels, pricingTable, version + vitest unit tests
 │   └── e2e/                      # Playwright browser regression specs (fixture APIs)
 ├── cdk/                          # 8 CDK TypeScript stacks
 │   ├── lib/stacks/               # Network, Data, Cluster, AgentCore, AppServices, …
@@ -247,7 +259,7 @@ model-monitoring/
 │   ├── architecture.md           # full system design
 │   ├── api-reference.md          # endpoint reference
 │   ├── onboarding.md             # onboarding guide: local setup, key concepts, common tasks
-│   ├── decisions/                # ADR-001 through ADR-029
+│   ├── decisions/                # ADR-001 through ADR-030
 │   ├── images/                   # README screenshots (ui/*-en.png, ui/*-ko.png)
 │   └── runbooks/                 # deploy, rollback, troubleshooting
 ├── CHANGELOG.md                  # Keep a Changelog format (bilingual, repo root)
@@ -303,6 +315,7 @@ Key endpoint groups:
 | Comparison Lab | `/api/compare/run` | JWT required |
 | Prompts | `/api/prompts/*` | list public; create, delete and optimize require JWT |
 | Cost / Reliability / Efficiency / Analysis | `/api/{cost,reliability,efficiency,analysis}/*` | public |
+| Unit Prices | `/api/pricing`, `/api/pricing/export` | public; review approval under `/api/admin/pricing/*` is admin only |
 | Parity Run | `/api/parity/*` | public reads; trigger requires JWT |
 | Claude API Features | `/api/features/*` | public reads; trigger requires JWT |
 | GPT on AWS | `/api/gptbench/*` | public |
@@ -341,9 +354,9 @@ This project is licensed under the MIT License.
 
 ## 개요
 
-Amazon Bedrock LLM Monitor는 Bedrock Global / US 추론 프로파일(Claude Opus 5.5 포함, v2.27.0), Anthropic CP on AWS, OpenAI GPT via Bedrock Mantle 인리전 엔드포인트(Path 4)와 GPT-5.6, GPT-6 Astra, Sol, Luna의 Bedrock Global cross-region 프로파일, GPT-6 Astra, Sol, Luna의 US cross-region 프로파일(v2.20.0, v2.25.0, v2.27.0)에 걸친 55개 LLM 채널(Bedrock 21, Anthropic CP on AWS 9, OpenAI GPT on Bedrock 25)을 지속적으로 프로빙하는 운영 등급 관측 플랫폼입니다. (OpenAI 1P direct 경로(Path 5)는 코드에 남아 있지만 v2.19.1부터 휴면·비노출 상태입니다.) 지연(TTFT, 총 응답시간, 서버 처리시간), 처리량(TPS), 출력 토큰 분포, 정지 사유 패턴, 다중 채널 신뢰성, 30일 비용 예측을 10개 모니터링 화면을 갖춘 Next.js 대시보드에서 제공합니다.
+Amazon Bedrock LLM Monitor는 Bedrock Global / US 추론 프로파일(Claude Opus 5.5 포함, v2.27.0), Anthropic CP on AWS, OpenAI GPT via Bedrock Mantle 인리전 엔드포인트(Path 4)와 GPT-5.6, GPT-6 Astra, Sol, Luna의 Bedrock Global cross-region 프로파일, GPT-6 Astra, Sol, Luna의 US cross-region 프로파일(v2.20.0, v2.25.0, v2.27.0)에 걸친 55개 LLM 채널(Bedrock 21, Anthropic CP on AWS 9, OpenAI GPT on Bedrock 25)을 지속적으로 프로빙하는 운영 등급 관측 플랫폼입니다. (OpenAI 1P direct 경로(Path 5)는 코드에 남아 있지만 v2.19.1부터 휴면·비노출 상태입니다.) 지연(TTFT, 총 응답시간, 서버 처리시간), 처리량(TPS), 출력 토큰 분포, 정지 사유 패턴, 다중 채널 신뢰성, 30일 비용 예측, 12시간마다 갱신되는 공식 단가를 11개 모니터링 화면을 갖춘 Next.js 대시보드에서 제공합니다.
 
-이 시스템은 AWS ECS Fargate (CDK 8개 스택)에서 동작하며, EventBridge Scheduler가 5분마다 6개 프롬프트 카테고리를 라운드로빈하는 워크로드 프로빙을 실행합니다. Claude Sonnet 4.6 + 4개 Bedrock 도구로 구성된 챗봇이 시계열 데이터에 대해 자연어 질의를 지원합니다.
+이 시스템은 AWS ECS Fargate (CDK 8개 스택)에서 동작하며, EventBridge Scheduler가 5분마다 6개 프롬프트 카테고리를 라운드로빈하는 워크로드 프로빙을 실행하고, 12시간마다 공식 단가를 동기화합니다. Claude Sonnet 4.6 + 4개 Bedrock 도구로 구성된 챗봇이 시계열 데이터에 대해 자연어 질의를 지원합니다.
 
 ![대시보드 개요: 채널 수, 모델별 상태 스트립, 수집 주기](docs/images/ui/dashboard-ko.png)
 
@@ -351,7 +364,8 @@ Amazon Bedrock LLM Monitor는 Bedrock Global / US 추론 프로파일(Claude Opu
 
 - **iPhone/iPad 설치형 앱(PWA)** — Safari에서 대시보드를 열고 공유 → "홈 화면에 추가"하면 전체화면 standalone 앱으로 사용 가능 (v2.21.0).
 - **실시간 자동 프로빙** — EventBridge Scheduler가 5분마다 Fargate 태스크를 실행하여 6개 워크로드 카테고리(짧은 대화, 추론, 코드 생성, 요약, JSON 추출, 번역)를 라운드로빈으로 55개 모니터링 채널에 호출합니다. Claude Platform on AWS 9채널도 매 사이클 다른 채널과 같은 카테고리로 호출합니다(v2.29.1에서 v2.29.0의 10분 주기를 되돌렸습니다). `ANTHROPIC_CP_PROBE_INTERVAL_S=600`으로 설정하면 이 채널만 두 사이클에 한 번, 카테고리를 따로 순환하며 호출하므로 월간 사용 한도가 다시 걸릴 때 운영 레버로 쓸 수 있습니다.
-- **10개 분석 페이지** — 대시보드(지연/TPS 추이), 모델 탐색(모델별 카드 + Converse/InvokeModel/Messages/Responses 코드 예제), 패리티 런(모델×API surface×피처 증거 매트릭스), 비용(30일 예측 + 채널 비교), 신뢰성(family/channel별 성공률 + 에러 버킷), 효율성(가중 0~100 점수), 분석(정지 사유 분포 + 출력 길이 히스토그램), 프롬프트(세트 CRUD + Bedrock OptimizePrompt), GPT on AWS(Bedrock Mantle 인리전과 교차 리전 프로파일 18채널 TTFB/TTFT 벤치 — GPT 5.4/5.5/5.6 Terra, GPT-6 Astra/Sol/Luna, 15분 주기), Claude API 기능 검증(문서 피처 × 엔드포인트 × 모델 증거 매트릭스 + 문서 드리프트 감지).
+- **11개 분석 페이지** — 대시보드(지연/TPS 추이), 모델 탐색(모델별 카드 + Converse/InvokeModel/Messages/Responses 코드 예제), 패리티 런(모델×API surface×피처 증거 매트릭스), 비용(30일 예측 + 채널 비교, 프로브마다 그 시각에 유효했던 단가로 계산), 비용 단가(모델 패밀리와 채널별 Standard 입력/출력 단가, 번호 각주 출처, CSV / Markdown / JSON 다운로드, v2.30.0), 신뢰성(family/channel별 성공률 + 에러 버킷), 효율성(가중 0~100 점수), 분석(정지 사유 분포 + 출력 길이 히스토그램), 프롬프트(세트 CRUD + Bedrock OptimizePrompt), GPT on AWS(Bedrock Mantle 인리전과 교차 리전 프로파일 18채널 TTFB/TTFT 벤치 — GPT 5.4/5.5/5.6 Terra, GPT-6 Astra/Sol/Luna, 15분 주기), Claude API 기능 검증(문서 피처 × 엔드포인트 × 모델 증거 매트릭스 + 문서 드리프트 감지).
+- **공식 출처 기반 단가** — 비용 단가 페이지(`/pricing`)가 활성 모델 패밀리마다 Claude Platform on AWS, Global, US, In-Region 채널의 Standard 입력, 출력 단가(1M 토큰당)를 보여 줍니다. 단가마다 번호 각주로 출처를 달고, 참고 자료 목록과 CSV, Markdown, JSON 다운로드를 제공합니다. 스케줄된 PricingSync 태스크가 12시간마다 Bedrock agreement offer rate card, AWS Price List API, Anthropic 요금 문서를 읽고, 입력이나 출력이 50%를 넘게 바뀌면 관리자 승인을 기다립니다. 비용과 효율성 수치는 각 프로브 시각에 유효했던 단가로 계산합니다. 화면과 모든 다운로드 파일에 공개 자료를 모은 참고용 정보이며 AWS 공식 입장이 아니라는 안내를 표시합니다 (v2.30.0, ADR-030).
 - **모델 카드 지표 등급** — 대시보드 카드의 TTFT, 총 응답시간, TPS 값을 운영 48시간 p90/p99로 정한 워크로드 카테고리별 기준에 따라 파랑(양호), 호박 ▲(경고), 장미 ◆(위험)으로 표시합니다(TPS는 낮은 쪽만 판정). 범례를 펼치면 전체 기준표가 나오고, 값마다 `data-grade` 속성과 스크린 리더 설명이 붙습니다 (v2.28.0, ADR-029).
 - **12시간 주기 패리티 스윕** — 스케줄된 Fargate 태스크가 모델 × API surface × 피처 셀 전체(6 surface × 19 피처)를 실행 증거(도구 카나리 왕복, JSON 유효성, 캐시 토큰 카운트, 스트림 델타)로 검증합니다 — HTTP 200만으로는 지원으로 판정하지 않습니다.
 - **일일 Claude API 기능 검증 스윕** — 스케줄된 Fargate 태스크(매일 17:30 UTC, 02:30 KST, v2.29.0)가 39행 카탈로그(= 문서 피처 33 + 코어 4 + Models API 1 + strict_tool_use 분할 1)를 Claude Platform on AWS · Bedrock Mantle `/anthropic` · Bedrock runtime(Messages API + InvokeModel + Converse)에서 대표 모델 5종(Claude Fable 5.1, Fable 5, Opus 5.5, Opus 5, Sonnet 5 — 런당 975셀, v2.28.0)으로 실행하고, 실측이 문서상 가용성과 어긋나면 문서 드리프트 배너로 표시합니다.
@@ -492,6 +506,10 @@ curl https://<your-cloudfront-domain>/api/auto-probe/latest
 # 워크로드 카테고리별 필터링
 curl "https://<your-cloudfront-domain>/api/auto-probe/latest?category=code-gen"
 
+# 단가(공식 출처, 12시간마다 갱신)와 CSV 다운로드
+curl -s https://<your-cloudfront-domain>/api/pricing | jq '{last_sync, pending_review, families: (.families | length)}'
+curl -OJ "https://<your-cloudfront-domain>/api/pricing/export?format=csv&lang=ko"
+
 # 로그인 후 수동 프로브 실행 (SSE 스트리밍)
 TOKEN=$(curl -sX POST https://<your-cloudfront-domain>/api/auth/login \
   -H 'Content-Type: application/json' \
@@ -552,16 +570,23 @@ model-monitoring/
 │   ├── prober.py                 # 활성 55개(+1P 5개 휴면) AVAILABLE_MODELS, retry, Bedrock + Anthropic CP + OpenAI Mantle/Global/US/1P
 │   ├── auto_prober.py            # EventBridge Fargate task가 호출하는 run_cycle()
 │   ├── gptbench.py               # GPT on AWS 벤치 사이클 (18채널 × 10회, TTFB/TTFT)
-│   ├── pricing.py                # 토큰 단가 테이블
+│   ├── pricing_sources.py        # 채널별 단가 식별자, 출처 매핑, 면책 문구, 참고 페이지 (v2.30.0)
+│   ├── pricing_seed.py           # 활성 55채널 공식 단가 seed + ensure_seed
+│   ├── pricing_parsers.py        # agreement offer, Price List, Anthropic pricing.md 파서
+│   ├── pricing_sync.py           # 12시간 동기화: 가져오기, 비교, 50% 안전장치, 기록
+│   ├── pricing_sync_runner.py    # PricingSync 태스크 진입점: python -m pricing_sync_runner --once
+│   ├── price_history.py          # 유효 단가, 행 단위 비용 서브쿼리, 계산 상태
+│   ├── pricing_payload.py        # /api/pricing 응답 (순서, 각주, 참고 자료)
+│   ├── pricing_export.py         # CSV, Markdown, JSON 내보내기
 │   ├── agent/                    # 챗봇 core: Bedrock model id, 4개 도구, AgentCore Memory, 스트리밍
 │   ├── parity/                   # 패리티 런 엔진: 카탈로그(6 surface × 19 피처), 엔진, 프로브, 러너
 │   ├── claude_features/          # 카탈로그(39행 × 5 surface × 5모델), 전송기, 프로브, 엔진, 러너 (v2.23.0)
-│   ├── routers/                  # 17개 라우터 모듈 (auth, admin, analysis, cost, gptbench, features, …)
+│   ├── routers/                  # 18개 라우터 모듈 (auth, admin, analysis, cost, pricing, gptbench, features, …)
 │   └── tests/                    # pytest 테스트
-├── frontend/                     # Next.js 16 standalone + 11 라우트 (설치형 PWA)
-│   ├── src/app/                  # /, /models, /parity, /gpt-on-aws, /claude-features, /chat, /prompts, /cost, /reliability, /efficiency, /analysis + manifest.ts / PWA 아이콘
+├── frontend/                     # Next.js 16 standalone + 12 라우트 (설치형 PWA)
+│   ├── src/app/                  # /, /models, /parity, /gpt-on-aws, /claude-features, /chat, /prompts, /cost, /pricing, /reliability, /efficiency, /analysis + manifest.ts / PWA 아이콘
 │   ├── src/components/           # 30+ React 컴포넌트 (대시보드, 패널, 챗)
-│   ├── src/lib/                  # API 클라이언트, i18n, sortModels, pricing 미러, version + vitest 단위 테스트
+│   ├── src/lib/                  # API 클라이언트, i18n, sortModels, pricingTable, version + vitest 단위 테스트
 │   └── e2e/                      # Playwright 브라우저 회귀 스펙 (모의 API)
 ├── cdk/                          # 8개 CDK TypeScript 스택
 │   ├── lib/stacks/               # Network, Data, Cluster, AgentCore, AppServices, …
@@ -570,7 +595,7 @@ model-monitoring/
 │   ├── architecture.md           # 전체 시스템 설계
 │   ├── api-reference.md          # 엔드포인트 레퍼런스
 │   ├── onboarding.md             # 온보딩 가이드: 로컬 환경 구성, 핵심 개념, 자주 하는 작업
-│   ├── decisions/                # ADR-001 ~ ADR-029
+│   ├── decisions/                # ADR-001 ~ ADR-030
 │   ├── images/                   # README 스크린샷 (ui/*-en.png, ui/*-ko.png)
 │   └── runbooks/                 # 배포, 롤백, 트러블슈팅
 ├── CHANGELOG.md                  # Keep a Changelog 형식 (bilingual, 저장소 루트)
@@ -626,6 +651,7 @@ https://<your-cloudfront-domain>/openapi.json
 | 비교 실험실 | `/api/compare/run` | JWT 필요 |
 | 프롬프트 | `/api/prompts/*` | 목록 공개, 생성, 삭제, 최적화는 JWT 필요 |
 | 비용 / 신뢰성 / 효율성 / 분석 | `/api/{cost,reliability,efficiency,analysis}/*` | 공개 |
+| 비용 단가 | `/api/pricing`, `/api/pricing/export` | 공개, 검토 대기 승인(`/api/admin/pricing/*`)은 admin 전용 |
 | 패리티 런 | `/api/parity/*` | 조회 공개, 실행은 JWT 필요 |
 | Claude API 기능 검증 | `/api/features/*` | 조회 공개, 실행은 JWT 필요 |
 | GPT on AWS | `/api/gptbench/*` | 공개 |
diff --git a/backend/CLAUDE.md b/backend/CLAUDE.md
index e541a57..301a0aa 100644
--- a/backend/CLAUDE.md
+++ b/backend/CLAUDE.md
@@ -8,11 +8,11 @@ separate scheduled Fargate tasks (reusing this image), NOT in-process.
 - Python 3.11
 - FastAPI + Uvicorn
 - SQLAlchemy 2.0 ORM + PostgreSQL 16
-- boto3 (AWS Bedrock converse_stream)
+- boto3 (AWS Bedrock converse_stream; `bedrock` `list_foundation_model_agreement_offers` and `pricing` `get_products` in us-east-1 for the price sync, v2.30.0)
 - `anthropic` SDK — Claude Platform on AWS channels (`prober.py`, `parity/runner.py`)
 - `openai` SDK — OpenAI Mantle in-region + Global/US CRIS (`prober.py`, `gptbench.py`, `parity/runner.py`)
 - `aws-bedrock-token-generator` — SigV4-derived bearer for Mantle `/anthropic` (`parity/runner.py`, `claude_features/transports.py`)
-- `httpx` — `claude_features/transports.py` raw HTTP transports (also FastAPI TestClient in `tests/`)
+- `httpx` — `claude_features/transports.py` raw HTTP transports, `pricing_sync.py` Anthropic `pricing.md` fetch (also FastAPI TestClient in `tests/`)
 - passlib + bcrypt (>=4.0, <4.1) for password hashing
 - python-jose for JWT
 - `sse-starlette` is in `requirements.txt` but imported nowhere — SSE endpoints use `StreamingResponse` (ADR-007)
@@ -33,16 +33,24 @@ separate scheduled Fargate tasks (reusing this image), NOT in-process.
 - `claude_features/` — Claude API Features 검증 엔진: `catalog.py` (39행 = 문서 피처 33 + 코어 4 + Models API 1 + strict_tool_use 분할 1; 5 surface — cp/mantle/bedrock_messages/bedrock_invoke/bedrock_converse, `documented_for`; 대표 `MODELS` 5종 — Opus 5.5 v2.28.0, 1런 975셀 = 프로브 813 + 사전판정 162, `MODELS` 변경 시 `runner.CATALOG_VERSION` 범프), `transports.py` (raw httpx CP/Mantle/bedrock-runtime Messages API + boto3 InvokeModel/Converse, SDK 미사용 — bedrock-runtime의 coral `UnknownOperationException`은 404로 정규화; 스레드 로컬 `record_request`/`last_request`로 마지막 요청 본문을 남겨 `run_probe`가 실패 셀 증거에 회수, v2.24.0), `probes.py` (피처별 프로브), `engine.py` (판정 순수 로직), `runner.py` (ThreadPoolExecutor 4, 60런 보존)
 - `anomalies.py` — 최근 N시간 프로브 실패의 모델별 요약 (`/api/auto-probe/anomalies`, v2.12.0)
 - `retention.py` — `RETENTION_DAYS` 초과 `probe_results` → `probe_results_hourly` 집계 이관
-- `pricing.py` — per-model token prices (`PRICE_TABLE`, `get_pricing` with prefix fallback, `estimate_cost_usd`); mirror of `frontend/src/lib/pricing.ts` — change both together
+- **Unit prices (v2.30.0, ADR-030)** — `pricing.py` (`PRICE_TABLE`, `get_pricing`, `estimate_cost_usd`) is gone; prices live in the `price_history` table, one row per `model_id` and `effective_from`:
+  - `pricing_sources.py` — pure data: `price_identity(model_id)` → `PriceIdentity(family_key, family, provider, channel, source_kind, source_ref)` or `None` (CP ids follow the prober `_ANTHROPIC_TARGETS` substring + `_is_point_release_of` rule, date suffixes included), `active_channels`, `tier_of`, `region_of`, `NOVA_USAGETYPES`, `ANTHROPIC_DOC_NAMES` (exact doc model names), `PROVIDER_ORDER`, `FAMILY_ORDER` (byte-identical to `frontend/src/lib/sortModels.ts`, pinned by pytest), `DISCLAIMER`, `OFFICIAL_PAGES`, `PRICE_NOTES` (manual GPT-5.6 Sol promo note)
+  - `pricing_seed.py` — `SEED` (46 non-CP channels), `CP_SEED` (9 CP families by `family_key`), `seed_rows`, `ensure_seed(engine, active)`: per-`model_id` idempotent insert with `effective_from` 1970-01-01 and `status='seed'`, own transaction under `pg_advisory_xact_lock(917350003)`; called after CP/OpenAI registration from the lifespan (failure does not stop startup) and from the runner
+  - `pricing_parsers.py` — pure parsers: `single_public_offer`, `select_offer_price` (`DIMENSION_RE` allow-list, per-channel order), `parse_pricelist` (1K → 1M tokens), `parse_anthropic_pricing_md` (header names, `<sup>` stripped from name and value cells, exact names only); raise `PriceParseError`
+  - `pricing_sync.py` — `run_sync(session_factory, active, fetchers)`: `CHANGE_THRESHOLD` 0.5 inclusive (above → `pending_review`; a rejected or pending value is not raised twice), `SYNC_DEADLINE_S` 300 (`skipped:deadline`), `Fetchers` injected (`default_fetchers()` = boto3 bedrock/pricing in us-east-1 + httpx, 3 retries with backoff); never stores or logs `offerToken` or `legalTerm.url`
+  - `pricing_sync_runner.py` — CLI entrypoint for the PricingSync task (`rate(12 hours)`): `python -m pricing_sync_runner --once` — `create_tables`, `_discover_anthropic_models`, `_register_openai_models`, `ensure_seed`, `run_sync` under `pg_advisory_lock(917350004)` (exits at once when the lock is held), ends with `os._exit`
+  - `price_history.py` — `effective_prices_subquery` (`LEAD(effective_from)` per `model_id`), `with_row_cost(query)` (LEFT JOIN on `model_id` + time range, NULL without a price) used by `routers/cost.py` and `routers/efficiency.py`, `current_rows`, `pending_rows`, `last_finished_run`, `verification_of` (`seed_only` / `verified` / `stale`)
+  - `pricing_payload.py` (`build_pricing_payload` — order, footnote numbers, references, `price_number`) and `pricing_export.py` (`to_json`, `to_markdown`, `to_csv`, `export_filename`)
+  - Adding a model: classify it in `pricing_sources.py` and seed it in `pricing_seed.py` — a test fails when an active channel has no identity or seed, and production shows a `no_baseline` pending row
 - `label_repair.py` — startup label self-repair (v2.22.1): `repair_model_labels` (called from `main.py` lifespan, own transaction) rewrites stored `model_name` in `probe_results` / `probe_results_hourly` to the current `AVAILABLE_MODELS` label; model_ids outside the catalog are left alone
 - `visibility.py` — `HIDDEN_MODEL_PATTERNS` (default `(1P)`) + `visible_only()` read filter used by the read routers, `latest_results.py`, `insights_runner.py` and chatbot tools; DB rows are kept (v2.19.1)
-- `tests/` — offline pytest suite (29 `test_*.py`; `conftest.py` sets a test JWT key and a dead `DATABASE_URL`, tests use SQLite or fake sessions)
+- `tests/` — offline pytest suite (`conftest.py` sets a test JWT key and a dead `DATABASE_URL`, tests use SQLite or fake sessions; price fixtures under `tests/fixtures/pricing/` carry no `offerToken`, `legalTerm.url` or presigned URLs)
 - `agent/` — chatbot core: `bedrock.py` (CHAT/INSIGHTS model IDs), `tools.py` (4 Bedrock tools), `memory.py` (AgentCore), `streaming.py`
 - `auth.py` — JWT creation/validation, bcrypt hashing, environment config
-- `models.py` — SQLAlchemy ORM models
+- `models.py` — SQLAlchemy ORM models (`PriceHistory`, `PriceSyncRun` since v2.30.0 — created by `create_all`, not the lifespan ALTER block)
 - `schemas.py` — Pydantic response schemas
 - `database.py` — DB connection, session factory
-- `routers/` — API endpoint handlers (17 routers)
+- `routers/` — API endpoint handlers (18 router modules)
 
 ## Commands
 ```bash
@@ -59,4 +67,5 @@ ruff check .                     # = `make backend-lint` (`ruff check backend/`
 - SQLAlchemy must be `<2.1`: 2.1 makes psycopg (v3) the default driver for plain `postgresql://` URLs, and only `psycopg2-binary` is installed, so every DB import fails (CI 2026-09-26 with 2.1.1; production image runs 2.0.54). Moving to 2.1 means adding `psycopg[binary]` or writing `postgresql+psycopg2://` in `database.py`
 - All user input in HTML must use `html.escape()`
 - Secrets must come from environment variables, never hardcoded
+- Timestamps are timezone-aware datetimes bound as ORM/Core parameters, never raw string literals in SQL (SQLite compares DateTime as text; `price_history` range joins depend on it)
 - New Bedrock models may deprecate parameters (e.g., Opus 4.7 → no temperature)
diff --git a/backend/main.py b/backend/main.py
index 2a29857..6d5c894 100644
--- a/backend/main.py
+++ b/backend/main.py
@@ -225,7 +225,7 @@ app = FastAPI(
     title="Bedrock Model Monitoring",
     description="Monitor latency, throughput, and reliability of AWS Bedrock LLM models.",
     # OpenAPI(/docs)에 노출되는 런타임 버전 — 릴리스 시 CLAUDE.md "Version strings" 목록과 함께 범프.
-    version="2.29.1",
+    version="2.30.0",
     lifespan=lifespan,
 )
 
diff --git a/backend/routers/CLAUDE.md b/backend/routers/CLAUDE.md
index 1688f1b..975178d 100644
--- a/backend/routers/CLAUDE.md
+++ b/backend/routers/CLAUDE.md
@@ -1,7 +1,7 @@
 # Backend Routers — API Endpoint Handlers
 
 ## Role
-FastAPI router modules defining all API endpoints (17 routers, registered in `main.py`).
+FastAPI router modules defining all API endpoints (18 router modules, registered in `main.py`; `pricing.py` holds two routers).
 `GET /api/health` (public liveness, `{"status": "ok"}`) is defined in `backend/main.py`, not in a router.
 
 ## Files
@@ -15,9 +15,10 @@ FastAPI router modules defining all API endpoints (17 routers, registered in `ma
 - `chat.py` — `/api/chat/stream` — Sonnet 4.6 chatbot, 4 tools, dynamic followups (JWT)
 - `insights.py` — `/api/insights/*` — list / latest (public); `POST /regenerate` (JWT, not streaming — starts a backend thread, returns `triggered` at once, lock-serialized) and `POST /stream-regenerate` (JWT, SSE)
 - `compare.py` — `/api/compare/run` — Comparison Lab: 1 prompt → N models in parallel, SSE stream (JWT)
-- `cost.py` — `/api/cost/*` — summary, channel-compare, trend
+- `cost.py` — `/api/cost/*` — summary, channel-compare, trend; every row priced at the unit price in effect at its timestamp (`price_history.with_row_cost`, v2.30.0), a model without a price has a null cost, response shapes unchanged
 - `reliability.py` — `/api/reliability/multi-channel` — family/channel success rate + error buckets
-- `efficiency.py` — `/api/efficiency/score` — 0-100 weighted Token Efficiency Score per category
+- `efficiency.py` — `/api/efficiency/score` — 0-100 weighted Token Efficiency Score per category (cost component = average per-row cost of priced success rows, v2.30.0)
+- `pricing.py` — `router` `/api/pricing` (public, `build_pricing_payload`, 60 s in-process cache without `lang` in the key) and `/api/pricing/export?format=csv|md|json&lang=ko|en` (public, `Content-Disposition: attachment; filename="llm-monitor-unit-prices-YYYY-MM-DD.<ext>"`); `admin_router` `/api/admin/pricing/pending`, `POST /pending/{row_id}/approve`, `POST /pending/{row_id}/reject` (admin only, `effective_from` kept on approve, `warnings` when a later verified price exists, `invalidate_cache()` after each — other backend tasks can lag up to 60 s) (v2.30.0, ADR-030)
 - `analysis.py` — `/api/analysis/*` — stop-reason distribution + output-length histograms
 - `parity.py` — `/api/parity/*` — catalog, latest (완료 런 매트릭스 + 직전 런 대비 changes diff, s-maxage=60), evidence (셀별 증거), trigger (JWT, backend 내 백그라운드 스레드 — 스케줄 런과 달리 Fargate 아님)
 - `gptbench.py` — `/api/gptbench/*` — latest (최신 **완료** 사이클 채널 스코어 카드 — 시작 후 14분 지난 사이클만 완료, 18채널 v2.28.0, `fam_rank` Astra, Sol, Luna, Terra, 5.5, 5.4), trend?hours= (사이클×채널 median 시계열, `hours` 1~168 — UI 최대 7일, 집계 7컬럼만 튜플 조회. 공개 엔드포인트라 상한이 곧 1요청 메모리 상한이다: 720h 전체 ORM 로드는 18채널에서 ~1 GB RSS로 1 GiB 태스크 OOM 위험) (public, v2.18.0)
@@ -34,5 +35,5 @@ FastAPI router modules defining all API endpoints (17 routers, registered in `ma
   (it re-wraps each string as another `data:` field → malformed/double-wrapped SSE). See ADR-007.
 
 ## Tests
-- `backend/tests/`: `test_auto_probe_status.py`, `test_auto_probe_latest.py`, `test_auto_probe_trend.py` (auto_probe), `test_reliability.py`, `test_gptbench.py`, `test_visibility.py` (results + `(1P)` hiding), `test_openai_pricing.py` (cost channel split), `test_claude_features.py` (`routers.features.build_latest_payload`)
+- `backend/tests/`: `test_auto_probe_status.py`, `test_auto_probe_latest.py`, `test_auto_probe_trend.py` (auto_probe), `test_reliability.py`, `test_gptbench.py`, `test_visibility.py` (results + `(1P)` hiding), `test_claude_features.py` (`routers.features.build_latest_payload`), `test_cost_time_effective.py` (cost and efficiency at the price in effect at each row), `test_pricing_router.py` (`/api/pricing`, export, admin approval — v2.30.0)
 - Run: `cd backend && python3.12 -m pytest tests/ -q` (Python 3.10+)
diff --git a/backend/tests/CLAUDE.md b/backend/tests/CLAUDE.md
index 23b51f5..5666201 100644
--- a/backend/tests/CLAUDE.md
+++ b/backend/tests/CLAUDE.md
@@ -1,7 +1,7 @@
 # Backend Tests — Offline pytest suite
 
 ## Role
-29 `test_*.py` modules (430 tests) covering probe logic, cadence, watchdogs, catalogs, routers and migrations.
+`test_*.py` modules covering probe logic, cadence, watchdogs, catalogs, unit prices, routers and migrations.
 No network, no AWS credentials, no PostgreSQL. CI runs the same suite on Python 3.11 (`.github/workflows/ci.yml`).
 
 ## Key Files
@@ -14,7 +14,8 @@ No network, no AWS credentials, no PostgreSQL. CI runs the same suite on Python
   - `test_auto_prober_timeout.py`, `test_auto_prober_runner.py`, `test_probe_watchdog.py`, `test_stream_watchdog.py` — one hung model yields an error row, the run completes, the runner exits via `os._exit` (2026-09-23)
   - `test_auto_prober_pool.py`, `test_database_config.py` — DB pool exhaustion incidents (2026-06-09, 2026-07-08)
   - `test_startup_migration.py`, `test_perf_indexes.py` — source-level guards on lifespan migration cost and index declarations
-  - `test_fable51_catalog.py`, `test_opus55_gpt6_catalog.py`, `test_openai_pricing.py`, `test_label_repair.py` — model catalog labels, pricing keys, point-release matching
+  - `test_fable51_catalog.py`, `test_opus55_gpt6_catalog.py`, `test_label_repair.py` — model catalog labels, seed prices and `price_identity` classification, point-release matching
+  - `test_pricing_sources.py`, `test_pricing_seed.py`, `test_pricing_parsers.py`, `test_pricing_sync.py`, `test_pricing_sync_runner.py`, `test_price_history.py`, `test_cost_time_effective.py`, `test_openai_pricing.py`, `test_pricing_payload.py`, `test_pricing_export.py`, `test_pricing_router.py` — unit prices (v2.30.0, ADR-030): offline parser fixtures in `fixtures/pricing/` (no `offerToken`, `legalTerm.url` or presigned URLs), sync thresholds (0.5 inclusive: 22 → 33 verified, 22 → 33.01 pending), seed coverage of every active channel, time-effective cost joins and the v2.29.1 equivalence copy, `/api/pricing` and export goldens, backend `FAMILY_ORDER` = `frontend/src/lib/sortModels.ts`. Shared data modules `pricing_catalog.py` (the 55 active channels), `_pricing_dataset.py` (payload and export golden dataset) and `_legacy_pricing_v2291.py` (frozen v2.29.1 price table, equivalence test only) are not collected
   - `test_claude_features.py`, `test_parity_logic.py`, `test_parity_openai_client.py` — verification engines (cell-count pins 813 + 162)
 
 ## Gotchas
diff --git a/cdk/CLAUDE.md b/cdk/CLAUDE.md
index b3cbc4b..f32bcd5 100644
--- a/cdk/CLAUDE.md
+++ b/cdk/CLAUDE.md
@@ -13,7 +13,7 @@ services + internal ALB, CloudFront, EventBridge Scheduler tasks and alarms. Cov
 - `lib/stacks/agentcore-stack.ts` — `CfnMemory` (30-day event expiry), memory access policy, SSM `/bedrock-monitor/agentcore-memory-id`
 - `lib/stacks/app-services-stack.ts` — backend (8000, `/api/health`, 300 s health-check grace) and frontend (3000) services, internal ALB with HTTPS:443 and a temporary HTTP:80 listener, `/api/*` → backend at priority 10, backend env + SSM secrets, `ENABLE_OPENAI_1P = false`
 - `lib/stacks/edge-stack.ts` — CloudFront → VPC Origin (currently `HTTP_ONLY` port 80 until the ALB cert is settled), alias `monitorDomain` (default `llm-monitor.whchoi.net`) + `monitorCertArn`; `/api/auto-probe/*` (short edge cache, compression) must stay declared before `/api/*` (no cache, no compression for SSE). No WAF is attached (cdk-nag CFR2 suppressed, deferred to a us-east-1 stack)
-- `lib/stacks/scheduler-stack.ts` — 5 schedules (AutoProber and Insights `rate(5 minutes)`, ParityRun 12 h, GptBench 15 min, FeaturesVerify `cron(30 17 * * ? *)` UTC); `buildTaskDef` reuses the backend image with a CMD override (512 CPU / 1024 MiB, ARM64); `ANTHROPIC_CP_PROBE_INTERVAL_S=300` (every cycle, v2.29.1; 600 = every other cycle) only on the AutoProber task
+- `lib/stacks/scheduler-stack.ts` — 6 schedules (AutoProber and Insights `rate(5 minutes)`, ParityRun 12 h, GptBench 15 min, FeaturesVerify `cron(30 17 * * ? *)` UTC, PricingSync 12 h); `buildTaskDef` reuses the backend image with a CMD override (512 CPU / 1024 MiB, ARM64); `ANTHROPIC_CP_PROBE_INTERVAL_S=300` (every cycle, v2.29.1; 600 = every other cycle) only on the AutoProber task. PricingSync (v2.30.0, ADR-030) runs `python -m pricing_sync_runner --once` with its own `PricingSyncTaskRole` — only `bedrock:ListFoundationModelAgreementOffers` and `pricing:GetProducts` on `*`, no model invocation — and the same env and secrets as AutoProber (CP discovery and OpenAI registration), log group `/ecs/pricingsync`, output `PricingSyncScheduleName`
 - `lib/stacks/observability-stack.ts` — SNS topic (+ email subscription when `alarmEmail` is set), ALB/ECS/RDS alarms, dashboard
 - `lib/constructs/fargate-service.ts` — task def (default 512/1024, ARM64), circuit breaker with rollback, target group, CPU 70% autoscaling 1..3; `imageOverride` switches to a pinned URI but keeps the legacy repo `grantPull`
 - `lib/constructs/pinned-image.ts` — `repoNameFromImageUri`, `pinnedContainerImage` (`ContainerImage.fromRegistry` + explicit `grantPull` on the parsed repo)
@@ -21,14 +21,14 @@ services + internal ALB, CloudFront, EventBridge Scheduler tasks and alarms. Cov
 ## Rules
 - Always pass the running images: `-c backendImage=<acct>.dkr.ecr.ap-northeast-2.amazonaws.com/bedrock-monitor-backend-v2:<tag>@sha256:<digest>` and `-c frontendImage=…/bedrock-monitor-frontend:<tag>@sha256:<digest>`. Without them AppServices and Scheduler synth `:latest` of the CDK-managed repos (legacy backend repo included — only a synth warning) and a deploy reverts production. Use the full registry host — a bare repo name resolves to docker.io and the deploy rolls back
 - Deploy app changes with `npx cdk deploy --exclusively BedrockMonitor-AppServices BedrockMonitor-Scheduler --require-approval never -c backendImage=… -c frontendImage=…`; without `--exclusively` CDK also deploys upstream stacks that have diffs. Never `npm run deploy` (`cdk deploy --all` with no image context). Procedure: `docs/runbooks/deploy.md`
-- Scheduler `ecs:RunTask` stays on task-def family `:*` (ADR-011) — a pinned revision fails silently after the next deploy
+- Scheduler `ecs:RunTask` stays on task-def family `:*` (ADR-011) — a pinned revision fails silently after the next deploy. A new scheduled task adds its family to `RunTaskFamilyWildcard` and its task role to `PassTaskRoles`
 - Backend env is defined twice (`backendEnv` in app-services-stack, `buildTaskDef` in scheduler-stack), and `ENABLE_OPENAI_1P` exists in both files — change both, deploy both stacks
 - Some test names are stale ("immutable tag", "X86_64"); the assertions check MUTABLE and CPU/memory only
 
 ## Commands
 ```bash
 cd cdk
-npm test             # jest, synthesizes every stack (~10 s, 79 tests) — CI runs `npx jest --ci`
+npm test             # jest, synthesizes every stack (~10 s, 85 tests) — CI runs `npx jest --ci`
 npm run typecheck    # tsc --noEmit
 npm run lint         # eslint
 npm run synth        # cdk synth --all --quiet (cdk-nag reports in cdk.out/*NagReport.csv)
diff --git a/docs/api-reference.md b/docs/api-reference.md
index d8ff7c5..80bc279 100644
--- a/docs/api-reference.md
+++ b/docs/api-reference.md
@@ -286,23 +286,101 @@ regeneration is running. Poll `GET /api/insights/latest` for the result.
 ## Analytics (Public)
 
 ### GET /api/cost/summary · /api/cost/channel-compare · /api/cost/trend
-30-day cost projection, per-channel comparison, cost trend. Costs are computed at query time from `backend/pricing.py`
-`PRICE_TABLE` (mirrored in `frontend/src/lib/pricing.ts`), so a price change re-prices past rows. A model without a price key
-has a null cost (shown as "-"). Since v2.28.0 the six GPT-6 Sol/Luna channels are priced from the Bedrock agreement-offer rate
-card (`gpt-6-sol` / `-us` $2.20 / $11, `-global` $2 / $10; `gpt-6-luna` / `-us` $0.11 / $0.55, `-global` $0.10 / $0.50 per
-MTok — ADR-028 v2.28.0 follow-up) instead of null.
+30-day cost projection, per-channel comparison, cost trend. Since v2.30.0 (ADR-030) every successful probe row is priced at the
+unit price in effect at its `timestamp`: `backend/price_history.py` joins `probe_results` to `price_history` on an exact
+`model_id` match and the row's time range (`effective_from` up to the next price's `effective_from`, rows in status `seed` or
+`verified`), and computes `row_cost = (input_tokens × input_per_mtok + output_tokens × output_per_mtok) / 1,000,000`. Summary and
+channel-compare sum those row costs; a model without a price row has a null cost (shown as "-") while its tokens still count in
+the totals, and channel-compare keeps adding a null as 0. Trend buckets use the same per-row costs. Before v2.30.0 costs were
+computed at query time from `backend/pricing.py` (removed), so a price change re-priced every past row (ADR-025 rule, now
+superseded). The time before the first PricingSync run is priced with the seed (`pricing_seed.py`, effective from
+1970-01-01): price changes made before v2.30.0 are not reconstructed, and the 11 channels whose code price was wrong (Bedrock
+Claude US, Nova 2.0 Lite) are corrected for all history. Response shapes are unchanged.
 
 ### GET /api/reliability/multi-channel
 Success rate + error buckets grouped by family/channel.
 
 ### GET /api/efficiency/score
-0-100 weighted Token Efficiency Score per workload category.
+0-100 weighted Token Efficiency Score per workload category. The cost component averages the per-row cost of successful rows
+that have a price (the unit price in effect at each probe's time, v2.30.0).
 
 ### GET /api/analysis/stop-reasons · /api/analysis/output-length
 Stop-reason distribution + output-length histograms.
 
 ---
 
+## Unit Prices (Public) — v2.30.0, ADR-030
+
+Data source for `/pricing` (Unit Prices / 비용 단가), Model Explorer card prices and Comparison Lab costs. Prices are USD per
+1M tokens, Standard tier input and output only (no cache, batch, long-context, priority or flex prices). The PricingSync task
+(`python -m pricing_sync_runner --once`, every 12 hours) refreshes them from three official sources: the Bedrock agreement-offer
+rate card (`ListFoundationModelAgreementOffers`, Bedrock Claude 20 + OpenAI 25 channels), the AWS Price List API (`GetProducts`,
+Nova 2.0 Lite) and Anthropic's `https://platform.claude.com/docs/en/about-claude/pricing.md` (Claude Platform on AWS 9 channels).
+A change of more than 50% on input or output (the boundary itself is applied) is stored as `pending_review` and waits for admin
+approval (see Admin below). Dormant 1P channels and labels matching `HIDDEN_MODEL_PATTERNS` are excluded.
+
+### GET /api/pricing
+Current price table. The backend keeps a 60 s in-process cache per task (no `lang` in the key — the body carries both languages).
+
+**Response (abridged):**
+```json
+{
+  "currency": "USD",
+  "unit": "per_1m_tokens",
+  "generated_at": "2026-09-26T16:00:00Z",
+  "last_sync": {"id": 12, "started_at": "2026-09-26T15:00:00Z", "finished_at": "2026-09-26T15:00:31Z", "status": "completed"},
+  "pending_review": 0,
+  "families": [
+    {
+      "family_key": "claude-opus-5-5", "family": "Claude Opus 5.5", "provider": "anthropic",
+      "tiers": {
+        "cp":     {"input": 4,   "output": 20, "model_ids": ["anthropic:claude-opus-5-5"], "source_ids": ["anthropic-pricing"], "footnotes": [1], "verification": "verified", "observed_at": "2026-09-26T15:00:00Z", "pending": null},
+        "global": {"input": 4,   "output": 20, "model_ids": ["global.anthropic.claude-opus-5-5"], "source_ids": ["offer:offer-7sp77cpl4rveu"], "footnotes": [2], "verification": "verified", "observed_at": "2026-09-26T15:00:00Z", "pending": null},
+        "us":     {"input": 4.4, "output": 22, "model_ids": ["us.anthropic.claude-opus-5-5"], "source_ids": ["offer:offer-7sp77cpl4rveu"], "footnotes": [2], "verification": "verified", "observed_at": "2026-09-26T15:00:00Z", "pending": null},
+        "in_region": []
+      },
+      "notes": []
+    }
+  ],
+  "models": {"us.anthropic.claude-opus-5-5": {"input": 4.4, "output": 22, "verification": "verified"}},
+  "references": [
+    {"n": 1, "id": "anthropic-pricing", "kind": "anthropic_doc", "title_en": "Anthropic API pricing (Claude Platform on AWS uses standard pricing)", "title_ko": "Anthropic API 요금 (Claude Platform on AWS는 표준 요금)", "url": "https://platform.claude.com/docs/en/about-claude/pricing#model-pricing", "as_of": "2026-09-26"}
+  ],
+  "disclaimer": {"en": "This price list is compiled automatically from public sources for reference only and is not an official AWS statement. Always confirm final prices on the official pricing pages.", "ko": "이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요."}
+}
+```
+
+- `families` come in display order (provider Anthropic Claude → Amazon Nova → OpenAI, then the family order of
+  `frontend/src/lib/sortModels.ts` `FAMILY_ORDER`, mirrored and pinned by `pricing_sources.FAMILY_ORDER`). Clients render that
+  order and the footnote numbers as sent; they never re-sort or renumber.
+- `tiers` always has the four keys `cp`, `global`, `us`, `in_region`. The first three are an object or `null`; `in_region` is
+  always an array whose elements add `regions` and group regions with the same price (sorted by region name).
+- Prices are JSON numbers with at most 6 decimals and no trailing zeros (`4`, `4.4`, `0.11`).
+- `verification` per cell: `verified` (observed by the latest finished run, whatever its status), `stale` (last observed
+  earlier — `observed_at` tells when), `seed_only` (never observed by an official source yet). `pending` is the latest
+  `pending_review` row of that `model_id` (`{id, input, output, observed_at}`) or `null`.
+- `models` maps each active `model_id` to its current price (used by Model Explorer and Comparison Lab).
+- `notes` holds manual notes that are not official-source facts (GPT-5.6 Sol promotional price, `min_until` 2026-11-21 with the
+  prior prices); a note disappears once a sync observes its `prior_price`.
+- `references[]`: `n` (1-based, in order of first citation, then fixed official pages, manual notes last), `id`
+  (`offer:<offerId>`, `pricelist:<usagetype>`, `anthropic-pricing`, `official:<slug>`, `note:<family_key>`), `kind`
+  (`agreement_offer`, `price_list`, `anthropic_doc`, `official_page`, `manual_note`), bilingual titles, `url`, `as_of` (UTC date
+  of the latest observation of that source, or the seed date 2026-09-26; `null` for `official_page` and `manual_note`, and a
+  `manual_note` has `url: null`).
+- Active channels are the backend's `AVAILABLE_MODELS` plus Claude Platform on AWS model ids observed in `price_history` in the
+  last 30 days (so the table stays full when CP discovery failed at startup), minus hidden labels.
+
+### GET /api/pricing/export?format=csv|md|json&lang=ko|en
+Download the same table as a file: `Content-Disposition: attachment; filename="llm-monitor-unit-prices-YYYY-MM-DD.<csv|md|json>"`.
+`lang` defaults to `ko`. `json` is the `/api/pricing` body. `md` starts with the disclaimer as a quote, then one table per
+provider (model | Claude Platform on AWS | Global | US | In-Region, cells with `[^n]`), notes, the references as footnote
+definitions and the disclaimer again. `csv` is UTF-8 with a BOM, a first line `# <disclaimer>`, the header
+`provider,family,channel,regions,model_ids,input_usd_per_1m,output_usd_per_1m,verification,observed_at,footnotes,source_ids`, one
+row per tier element (`channel` is `cp`, `global`, `us` or `in_region`; list columns are space-separated), a blank line, then
+`reference_n,reference_id,kind,title,url,as_of` and the references.
+
+---
+
 ## Parity Run (Public read, trigger = Auth Required) — v2.11.0
 
 ### GET /api/parity/catalog
@@ -405,3 +483,22 @@ User management.
 
 ### POST /api/admin/reset-monitoring-data
 Purge stored probe data.
+
+### GET /api/admin/pricing/pending — v2.30.0
+Unit prices waiting for review (`status = 'pending_review'`): for each row the current effective price, the new price, the input
+and output change ratios, the source and the reason — `changed` (a change above 50%) or `no_baseline` (a `model_id` with no
+seed or verified price; approving it applies the price to all history, `effective_from` 1970-01-01). Response
+`{"pending": [{id, model_id, family_key, channel, reason, current: {input, output} | null, new: {input, output}, change:
+{input, output} | null, source_id, effective_from, observed_at}]}`, ordered by `id`, pending rows of every `model_id`.
+
+### POST /api/admin/pricing/pending/{row_id}/approve — v2.30.0
+Sets the row to `verified` and keeps its `effective_from` (the start of the run that observed it, or 1970-01-01 for
+`no_baseline`), so costs from that time use the new price; when a later verified price for the same `model_id` already exists
+the response lists it in `warnings`.
+
+### POST /api/admin/pricing/pending/{row_id}/reject — v2.30.0
+Sets the row to `rejected`; the same value is not raised again until the official value changes.
+
+Approve and reject both clear the `/api/pricing` cache of the backend task that served the request; other backend tasks can serve the previous
+table for up to 60 s. Both return `{ok, id, status, effective_from, warnings}`. `401` without a token, `403` for a non-admin
+user, `404` for an unknown `row_id`, `409` when the row is not `pending_review`.
diff --git a/docs/architecture.md b/docs/architecture.md
index da3e435..59cf327 100644
--- a/docs/architecture.md
+++ b/docs/architecture.md
@@ -11,12 +11,14 @@
 
 ## System Overview
 
-Bedrock LLM Monitor v2 measures a 55-channel active catalog across Amazon Bedrock, Claude Platform on AWS (Anthropic CP), and OpenAI GPT on Bedrock (Mantle in-region plus Global and US cross-region profiles). A scheduled AutoProber task probes every channel every 5 minutes, including the 9 Claude Platform on AWS channels (v2.29.1 reverted the v2.29.0 10-minute CP cadence; `ANTHROPIC_CP_PROBE_INTERVAL_S=600` brings it back as an operational lever). Four more scheduled tasks produce AI insights, a 12-hourly model × API surface × feature parity sweep, a 15-minute GPT TTFB/TTFT bench, and a daily Claude API Features evidence sweep. A chatbot answers natural-language questions over the stored time series.
+Bedrock LLM Monitor v2 measures a 55-channel active catalog across Amazon Bedrock, Claude Platform on AWS (Anthropic CP), and OpenAI GPT on Bedrock (Mantle in-region plus Global and US cross-region profiles). A scheduled AutoProber task probes every channel every 5 minutes, including the 9 Claude Platform on AWS channels (v2.29.1 reverted the v2.29.0 10-minute CP cadence; `ANTHROPIC_CP_PROBE_INTERVAL_S=600` brings it back as an operational lever). Five more scheduled tasks produce AI insights, a 12-hourly model × API surface × feature parity sweep, a 15-minute GPT TTFB/TTFT bench, a daily Claude API Features evidence sweep, and a 12-hourly sync of official unit prices (v2.30.0). A chatbot answers natural-language questions over the stored time series.
 
 Traffic enters through CloudFront at `llm-monitor.whchoi.net` (the default `d36s7ml54xwemr.cloudfront.net` name also works), reaches an internal ALB through a VPC Origin, and is routed to two ECS Fargate services: `frontend` (Next.js standalone) and `backend` (FastAPI). All data lands in a single RDS PostgreSQL instance. Viewers connect over HTTPS. The VPC Origin currently reaches the ALB over HTTP port 80 inside the VPC, a temporary setting in `edge-stack.ts` until the origin switches to `HTTPS_ONLY`; the ALB is internal, sits in private subnets, and its security group admits only the VPC CIDR.
 
 Dashboard model cards grade TTFT, total latency, and TPS values against per-workload-category thresholds (normal blue, warning amber, critical rose). The grading is a pure frontend function in `frontend/src/lib/metricGrade.ts` with no backend involvement (v2.28.0, ADR-029).
 
+Unit prices have one source, the backend `price_history` table (v2.30.0, ADR-030). The PricingSync task reads the Standard input and output price of every active channel from three official sources every 12 hours: the Bedrock agreement-offer rate cards (Bedrock Claude and OpenAI), the AWS Price List API (Nova 2.0 Lite) and Anthropic's `pricing.md` (Claude Platform on AWS). A change above 50% on input or output waits for admin approval. `/api/cost/*` and `/api/efficiency/score` price each probe row at the unit price in effect at its timestamp, and the `/pricing` page, its CSV, Markdown and JSON downloads, Model Explorer and Comparison Lab read `/api/pricing`.
+
 ## Full Architecture
 
 ```mermaid
@@ -34,7 +36,7 @@ flowchart TB
   end
 
   subgraph apilayer[API Layer]
-    be["backend service: FastAPI, 17 routers, port 8000"]
+    be["backend service: FastAPI, 18 routers, port 8000"]
   end
 
   subgraph ingestion[Scheduled Ingestion Layer]
@@ -44,6 +46,7 @@ flowchart TB
     par["ParityRun task: 12 h"]
     gpt["GptBench task: 15 min"]
     feat["FeaturesVerify task: daily 17:30 UTC"]
+    prc["PricingSync task: 12 h"]
   end
 
   subgraph storage[Storage Layer]
@@ -60,6 +63,12 @@ flowchart TB
     ses["Amazon SES us-east-1"]
   end
 
+  subgraph pricesrc[Official Price Sources]
+    offers["Bedrock agreement offers, us-east-1"]
+    plist["AWS Price List API, us-east-1"]
+    adoc["Anthropic pricing.md, platform.claude.com"]
+  end
+
   subgraph obs[Observability Layer]
     cw["CloudWatch Logs, Alarms, Dashboard"]
     sns[SNS alarm topic]
@@ -69,15 +78,17 @@ flowchart TB
   user --> cf --> vpco --> alb
   alb -->|"/*"| fe
   alb -->|"/api/*"| be
-  sched --> ap & ins & par & gpt & feat
+  sched --> ap & ins & par & gpt & feat & prc
   ap & par & feat --> providers
+  prc --> offers & plist & adoc
+  prc -.->|"CP model list"| cp
   gpt --> br & mantle
   ins --> br
   be --> br
   be --> opt
   be --> ses
   be --> mem
-  be & ap & ins & par & gpt & feat --> rds
+  be & ap & ins & par & gpt & feat & prc --> rds
   sec -.->|"secrets at task start"| be
   be & fe & ap --> cw
   cw --> sns
@@ -100,6 +111,13 @@ flowchart LR
   A([Browser]) --> B[CloudFront] --> C[VPC Origin] --> D[Internal ALB] --> E[backend FastAPI] --> F[(RDS PostgreSQL)]
 ```
 
+Unit price path (v2.30.0, ADR-030):
+
+```mermaid
+flowchart LR
+  A([EventBridge Scheduler]) --> B[PricingSync task] --> C["Agreement offers, Price List, Anthropic pricing.md"] --> D[(price_history in RDS)] --> E["backend /api/pricing, /api/cost/*"] --> F["frontend /pricing, /cost"] --> G([Browser])
+```
+
 `/api/auto-probe/status` and `/api/auto-probe/latest` read the latest `ProbeRun(is_auto=1)` rows from the database, not in-process state, because the prober runs in a separate Fargate task. `/latest` returns each model's latest row within its own cadence window (3 intervals: 15 minutes for every channel at the default cadence, 30 minutes for CP when `ANTHROPIC_CP_PROBE_INTERVAL_S=600`), and `/status` exposes `channel_intervals` so the dashboard judges freshness per channel.
 
 ## Components by Layer
@@ -122,14 +140,14 @@ flowchart LR
 | S3 (ALB logs) | ALB access logs, 90-day retention |
 | ECS cluster `bedrock-monitor` | Container Insights enabled |
 | ECR `bedrock-monitor-backend-v2`, `bedrock-monitor-frontend` | `bedrock-monitor-backend-v2` is created outside CDK with IMMUTABLE tags (ADR-018); the CDK-managed `bedrock-monitor-frontend` (and the legacy `bedrock-monitor-backend`) are MUTABLE, so releases rely on unique `v<epoch>` tags plus digest-pinned task definitions (`pinned-image.ts`) |
-| frontend Fargate service | Next.js standalone on port 3000, 0.5 vCPU / 1 GB, CPU autoscaling 1 to 3; pages `/`, `/models`, `/parity`, `/cost`, `/reliability`, `/efficiency`, `/analysis`, `/gpt-on-aws`, `/claude-features`, `/prompts`, `/chat` |
-| backend Fargate service | FastAPI on port 8000, 0.5 vCPU / 1 GB, CPU autoscaling 1 to 3, health-check grace 300 s for startup migrations; 17 routers under `backend/routers/` |
+| frontend Fargate service | Next.js standalone on port 3000, 0.5 vCPU / 1 GB, CPU autoscaling 1 to 3; pages `/`, `/models`, `/parity`, `/cost`, `/pricing`, `/reliability`, `/efficiency`, `/analysis`, `/gpt-on-aws`, `/claude-features`, `/prompts`, `/chat` |
+| backend Fargate service | FastAPI on port 8000, 0.5 vCPU / 1 GB, CPU autoscaling 1 to 3, health-check grace 300 s for startup migrations; 18 router modules under `backend/routers/`; `/api/pricing` keeps a 60 s in-process cache per task |
 
 ### Storage
 
 | Resource | Role |
 |----------|------|
-| RDS PostgreSQL 16.8 (t4g.micro) | 20 GB gp3, Single-AZ, 7-day backups, encrypted; raw `probe_results` older than `RETENTION_DAYS` (60) move to `probe_results_hourly` |
+| RDS PostgreSQL 16.8 (t4g.micro) | 20 GB gp3, Single-AZ, 7-day backups, encrypted; raw `probe_results` older than `RETENTION_DAYS` (60) move to `probe_results_hourly`; `price_history` (unit prices per `model_id` with `effective_from`) and `price_sync_runs` (one row per PricingSync run) since v2.30.0 |
 | Secrets Manager `bedrock-monitor/db` | Generated RDS credentials |
 | SSM `/bedrock-monitor/jwt-secret-key` | JWT signing key |
 | SSM `/bedrock-monitor/agentcore-memory-id` | AgentCore Memory ID |
@@ -148,6 +166,7 @@ flowchart LR
 | AgentCore Memory `BedrockMonitorChatMemory` | Chat context, 30-day retention; IAM managed policy attached to the backend task role |
 | Bedrock Agent Runtime OptimizePrompt | `/api/prompts/optimize` in `BEDROCK_OPTIMIZE_REGION` (default us-east-1) |
 | Amazon SES (us-east-1) | Registration approval email to the admin address |
+| Official price sources | Bedrock `ListFoundationModelAgreementOffers` (us-east-1, 18 foundation models), AWS Price List `GetProducts` (us-east-1, Nova 2.0 Lite) and `https://platform.claude.com/docs/en/about-claude/pricing.md` (Claude Platform on AWS); read only by the PricingSync task (ADR-030) |
 
 ### Scheduled Ingestion
 
@@ -158,15 +177,16 @@ flowchart LR
 | `ParityRunSchedule` | `rate(12 hours)` | `python -m parity_runner --once` | Model × 6 surfaces × 19 features evidence cells |
 | `GptBenchSchedule` | `rate(15 minutes)` | `python -m gptbench_runner --once` | 18 GPT channels (Mantle in-region 11 + CRIS 7) × 10 sequential calls; per-call watchdog `GPT_BENCH_CALL_TIMEOUT` 90 s, cycle deadline `GPT_BENCH_DEADLINE` 780 s |
 | `FeaturesVerifySchedule` | `cron(30 17 * * ? *)` Etc/UTC | `python -m features_runner --once` | 39 rows × 5 surfaces × 5 models (Claude Fable 5.1, Fable 5, Opus 5.5, Opus 5, Sonnet 5) = 975 cells (813 probed + 162 pre-decided), about 9 minutes, daily at 17:30 UTC (02:30 KST) |
+| `PricingSyncSchedule` | `rate(12 hours)` | `python -m pricing_sync_runner --once` | One `price_sync_runs` row (`completed`, `partial` or `failed`) and, per active channel, an unchanged observation, a new `verified` price (change of 50% or less) or a `pending_review` row; run cap 300 s, serialized by `pg_advisory_lock(917350004)` (v2.30.0, ADR-030) |
 
-Every scheduled task uses the backend image with a command override, 0.5 vCPU / 1 GB, and a task definition family `:*` wildcard in the scheduler role's `ecs:RunTask` policy (ADR-011).
+Every scheduled task uses the backend image with a command override, 0.5 vCPU / 1 GB, and a task definition family `:*` wildcard in the scheduler role's `ecs:RunTask` policy (ADR-011). PricingSync runs with its own task role that allows only `bedrock:ListFoundationModelAgreementOffers` and `pricing:GetProducts`, with no model invocation.
 
 ### Network
 
 | Resource | Role |
 |----------|------|
 | VPC 10.20.0.0/16 (or an existing VPC) | 2 AZs with Public, App, and Data subnets |
-| NAT gateway × 1 | Egress for App subnets to endpoints without PrivateLink coverage (Claude Platform on AWS, Mantle, OpenAI CRIS in us-east-1) |
+| NAT gateway × 1 | Egress for App subnets to endpoints without PrivateLink coverage (Claude Platform on AWS, Mantle, OpenAI CRIS in us-east-1, and for PricingSync the Bedrock control plane and Price List API in us-east-1 plus `platform.claude.com`) |
 | Interface VPC endpoints × 9 | ECR API, ECR Docker, CloudWatch Logs, SSM, SSM Messages, Secrets Manager, KMS, Bedrock Runtime, Bedrock AgentCore |
 | Gateway VPC endpoint × 1 | S3 |
 
@@ -174,7 +194,7 @@ Every scheduled task uses the backend image with a command override, 0.5 vCPU /
 
 | Resource | Role |
 |----------|------|
-| CloudWatch log groups | `/ecs/{backend,frontend,autoprober,insights,parityrun,gptbench,features}`, 14-day retention |
+| CloudWatch log groups | `/ecs/{backend,frontend,autoprober,insights,parityrun,gptbench,features,pricingsync}`, 14-day retention |
 | CloudWatch alarms × 7 | ALB 5xx ratio, ALB latency, backend and frontend running task count, RDS CPU, storage, connections |
 | CloudWatch dashboard `BedrockMonitor-v2` | 4 graph widgets plus an alarm status widget |
 | SNS topic `bedrock-monitor-alarms` | Alarm fan-out |
@@ -200,14 +220,14 @@ Every scheduled task uses the backend image with a command override, 0.5 vCPU /
 | AgentCore | none | AgentCore Memory and IAM policy |
 | AppServices | Network, Data, Cluster, AgentCore | frontend and backend Fargate services, internal ALB, ALB logs |
 | Edge | AppServices | CloudFront, alias certificate, cache policies, CloudFront logs |
-| Scheduler | Network, Data, Cluster, AgentCore | 5 EventBridge schedules and 5 task definitions |
+| Scheduler | Network, Data, Cluster, AgentCore | 6 EventBridge schedules and 6 task definitions |
 | Observability | AppServices, Cluster, Data | Alarms, dashboard, SNS topic |
 
 Reusable constructs live in `cdk/lib/constructs/`: `fargate-service.ts` (service, target group, autoscaling, log group) and `pinned-image.ts` (digest-pinned image URIs from `-c backendImage=` and `-c frontendImage=`).
 
 ## Key Design Decisions
 
-See ADR-001 through ADR-029 in [`docs/decisions/`](./decisions/) (012, 014, 015, and 016 are unused numbers).
+See ADR-001 through ADR-030 in [`docs/decisions/`](./decisions/) (012, 014, 015, and 016 are unused numbers).
 
 | ADR | Decision |
 |-----|----------|
@@ -236,6 +256,7 @@ See ADR-001 through ADR-029 in [`docs/decisions/`](./decisions/) (012, 014, 015,
 | 027 | GPT-6 Astra: inference-profile-only OpenAI model, US CRIS pseudo-region `us`, Mantle in-region us-west-2 only |
 | 028 | Claude Opus 5.5 and GPT-6 Sol, Luna: CP point-release guard `_is_point_release_of`, Sol and Luna Mantle in-region us-east-1 only, agreement-offer pricing |
 | 029 | Dashboard metric grades: per-category absolute thresholds from 48 h p90/p99, TPS graded on the low side only, `lib/metricGrade.ts` as the single source |
+| 030 | Official unit prices synced every 12 hours into a per-`model_id` price history, costs at the price in effect at each probe, 50% guard with admin approval (supersedes the ADR-025 retroactive re-pricing rule) |
 
 ## Operations
 
@@ -252,12 +273,14 @@ See ADR-001 through ADR-029 in [`docs/decisions/`](./decisions/) (012, 014, 015,
 
 ## 시스템 개요
 
-Bedrock LLM Monitor v2는 Amazon Bedrock, Claude Platform on AWS(Anthropic CP), OpenAI GPT on Bedrock(Mantle 인리전과 Global, US 교차 리전 프로파일)에 걸친 활성 55개 채널을 측정합니다. 스케줄된 AutoProber 태스크가 Claude Platform on AWS 9채널을 포함한 모든 채널을 5분마다 프로빙합니다(v2.29.1에서 v2.29.0의 CP 10분 주기를 되돌렸고, `ANTHROPIC_CP_PROBE_INTERVAL_S=600`을 운영 레버로 써서 다시 켤 수 있습니다). 나머지 스케줄 태스크 4개가 AI 인사이트, 12시간 주기 모델 × API surface × 피처 패리티 스윕, 15분 주기 GPT TTFB/TTFT 벤치, 일 1회 Claude API Features 실행 증거 스윕을 만듭니다. 챗봇이 저장된 시계열에 대한 자연어 질문에 답합니다.
+Bedrock LLM Monitor v2는 Amazon Bedrock, Claude Platform on AWS(Anthropic CP), OpenAI GPT on Bedrock(Mantle 인리전과 Global, US 교차 리전 프로파일)에 걸친 활성 55개 채널을 측정합니다. 스케줄된 AutoProber 태스크가 Claude Platform on AWS 9채널을 포함한 모든 채널을 5분마다 프로빙합니다(v2.29.1에서 v2.29.0의 CP 10분 주기를 되돌렸고, `ANTHROPIC_CP_PROBE_INTERVAL_S=600`을 운영 레버로 써서 다시 켤 수 있습니다). 나머지 스케줄 태스크 5개가 AI 인사이트, 12시간 주기 모델 × API surface × 피처 패리티 스윕, 15분 주기 GPT TTFB/TTFT 벤치, 일 1회 Claude API Features 실행 증거 스윕, 12시간 주기 공식 단가 동기화(v2.30.0)를 만듭니다. 챗봇이 저장된 시계열에 대한 자연어 질문에 답합니다.
 
 트래픽은 `llm-monitor.whchoi.net`(기본 이름 `d36s7ml54xwemr.cloudfront.net`도 동작)의 CloudFront로 들어와 VPC Origin을 거쳐 내부 ALB에 도달하고, ECS Fargate 서비스 2개인 `frontend`(Next.js standalone)와 `backend`(FastAPI)로 라우팅됩니다. 모든 데이터는 RDS PostgreSQL 인스턴스 하나에 저장됩니다. 뷰어 구간은 HTTPS입니다. VPC Origin은 현재 VPC 내부에서 HTTP 포트 80으로 ALB에 연결하며, 이는 origin을 `HTTPS_ONLY`로 바꾸기 전까지의 임시 설정입니다(`edge-stack.ts`). ALB는 internal scheme이고 프라이빗 서브넷에 있으며 보안 그룹은 VPC CIDR만 허용합니다.
 
 대시보드 모델 카드는 TTFT, 총 응답시간, TPS 값을 워크로드 카테고리별 임계치로 등급 표시합니다(양호 파랑, 경고 호박, 위험 장미). 등급 판정은 `frontend/src/lib/metricGrade.ts`의 순수 프런트엔드 함수이며 백엔드는 관여하지 않습니다(v2.28.0, ADR-029).
 
+단가의 출처는 backend `price_history` 테이블 하나입니다(v2.30.0, ADR-030). PricingSync 태스크가 12시간마다 공식 출처 3개에서 활성 채널의 Standard 입력, 출력 단가를 읽습니다. Bedrock agreement offer rate card(Bedrock Claude, OpenAI), AWS Price List API(Nova 2.0 Lite), Anthropic `pricing.md`(Claude Platform on AWS)입니다. 입력이나 출력이 50%를 넘게 바뀌면 관리자 승인을 기다립니다. `/api/cost/*`와 `/api/efficiency/score`는 프로브 행마다 그 시각에 유효했던 단가로 비용을 계산하고, `/pricing` 페이지와 CSV, Markdown, JSON 다운로드, 모델 탐색, Comparison Lab은 `/api/pricing`을 읽습니다.
+
 ## 전체 아키텍처
 
 ```mermaid
@@ -275,7 +298,7 @@ flowchart TB
   end
 
   subgraph apilayer[API Layer]
-    be["backend service: FastAPI, 17 routers, port 8000"]
+    be["backend service: FastAPI, 18 routers, port 8000"]
   end
 
   subgraph ingestion[Scheduled Ingestion Layer]
@@ -285,6 +308,7 @@ flowchart TB
     par["ParityRun task: 12 h"]
     gpt["GptBench task: 15 min"]
     feat["FeaturesVerify task: daily 17:30 UTC"]
+    prc["PricingSync task: 12 h"]
   end
 
   subgraph storage[Storage Layer]
@@ -301,6 +325,12 @@ flowchart TB
     ses["Amazon SES us-east-1"]
   end
 
+  subgraph pricesrc[Official Price Sources]
+    offers["Bedrock agreement offers, us-east-1"]
+    plist["AWS Price List API, us-east-1"]
+    adoc["Anthropic pricing.md, platform.claude.com"]
+  end
+
   subgraph obs[Observability Layer]
     cw["CloudWatch Logs, Alarms, Dashboard"]
     sns[SNS alarm topic]
@@ -310,15 +340,17 @@ flowchart TB
   user --> cf --> vpco --> alb
   alb -->|"/*"| fe
   alb -->|"/api/*"| be
-  sched --> ap & ins & par & gpt & feat
+  sched --> ap & ins & par & gpt & feat & prc
   ap & par & feat --> providers
+  prc --> offers & plist & adoc
+  prc -.->|"CP model list"| cp
   gpt --> br & mantle
   ins --> br
   be --> br
   be --> opt
   be --> ses
   be --> mem
-  be & ap & ins & par & gpt & feat --> rds
+  be & ap & ins & par & gpt & feat & prc --> rds
   sec -.->|"secrets at task start"| be
   be & fe & ap --> cw
   cw --> sns
@@ -341,6 +373,13 @@ flowchart LR
   A([Browser]) --> B[CloudFront] --> C[VPC Origin] --> D[Internal ALB] --> E[backend FastAPI] --> F[(RDS PostgreSQL)]
 ```
 
+단가 경로(v2.30.0, ADR-030):
+
+```mermaid
+flowchart LR
+  A([EventBridge Scheduler]) --> B[PricingSync task] --> C["Agreement offers, Price List, Anthropic pricing.md"] --> D[(price_history in RDS)] --> E["backend /api/pricing, /api/cost/*"] --> F["frontend /pricing, /cost"] --> G([Browser])
+```
+
 프로버가 별도 Fargate 태스크에서 돌기 때문에 `/api/auto-probe/status`와 `/api/auto-probe/latest`는 프로세스 내부 상태가 아니라 DB의 최신 `ProbeRun(is_auto=1)` 행을 읽습니다. `/latest`는 모델마다 자기 주기 범위 안의 최신 행을 돌려주고(주기 3회: 기본 주기에서는 모든 채널 15분, `ANTHROPIC_CP_PROBE_INTERVAL_S=600`이면 CP는 30분), `/status`는 `channel_intervals`를 내보내 대시보드가 채널별로 신선도를 판정합니다.
 
 ## 레이어별 컴포넌트
@@ -363,14 +402,14 @@ flowchart LR
 | S3 (ALB logs) | ALB 액세스 로그, 90일 보존 |
 | ECS cluster `bedrock-monitor` | Container Insights 활성 |
 | ECR `bedrock-monitor-backend-v2`, `bedrock-monitor-frontend` | `bedrock-monitor-backend-v2`는 CDK 밖에서 IMMUTABLE 태그로 만든 저장소(ADR-018), CDK가 관리하는 `bedrock-monitor-frontend`(와 옛 `bedrock-monitor-backend`)는 MUTABLE이라 릴리스는 고유 `v<epoch>` 태그와 digest 고정 태스크 정의(`pinned-image.ts`)에 의존 |
-| frontend Fargate service | Next.js standalone 포트 3000, 0.5 vCPU / 1 GB, CPU 오토스케일 1~3, 페이지 `/`, `/models`, `/parity`, `/cost`, `/reliability`, `/efficiency`, `/analysis`, `/gpt-on-aws`, `/claude-features`, `/prompts`, `/chat` |
-| backend Fargate service | FastAPI 포트 8000, 0.5 vCPU / 1 GB, CPU 오토스케일 1~3, 기동 마이그레이션용 헬스체크 유예 300초, `backend/routers/` 라우터 17개 |
+| frontend Fargate service | Next.js standalone 포트 3000, 0.5 vCPU / 1 GB, CPU 오토스케일 1~3, 페이지 `/`, `/models`, `/parity`, `/cost`, `/pricing`, `/reliability`, `/efficiency`, `/analysis`, `/gpt-on-aws`, `/claude-features`, `/prompts`, `/chat` |
+| backend Fargate service | FastAPI 포트 8000, 0.5 vCPU / 1 GB, CPU 오토스케일 1~3, 기동 마이그레이션용 헬스체크 유예 300초, `backend/routers/` 라우터 모듈 18개, `/api/pricing`은 태스크마다 60초 인메모리 캐시 |
 
 ### Storage
 
 | 리소스 | 역할 |
 |--------|------|
-| RDS PostgreSQL 16.8 (t4g.micro) | 20 GB gp3, Single-AZ, 7일 백업, 암호화, `RETENTION_DAYS`(60)를 넘은 원본 `probe_results`는 `probe_results_hourly`로 이관 |
+| RDS PostgreSQL 16.8 (t4g.micro) | 20 GB gp3, Single-AZ, 7일 백업, 암호화, `RETENTION_DAYS`(60)를 넘은 원본 `probe_results`는 `probe_results_hourly`로 이관, v2.30.0부터 `price_history`(`model_id`별 단가와 `effective_from`)와 `price_sync_runs`(PricingSync 런마다 1행) |
 | Secrets Manager `bedrock-monitor/db` | 자동 생성 RDS 자격 증명 |
 | SSM `/bedrock-monitor/jwt-secret-key` | JWT 서명 키 |
 | SSM `/bedrock-monitor/agentcore-memory-id` | AgentCore Memory ID |
@@ -389,6 +428,7 @@ flowchart LR
 | AgentCore Memory `BedrockMonitorChatMemory` | 대화 컨텍스트 30일 보존, IAM 관리형 정책을 backend 태스크 역할에 연결 |
 | Bedrock Agent Runtime OptimizePrompt | `/api/prompts/optimize`, `BEDROCK_OPTIMIZE_REGION`(기본 us-east-1) |
 | Amazon SES (us-east-1) | 가입 승인 메일을 관리자 주소로 발송 |
+| 공식 단가 출처 | Bedrock `ListFoundationModelAgreementOffers`(us-east-1, 파운데이션 모델 18개), AWS Price List `GetProducts`(us-east-1, Nova 2.0 Lite), `https://platform.claude.com/docs/en/about-claude/pricing.md`(Claude Platform on AWS), PricingSync 태스크만 읽음 (ADR-030) |
 
 ### 스케줄 수집
 
@@ -399,15 +439,16 @@ flowchart LR
 | `ParityRunSchedule` | `rate(12 hours)` | `python -m parity_runner --once` | 모델 × surface 6개 × 피처 19개 실행 증거 셀 |
 | `GptBenchSchedule` | `rate(15 minutes)` | `python -m gptbench_runner --once` | GPT 18채널(Mantle 인리전 11 + CRIS 7) × 순차 10회, 호출당 watchdog `GPT_BENCH_CALL_TIMEOUT` 90초, 사이클 데드라인 `GPT_BENCH_DEADLINE` 780초 |
 | `FeaturesVerifySchedule` | `cron(30 17 * * ? *)` Etc/UTC | `python -m features_runner --once` | 39행 × surface 5개 × 모델 5개(Claude Fable 5.1, Fable 5, Opus 5.5, Opus 5, Sonnet 5) = 975셀(프로브 813 + 사전판정 162), 약 9분, 매일 17:30 UTC(02:30 KST) |
+| `PricingSyncSchedule` | `rate(12 hours)` | `python -m pricing_sync_runner --once` | `price_sync_runs` 1행(`completed`, `partial`, `failed`)과 활성 채널마다 변경 없음 관측, 새 `verified` 단가(변화 50% 이하), `pending_review` 행 중 하나, 런 상한 300초, `pg_advisory_lock(917350004)`로 직렬화 (v2.30.0, ADR-030) |
 
-모든 스케줄 태스크는 backend 이미지를 command override로 쓰고 0.5 vCPU / 1 GB이며, 스케줄러 역할의 `ecs:RunTask` 정책은 태스크 정의 family `:*` 와일드카드를 씁니다(ADR-011).
+모든 스케줄 태스크는 backend 이미지를 command override로 쓰고 0.5 vCPU / 1 GB이며, 스케줄러 역할의 `ecs:RunTask` 정책은 태스크 정의 family `:*` 와일드카드를 씁니다(ADR-011). PricingSync는 `bedrock:ListFoundationModelAgreementOffers`와 `pricing:GetProducts`만 허용하는 전용 태스크 역할로 돌며 모델 호출 권한이 없습니다.
 
 ### Network
 
 | 리소스 | 역할 |
 |--------|------|
 | VPC 10.20.0.0/16 (또는 기존 VPC) | 2 AZ, Public, App, Data 서브넷 |
-| NAT gateway × 1 | PrivateLink가 없는 엔드포인트(Claude Platform on AWS, Mantle, us-east-1 OpenAI CRIS)로 가는 App 서브넷 egress |
+| NAT gateway × 1 | PrivateLink가 없는 엔드포인트(Claude Platform on AWS, Mantle, us-east-1 OpenAI CRIS, PricingSync가 쓰는 us-east-1 Bedrock control plane과 Price List API, `platform.claude.com`)로 가는 App 서브넷 egress |
 | Interface VPC endpoints × 9 | ECR API, ECR Docker, CloudWatch Logs, SSM, SSM Messages, Secrets Manager, KMS, Bedrock Runtime, Bedrock AgentCore |
 | Gateway VPC endpoint × 1 | S3 |
 
@@ -415,7 +456,7 @@ flowchart LR
 
 | 리소스 | 역할 |
 |--------|------|
-| CloudWatch log groups | `/ecs/{backend,frontend,autoprober,insights,parityrun,gptbench,features}`, 14일 보존 |
+| CloudWatch log groups | `/ecs/{backend,frontend,autoprober,insights,parityrun,gptbench,features,pricingsync}`, 14일 보존 |
 | CloudWatch alarms × 7 | ALB 5xx 비율, ALB 지연, backend, frontend 실행 태스크 수, RDS CPU, 스토리지, 연결 수 |
 | CloudWatch dashboard `BedrockMonitor-v2` | 그래프 위젯 4개 + 알람 상태 위젯 1개 |
 | SNS topic `bedrock-monitor-alarms` | 알람 fan-out |
@@ -441,14 +482,14 @@ flowchart LR
 | AgentCore | 없음 | AgentCore Memory, IAM 정책 |
 | AppServices | Network, Data, Cluster, AgentCore | frontend, backend Fargate 서비스, 내부 ALB, ALB 로그 |
 | Edge | AppServices | CloudFront, alias 인증서, 캐시 정책, CloudFront 로그 |
-| Scheduler | Network, Data, Cluster, AgentCore | EventBridge 스케줄 5개, 태스크 정의 5개 |
+| Scheduler | Network, Data, Cluster, AgentCore | EventBridge 스케줄 6개, 태스크 정의 6개 |
 | Observability | AppServices, Cluster, Data | 알람, 대시보드, SNS 토픽 |
 
 재사용 construct는 `cdk/lib/constructs/`에 있습니다. `fargate-service.ts`(서비스, 타깃 그룹, 오토스케일, 로그 그룹)와 `pinned-image.ts`(`-c backendImage=`, `-c frontendImage=`로 받은 digest 고정 이미지 URI)입니다.
 
 ## 핵심 설계 결정
 
-[`docs/decisions/`](./decisions/)의 ADR-001~ADR-029를 참조합니다(012, 014, 015, 016은 결번).
+[`docs/decisions/`](./decisions/)의 ADR-001~ADR-030을 참조합니다(012, 014, 015, 016은 결번).
 
 | ADR | 결정 |
 |-----|------|
@@ -477,6 +518,7 @@ flowchart LR
 | 027 | GPT-6 Astra: 추론 프로파일 전용 OpenAI 모델, US CRIS 유사 리전 `us`, Mantle 인리전은 us-west-2만 |
 | 028 | Claude Opus 5.5와 GPT-6 Sol, Luna: CP 점 버전 가드 `_is_point_release_of`, Sol, Luna Mantle 인리전은 us-east-1만, agreement offer 단가 |
 | 029 | 대시보드 지표 등급: 48시간 p90/p99 기반 카테고리별 절대 임계치, TPS는 낮은 쪽만 판정, `lib/metricGrade.ts` 단일 출처 |
+| 030 | 공식 단가 12시간 자동 동기화와 `model_id` 단위 단가 이력, 프로브 시각 기준 단가로 비용 계산, 50% 안전장치와 관리자 승인 (ADR-025의 소급 재계산 규칙 대체) |
 
 ## 운영
 
diff --git a/docs/decisions/ADR-025-openai-global-cris-channels.md b/docs/decisions/ADR-025-openai-global-cris-channels.md
index 81202f0..7f028ee 100644
--- a/docs/decisions/ADR-025-openai-global-cris-channels.md
+++ b/docs/decisions/ADR-025-openai-global-cris-channels.md
@@ -74,3 +74,11 @@ tools/parity는 전부 동적이라 무변경 자동 편입 (parity는 12h 런
 - 1P 재노출 선행 조건(`-1p` 단가 분리)은 그대로다. 다만 방향이 모델마다 다르다: Terra/Luna는 base 키가 1P 정가보다
   10% 높아 과대 산정, Sol은 프로모션 단가가 1P 정가($5/$30)보다 낮아 과소 산정된다. 자세한 기록은 ADR-028 후속(v2.28.1).
 
+## 후속 (v2.30.0, 2026-09-26) — 소급 정책 대체
+
+- 이 ADR의 "비용은 조회 시점 계산이라 소급 재계산됨" 정책은 **ADR-030이 대체했다.** v2.30.0부터 비용은 각 프로브 시각에 유효했던
+  단가로 계산하고, 단가는 `price_history` 테이블에 `model_id` 단위 행으로 두며 PricingSync 태스크가 12시간마다 공식 출처에서 갱신한다.
+- `PRICE_TABLE`, `_normalize_key`, `-global` / `-us` suffix 키, `get_pricing` prefix fallback은 `backend/pricing.py`와 함께 삭제됐다.
+  Global CRIS 단가가 in-region과 다르다는 사실은 그대로이며, 이제 채널마다 별도 단가 행이다.
+- 같은 조사에서 `_normalize_key`가 Claude `us.`와 `global.`을 같은 키로 합쳐 Bedrock Claude US 10채널이 Global 단가(공식 US는
+  Global × 1.1)로 산정되던 오류를 찾았고, v2.30.0 seed로 과거까지 교정했다(ADR-030 Decision 2).
diff --git a/docs/decisions/ADR-028-claude-opus-5-5-and-gpt-6-sol-luna.md b/docs/decisions/ADR-028-claude-opus-5-5-and-gpt-6-sol-luna.md
index 9f05475..cd9cf7d 100644
--- a/docs/decisions/ADR-028-claude-opus-5-5-and-gpt-6-sol-luna.md
+++ b/docs/decisions/ADR-028-claude-opus-5-5-and-gpt-6-sol-luna.md
@@ -196,3 +196,12 @@ US CRIS 3; 휴면 1P 5 포함 총계 51 → 60). reliability/cost/analysis/effic
   "최소 2026-11-21까지" 프로모션이라고 밝히므로 종료 후 재확인이 필요하다. 비용은 조회 시점에 계산되므로 과거 행도
   새 단가로 소급 산정된다(사용자 승인). Terra, Luna는 카드와 저장소가 일치해 변경 없음.
 
+## 후속 (v2.30.0, 2026-09-26)
+
+- **GPT-6 Sol, Luna 모델 카드 재대조 완료**: 두 모델의 AWS 모델 카드가 게시됐고 값이 agreement offer(Sol `offer-pycji3sz5gpcc`,
+  Luna `offer-gmo53nkzc5or6`)와 일치한다. "모델 카드가 게재되면 재대조" 후속은 닫는다.
+- **단가 관리 방식 변경**: v2.30.0부터 단가는 코드 표가 아니라 `price_history`에 있고 PricingSync가 12시간마다 같은 offer API로
+  확인한다. 위 "비용은 조회 시점 계산이라 소급 산정된다"는 문장은 ADR-030이 대체했다(비용은 프로브 시각의 단가로 계산).
+- Opus 5.5 US(`us.anthropic.claude-opus-5-5`)의 공식 단가는 $4.40 / $22(Global × 1.1)다. v2.29.1 코드는 Global과 같은 $4 / $20이었고
+  v2.30.0 seed로 과거까지 교정했다(ADR-030).
+- GPT-5.6 Sol 프로모션의 "최소 2026-11-21까지"는 현재 공식 출처에 없어 `pricing_sources.PRICE_NOTES` 수동 메모로 관리한다.
diff --git a/docs/onboarding.md b/docs/onboarding.md
index d9ff8f6..a5cfa8a 100644
--- a/docs/onboarding.md
+++ b/docs/onboarding.md
@@ -59,7 +59,8 @@ npm run dev
 - **Model Cards**: Catalog coverage, current failures, stale results and unmeasured channels; search/filter/sort and select cards to compare trends. TTFT / total latency / TPS values are graded per workload category — blue normal, amber ▲ warning, rose ◆ critical; thresholds live in `frontend/src/lib/metricGrade.ts` (v2.28.0, ADR-029).
 - **Trend Charts**: Actual elapsed time with explicit gaps for failed or missing measurements. Filter/selection state is preserved in dashboard URLs.
 - **Shared UI**: Public pages render during sign-in checks. Failed reads keep same-query cached results with a warning and retry; a changed filter cannot display an older query's data.
-- **Model Explorer** (`/models`, v2.9.0): per-model cards with channel info, pricing, and copy-paste code examples per API (Converse / InvokeModel / Messages / Responses)
+- **Model Explorer** (`/models`, v2.9.0): per-model cards with channel info, unit prices from `/api/pricing`, and copy-paste code examples per API (Converse / InvokeModel / Messages / Responses)
+- **Unit Prices** (`/pricing`, v2.30.0): Standard input/output price per model family and channel with source footnotes and CSV / Markdown / JSON download. The PricingSync Fargate task refreshes prices from official sources every 12 hours into `price_history`; costs use the price in effect at each probe's time, and a change above 50% waits for admin approval — see ADR-030
 - **Parity Run** (`/parity`, v2.11.0): Fargate sweep every 12 hours probing model × API surface × feature with execution evidence — see `backend/parity/CLAUDE.md` and ADR-021
 - **Comparison Lab**: one prompt → N models in parallel via `/api/compare/run` (SSE, auth)
 
@@ -74,6 +75,7 @@ npm run dev
 | View backend logs (prod) | `aws logs tail /ecs/backend --follow` |
 | View autoprober logs | `aws logs tail /ecs/autoprober --since 1h` |
 | View parity run logs | `aws logs tail /ecs/parityrun --since 1d` |
+| View price sync logs | `aws logs tail /ecs/pricingsync --since 13h` |
 | Trigger probe (local, JWT) | `curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/auto-probe/trigger` |
 | Access DB (local) | `docker exec -it monitoring-postgres psql -U postgres -d monitoring` |
 
diff --git a/docs/runbooks/deploy.md b/docs/runbooks/deploy.md
index dd61748..fbc4d0d 100644
--- a/docs/runbooks/deploy.md
+++ b/docs/runbooks/deploy.md
@@ -103,12 +103,13 @@ BE_ARN=$(aws ecs register-task-definition --region $REGION \
 aws ecs update-service --cluster bedrock-monitor --service backend \
   --task-definition "$BE_ARN" --region $REGION
 
-# 스케줄 태스크 5개 모두 동일하게 (각각 별도 Fargate Task — backend image 공용). 하나라도 빠지면 그 태스크만 옛 이미지로 돈다.
+# 스케줄 태스크 6개 모두 동일하게 (각각 별도 Fargate Task — backend image 공용). 하나라도 빠지면 그 태스크만 옛 이미지로 돈다.
 # AutoProber:     family BedrockMonitorSchedulerAutoProberTaskDef*,     schedule rate(5 minutes),  CLI auto_prober_runner --once (env ANTHROPIC_CP_PROBE_INTERVAL_S=300 = CP도 매 사이클 — v2.29.1, 600이면 CP만 두 사이클에 한 번)
 # Insights:       family BedrockMonitorSchedulerInsightsTaskDef*,       schedule rate(5 minutes),  CLI insights_runner --window 6h
 # ParityRun:      family BedrockMonitorSchedulerParityRunTaskDef*,      schedule rate(12 hours),   CLI parity_runner --once (v2.11.0)
 # GptBench:       family BedrockMonitorSchedulerGptBenchTaskDef*,       schedule rate(15 minutes), CLI gptbench_runner --once (v2.18.0)
 # FeaturesVerify: family BedrockMonitorSchedulerFeaturesVerifyTaskDef*, schedule cron(30 17 * * ? *) Etc/UTC, CLI features_runner --once (v2.23.0, 고정 cron v2.29.0)
+# PricingSync:    family BedrockMonitorSchedulerPricingSyncTaskDef*,    schedule rate(12 hours),   CLI pricing_sync_runner --once (v2.30.0, 전용 task role — 최초 배포는 CDK로만)
 # 정확한 family 이름: aws ecs list-task-definition-families --family-prefix BedrockMonitorScheduler --status ACTIVE --region $REGION
 AP_FAM=$(aws ecs list-task-definition-families --family-prefix BedrockMonitorSchedulerAutoProberTaskDef \
   --status ACTIVE --region $REGION --query 'families[0]' --output text)
@@ -117,7 +118,7 @@ aws ecs describe-task-definition --task-definition "$AP_FAM" \
 # ... (위와 동일하게 image 교체 + register) ...
 AP_ARN=...
 # 스케줄 이름 — AutoProber/Insights는 Scheduler 스택 output(AutoProberScheduleName / InsightsScheduleName)에 있다.
-# 5개 전부: aws scheduler list-schedules --name-prefix BedrockMonitor-Scheduler- --region $REGION --query 'Schedules[].Name'
+# 6개 전부: aws scheduler list-schedules --name-prefix BedrockMonitor-Scheduler- --region $REGION --query 'Schedules[].Name'
 AP_SCHED=$(aws cloudformation describe-stacks --stack-name BedrockMonitor-Scheduler --region $REGION \
   --query "Stacks[0].Outputs[?OutputKey=='AutoProberScheduleName'].OutputValue" --output text)
 aws scheduler get-schedule --name "$AP_SCHED" --region $REGION > /tmp/sched.json
@@ -411,6 +412,66 @@ curl -s "https://$CF_DOMAIN/api/auto-probe/status" | jq '{interval_seconds, chan
   `ANTHROPIC_CP_PROBE_INTERVAL_S=600`을 AutoProber task와 backend 서비스에 넣고 같은 경로로 배포한 뒤 §5-2의 2~4번으로 확인한다.
 - FeaturesVerify는 바뀌지 않는다(`cron(30 17 * * ? *)` Etc/UTC).
 
+### 5-4. v2.30.0 배포 경로와 확인 (비용 단가 메뉴, PricingSync)
+
+**배포 경로**: CDK 변경이 있다. Scheduler 스택에 `PricingSyncTaskRole`(`bedrock:ListFoundationModelAgreementOffers`,
+`pricing:GetProducts`만), `PricingSyncTaskDef`(`python -m pricing_sync_runner --once`, 로그 그룹 `/ecs/pricingsync`),
+`PricingSyncSchedule`(`rate(12 hours)`), Scheduler 역할의 RunTask family `:*`와 PassRole 추가, output `PricingSyncScheduleName`이
+생긴다. 이미지-only 경로(§2-1) 금지 — 새 태스크 정의와 스케줄은 CDK로만 생긴다. **digest 고정 CDK로
+`BedrockMonitor-AppServices` + `BedrockMonitor-Scheduler`**를 backend, frontend 이미지 모두로 배포한다(§3 경고). 신규 env는 없다.
+DB는 새 테이블 2개(`price_history`, `price_sync_runs`)를 backend 기동 시 `create_all`이 만들고, 같은 기동에서 seed(활성 55채널,
+`effective_from` 1970-01-01)를 넣는다. 그래서 배포 직후부터 `/cost`의 Bedrock Claude US 10채널과 Nova 2.0 Lite 비용이 과거까지
+교정된 값으로 보인다.
+
+```bash
+REGION=ap-northeast-2
+CF_DOMAIN=d36s7ml54xwemr.cloudfront.net
+# 1. 스케줄 — rate(12 hours), PricingSync task def를 가리킨다
+SCHED=$(aws cloudformation describe-stacks --stack-name BedrockMonitor-Scheduler --region $REGION \
+  --query "Stacks[0].Outputs[?OutputKey=='PricingSyncScheduleName'].OutputValue" --output text)
+aws scheduler get-schedule --name "$SCHED" --region $REGION \
+  --query '{e:ScheduleExpression,td:Target.EcsParameters.TaskDefinitionArn}'
+# 기댓값: {"e": "rate(12 hours)", "td": "arn:aws:ecs:ap-northeast-2:…:task-definition/BedrockMonitorSchedulerPricingSyncTaskDef…:N"}
+
+# 2. 첫 스케줄 런(배포 뒤 최대 12시간)을 기다리지 않고 1회 수동 실행 — 네트워크 설정은 스케줄 타깃에서 복사
+FAM=$(aws ecs list-task-definition-families --family-prefix BedrockMonitorSchedulerPricingSyncTaskDef --status ACTIVE \
+  --region $REGION --query 'families[0]' --output text)
+NETCFG=$(aws scheduler get-schedule --name "$SCHED" --region $REGION \
+  --query 'Target.EcsParameters.NetworkConfiguration.awsvpcConfiguration' --output json \
+  | jq -c '{awsvpcConfiguration: {subnets: .Subnets, securityGroups: .SecurityGroups, assignPublicIp: .AssignPublicIp}}')
+aws ecs run-task --cluster bedrock-monitor --task-definition "$FAM" --launch-type FARGATE --region $REGION \
+  --network-configuration "$NETCFG" --query 'tasks[0].taskArn' --output text
+# 약 1분 뒤 로그 (런 요약 한 줄: run_id, status, 채널별 결과 수, 오류 수)
+aws logs tail /ecs/pricingsync --since 15m --region $REGION
+
+# 3. 그 런이 completed이고 55채널이 verified인지
+curl -s "https://$CF_DOMAIN/api/pricing" | jq '{last_sync, pending_review, families: (.families | length),
+  models: (.models | length), references: (.references | length),
+  verification: ([.models[] | .verification] | group_by(.) | map({(.[0]): length}) | add)}'
+# 기댓값: last_sync.status "completed", pending_review 0, families 19, models 55, verification {"verified": 55},
+#   references 약 30(오퍼 18, Price List 1~2, Anthropic 1, 공식 페이지 9, 수동 메모 1)
+
+# 4. 교정 11채널 — 비용이 seed 단가와 맞는지 (첫 동기화가 값을 바꾸지 않았으면 과거 전체가 이 단가다)
+curl -s "https://$CF_DOMAIN/api/cost/summary?window=24h" | jq '[.rows[]
+  | select(.model_id == "us.amazon.nova-2-lite-v1:0" or .model_id == "us.anthropic.claude-opus-5-5" or .model_id == "global.anthropic.claude-opus-5-5")
+  | {model_id, cost_usd, expected: ((.input_tokens * (if (.model_id | startswith("us.amazon")) then 0.33 elif (.model_id | startswith("us.")) then 4.4 else 4 end)
+      + .output_tokens * (if (.model_id | startswith("us.amazon")) then 2.75 elif (.model_id | startswith("us.")) then 22 else 20 end)) / 1000000)}]'
+# 기댓값: 행마다 cost_usd ≈ expected (부동소수 반올림 차이만). US Opus 5.5는 Global의 1.1배 단가다.
+
+# 5. 다운로드 3형식 — 첨부 파일 이름과 면책 문구
+for f in csv md json; do
+  curl -s -D - -o /dev/null "https://$CF_DOMAIN/api/pricing/export?format=$f&lang=ko" | grep -i '^content-disposition'
+done
+curl -s "https://$CF_DOMAIN/api/pricing/export?format=csv&lang=ko" | head -2
+# 기댓값: attachment; filename="llm-monitor-unit-prices-YYYY-MM-DD.csv" (md, json 동일 형식), CSV 첫 줄은 BOM + "# 이 가격표는 공개 자료를 …"
+```
+
+- 화면 확인: `/pricing`(헤더 메뉴 "비용" 바로 뒤 "비용 단가")에 면책 상자, 마지막 자동 확인 시각, 다운로드 버튼 3개, 제공사별 표,
+  각주 번호, 참고 자료 목록이 보인다. 첫 런 전에는 모든 셀에 "자동 확인 안 됨"(초기값) 배지가 붙는 것이 정상이다.
+- `pending_review`가 0보다 크면 `troubleshooting.md`의 "검토 대기 단가 승인"을 따른다. 3번에서 `verified`가 55보다 적으면
+  같은 문서의 "비용 단가 동기화 실패"로 원인을 찾는다.
+- 모델 탐색(`/models`) 카드 단가와 `/cost` 방법론 문단의 `/pricing` 링크도 확인한다.
+
 ## 6. 후속 배포 (코드만 변경 시)
 
 ⚠️ **신규 env가 추가된 릴리스(예: v2.20.0 `OPENAI_GLOBAL_BASE_URL`, v2.25.0 `OPENAI_US_BASE_URL` + `BEDROCK_OPENAI_GPT_6_ASTRA_MODEL_ID`)에는 이미지-only
@@ -418,7 +479,7 @@ curl -s "https://$CF_DOMAIN/api/auto-probe/status" | jq '{interval_seconds, chan
 그대로 복사돼 신규 env가 누락되고, prober는 base_url env가 없으면 해당 채널을 **조용히
 skip**한다 (에러 없음, 해당 채널만 카탈로그에서 사라짐). 반드시 CDK 배포
 (`BedrockMonitor-AppServices` + `BedrockMonitor-Scheduler`, digest 고정 `-c backendImage/-c frontendImage`)로
-backend 서비스와 스케줄 태스크(autoprober/insights/parityrun/gptbench/featuresverify) **양쪽** task def를 갱신할 것.
+backend 서비스와 스케줄 태스크(autoprober/insights/parityrun/gptbench/featuresverify/pricingsync) **양쪽** task def를 갱신할 것.
 
 ```bash
 make build   # 로컬 확인 전용 — :dev 태그, --platform linux/arm64와 RUM build arg가 없어 운영 push 금지
diff --git a/docs/runbooks/rollback.md b/docs/runbooks/rollback.md
index 77a7add..1bda81e 100644
--- a/docs/runbooks/rollback.md
+++ b/docs/runbooks/rollback.md
@@ -67,7 +67,7 @@ aws ecs update-service --cluster bedrock-monitor --service backend --region $REG
 
 이 경로는 CDK 상태와 어긋나므로 다음 CDK 배포가 context 이미지로 덮어쓴다. 스케줄 태스크만 되돌려야 하면
 [deploy.md §2-1](./deploy.md)의 절차(image 교체 revision 등록 → `get-schedule` → `TaskDefinitionArn` 교체 → `update-schedule`)를
-직전 image로 5개 스케줄에 적용한다.
+직전 image로 6개 스케줄에 적용한다(v2.30.0 PricingSync 포함).
 
 **ECS circuit breaker**(`circuitBreaker: { rollback: true }`)는 새 task가 기동이나 헬스체크에 계속 실패할 때만 직전 안정
 배포로 자동 복귀한다. task가 정상 기동하는 코드 회귀(기능 버그, 잘못된 값)는 위 절차로 직접 되돌린다.
diff --git a/docs/runbooks/troubleshooting.md b/docs/runbooks/troubleshooting.md
index ca9dd43..8b3c283 100644
--- a/docs/runbooks/troubleshooting.md
+++ b/docs/runbooks/troubleshooting.md
@@ -2,6 +2,131 @@
 
 증상별 확인과 조치. 배포 절차는 [deploy.md](deploy.md), 되돌리기는 [rollback.md](rollback.md)를 본다.
 
+## 비용 단가 동기화 실패 — "자동 확인 안 됨" 배지 (v2.30.0, ADR-030)
+
+**배경**: PricingSync 태스크(`python -m pricing_sync_runner --once`, `rate(12 hours)`)가 공식 출처 3개에서 활성 55채널의 단가를
+읽는다. Bedrock agreement offer rate card(Bedrock Claude 20 + OpenAI 25, FM 18개를 순차 호출), AWS Price List API(Nova 2.0 Lite),
+Anthropic `https://platform.claude.com/docs/en/about-claude/pricing.md`(Claude Platform on AWS 9)다. 공식 값을 구하지 못한 채널은
+기존 단가를 그대로 두고(`skipped:<reason>`) 화면에 "자동 확인 안 됨"으로 드러난다. 비용 계산은 멈추지 않는다 — 마지막 유효 단가를
+계속 쓴다.
+
+### 증상
+
+- `/pricing` 셀에 "자동 확인 안 됨" 배지(툴팁: 마지막 확인일, 또는 "초기값"). `verification`이 `stale`(마지막 확인이 가장 최근에 끝난
+  런보다 이전) 또는 `seed_only`(한 번도 확인되지 않음)다.
+- 한 출처만 실패하면 그 출처의 채널만 `stale`이 된다. 예: Anthropic 문서가 실패한 `partial` 런 뒤에는 Claude Platform on AWS 열 9셀만
+  배지가 붙는다.
+- "마지막 자동 확인" 시각이 12시간보다 오래됐으면 태스크가 돌지 않은 것이다.
+
+### 확인
+
+```bash
+REGION=ap-northeast-2
+CF_DOMAIN=d36s7ml54xwemr.cloudfront.net
+# 1. 마지막 런과 확인되지 않은 셀
+curl -s "https://$CF_DOMAIN/api/pricing" | jq '{last_sync, pending_review, not_verified: [.families[] | .family as $f
+  | ([(.tiers.cp, .tiers.global, .tiers.us) // empty] + .tiers.in_region)[]
+  | select(.verification != "verified") | {family: $f, model_ids, verification, observed_at, pending}]}'
+
+# 2. 최근 런 로그 (런 요약 한 줄 = 상태, 채널별 결과 수 — unchanged, changed, pending, no_baseline, rejected, skipped:<reason> — 와 오류 수.
+#    출처 호출이 재시도되면 "pricing sync: … retry n/3" 경고가 먼저 찍힌다)
+aws logs tail /ecs/pricingsync --since 13h --region $REGION
+
+# 3. 최근 태스크 종료 사유 — 컨테이너 이름은 pricingsynctaskdef (containers[0]은 GuardDuty 사이드카일 수 있다)
+FAM=$(aws ecs list-task-definition-families --family-prefix BedrockMonitorSchedulerPricingSyncTaskDef --status ACTIVE \
+  --region $REGION --query 'families[0]' --output text)
+for T in $(aws ecs list-tasks --cluster bedrock-monitor --family "$FAM" --desired-status STOPPED \
+    --region $REGION --query 'taskArns[]' --output text); do
+  aws ecs describe-tasks --cluster bedrock-monitor --tasks "$T" --region $REGION \
+    --query "tasks[].[createdAt,stoppedReason,containers[?name=='pricingsynctaskdef'].exitCode|[0]]" --output text
+done
+```
+
+| 원인 | 표지 | 조치 |
+|------|------|------|
+| 스케줄이 태스크를 실행하지 못함 | `last_sync.started_at`이 12시간보다 오래됨, `/ecs/pricingsync`에 새 로그 없음 | Scheduler 역할의 `RunTaskFamilyWildcard`에 PricingSync family `:*`, `PassTaskRoles`에 `PricingSyncTaskRole`이 있는지 확인(ADR-011). 없으면 digest 고정 CDK로 Scheduler 스택을 다시 배포 |
+| 출처 권한 거부 | 로그에 `AccessDeniedException` (`ListFoundationModelAgreementOffers` 또는 `GetProducts`) | `PricingSyncTaskRole` 인라인 정책의 두 액션 확인. 다른 권한은 필요 없다(모델 호출 권한은 의도적으로 없음) |
+| Anthropic 문서 형식 변경 | CP 9셀만 `stale`, 로그에 파싱 실패(표나 헤더 "Model", "Base input tokens", "Output tokens"를 찾지 못함) | 문서를 열어 표 구조를 확인하고 `backend/pricing_parsers.py` `parse_anthropic_pricing_md`와 fixture를 고친다. 모델명이 바뀌었으면 `pricing_sources.ANTHROPIC_DOC_NAMES`도 고친다 |
+| 오퍼 형식 변경 | 특정 모델 채널만 `skipped:<reason>`(오퍼 수 ≠ 1, 필수 차원 없음) | `aws bedrock list-foundation-model-agreement-offers --model-id <FM id> --offer-type PUBLIC --region us-east-1 --query 'offers[].termDetails.usageBasedPricingTerm.rateCard[].[dimension, price, unit]' --output table`로 차원 이름을 보고 `pricing_parsers.DIMENSION_RE`와 선택 순서를 고친다(출력에 `offerToken`과 `legalTerm.url`이 나오지 않도록 `--query`를 유지한다) |
+| Price List 단위 변경 | Nova 1셀만 `stale` | `unit`이 `1K tokens`가 아니면 파서가 변경 없음으로 둔다. 새 단위를 확인하고 `parse_pricelist`를 고친다 |
+| 5분 상한 초과 | 런 `partial`, 채널 결과 `skipped:deadline` | 대개 출처 응답 지연이다. 다음 런에서 회복하는지 본다. 반복되면 로그의 재시도 경고(`retry n/3`)로 느린 출처를 찾는다 |
+| 다른 런이 실행 중 | 로그에 잠금을 못 잡아 종료했다는 한 줄(`lock 917350004 held by another sync`), 새 런 행 없음, exit code 1 | 정상이다(`pg_advisory_lock(917350004)`로 수동 실행과 스케줄 실행을 직렬화). 앞 런이 끝난 뒤 다시 실행한다 |
+| CP 디스커버리 실패 | CP 9셀만 `stale`, 런 `partial` | Claude Platform on AWS `/v1/models` 호출이 실패한 것이다(키, workspace, 조직 상태). 표는 최근 30일에 관측된 CP model_id로 계속 채워진다 |
+
+### 조치
+
+- 원인을 고친 뒤 `deploy.md` §5-4의 2번(수동 `run-task`)으로 한 번 더 돌리고 1번으로 `verified`가 돌아왔는지 본다.
+- DB를 직접 고치지 않는다. 단가를 바꿔야 하면 동기화가 새 값을 관측하게 하거나, 검토 대기 행을 아래 절차로 승인한다.
+- 동기화가 실패해도 비용 화면은 마지막 유효 단가로 계속 계산된다. 공식 값이 실제로 바뀌었는데 동기화가 못 읽는 동안에는 그 차이가
+  비용에 반영되지 않는다.
+
+## 검토 대기 단가 승인 — "검토 대기" 배지 (v2.30.0, ADR-030)
+
+**배경**: 동기화가 관측한 새 공식 값이 현재 유효 단가보다 입력이나 출력 어느 쪽이든 50%를 넘게 다르면(정확히 50%는 자동 적용)
+자동으로 적용하지 않고 `pending_review` 행으로 남긴다. 단위 오류(1000배)나 파서 오류가 비용에 그대로 들어가는 것을 막는 안전장치다.
+seed에도 없는 새 model_id(`no_baseline`)도 같은 대기열에 들어간다. 승인 전까지 비용은 기존 단가로 계산된다.
+
+### 확인
+
+```bash
+CF_DOMAIN=d36s7ml54xwemr.cloudfront.net
+curl -s "https://$CF_DOMAIN/api/pricing" | jq '.pending_review'
+TOKEN=$(curl -sX POST "https://$CF_DOMAIN/api/auth/login" -H 'Content-Type: application/json' \
+  -d '{"username":"admin","password":"<SEED_ADMIN_PASSWORD>"}' | jq -r .access_token)
+# 행마다 현재 유효 값, 새 값, 입력과 출력 변화율, 출처, 사유(changed 또는 no_baseline)
+curl -s "https://$CF_DOMAIN/api/admin/pricing/pending" -H "Authorization: Bearer $TOKEN" | jq .
+```
+
+### 판단과 조치
+
+1. 새 값을 공식 페이지에서 직접 확인한다. Bedrock 채널은 `/pricing` 참고 자료의 모델 카드나 Amazon Bedrock 요금 페이지, Claude
+   Platform on AWS는 Anthropic 요금 문서, Nova는 Amazon Bedrock 요금 페이지다.
+2. 공식 값이 맞으면 승인한다. 승인한 단가는 그 값을 처음 관측한 런의 시작 시각부터 적용되고, `no_baseline`이면 과거 전체에 적용된다.
+   응답의 `warnings`는 그보다 늦게 시작한 verified 단가가 이미 있다는 뜻이다 — 그 구간은 늦은 단가가 계속 우선한다.
+
+   ```bash
+   curl -s -X POST "https://$CF_DOMAIN/api/admin/pricing/pending/<id>/approve" -H "Authorization: Bearer $TOKEN" | jq .
+   ```
+
+3. 오류 값이면 거부한다. 거부한 값은 공식 값이 다시 바뀔 때까지 대기열에 올라오지 않는다. 파서 오류가 원인이면 위 "비용 단가 동기화
+   실패"의 표대로 코드를 고친다.
+
+   ```bash
+   curl -s -X POST "https://$CF_DOMAIN/api/admin/pricing/pending/<id>/reject" -H "Authorization: Bearer $TOKEN" | jq .
+   ```
+
+- 승인이나 거부를 처리한 backend 태스크는 `/api/pricing` 캐시를 바로 비우지만, 다른 backend 태스크(오토스케일 1~3개)는 최대 60초
+  동안 이전 표를 줄 수 있다. 60초 뒤 다시 조회해서 확인한다.
+- `401`은 토큰 없음이나 만료, `403`은 admin이 아닌 계정이다.
+
+## GPT-5.6 Sol 프로모션 종료 확인 — 2026-11-21 이후 (v2.30.0)
+
+**배경**: GPT-5.6 Sol 단가 In-Region, Geo $4.40 / $22, Global $4 / $20은 프로모션 단가다(v2.28.1). 2026-09-23 AWS 모델 카드에는 "최소
+2026-11-21까지"가 있었지만 지금 공식 출처 어디에도 종료일이 없어서, 이 정보는 `pricing_sources.PRICE_NOTES` 수동 메모로만
+관리한다. `/pricing`의 Sol 셀에는 "프로모션(최소 2026-11-21까지, 수동 메모)" 배지가 붙고, 날짜가 지나면 "프로모션 종료 여부 확인
+필요"로 바뀐다.
+
+### 확인
+
+```bash
+CF_DOMAIN=d36s7ml54xwemr.cloudfront.net
+curl -s "https://$CF_DOMAIN/api/pricing" | jq '[.families[] | select(.family_key == "gpt-5.6-sol")
+  | {global: (.tiers.global | {input, output, verification, pending}),
+     in_region: [.tiers.in_region[] | {regions, input, output, verification, pending}], notes}]'
+# 공식 오퍼 값 직접 조회 (offerToken, legalTerm.url은 출력하지 않는다)
+aws bedrock list-foundation-model-agreement-offers --model-id openai.gpt-5.6-sol --offer-type PUBLIC --region us-east-1 \
+  --query "offers[].termDetails.usageBasedPricingTerm.rateCard[?dimension=='input_tokens_standard' || dimension=='output_tokens_standard' || dimension=='input_tokens_global_standard' || dimension=='output_tokens_global_standard'][].[dimension, price]" \
+  --output table
+```
+
+### 해석과 조치
+
+- 오퍼가 여전히 4.4 / 22, 4 / 20이면 프로모션이 계속되는 것이다. 모델 카드에서 새 종료일을 확인하고, 있으면
+  `pricing_sources.PRICE_NOTES`의 `min_until`을 고쳐 다음 릴리스로 배포한다.
+- 프로모션이 끝나 이전 단가(In-Region, Geo $5.50 / $33, Global $5 / $30)로 돌아가면 입력 +25%, 출력 +50%라 경계 포함 규칙으로 **자동
+  적용**된다(`verified`, 관측한 런의 시작 시각부터). 동기화가 `prior_price`와 같은 값을 관측하면 수동 메모는 응답에서 빠진다.
+- 이전 단가가 아닌 다른 값으로 바뀌어 50%를 넘으면 검토 대기로 간다. 위 "검토 대기 단가 승인"을 따른다.
+
 ## Claude Platform on AWS 채널 전부 429 — 월간 사용량 상한 (2026-09-23, v2.29.0에서 재시도 제거)
 
 **배경**: 2026-09-23 19:52 UTC부터 CP on AWS 호출이 전부 429로 거부됐다. 조직이 API 등급(tier)에 따라 정해진 월간
diff --git a/frontend/package-lock.json b/frontend/package-lock.json
index 3d9fa03..f8dc07d 100644
--- a/frontend/package-lock.json
+++ b/frontend/package-lock.json
@@ -1,12 +1,12 @@
 {
   "name": "bedrock-monitor",
-  "version": "2.29.1",
+  "version": "2.30.0",
   "lockfileVersion": 3,
   "requires": true,
   "packages": {
     "": {
       "name": "bedrock-monitor",
-      "version": "2.29.1",
+      "version": "2.30.0",
       "dependencies": {
         "next": "16.3.5",
         "react": "^18.3.0",
diff --git a/frontend/package.json b/frontend/package.json
index 4ac16ad..c76eb53 100644
--- a/frontend/package.json
+++ b/frontend/package.json
@@ -1,6 +1,6 @@
 {
   "name": "bedrock-monitor",
-  "version": "2.29.1",
+  "version": "2.30.0",
   "private": true,
   "scripts": {
     "dev": "next dev -p 3000",
diff --git a/frontend/src/app/CLAUDE.md b/frontend/src/app/CLAUDE.md
index db5f4b6..54f0ade 100644
--- a/frontend/src/app/CLAUDE.md
+++ b/frontend/src/app/CLAUDE.md
@@ -12,9 +12,9 @@ from `src/components/` in `AppShell` (header, page title, `FloatingChat`).
 - `page.tsx` — `/` dashboard (`AutoDashboard`); `?view=manual` switches to the manual probe view (`useProbeStream`, results/charts/compare tabs, history). `useSearchParams` is read inside `<Suspense>`
 - `chat/page.tsx` — `/chat`, the popup-window target of `FloatingChat` (Firefox/Safari). Renders `ChatPanel variant="popup"` without `AppShell` (no header, no floating button); the auth token is shared through same-origin `localStorage`
 - `prompts/page.tsx` — login gate via `useAuth()`, then `PromptsPanel`
-- `models/`, `parity/`, `gpt-on-aws/`, `claude-features/`, `cost/`, `reliability/`, `efficiency/`, `analysis/` — one-line pages: `<AppShell navKey="…"><Panel /></AppShell>`
+- `models/`, `parity/`, `gpt-on-aws/`, `claude-features/`, `cost/`, `pricing/` (v2.30.0, `PricingPanel`), `reliability/`, `efficiency/`, `analysis/` — one-line pages: `<AppShell navKey="…"><Panel /></AppShell>`
 
 ## Rules
 - Every route page except `/chat` exports `dynamic = "force-dynamic"` so HTML is never statically cached (stale buildId chunk URLs caused 404 / blank screens after deploys). `src/proxy.ts` also sets `Cache-Control: no-store` on HTML and its matcher excludes `api`, `_next/static`, `icons/`, `icon.png`, `apple-icon.png`, `manifest.webmanifest` — keep new PWA assets in that exclusion
-- `navKey` must match a `key` in `AppHeader.tsx` `useNavItems` (`dashboard`, `manual`, `models`, `parity`, `gptbench`, `features`, …); the active item's label becomes the page title via `usePageTitle`, so an unknown key leaves the title as plain "LLM Monitor"
+- `navKey` must match a `key` in `AppHeader.tsx` `useNavItems` (`dashboard`, `manual`, `models`, `parity`, `gptbench`, `features`, `pricing`, …); the active item's label becomes the page title via `usePageTitle`, so an unknown key leaves the title as plain "LLM Monitor"
 - A new page = folder + `page.tsx` wrapping a component + a `useNavItems` entry (labels there are inline `L(en, ko)`, not `i18n.ts`)
diff --git a/frontend/src/components/CLAUDE.md b/frontend/src/components/CLAUDE.md
index a5b8f63..d8cef76 100644
--- a/frontend/src/components/CLAUDE.md
+++ b/frontend/src/components/CLAUDE.md
@@ -5,7 +5,7 @@ React UI components for the monitoring dashboard (monitoring panels, shared UI p
 
 ## Key Components
 - `RumProvider.tsx` — RUM(Real User Monitoring, v2.16.5): 자체 호스팅 `public/rum-sdk.min.js`를 next/script로 로드, appName=llm-monitor. `NEXT_PUBLIC_RUM_ENDPOINT/_API_KEY`는 **빌드 타임** 인라인 — 미설정 빌드는 수집 비활성
-- `AppHeader.tsx` — 공용 헤더 (v2.16.0): NavItem 데이터 기반 — 데스크톱(md+) 별도 가로 내비 행 / 모바일 햄버거 드롭다운, 페이지별 `actions` 슬롯. 로그인 필요 메뉴(수동 프로브·프롬프트)는 항목 순서상 맨 뒤 (v2.16.1)
+- `AppHeader.tsx` — 공용 헤더 (v2.16.0): NavItem 데이터 기반 — 데스크톱(md+) 별도 가로 내비 행 / 모바일 햄버거 드롭다운, 페이지별 `actions` 슬롯. 로그인 필요 메뉴(수동 프로브·프롬프트)는 항목 순서상 맨 뒤 (v2.16.1). "비용 단가"(`/pricing`, v2.30.0)는 "비용" 바로 뒤
 - `AutoDashboard.tsx` — Main dashboard: monitoring overview, catalog coverage, scoped 12h failures, DB-sourced collection status, model search/health/sort filters, and shareable trend selection
 - `ModelStatusGrid.tsx` — family-grouped cards by default; flat attention/TTFT sorting; explicit freshness, missing results, metrics and expandable errors. **Metric value grading (v2.28.0, ADR-029)**: TTFT/total latency/TPS value text is graded per workload category by `lib/metricGrade.ts` (single source — threshold table, `roundForDisplay` so the grade matches the shown number, `GRADE_TEXT_CLASS`, `GRADE_MARKER` ▲/◆ — normal is `""`, so the legend shows normal as a plain color swatch); each value has `data-grade` + `title` tooltip, warning/critical values get an `sr-only` description via `aria-describedby`, and `MetricGradeLegend` (`<details>`, visible "지표 등급:" label) above the grid expands into the full threshold table. Value, unit and marker are separate flex items (`flex-wrap`) so a narrow 320px column wraps before the marker instead of overflowing into the next value. Change thresholds only in `metricGrade.ts`.
 - `GptOnAwsPanel.tsx` — GPT on AWS bench (v2.18.0): 18 channels since v2.28.0 (Mantle in-region 11 + CRIS 7). Scorecards grouped by generation (`FAMILY_GROUPS` GPT 6 / GPT 5.x, unknown families go to an "Other" column), trend lines color = region × dash = family (`FAMILY_DASH`, 6 distinct patterns, 40px legend swatch); `regionOf`, `familyOf` (anchored regex — "GPT 5.6 Sol" never reads as "6 Sol", unknown → ""), `groupCardsByFamily`, `legendItemsBelowFold` (phone-only "+N more, scroll the legend" cue under each trend legend, `sm:hidden`, v2.28.0) are named exports tested by vitest (`frontend/vitest.config.ts`). New bench families need `FAMILY_DASH` + `FAMILY_GROUPS` here and `fam_rank` in `backend/routers/gptbench.py`.
@@ -14,11 +14,12 @@ React UI components for the monitoring dashboard (monitoring panels, shared UI p
 - `ModelSelector.tsx` — multi-select model chips (`selectedModels: Set<string>`)
 - `ProbeConfigPanel.tsx` + `StreamingView.tsx` — manual probe config + live SSE token stream
 - `ComparisonView.tsx` — 수동 프로브(`/?view=manual`)의 "비교 분석" 탭: 해당 프로브 결과 비교
-- `ComparePanel.tsx` — Comparison Lab UI (`compareStream` → `/api/compare/run`, N-model parallel invoke); currently not mounted by any page
-- `CostDashboardPanel.tsx`, `ReliabilityPanel.tsx`, `EfficiencyPanel.tsx`, `AnalysisPanel.tsx` — per-page analytical panels
+- `ComparePanel.tsx` — Comparison Lab UI (`compareStream` → `/api/compare/run`, N-model parallel invoke); cost per result from `/api/pricing` `models` via `lib/pricingTable.ts` `costFromPrices` (null → "—", left out of the cheapest highlight, v2.30.0); currently not mounted by any page
+- `CostDashboardPanel.tsx`, `ReliabilityPanel.tsx`, `EfficiencyPanel.tsx`, `AnalysisPanel.tsx` — per-page analytical panels (the cost methodology text says prices are refreshed from official sources every 12 hours and applied at each probe's time, with a link to `/pricing`, v2.30.0)
+- `PricingPanel.tsx` — Unit Prices page (`/pricing`, v2.30.0): amber-bordered disclaimer box (`disclaimer[lang]` from the API) with Amazon Bedrock and Anthropic pricing links, last automatic check and pending-review count, CSV / Markdown / JSON download links (`pricingExportUrl`), one table per provider in API order (model | Claude Platform on AWS | Global | US | In-Region, `$in / $out` + footnote `[n]` jumping to `#ref-n` with a 1.5 s highlight, badges from `tierBadges`), notes list, references list (`rel="noopener noreferrer"`, manual notes marked) and the disclaimer again. Only the table container scrolls horizontally on phones (model column fixed). Inline `L(en, ko)` like the analysis panels
 - `InsightsPanel.tsx` — SSE stream-regenerate AI insights
 - `PromptsPanel.tsx` — prompt CRUD + Bedrock OptimizePrompt target selector
-- `ModelExplorer.tsx` — 모델 카드 그리드 + 상세 모달 (API 탭: Converse/InvokeModel/Messages/Responses, `lib/modelExplorer.ts` 유도, v2.9.x)
+- `ModelExplorer.tsx` — 모델 카드 그리드 + 상세 모달 (API 탭: Converse/InvokeModel/Messages/Responses, `lib/modelExplorer.ts` 유도, v2.9.x). 카드 단가는 `/api/pricing` `models`를 `lib/pricingTable.ts` 포맷터로 표시("1M in/out" KO/EN 번역, v2.30.0)
 - `ParityPanel.tsx` — 패리티: provider 요약 카드(세그먼트 막대 `HealthBar`)+Key Findings 드로어, 직전 런 대비 변경 배너, 모델 콤보박스, 피처별 접이식 그룹(분포 바, Broken 자동 펼침), `EvidenceModal`(Request/Response JSON 접이식) + 수동 트리거 (v2.15.x)
 - `ClaudeFeaturesPanel.tsx` — Claude API Features: 5열(CP/Mantle/Bedrock runtime Messages API·InvokeModel·Converse) 매트릭스; 헬스 카드(문서 기준 헬스 docHealth + 6상태 분포 막대 + "{total} 셀" 칩, 클릭 → `SurfaceDrawer` Key Findings 6섹션 — 헤더 sticky, Escape 닫기, 폰 탭아웃 여백); 모델 칩(전체/Fable 5.1/Fable 5/Opus 5.5/Opus 5/Sonnet 5 — 카탈로그 `models` 순서, `buildGroups(..., modelKey, modelOrder)`·`surfaceFindings(..., modelKey)`, 카드·배너·드로어 동일 필터, 드로어 메타 줄에 모델 라벨); 문서 드리프트 배너(0건이면 "문서 드리프트 없음" 카드); 직전 런 대비 변경 배너(`kind` 카탈로그 규칙/실측 태그, 항목 클릭 → 증거 모달, 0건이면 "변경 없음" 카드); 셀 툴팁 모델별 프로브 소요 시간 + 드롭다운 ms/mono model_id; 상태/드리프트 필터 활성 시 그룹 강제 펼침 + 모두 펼치기/접기; 증거 모달(요청 스냅샷·응답 신호·문서 링크·검증 강도 툴팁); 수동 트리거 (`lib/claudeFeatures.ts` 순수 로직 + vitest, v2.24.0). **i18n 예외**: 이 패널과 `ParityPanel`은 `src/lib/i18n.ts` 대신 인라인 `L(en, ko)`/삼항 헬퍼를 쓴다(하위 컴포넌트는 `useLang()` + 로컬 `T`). 라벨은 카탈로그(`labelMaps`)가 단일 출처, 한글 문장은 쉼표 열거·"1." 번호·단정형 판정 문구.
 - `ThemeToggle.tsx` — dark/light theme toggle in `AppHeader` (`lib/theme.ts` `setTheme`/`useTheme`, `aria-pressed`)
diff --git a/frontend/src/lib/CLAUDE.md b/frontend/src/lib/CLAUDE.md
index 3bdb613..b885378 100644
--- a/frontend/src/lib/CLAUDE.md
+++ b/frontend/src/lib/CLAUDE.md
@@ -2,17 +2,18 @@
 
 ## Role
 Framework-light modules shared by components: the API client, auth/language providers, and pure functions
-(sorting, pricing, grading, trend pivoting, feature-matrix aggregation) that vitest covers.
+(sorting, price-table formatting, grading, trend pivoting, feature-matrix aggregation) that vitest covers.
 
 ## Key Files
-- `api.ts` — every backend call. Token in `localStorage["auth_token"]` (in-memory fallback when storage is blocked); `setToken` dispatches `auth-changed`; a 401 clears the token only if it is still the one that was sent. SSE clients `runProbe`, `chatStream`, `compareStream`, `streamRegenerateInsight` parse `event:` / `data:` blocks by hand
+- `api.ts` — every backend call. Token in `localStorage["auth_token"]` (in-memory fallback when storage is blocked); `setToken` dispatches `auth-changed`; a 401 clears the token only if it is still the one that was sent. SSE clients `runProbe`, `chatStream`, `compareStream`, `streamRegenerateInsight` parse `event:` / `data:` blocks by hand. `fetchPricing` (`GET /api/pricing`) and `pricingExportUrl(format, lang)` (v2.30.0)
 - `http.ts` — `fetchJson` (20 s default timeout → `TimeoutError`, caller `signal` honored) and `ApiError(status)` carrying FastAPI `detail`. Streams use plain `fetch` with no read timeout
 - `auth-context.tsx` — `AuthProvider` / `useAuth()`: one session check and one login dialog for the whole app; `openLogin(afterLogin?)` resumes the action after sign-in (used by `FloatingChat`)
 - `i18n.ts` + `i18n-context.tsx` — `ko` / `en` `Translations`, `LanguageProvider` (initial value from the `lang` cookie, then `localStorage`, cross-tab `storage` sync, writes the cookie back), `useT()`, `useLang()`
 - `sortModels.ts` — `FAMILY_ORDER` (substring `includes`, so a longer name such as Fable 5.1 / Opus 5.5 must precede its prefix), `channelRank` (Anthropic 0 → `(Global)` 1 → US / OpenAI `(US)` 2 → OpenAI regions 3; keep the branch order), `EXCLUDED_FAMILIES` (Opus 4.5, Sonnet 4.5, `(1P)` — hard filter), `sortResults`, `groupByFamily`
 - `monitoring.ts` — card rows and health: `channelKey` (model_id prefix before `:`), `cadenceResolver` (per-channel seconds from `/status` `channel_intervals`, base otherwise), `getFreshness` (stale after cadence + min(cadence, 300 s)), `buildMonitoringRows`, `summarizeMonitoring`, `filterMonitoringRows`
 - `metricGrade.ts` — only source of card grade thresholds (`LATENCY_THRESHOLDS` per workload category, `FALLBACK_LATENCY_THRESHOLDS`, `TPS_THRESHOLD` warn < 40 / crit < 15), `roundForDisplay` (grade what is shown), `GRADE_TEXT_CLASS`, `GRADE_MARKER` (ADR-029). `WORKLOAD_CATEGORY_IDS` mirrors `backend/auto_prober.py` `WORKLOAD_PRESETS`
-- `pricing.ts` — `PRICE_TABLE` + `getPricing` / `estimateCost` / `formatCost`; mirror of `backend/pricing.py`. Key derivation strips `anthropic:`, `openai:<region>:`, `global.` / `us.` and vendor prefixes, adds `-global` / `-us` for OpenAI CRIS, then exact match before prefix fallback
+- `pricing.ts` — `formatCost` only. v2.30.0 removed `PRICE_TABLE`, `getPricing` and `estimateCost`: unit prices come from `GET /api/pricing` (ADR-030)
+- `pricingTable.ts` — pure helpers for `/pricing` and price display: `formatUnitPrice` (`$4.00`), `formatPricePair` (`$4.00 / $20.00`), `tierBadges` ("unverified" for `stale` / `seed_only`, "pending", promo note, "promo_check" after `min_until`), `costFromPrices(models, modelId, inputTokens, outputTokens)` (null without a price, Comparison Lab); Model Explorer cards use `formatPricePair`. No sorting and no footnote numbering: the backend sends the order and `n`
 - `pivotTrend.ts` — `pivotTrend` to Recharts wide rows + per-series data; `cadenceSeconds` (number or per-model function) breaks a line after a longer silence; `isolatedSampleTimes` keeps lone samples visible
 - `trendSelection.ts` — `defaultTrendSelection` (one line per family), `buildTrendQuery` / `parseTrendQuery` (models/hours/category in the URL, `models=all` sentinel)
 - `claudeFeatures.ts` — `/claude-features` types and pure logic (`aggregateCell`, `buildGroups`, `surfaceSummary`, `surfaceFindings`, `labelMaps`, change-kind summary, latency helpers); mirrors `backend/claude_features/engine.py` status/verdict vocabulary
@@ -21,12 +22,12 @@ Framework-light modules shared by components: the API client, auth/language prov
 - `version.ts` — `APP_VERSION`, canonical app version shown in every header (bump list in root CLAUDE.md)
 
 ## Rules
-- `pricing.ts` and `backend/pricing.py` must change together — no test compares the two tables. Add every channel's exact key (e.g. `claude-opus-5-5`, the 3 GPT-6 keys) or prefix fallback silently picks a sibling's price
+- Never add a price table to the frontend: prices live only in the backend `price_history` table and reach the UI through `/api/pricing`. Render `families`, `references` and footnote numbers in the order the API sends them
 - Change grade thresholds only in `metricGrade.ts`; tests and e2e read `data-grade`, and the KO grade name is 양호, never 정상 (`metricGrade.test.ts`)
-- New model families: `FAMILY_ORDER` here plus `TrendChart.tsx` `MODEL_COLORS` (labels must match byte-for-byte)
+- New model families: `FAMILY_ORDER` here plus `TrendChart.tsx` `MODEL_COLORS` (labels must match byte-for-byte) and backend `pricing_sources.FAMILY_ORDER` (a pytest reads `sortModels.ts` and pins equality)
 
 ## Commands
 ```bash
-cd frontend && npm test        # vitest run — 11 lib test files + components/GptOnAwsPanel.test.ts
+cd frontend && npm test        # vitest run — src/**/*.test.{ts,tsx}: lib tests + components GptOnAwsPanel, PricingPanel, ComparePanel
 npm run typecheck              # next typegen && tsc --noEmit
 ```
diff --git a/frontend/src/lib/version.ts b/frontend/src/lib/version.ts
index f834038..d61d091 100644
--- a/frontend/src/lib/version.ts
+++ b/frontend/src/lib/version.ts
@@ -1,3 +1,3 @@
 // 단일 source of truth — CHANGELOG.md의 최신 release와 동기화.
 // 새 버전 release 시 이 파일을 갱신하면 모든 페이지 헤더에 즉시 반영된다.
-export const APP_VERSION = "v2.29.1";
+export const APP_VERSION = "v2.30.0";
````

#### `t14-late` — `@scratch/patches/t14-late.patch`

<!-- plan-block id=t14-late path=@scratch/patches/t14-late.patch sha256=4507331b7669484482dba1289c35a80a1097e2f43243e8e68672396f89391e4f -->
````diff
diff --git a/AGENTS.md b/AGENTS.md
index 3b32ac9..320b971 100644
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -8,7 +8,7 @@ AWS resource state are authoritative when older examples differ.
 - Browser verification and its isolated container recipe are recorded in
   [the UX review](docs/reviews/2026-09-22-monitoring-ux.md).
 - Production images use immutable tags and explicit digests.
-- Update the backend service and all five scheduled task definitions together
+- Update the backend service and all six scheduled task definitions together
   when their shared backend image changes.
 - RUM configuration is injected into the frontend at build time.
 - Preserve unrelated local files when staging a release.
@@ -17,5 +17,5 @@ AWS resource state are authoritative when older examples differ.
 
 기존 프로젝트 규칙은 [CLAUDE.md](CLAUDE.md)를 따른다. 오래된 예시와 실제 코드·운영
 상태가 다르면 현재 상태를 확인한다. 검증은 `make verify`를 사용하고, 운영 이미지는
-불변 태그와 digest로 고정한다. 공용 백엔드 이미지가 바뀌면 서비스와 5개 스케줄을
+불변 태그와 digest로 고정한다. 공용 백엔드 이미지가 바뀌면 서비스와 6개 스케줄을
 함께 갱신한다. RUM 빌드 설정을 확인하고 작업과 무관한 로컬 파일은 보존한다.
diff --git a/frontend/CLAUDE.md b/frontend/CLAUDE.md
index ed1e14f..2446839 100644
--- a/frontend/CLAUDE.md
+++ b/frontend/CLAUDE.md
@@ -28,7 +28,7 @@ Dashboard UI for monitoring LLM channel performance — Amazon Bedrock, Claude P
 - Components use Tailwind dark theme (bg-gray-900/950 palette); v2.8.0부터 화이트 테마 토글 (`html.light` class + `light:` variant, `lib/theme.ts`)
 - Default model cards group by family (newest first), then channel (Anthropic → Global → US → OpenAI regions). Attention/TTFT sorting uses a flat grid. An empty comparison selection means all models.
 - Card metric values are graded per workload category (normal blue / warning amber ▲ / critical rose ◆, v2.28.0). The KO grade names are 양호/경고/위험 — never 정상 for a grade, which belongs to the channel health badge. Thresholds, display rounding and color classes live only in `src/lib/metricGrade.ts` (ADR-029); tests and e2e read the `data-grade` attribute, not color classes.
-- Pages: `/` 대시보드 (`/?view=manual` = 수동 프로브, 로그인 필요 — 결과 테이블/차트/비교 분석 탭, 비교 분석 탭은 `ComparisonView`), `/chat` 챗봇 팝업 창(헤더 없음, `FloatingChat`이 여는 `ChatPanel variant="popup"`), `/models` Model Explorer (v2.9.0), `/parity` 패리티 매트릭스 (v2.11.0), `/gpt-on-aws` GPT on AWS 벤치 (v2.18.0), `/claude-features` Claude API Features 매트릭스 (v2.23.0), `/prompts`, `/cost`, `/reliability`, `/efficiency`, `/analysis`
+- Pages: `/` 대시보드 (`/?view=manual` = 수동 프로브, 로그인 필요 — 결과 테이블/차트/비교 분석 탭, 비교 분석 탭은 `ComparisonView`), `/chat` 챗봇 팝업 창(헤더 없음, `FloatingChat`이 여는 `ChatPanel variant="popup"`), `/models` Model Explorer (v2.9.0), `/parity` 패리티 매트릭스 (v2.11.0), `/gpt-on-aws` GPT on AWS 벤치 (v2.18.0), `/claude-features` Claude API Features 매트릭스 (v2.23.0), `/prompts`, `/cost`, `/pricing` 비용 단가 (v2.30.0 — 단가는 `/api/pricing`만 읽고 프런트에 단가 표를 두지 않는다), `/reliability`, `/efficiency`, `/analysis`
 
 ## Commands
 ```bash
````
