"""Composition root: builds every service from ``Settings``.

Tests and the evaluation runner build isolated containers (temporary data dir, in-memory
vector store, fault-injecting providers) through the same function, so what is tested is what
runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Engine

from app.audit.service import AuditService
from app.classification.service import DocumentClassifier
from app.core.config import Settings
from app.core.registry import DocumentTypeRegistry
from app.core.resilience import RetryPolicy
from app.demo.budget import BudgetedLLMProvider, DailyBudget
from app.demo.jobs import BackgroundJobs
from app.demo.limits import RateLimiter
from app.documents.pages import PageService
from app.drift.monitor import DriftMonitor, DriftThresholds
from app.extraction.service import EntityExtractor
from app.human_review.service import HumanReviewService
from app.ingestion.extractors import DocumentTextExtractor, TextExtractionService
from app.ingestion.service import IngestionService
from app.observability.cost import CostEstimator
from app.observability.metrics import InMemoryMetrics
from app.persistence.db import create_db_engine, make_session_factory
from app.persistence.repositories import (
    AnswerRepository,
    AuditRepository,
    DocumentRepository,
    DocumentTextRepository,
    EvaluationRepository,
    ExtractionRepository,
    InvocationRepository,
    RetentionRepository,
    ReviewRepository,
    WorkflowRepository,
)
from app.prompts.registry import PromptRegistry
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.factory import (
    build_embedding_provider,
    build_llm_provider,
    build_metrics,
    build_ocr_extractor,
    build_vector_store,
)
from app.providers.llm.base import LLMProvider
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.mock_handlers import default_handlers
from app.providers.ocr.tesseract import TesseractOCRExtractor
from app.providers.storage.local import DocumentStore, LocalDocumentStore
from app.providers.vectorstore.base import VectorStore
from app.rag.service import RAGService, RAGSettings
from app.retrieval.chunking import Chunker
from app.retrieval.indexer import Indexer
from app.retrieval.retriever import Retriever
from app.services.model_gateway import ModelGateway
from app.workflows.orchestrator import DocumentWorkflow
from app.workflows.state_machine import WorkflowStateMachine

_UNSET = object()


@dataclass
class Container:
    settings: Settings
    engine: Engine
    registry: DocumentTypeRegistry
    prompts: PromptRegistry
    metrics: InMemoryMetrics
    llm: LLMProvider
    embedder: EmbeddingProvider
    vector_store: VectorStore
    documents: DocumentRepository
    texts: DocumentTextRepository
    extractions: ExtractionRepository
    workflows: WorkflowRepository
    reviews_repo: ReviewRepository
    invocations: InvocationRepository
    answers: AnswerRepository
    evaluations: EvaluationRepository
    audit: AuditService
    gateway: ModelGateway
    ingestion: IngestionService
    text_extraction: TextExtractionService
    classifier: DocumentClassifier
    extractor: EntityExtractor
    chunker: Chunker
    retriever: Retriever
    reviews: HumanReviewService
    workflow: DocumentWorkflow
    rag: RAGService
    drift: DriftMonitor
    store: DocumentStore
    retention: RetentionRepository
    pages: PageService
    budget: DailyBudget | None = None
    limiter: RateLimiter = field(default_factory=RateLimiter)
    jobs: BackgroundJobs = field(default_factory=BackgroundJobs)

    def close(self) -> None:
        self.jobs.shutdown()
        self.engine.dispose()


def build_container(
    settings: Settings,
    llm: LLMProvider | None = None,
    embedder: EmbeddingProvider | None = None,
    vector_store: VectorStore | None = None,
    ocr: DocumentTextExtractor | object | None = _UNSET,
    retry_policy: RetryPolicy | None = None,
) -> Container:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    registry = DocumentTypeRegistry.load(settings.config_dir)
    prompts = PromptRegistry.load(settings.prompts_dir)
    metrics = build_metrics(settings)
    cost = CostEstimator.load(settings.config_dir)

    llm = llm or build_llm_provider(settings, registry)
    embedder = embedder or build_embedding_provider(settings)
    vector_store = vector_store or build_vector_store(settings, embedder.model_name)
    ocr_engine = build_ocr_extractor(settings) if ocr is _UNSET else ocr
    assert ocr_engine is None or isinstance(ocr_engine, DocumentTextExtractor)

    engine = create_db_engine(settings.resolved_database_url)
    sf = make_session_factory(engine)
    documents = DocumentRepository(sf)
    texts = DocumentTextRepository(sf)
    extractions = ExtractionRepository(sf)
    workflows = WorkflowRepository(sf)
    reviews_repo = ReviewRepository(sf)
    invocations = InvocationRepository(sf)
    answers = AnswerRepository(sf)
    evaluations = EvaluationRepository(sf)
    audit = AuditService(AuditRepository(sf))

    budget: DailyBudget | None = None
    if settings.demo_mode and not llm.is_mock:
        budget = DailyBudget(invocations, settings.demo_daily_budget_usd)
        llm = BudgetedLLMProvider(llm, MockLLMProvider(default_handlers(registry)), budget)

    gateway = ModelGateway(
        provider=llm,
        prompts=prompts,
        invocations=invocations,
        metrics=metrics,
        cost=cost,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout_s=settings.llm_timeout_s,
        retry_policy=retry_policy
        or RetryPolicy(
            max_retries=settings.llm_max_retries, backoff_s=settings.llm_retry_backoff_s
        ),
        json_repair_attempts=settings.llm_json_repair_attempts,
    )
    store = LocalDocumentStore(settings.data_dir / "documents")
    ingestion = IngestionService(
        documents, store, audit, metrics, settings.max_upload_bytes, settings.effective_max_pages
    )
    text_extraction = TextExtractionService(
        ocr=ocr_engine, min_chars_per_page=settings.ocr_min_chars_per_page
    )
    classifier = DocumentClassifier(
        gateway, settings.classification_min_confidence, settings.classification_max_chars
    )
    extractor = EntityExtractor(
        gateway, settings.extraction_min_confidence, settings.amount_tolerance_ratio
    )
    chunker = Chunker(settings.chunk_size, settings.chunk_overlap)
    indexer = Indexer(embedder, vector_store, metrics)
    retriever = Retriever(
        embedder,
        vector_store,
        metrics,
        settings.retrieval_top_k,
        settings.retrieval_min_score,
        settings.retrieval_min_score_scoped,
    )
    state_machine = WorkflowStateMachine(documents, workflows, audit)
    reviews = HumanReviewService(
        reviews_repo,
        documents,
        texts,
        extractions,
        state_machine,
        audit,
        metrics,
        settings.amount_tolerance_ratio,
    )
    workflow = DocumentWorkflow(
        documents=documents,
        texts=texts,
        extractions=extractions,
        store=store,
        state_machine=state_machine,
        text_extraction=text_extraction,
        classifier=classifier,
        extractor=extractor,
        chunker=chunker,
        indexer=indexer,
        reviews=reviews,
        audit=audit,
        metrics=metrics,
        review_ocr_documents=settings.review_ocr_documents,
    )
    reviews.set_reprocessor(workflow)
    rag = RAGService(
        retriever=retriever,
        gateway=gateway,
        documents=documents,
        answers=answers,
        reviews=reviews,
        audit=audit,
        metrics=metrics,
        settings=RAGSettings(
            min_answer_confidence=settings.answer_min_confidence,
            groundedness_min=settings.groundedness_min,
            retrieval_min_score=settings.retrieval_min_score,
            retrieval_strong_score=settings.retrieval_strong_score,
            max_context_chars=settings.max_context_chars,
            review_on_insufficient_evidence=settings.review_on_insufficient_evidence,
        ),
        embedding_model=embedder.model_name,
    )
    return Container(
        settings=settings,
        engine=engine,
        registry=registry,
        prompts=prompts,
        metrics=metrics,
        llm=llm,
        embedder=embedder,
        vector_store=vector_store,
        documents=documents,
        texts=texts,
        extractions=extractions,
        workflows=workflows,
        reviews_repo=reviews_repo,
        invocations=invocations,
        answers=answers,
        evaluations=evaluations,
        audit=audit,
        gateway=gateway,
        ingestion=ingestion,
        text_extraction=text_extraction,
        classifier=classifier,
        extractor=extractor,
        chunker=chunker,
        retriever=retriever,
        reviews=reviews,
        workflow=workflow,
        rag=rag,
        drift=DriftMonitor(
            documents,
            extractions,
            reviews_repo,
            answers,
            invocations,
            evaluations,
            DriftThresholds.load(settings.config_dir),
        ),
        store=store,
        retention=RetentionRepository(sf),
        pages=PageService(
            store,
            ocr=ocr_engine if isinstance(ocr_engine, TesseractOCRExtractor) else None,
        ),
        budget=budget,
    )
