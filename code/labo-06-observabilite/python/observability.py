"""Observabilité locale — Labo 6.

Principe central du labo :

    Une suite de logs isolés ne suffit pas. Il faut CORRÉLER les opérations d'une
    même interaction au moyen d'un identifiant de trace commun (trace_id).

Ce module fournit une observabilité volontairement légère et locale (aucune
infrastructure externe : ni OpenTelemetry, ni Jaeger, ni Grafana) permettant de
reconstruire une exécution complète :

    TraceContext  → une interaction métier complète
      ├── spans                (opérations mesurées : llm, rag, mcp, security…)
      ├── events               (application + sécurité, rattachés à la trace)
      ├── workflow_transitions (étape avant → étape après, avec la raison)
      └── metrics              (durées, compteurs, résultat final)

Confidentialité : on n'enregistre PAS les prompts complets ni les embeddings.
On conserve des résumés, des tailles et des scores.
"""

import json
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime

MAX_TRACES = 20

# --- Statuts de trace ---------------------------------------------------------
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_REFUSED = "refused"

# --- Résultats finaux (identiques en Python et .NET) --------------------------
OUTCOME_CREATED = "created"
OUTCOME_CANCELLED = "cancelled"
OUTCOME_ABORTED = "aborted"
OUTCOME_NOT_ELIGIBLE = "not_eligible"
OUTCOME_REFUSED = "refused"
OUTCOME_FAILED = "failed"
OUTCOME_ANSWERED = "answered"

# --- Catégories de spans ------------------------------------------------------
CAT_LLM = "llm"
CAT_RAG = "rag"
CAT_MCP = "mcp"
CAT_SECURITY = "security"
CAT_WORKFLOW = "workflow"
CAT_APPLICATION = "application"

# --- Événements d'application (les événements de sécurité viennent de security.py)
MCP_UNAVAILABLE = "mcp_unavailable"
RAG_NO_RESULT = "rag_no_result"
LLM_ERROR = "llm_error"
WORKFLOW_ABORTED = "workflow_aborted"
TRACE_EXPORTED = "trace_exported"


def estimate_tokens(text):
    """Estimation volontairement approximative : ~4 caractères par token.

    Documentée comme telle : on n'ajoute pas de dépendance lourde (tokenizer)
    uniquement pour compter des tokens dans un laboratoire pédagogique.
    """
    return len(text or "") // 4


@dataclass
class TraceSpan:
    span_id: str
    trace_id: str
    name: str
    category: str
    started_at: str
    offset_ms: int              # décalage depuis le début de la trace
    ended_at: str = ""
    duration_ms: int = 0
    status: str = STATUS_RUNNING
    attributes: dict = field(default_factory=dict)
    error: str = ""

    def set(self, **attributes):
        """Ajoute des attributs au span (résumés, tailles, scores…)."""
        self.attributes.update(attributes)
        return self

    def to_dict(self):
        return {
            "span_id": self.span_id, "name": self.name, "category": self.category,
            "started_at": self.started_at, "offset_ms": self.offset_ms,
            "ended_at": self.ended_at, "duration_ms": self.duration_ms,
            "status": self.status, "attributes": self.attributes,
            "error": self.error,
        }


@dataclass
class TraceEvent:
    timestamp: str
    trace_id: str
    event_type: str
    source: str
    severity: str
    details: str
    attributes: dict = field(default_factory=dict)

    def to_dict(self):
        return {"timestamp": self.timestamp, "event_type": self.event_type,
                "source": self.source, "severity": self.severity,
                "details": self.details, "attributes": self.attributes}


@dataclass
class WorkflowTransition:
    timestamp: str
    trace_id: str
    step_before: str
    step_after: str
    reason: str
    status: str = "ok"

    def to_dict(self):
        return {"timestamp": self.timestamp, "step_before": self.step_before,
                "step_after": self.step_after, "reason": self.reason,
                "status": self.status}


@dataclass
class TraceContext:
    trace_id: str
    started_at: str
    user_request_summary: str
    _start_perf: float
    ended_at: str = ""
    duration_ms: int = 0
    status: str = STATUS_RUNNING
    final_outcome: str = ""
    error: str = ""
    spans: list = field(default_factory=list)
    events: list = field(default_factory=list)
    security_events: list = field(default_factory=list)
    workflow_transitions: list = field(default_factory=list)

    # --- Métriques dérivées ---------------------------------------------------

    def metrics(self):
        def by_cat(cat):
            return [s for s in self.spans if s.category == cat]

        llm, rag_spans, mcp = by_cat(CAT_LLM), by_cat(CAT_RAG), by_cat(CAT_MCP)
        metrics = {
            "total_duration_ms": self.duration_ms,
            "llm_calls": len(llm),
            "llm_duration_ms": sum(s.duration_ms for s in llm),
            "rag_searches": len(rag_spans),
            "rag_duration_ms": sum(s.duration_ms for s in rag_spans),
            "mcp_calls": len(mcp),
            "mcp_duration_ms": sum(s.duration_ms for s in mcp),
            "security_event_count": len(self.security_events),
            "workflow_transition_count": len(self.workflow_transitions),
            "error_count": sum(1 for s in self.spans if s.status == STATUS_FAILED),
            "final_outcome": self.final_outcome,
        }
        # Compléments optionnels agrégés depuis les attributs des spans.
        metrics["estimated_input_tokens"] = sum(
            s.attributes.get("estimated_input_tokens", 0) for s in llm)
        metrics["estimated_output_tokens"] = sum(
            s.attributes.get("estimated_output_tokens", 0) for s in llm)
        metrics["retrieved_chunks"] = sum(
            s.attributes.get("result_count", 0) for s in rag_spans)
        metrics["context_chars"] = sum(
            s.attributes.get("context_chars", 0) for s in rag_spans)
        return metrics

    def to_dict(self):
        return {
            "trace_id": self.trace_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "final_outcome": self.final_outcome,
            "user_request_summary": self.user_request_summary,
            "error": self.error,
            "metrics": self.metrics(),
            "spans": [s.to_dict() for s in self.spans],
            "events": [e.to_dict() for e in self.events],
            "security_events": [e.to_dict() for e in self.security_events],
            "workflow_transitions": [t.to_dict() for t in self.workflow_transitions],
        }

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class ObservabilityService:
    """Crée les traces, ouvre/ferme les spans, journalise événements et transitions.

    Contient aussi les latences simulées (contrôle pédagogique) : elles allongent
    réellement les spans concernés, sans modifier le résultat métier.
    """

    def __init__(self, max_traces=MAX_TRACES):
        self.traces = deque(maxlen=max_traces)
        self.current = None
        # Latences simulées, en millisecondes (0 = désactivé).
        self.latency = {CAT_LLM: 0, CAT_RAG: 0, CAT_MCP: 0}

    # --- Cycle de vie d'une trace --------------------------------------------

    def start_trace(self, user_request_summary):
        trace = TraceContext(
            trace_id="trc-" + uuid.uuid4().hex[:8],
            started_at=datetime.now().isoformat(timespec="milliseconds"),
            user_request_summary=(user_request_summary or "")[:160],
            _start_perf=time.perf_counter(),
        )
        self.traces.append(trace)
        self.current = trace
        return trace

    def finish_trace(self, status=STATUS_COMPLETED, final_outcome=""):
        trace = self.current
        if trace is None:
            return None
        trace.ended_at = datetime.now().isoformat(timespec="milliseconds")
        trace.duration_ms = int((time.perf_counter() - trace._start_perf) * 1000)
        trace.status = status
        trace.final_outcome = final_outcome or trace.final_outcome
        return trace

    # --- Spans ----------------------------------------------------------------

    @contextmanager
    def span(self, name, category, **attributes):
        """Ouvre un span, le ferme quoi qu'il arrive (succès ou exception).

        Applique aussi la latence simulée de la catégorie, afin qu'elle soit
        visible dans la chronologie et les métriques.
        """
        trace = self.current
        if trace is None:  # hors trace : on n'instrumente pas
            yield TraceSpan("", "", name, category, "", 0)
            return

        start = time.perf_counter()
        span = TraceSpan(
            span_id="spn-" + uuid.uuid4().hex[:6], trace_id=trace.trace_id,
            name=name, category=category,
            started_at=datetime.now().isoformat(timespec="milliseconds"),
            offset_ms=int((start - trace._start_perf) * 1000),
            attributes=dict(attributes),
        )
        trace.spans.append(span)

        delay_ms = self.latency.get(category, 0)
        if delay_ms:
            time.sleep(delay_ms / 1000)
            span.attributes["simulated_latency_ms"] = delay_ms

        try:
            yield span
            if span.status == STATUS_RUNNING:
                span.status = "success"
        except Exception as error:  # noqa: BLE001 — on ferme le span puis on relaie
            span.status = STATUS_FAILED
            span.error = f"{type(error).__name__}: {error}"[:300]
            raise
        finally:
            span.ended_at = datetime.now().isoformat(timespec="milliseconds")
            span.duration_ms = int((time.perf_counter() - start) * 1000)

    # --- Événements et transitions -------------------------------------------

    def record_event(self, event_type, source, severity, details, **attributes):
        if self.current is None:
            return None
        event = TraceEvent(datetime.now().strftime("%H:%M:%S.%f")[:-3],
                           self.current.trace_id, event_type, source, severity,
                           details, dict(attributes))
        self.current.events.append(event)
        return event

    def record_security_event(self, security_event):
        """Rattache un SecurityEvent (labo 5) à la trace courante."""
        if self.current is None:
            return
        self.current.security_events.append(TraceEvent(
            security_event.timestamp, self.current.trace_id,
            security_event.event_type, security_event.source,
            security_event.severity, security_event.details,
            {"action": security_event.action}))

    def record_transition(self, step_before, step_after, reason, status="ok"):
        if self.current is None:
            return
        self.current.workflow_transitions.append(WorkflowTransition(
            datetime.now().strftime("%H:%M:%S.%f")[:-3], self.current.trace_id,
            step_before, step_after, reason, status))

    def record_error(self, event_type, source, details):
        self.record_event(event_type, source, "critical", details)
        if self.current is not None:
            self.current.error = details[:300]

    # --- Export ---------------------------------------------------------------

    def export_json(self, trace):
        payload = trace.to_json()
        self.record_event(TRACE_EXPORTED, "application", "info",
                          f"Trace {trace.trace_id} exportée ({len(payload)} caractères).")
        return payload
