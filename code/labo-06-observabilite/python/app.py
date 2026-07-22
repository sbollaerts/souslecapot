"""Assistant Bikaroo — Labo 6 : observer, diagnostiquer et expliquer.

Reprend l'assistant du labo 5 (chat + RAG + MCP + processus en 5 étapes +
sécurité avec modes vulnérable/protégé) et ajoute une observabilité locale :
chaque interaction reçoit un trace_id, chaque opération significative est un
span mesuré, et les événements de sécurité, transitions de workflow et erreurs
sont corrélés à la même trace.

Aucune infrastructure externe n'est requise (ni OpenTelemetry, ni Jaeger…).
"""

import json
from pathlib import Path

import streamlit as st

import mcp_client
import observability as obsmod
import orchestration
import rag
import security
import trusted_context

MODEL = "qwen2.5:3b"
MCP_URL = "http://localhost:8000/mcp"
CORPUS_DIR = Path(__file__).resolve().parents[1] / "ressources"
DB_PATH = Path(__file__).resolve().parent / "bikaroo_rag.db"

BASE_SYSTEM_PROMPT = (
    "Tu es l'Assistant Bikaroo, l'assistant virtuel de Bikaroo, une société de "
    "vélos partagés à Bruxelles. Tu réponds toujours en français, de manière "
    "claire, polie et concise.\n"
    "Tu disposes d'un contexte documentaire et de tools de lecture. Appuie-toi "
    "dessus et n'invente pas."
)

st.set_page_config(page_title="Assistant Bikaroo — Labo 6", page_icon="🔭", layout="wide")

# --- État de session ---------------------------------------------------------
for key, default in [("messages", []), ("last_sources", None),
                     ("last_tool_calls", None), ("process", None)]:
    if key not in st.session_state:
        st.session_state[key] = default

if "obs" not in st.session_state:
    st.session_state.obs = obsmod.ObservabilityService()
obs = st.session_state.obs

if "trusted" not in st.session_state:
    st.session_state.trusted = trusted_context.new_context("MBR-1042")
if "policy" not in st.session_state:
    # Couplage faible : la politique publie ses événements, l'observabilité les
    # rattache à la trace courante.
    st.session_state.policy = security.SecurityPolicy(
        protected=True, event_sink=obs.record_security_event)
trusted = st.session_state.trusted
policy = st.session_state.policy

# --- Indexation du corpus ----------------------------------------------------
if "index_size" not in st.session_state:
    try:
        with st.spinner("Indexation du corpus documentaire…"):
            st.session_state.index_size = rag.ensure_index(DB_PATH, CORPUS_DIR)
    except Exception as error:  # noqa: BLE001
        st.error(f"Impossible d'indexer le corpus. Détail : {error}")
        st.stop()

if "mcp_tools" not in st.session_state:
    try:
        st.session_state.mcp_tools = mcp_client.list_tool_names(MCP_URL)
    except Exception:  # noqa: BLE001
        st.session_state.mcp_tools = None


def _make_deps(top_k):
    return orchestration.Deps(
        model=MODEL,
        get_trip_raw=lambda tid: mcp_client.call_tool(MCP_URL, "get_trip_status", {"trip_id": tid}),
        create_revision=lambda params: json.loads(
            mcp_client.call_tool(MCP_URL, "create_revision_request", params)),
        rag_search=lambda q: rag.search(DB_PATH, q, top_k=top_k),
        rag_build_context=rag.build_context,
        policy=policy, context=trusted, obs=obs,
    )


def _trace_status(outcome):
    """Statut de trace déduit du résultat final (mêmes valeurs qu'en .NET)."""
    if outcome in (obsmod.OUTCOME_CREATED, obsmod.OUTCOME_ANSWERED):
        return obsmod.STATUS_COMPLETED
    if outcome in (obsmod.OUTCOME_REFUSED, obsmod.OUTCOME_NOT_ELIGIBLE):
        return obsmod.STATUS_REFUSED
    if outcome in (obsmod.OUTCOME_CANCELLED, obsmod.OUTCOME_ABORTED):
        return obsmod.STATUS_CANCELLED
    if outcome == obsmod.OUTCOME_FAILED:
        return obsmod.STATUS_FAILED
    return obsmod.STATUS_COMPLETED


# --- Barre latérale ----------------------------------------------------------
with st.sidebar:
    st.header("Sécurité")
    mode = st.radio("Mode de sécurité", ["Protégé", "Vulnérable"])
    policy.protected = (mode == "Protégé")
    st.code(f"Membre authentifié : {trusted.authenticated_member_id}\n"
            f"Actions : {', '.join(trusted.allowed_actions)}\n"
            f"Session : {trusted.session_id}", language="text")

    st.header("Observabilité")
    st.caption("Latence simulée (n'affecte pas le résultat métier, seulement les durées)")
    obs.latency[obsmod.CAT_LLM] = st.slider("Latence LLM (ms)", 0, 2000, 0, 100)
    obs.latency[obsmod.CAT_RAG] = st.slider("Latence RAG (ms)", 0, 2000, 0, 100)
    obs.latency[obsmod.CAT_MCP] = st.slider("Latence MCP (ms)", 0, 2000, 0, 100)

    st.header("Configuration")
    use_rag = st.toggle("Avec RAG (hors processus)", value=True)
    system_prompt = st.text_area("Prompt système (hors processus)",
                                 value=BASE_SYSTEM_PROMPT, height=120)
    temperature = st.slider("Température", 0.0, 1.0, 0.7, 0.1)
    max_tokens = st.slider("Max tokens", 64, 2048, 512, 64)
    top_k = st.slider("top-k", 1, 6, 4, 1)

    if st.session_state.mcp_tools:
        st.success("MCP connecté · " + ", ".join(st.session_state.mcp_tools))
    else:
        st.warning("Serveur MCP injoignable.")

    if st.button("Effacer la conversation"):
        for key in ["messages", "last_sources", "last_tool_calls", "process"]:
            st.session_state[key] = [] if key == "messages" else None
        st.rerun()

deps = _make_deps(top_k)

st.title("🔭 Assistant Bikaroo")
st.caption(f"Labo 6 — Observabilité · mode **{mode}** · {MODEL} + {rag.EMBEDDING_MODEL} · "
           f"{st.session_state.index_size} chunks")

process = st.session_state.process
if process and process["active"]:
    st.info(f"**Processus — Étape {process['step']}/5 : "
            f"{orchestration.STEP_LABELS[process['step']]}**")

col_chat, col_obs = st.columns([3, 2])

# --- Colonne conversation ----------------------------------------------------
with col_chat:
    user_input = st.chat_input("Posez votre question ou décrivez votre demande…")

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        obs.start_trace(user_input)          # une trace par interaction
        outcome = obsmod.OUTCOME_ANSWERED
        try:
            process = st.session_state.process
            if process and process["active"]:
                answer = orchestration.handle_message(process, user_input, deps)
                outcome = process["outcome"] or obsmod.OUTCOME_ANSWERED
            elif st.session_state.mcp_tools and orchestration.detect_revision_intent(
                    MODEL, user_input, obs):
                process = orchestration.new_process(trusted)
                process["trip_id"] = orchestration.find_trip_id(user_input)
                st.session_state.process = process
                answer = orchestration.advance_after_start(process, user_input, deps)
                outcome = process["outcome"] or obsmod.OUTCOME_ANSWERED
            else:
                policy.scan_for_injection(user_input, "user_message")
                context = ""
                sources = None
                if use_rag:
                    with obs.span("rag_search", obsmod.CAT_RAG,
                                  query=user_input[:80], top_k=top_k) as span:
                        sources = rag.search(DB_PATH, user_input, top_k=top_k)
                        raw_context = rag.build_context(sources)
                        span.set(result_count=len(sources),
                                 documents=[s["document"] for s in sources],
                                 headings=[s["heading"] for s in sources],
                                 scores=[round(s["score"], 3) for s in sources],
                                 context_chars=len(raw_context))
                        if not sources:
                            obs.record_event(obsmod.RAG_NO_RESULT, "rag", "warning",
                                             "Aucun extrait documentaire retrouvé.")
                    policy.scan_for_injection(raw_context, "rag_document")
                    context = policy.wrap_untrusted(raw_context,
                                                    security.UNTRUSTED_DOCUMENTS_TAG)

                prompt = system_prompt
                if policy.protected:
                    prompt += "\n" + security.SecurityPolicy.untrusted_prompt_rule()
                messages = [{"role": "system", "content": prompt}]
                if context:
                    messages.append({"role": "system",
                                     "content": "Contexte documentaire :\n\n" + context})
                messages.extend(st.session_state.messages)

                with obs.span("llm_formulation", obsmod.CAT_LLM, model=MODEL,
                              call_type="free_chat", temperature=temperature,
                              num_predict=max_tokens,
                              input_chars=sum(len(m["content"]) for m in messages)) as span:
                    answer, tool_calls, mcp_available = mcp_client.answer(
                        MCP_URL, MODEL, messages,
                        {"temperature": temperature, "num_predict": max_tokens})
                    span.set(output_chars=len(answer),
                             estimated_output_tokens=obsmod.estimate_tokens(answer),
                             mcp_available=mcp_available, tool_calls=len(tool_calls))
                if not mcp_available:
                    obs.record_event(obsmod.MCP_UNAVAILABLE, "mcp", "warning",
                                     "Serveur MCP injoignable : réponse sans tools.")
                st.session_state.last_sources = sources
                st.session_state.last_tool_calls = tool_calls

            with obs.span("final_response", obsmod.CAT_APPLICATION,
                          output_chars=len(answer), outcome=outcome):
                pass
            st.session_state.messages.append({"role": "assistant", "content": answer})
        except Exception as error:  # noqa: BLE001
            outcome = obsmod.OUTCOME_FAILED
            obs.record_error("application_error", "application", str(error))
            st.error(f"Une erreur est survenue. Détail : {error}")
        finally:
            obs.finish_trace(_trace_status(outcome), outcome)

    for message in st.session_state.messages:
        st.markdown(f"**{'Vous' if message['role'] == 'user' else 'Assistant'} :** "
                    f"{message['content']}")

    process = st.session_state.process
    if process and process["active"] and process.get("need_confirmation"):
        c1, c2 = st.columns(2)
        if c1.button("✅ Confirmer", use_container_width=True):
            obs.start_trace("Clic sur Confirmer")
            message = orchestration.confirm(process, deps)
            st.session_state.messages.append({"role": "assistant", "content": message})
            if process.get("last_tool_call"):
                st.session_state.last_tool_calls = [process["last_tool_call"]]
            out = process["outcome"] or obsmod.OUTCOME_REFUSED
            obs.finish_trace(_trace_status(out), out)
            st.rerun()
        if c2.button("✖ Annuler", use_container_width=True):
            obs.start_trace("Clic sur Annuler")
            message = orchestration.cancel(process, deps)
            st.session_state.messages.append({"role": "assistant", "content": message})
            obs.finish_trace(obsmod.STATUS_CANCELLED, obsmod.OUTCOME_CANCELLED)
            st.rerun()

# --- Colonne observabilité ---------------------------------------------------
with col_obs:
    st.subheader("🔭 Observabilité")

    if not obs.traces:
        st.caption("Aucune trace pour l'instant : posez une question.")
    else:
        labels = [f"{t.trace_id} — {t.final_outcome or t.status} — {t.duration_ms} ms"
                  for t in reversed(obs.traces)]
        choice = st.selectbox("Historique des traces", labels, index=0)
        trace = list(reversed(obs.traces))[labels.index(choice)]
        metrics = trace.metrics()

        # 1) Vue synthétique
        st.markdown("**Vue synthétique**")
        st.code(
            f"Trace       : {trace.trace_id}\n"
            f"Résultat    : {(trace.final_outcome or '—').upper()}  (statut : {trace.status})\n"
            f"Durée totale: {metrics['total_duration_ms']} ms\n"
            f"Spans       : {len(trace.spans)}\n"
            f"LLM         : {metrics['llm_calls']} appels / {metrics['llm_duration_ms']} ms\n"
            f"RAG         : {metrics['rag_searches']} recherche(s) / {metrics['rag_duration_ms']} ms\n"
            f"MCP         : {metrics['mcp_calls']} appels / {metrics['mcp_duration_ms']} ms\n"
            f"Sécurité    : {metrics['security_event_count']} événement(s)\n"
            f"Transitions : {metrics['workflow_transition_count']}\n"
            f"Erreurs     : {metrics['error_count']}", language="text")

        # 2) Chronologie
        with st.expander("Chronologie", expanded=True):
            for span in trace.spans:
                icon = "❌" if span.status == obsmod.STATUS_FAILED else "✅"
                st.markdown(f"`{span.offset_ms:>6} ms` {icon} **{span.name}** "
                            f"*({span.category})* — {span.duration_ms} ms")

        # 3) Détails
        with st.expander("Détails des spans"):
            for span in trace.spans:
                st.markdown(f"**{span.name}** · `{span.category}` · {span.duration_ms} ms · "
                            f"statut : `{span.status}`")
                if span.attributes:
                    st.json(span.attributes, expanded=False)
                if span.error:
                    st.error(span.error)

        with st.expander("Transitions du workflow"):
            if not trace.workflow_transitions:
                st.caption("Aucune transition.")
            for t in trace.workflow_transitions:
                st.markdown(f"`{t.timestamp}` **{t.step_before} → {t.step_after}** "
                            f"— {t.reason} *(statut : {t.status})*")

        with st.expander("Événements de sécurité"):
            if not trace.security_events:
                st.caption("Aucun événement de sécurité.")
            for e in trace.security_events:
                st.markdown(f"`{e.timestamp}` **[{e.attributes.get('action', '')}]** "
                            f"`{e.event_type}` — {e.details}")

        with st.expander("Événements d'application"):
            if not trace.events:
                st.caption("Aucun événement.")
            for e in trace.events:
                st.markdown(f"`{e.timestamp}` `{e.event_type}` ({e.severity}) — {e.details}")

        with st.expander("Métriques"):
            st.json(metrics, expanded=True)

        st.download_button("⬇️ Exporter la trace JSON",
                           data=obs.export_json(trace).encode("utf-8"),
                           file_name=f"{trace.trace_id}.json", mime="application/json")

    if st.session_state.last_tool_calls:
        with st.expander("Derniers appels de tools"):
            for call in st.session_state.last_tool_calls:
                st.markdown(f"`{call['name']}` — `{call['arguments']}`")
                st.caption(call["result"][:300])
