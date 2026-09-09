"""
ai/chat_service.py
==================

CogniSphere RAG Chat Service — v3
-----------------------------------

Pipeline:

    User Query
        ↓
    ACMA Retrieval
        ↓
    Simple Query? ──YES──→ Fast Deterministic Answer (no Ollama, <1s)
        │                       ↓
        NO                 Return with sources + memory address
        ↓
    Context Builder + Planner
        ↓
    Ollama (phi3:mini, 30s timeout)
        │
        ├─ Success → return AI answer + sources + memory address
        └─ Timeout/Error → graceful fallback to fast memory answer

Design goals:
    - NEVER show a timeout error to the user. Always return something.
    - Return file path address of every memory used (source + abstract).
    - Simple memory queries answered in <1s without calling Ollama.
    - Keep Ollama warm to reduce cold-start latency.
    - Keep prompts compact enough for local CPU inference.
    - Fail gracefully when Ollama is unavailable.
"""

from __future__ import annotations

import os
import re
import time
from typing import List, Dict, Any

import requests
from sqlalchemy.orm import Session

from ai.semantic_search import acma_search
from ai.query_intent import detect_intent
from ai.context_builder import build_context
from ai.planner_service import build_plan


# ============================================================================
# Ollama / LLM Configuration
# ============================================================================

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_URL = os.getenv("OLLAMA_URL", f"{OLLAMA_BASE_URL}/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi3:mini")

# Keep phi3:mini loaded in memory between requests.
OLLAMA_KEEP_ALIVE = -1

# Maximum characters of compressed section text sent to Ollama.
MAX_CONTEXT_CHARS = 2200

# Enough tokens for a useful 4-6 sentence answer.
NUM_PREDICT = 200

# Reduced hard timeout — if Ollama can't answer in 30s, use fast path.
OLLAMA_TIMEOUT = 30

# ============================================================================
# System Prompt
# ============================================================================

SYSTEM_PROMPT = """
You are CogniSphere, a personal memory assistant.

Answer the user's question using ONLY the retrieved memory context below.
Do not invent facts.
Do not mention that you are an AI model unless necessary.
Give a concise but useful answer.
If the user asks about a project, summarize:
1. What the project is
2. Problem it solves
3. Main objectives
4. Proposed approach/methodology
5. Important technologies/components
6. Expected result/innovation
""".strip()


# ============================================================================
# Memory Address Builder
# ============================================================================

def _build_memory_address(mem: Dict[str, Any]) -> str:
    """
    Reconstruct the best available file address for a memory.

    Priority:
    1. `location` field (set by desktop agent — full OS path)
    2. `source` filename in the uploads directory
    3. Just the filename
    """
    location = (mem.get("location") or "").strip()
    if location:
        return location

    source = (mem.get("source") or "").strip()
    if not source:
        return ""

    # Try to find the file in the uploads directory
    uploads_dir = os.getenv("UPLOAD_DIR", "uploads")
    candidate = os.path.join(uploads_dir, source)
    if os.path.isfile(candidate):
        return os.path.abspath(candidate)

    return source  # Fall back to just the filename


def _build_abstract(mem: Dict[str, Any], max_chars: int = 300) -> str:
    """
    Build a clean 1-3 sentence abstract from the memory's description
    or the first part of text_content.
    """
    text = (
        mem.get("description")
        or mem.get("text_content", "")[:1000]
        or ""
    )
    text = str(text).strip()

    if not text:
        return ""

    # Normalize
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"\.{3,}", " ", text)
    text = re.sub(r"[ \t]+", " ", text)

    # Split to sentences and pick first 2-3 meaningful ones
    sentences = re.split(r"(?<=[.!?])\s+", text)
    result_parts = []
    char_count = 0
    for s in sentences:
        s = s.strip()
        if len(s) < 20:
            continue
        if char_count + len(s) > max_chars:
            break
        result_parts.append(s)
        char_count += len(s)
        if len(result_parts) >= 3:
            break

    return " ".join(result_parts)


def _enrich_sources(memories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build the `sources` list with full file address and abstract for each memory.

    Each source entry:
    {
        "memory_id": int,
        "title": str,
        "file_type": str,
        "source": str,          # original filename
        "file_path": str,       # full OS path or best available address
        "abstract": str,        # 1-3 sentence clean summary
        "relevance_score": float,
        "timestamp": str,
    }
    """
    sources = []
    for mem in memories:
        sources.append({
            "memory_id":       mem.get("id"),
            "title":           mem.get("title") or "Untitled",
            "file_type":       mem.get("file_type") or "unknown",
            "source":          mem.get("source") or "",
            "file_path":       _build_memory_address(mem),
            "abstract":        _build_abstract(mem),
            "relevance_score": float(
                mem.get("activation_score",
                mem.get("confidence",
                mem.get("score", 0))) or 0
            ),
            "timestamp":       mem.get("date") or mem.get("created_at") or "",
            "image":           mem.get("image") or "",
        })
    return sources


# ============================================================================
# Memory Expansion
# ============================================================================

def expand_memories(
    db: Session,
    memories: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Expand retrieved memories with additional context if needed.

    Currently this intentionally returns the ACMA results unchanged.

    This function is kept as an extension point for future features such as:
        - parent/child memories
        - graph relationships
        - related documents
        - temporal neighbors
        - goal-linked memories
    """
    return memories


# ============================================================================
# Explainability / Evidence
# ============================================================================

def build_evidence(
    memories: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Build an explainability trace showing which memories contributed
    to the answer.
    """

    evidence: List[Dict[str, Any]] = []

    for mem in memories:
        content = (
            mem.get("content")
            or mem.get("description")
            or mem.get("text_content")
            or ""
        )

        evidence.append(
            {
                "memory_id": mem.get("id"),
                "content_preview": content[:200],
                "relevance_score": mem.get(
                    "confidence",
                    mem.get("score", 0),
                ),
                "source": mem.get("source", "unknown"),
                "timestamp": mem.get(
                    "created_at",
                    mem.get("date"),
                ),
            }
        )

    return evidence


# ============================================================================
# Memory Snippet Builder
# ============================================================================

def _extract_rag_context(mem: Dict[str, Any]) -> str:
    """
    Extract a compact, section-based RAG context from one memory.

    Strategy:
    1. Normalize PDF whitespace artifacts.
    2. Skip cover-page / TOC region (first ~5500 chars or past the last
       TOC-style line), which avoids matching headings that appear in the
       table of contents.
    3. Search the document body for both spaced headings ("Problem Statement")
       and run-together CamelCase headings ("ProblemStatement") using inline
       regex patterns.
    4. Extract content between adjacent section matches.
    5. Build a compressed context capped at MAX_CONTEXT_CHARS.

    Raw PDF text is NEVER forwarded to the frontend or LLM directly.
    """

    title = (mem.get("title") or "Untitled").strip()
    source = (mem.get("source") or "Unknown source").strip()
    text = str(mem.get("text_content") or mem.get("description") or "").strip()

    if not text:
        desc = str(mem.get("description") or "").strip()[:800]
        return f"Title: {title}\nSource: {source}\n{desc}"

    # ------------------------------------------------------------------
    # 1. Normalize
    # ------------------------------------------------------------------
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"\.{3,}", " ", text)          # dot leaders
    text = re.sub(r"(?m)^\s*\d{1,3}\s*$", " ", text)  # page numbers
    text = re.sub(r"[ \t]+", " ", text)

    # ------------------------------------------------------------------
    # 2. Skip TOC / cover-page region
    # ------------------------------------------------------------------
    toc_pattern = re.compile(
        r"(?m)^\s*(?:\d+\.)?\s*[A-Za-z][A-Za-z\s/,()-]{3,60}\s+\d{1,3}\s*$"
    )
    toc_end = 0
    for m in toc_pattern.finditer(text):
        toc_end = m.end()

    body_start = min(max(toc_end, 5000), 12000)
    body = text[body_start:]

    # ------------------------------------------------------------------
    # 3. Section definitions
    # ------------------------------------------------------------------
    SECTION_DEFS = [
        ("Abstract",
         ["ABSTRACT"],
         r"\bAbstract\b"),
        ("Problem Statement",
         ["PROBLEM STATEMENT", "PROBLEM DEFINITION"],
         r"\bProblem\s*(?:Statement|Definition)\b|ProblemStatement\b|ProblemDefinition\b"),
        ("Objectives",
         ["OBJECTIVES OF THE PROJECT", "OBJECTIVES", "OBJECTIVE"],
         r"\bObjectives?\s*(?:of\s*(?:the\s*)?[Pp]roject)?\b|ObjectivesoftheProject\b"),
        ("Scope",
         ["SCOPE OF THE PROJECT", "SCOPE"],
         r"\bScope\s*(?:of\s*(?:the\s*)?[Pp]roject)?\b|ScopeoftheProject\b"),
        ("Proposed Methodology",
         ["PROPOSED METHODOLOGY", "PROPOSED SYSTEM", "PROPOSED SOLUTION",
          "OVERVIEW OF PROPOSED WORK"],
         r"\bProposed\s*(?:Methodology|System|Solution|Work)\b"
         r"|ProposedMethodology\b|OverviewofProposedWork\b"),
        ("Architecture",
         ["SYSTEM ARCHITECTURE", "ARCHITECTURE"],
         r"\bSystem\s*Architecture\b|SystemArchitecture\b"),
        ("Technologies",
         ["SOFTWARE REQUIREMENTS", "TECHNOLOGIES USED",
          "TECHNOLOGY STACK", "TOOLS AND TECHNOLOGIES"],
         r"\bSoftware\s*Requirements?\b|Technolog(?:ies\s*Used|y\s*Stack)\b"
         r"|SoftwareRequirements\b|ToolsandTechnologies\b"),
        ("Expected Results",
         ["EXPECTED RESULTS", "EXPECTED OUTCOME"],
         r"\bExpected\s*(?:Results?|Outcome)\b|ExpectedOutcome\b"),
        ("Innovation",
         ["INNOVATION", "NOVELTY", "INNOVATION/NOVELTY"],
         r"\bInnovation(?:\s*/\s*Novelty)?\b|Novelty\b"),
        ("Future Scope",
         ["FUTURE SCOPE", "FUTURE ENHANCEMENTS"],
         r"\bFuture\s*(?:Scope|Enhancements?)\b|FutureScope\b"),
        ("Conclusion",
         ["CONCLUSION"],
         r"\bConclusion\b"),
    ]

    def find_in_body(search_text: str, exact_aliases: list, inline_pat: str):
        best = None
        for alias in exact_aliases:
            for m in re.finditer(
                rf"(?im)^\s*{re.escape(alias)}\s*:?\s*$",
                search_text,
            ):
                if best is None or m.start() < best.start():
                    best = m
        m = re.search(inline_pat, search_text)
        if m and (best is None or m.start() < best.start()):
            best = m
        return best

    matches = []  # [(start, end, label)]

    for label, exact_aliases, inline_pat in SECTION_DEFS:
        m = find_in_body(body, exact_aliases, inline_pat)
        if m:
            matches.append((m.start(), m.end(), label))

    matches.sort(key=lambda x: x[0])

    extracted = []  # [(label, content)]
    seen_labels: set = set()

    for i, (mstart, mend, label) in enumerate(matches):
        if label in seen_labels:
            continue
        seen_labels.add(label)

        next_start = matches[i + 1][0] if i + 1 < len(matches) else len(body)
        raw = body[mend:next_start]
        content = re.sub(r"\s+", " ", raw).strip()

        if len(content) >= 80:
            extracted.append((label, content))

    SECTION_BUDGET = {
        "Abstract":             260,
        "Problem Statement":    240,
        "Objectives":           240,
        "Proposed Methodology": 220,
        "Technologies":         200,
        "Expected Results":     200,
        "Innovation":           160,
        "Architecture":         150,
        "Scope":                120,
        "Future Scope":         120,
        "Conclusion":           120,
    }

    parts: List[str] = [f"Title: {title}", f"Source: {source}"]
    used = 0
    budget = MAX_CONTEXT_CHARS - len(title) - len(source) - 30

    for label, content in extracted:
        if used >= budget:
            break
        alloc = min(SECTION_BUDGET.get(label, 200), budget - used)
        snippet = content[:alloc]
        last_stop = max(snippet.rfind(". "), snippet.rfind("! "), snippet.rfind("? "))
        if last_stop > alloc * 0.5:
            snippet = snippet[:last_stop + 1]
        parts.append(f"\n[{label}]\n{snippet}")
        used += len(snippet)

    if len(parts) <= 2:
        desc = str(mem.get("description") or "").strip()
        if desc:
            parts.append(desc[:600])
        else:
            parts.append(body[:1000])

    return "\n".join(parts)


def _build_memory_snippet(
    mem: Dict[str, Any],
) -> str:
    """
    Convert one retrieved memory into a compact, useful RAG snippet.
    """

    text_content = mem.get("text_content") or ""

    if str(text_content).strip():
        return _extract_rag_context(mem)

    title = mem.get("title") or "Untitled"
    source = mem.get("source") or "Unknown"
    file_type = mem.get("file_type") or "Unknown"

    description = (
        mem.get("description")
        or mem.get("content")
        or ""
    )
    description = str(description).strip()[:500]

    return (
        f"Title: {title}\n"
        f"File: {source}\n"
        f"Type: {file_type}\n"
        f"Description: {description}"
    )


def _build_memory_context(
    memories: List[Dict[str, Any]],
) -> str:
    """
    Build the final memory context sent to Ollama.
    """

    snippets = []
    seen_bases = set()

    for mem in memories:
        title = (mem.get("title") or "").strip()
        source = (mem.get("source") or "").strip()
        base_key = re.sub(r"\s*\(\d+\)", "", (source or title)).lower().strip()

        if base_key and base_key in seen_bases and len(memories) > 1:
            continue

        seen_bases.add(base_key)
        snippets.append(_build_memory_snippet(mem))

    context = "\n\n--- MEMORY ---\n\n".join(snippets)

    if len(context) > MAX_CONTEXT_CHARS:
        context = (
            context[:MAX_CONTEXT_CHARS]
            + "\n...[context trimmed]"
        )

    return context


# ============================================================================
# Ollama Call
# ============================================================================

def _call_ollama(prompt: str) -> tuple[str, float]:
    """
    Call Ollama and return (answer, elapsed_seconds).

    Raises:
        requests.exceptions.ConnectionError
        requests.exceptions.Timeout
        requests.exceptions.RequestException
    """

    start = time.time()

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "num_predict": NUM_PREDICT,
            "temperature": 0.2,
            "top_k": 40,
            "top_p": 0.9,
        },
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=OLLAMA_TIMEOUT,
    )

    elapsed = time.time() - start

    response.raise_for_status()

    data = response.json()

    answer = (
        data.get("response") or ""
    ).strip()

    return answer, elapsed


# ============================================================================
# Fast Memory Answer (no Ollama — deterministic, <1s)
# ============================================================================
def _build_fast_memory_answer(query: str, memories: list[dict]) -> str:
    """
    Fast structured summarization of an already-identified memory.

    IMPORTANT:
    - Does NOT call Ollama.
    - Does NOT send the entire document to the frontend.
    - Uses the stored text_content as the source.
    - Extracts important project/document sections.
    - Produces a concise deterministic summary.
    """

    if not memories:
        return "I couldn't find a relevant memory for that question."

    mem = memories[0]

    title = (mem.get("title") or "Untitled").strip()
    source = (mem.get("source") or "Unknown source").strip()

    text = (
        mem.get("text_content")
        or mem.get("description")
        or ""
    )

    text = str(text).strip()

    if not text:
        return (
            f"I found **{title}**, but there is no detailed "
            f"content available for this memory."
        )

    # Normalize PDF text
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\.{3,}", " ", text)
    text = re.sub(r"\s+\d{1,3}\s+", " ", text)
    text = re.sub(r"[ \t]+", " ", text)

    # Define important sections
    section_aliases = {
        "Abstract": ["ABSTRACT"],
        "Problem Statement": ["PROBLEM STATEMENT", "PROBLEM DEFINITION"],
        "Objectives": ["OBJECTIVES OF THE PROJECT", "OBJECTIVES", "OBJECTIVE"],
        "Scope": ["SCOPE OF THE PROJECT", "SCOPE"],
        "Proposed Methodology": ["PROPOSED METHODOLOGY", "PROPOSED SYSTEM", "PROPOSED SOLUTION"],
        "Architecture": ["SYSTEM ARCHITECTURE", "ARCHITECTURE"],
        "Technologies": ["SOFTWARE REQUIREMENTS", "TECHNOLOGIES USED", "TECHNOLOGY STACK", "TOOLS AND TECHNOLOGIES"],
        "Expected Results": ["EXPECTED RESULTS", "EXPECTED OUTCOME"],
        "Innovation": ["INNOVATION", "NOVELTY"],
        "Conclusion": ["CONCLUSION"],
        "Future Scope": ["FUTURE SCOPE"],
    }

    # Extract sections
    sections = {}
    for section_name, aliases in section_aliases.items():
        start_match = None
        for alias in aliases:
            match = re.search(
                rf"(?im)^\s*{re.escape(alias)}\s*:?\s*$",
                text,
            )
            if match:
                start_match = match
                break

        if not start_match:
            continue

        start = start_match.end()

        next_match = re.search(
            r"""
            (?im)
            ^
            \s*
            (?:
                \d+(?:\.\d+)*\s+
            )?
            [A-Z][A-Z\s/&\-]{4,70}
            \s*:?
            \s*$
            """,
            text[start:],
            flags=re.VERBOSE,
        )

        if next_match:
            end = start + next_match.start()
        else:
            end = min(start + 6000, len(text))

        content = re.sub(r"\s+", " ", text[start:end].strip())

        if len(content) >= 80:
            sections[section_name] = content

    def sentences(value: str) -> list[str]:
        value = re.sub(r"\s+", " ", value).strip()
        parts = re.split(r"(?<=[.!?])\s+", value)
        result = []
        for sentence in parts:
            sentence = sentence.strip()
            if len(sentence) < 45:
                continue
            if "." * 3 in sentence:
                continue
            if len(re.findall(r"\d+", sentence)) > 8:
                continue
            result.append(sentence)
        return result

    def summarize_section(content: str, max_sentences: int = 2, max_chars: int = 500) -> str:
        sents = sentences(content)
        if not sents:
            return content[:max_chars].strip()

        keywords = [
            "project", "system", "platform", "ai", "artificial intelligence",
            "detect", "prevent", "protect", "user", "data", "analysis",
            "model", "machine learning", "deep learning", "security",
        ]

        scored = []
        for index, sentence in enumerate(sents):
            lower = sentence.lower()
            score = sum(1 for kw in keywords if kw in lower)
            score += max(0, 2 - (index * 0.05))
            scored.append((score, index, sentence))

        scored.sort(key=lambda x: x[0], reverse=True)
        selected = sorted(scored[:max_sentences], key=lambda x: x[1])
        result = " ".join(item[2] for item in selected)

        if len(result) > max_chars:
            result = result[:max_chars].rsplit(" ", 1)[0] + "..."

        return result

    # Build concise summary
    output = [f"### {title}", ""]

    if "Abstract" in sections:
        output.append("**Overview**")
        output.append(summarize_section(sections["Abstract"], max_sentences=2, max_chars=650))
        output.append("")

    if "Problem Statement" in sections:
        output.append("**Problem Addressed**")
        output.append(summarize_section(sections["Problem Statement"], max_sentences=2, max_chars=500))
        output.append("")

    if "Objectives" in sections:
        output.append("**Main Objectives**")
        output.append(summarize_section(sections["Objectives"], max_sentences=2, max_chars=500))
        output.append("")

    if "Proposed Methodology" in sections:
        output.append("**Proposed Approach**")
        output.append(summarize_section(sections["Proposed Methodology"], max_sentences=2, max_chars=550))
        output.append("")

    if "Architecture" in sections:
        output.append("**Architecture**")
        output.append(summarize_section(sections["Architecture"], max_sentences=2, max_chars=450))
        output.append("")

    if "Technologies" in sections:
        output.append("**Technologies / Requirements**")
        output.append(summarize_section(sections["Technologies"], max_sentences=2, max_chars=450))
        output.append("")

    if "Innovation" in sections:
        output.append("**Innovation / Novelty**")
        output.append(summarize_section(sections["Innovation"], max_sentences=2, max_chars=450))
        output.append("")

    if "Expected Results" in sections:
        output.append("**Expected Results**")
        output.append(summarize_section(sections["Expected Results"], max_sentences=2, max_chars=450))
        output.append("")

    if "Future Scope" in sections:
        output.append("**Future Scope**")
        output.append(summarize_section(sections["Future Scope"], max_sentences=2, max_chars=450))
        output.append("")

    # Fallback: no structured sections found — use first sentences
    if len(output) <= 3:
        fallback_sents = sentences(text)
        useful = fallback_sents[:6]
        if useful:
            output.append("**Summary**")
            output.append(" ".join(useful)[:3000])

    output.append(f"**Source:** {source}")

    return "\n".join(output)


# ============================================================================
# Simple Memory Query Detection
# ============================================================================

def _is_simple_memory_query(query: str) -> bool:
    """
    Detect questions that can be answered directly from memory
    without LLM synthesis.
    """

    q = query.lower().strip()

    complex_terms = [
        "compare", "comparison", "difference", "differences",
        "versus", " vs ", "which is better", "analyze",
        "analyse", "evaluate", "recommend",
    ]

    if any(term in q for term in complex_terms):
        return False

    simple_patterns = [
        "tell me about", "what is", "what's",
        "give me information about", "give me details about",
        "describe", "overview of", "summary of", "explain my",
        "what do you know about", "show me", "find my",
        "where is", "when did", "who is",
    ]

    return any(pattern in q for pattern in simple_patterns)


# ============================================================================
# Main Chat Function
# ============================================================================

def chat_with_memories(
    query: str,
    db: Session,
    conversation_history: list[dict] | None = None,
    user_id: int | None = None,
) -> dict:
    """
    Execute the CogniSphere RAG chat pipeline.

    Returns:
        {
            "answer": str,
            "intent": str,
            "confidence": float,
            "memories_used": list,
            "goal_context": list,
            "sources": list,       # enriched with file_path + abstract
            "plan": dict,
            "fast_answer": bool    # True if answered without Ollama
        }
    """

    t0 = time.time()

    print("=" * 70)
    print("CHAT REQUEST RECEIVED")
    print("Query:", query)
    print("=" * 70)

    # ------------------------------------------------------------------------
    # 1. ACMA Retrieval
    # ------------------------------------------------------------------------

    retrieval_start = time.time()

    try:
        acma_results = acma_search(
            query=query,
            db=db,
            top_k=3,
            user_id=user_id,
        )
    except Exception as e:
        print("[Chat] ACMA search error:", e)

        return {
            "answer": (
                "I couldn't search your memory database. "
                "Please try again in a moment."
            ),
            "intent": "unknown",
            "confidence": 0.0,
            "memories_used": [],
            "goal_context": [],
            "sources": [],
            "plan": {},
            "fast_answer": True,
        }

    retrieval_time = time.time() - retrieval_start

    print(f"ACMA returned: {len(acma_results)} memories in {retrieval_time:.2f}s")

    # ------------------------------------------------------------------------
    # 2. No memories found
    # ------------------------------------------------------------------------

    if not acma_results:
        print("[Chat] No relevant memories found.")

        return {
            "answer": (
                "I couldn't find any relevant memories for your question. "
                "Try uploading related documents or files first."
            ),
            "intent": "unknown",
            "confidence": 0.0,
            "memories_used": [],
            "goal_context": [],
            "sources": [],
            "plan": {},
            "fast_answer": True,
        }

    # ------------------------------------------------------------------------
    # 3. Expand Memories
    # ------------------------------------------------------------------------

    try:
        acma_results = expand_memories(db, acma_results)
    except Exception as e:
        print("[Chat] Memory expansion error:", e)

    # ------------------------------------------------------------------------
    # 4. Build enriched sources list (always — regardless of answer path)
    # ------------------------------------------------------------------------

    sources = _enrich_sources(acma_results)

    # ------------------------------------------------------------------------
    # 5. Fast path: simple memory query → no Ollama needed
    # ------------------------------------------------------------------------

    if _is_simple_memory_query(query):
        print("[Chat] Fast path: simple memory query — skipping Ollama.")

        fast_answer = _build_fast_memory_answer(query, acma_results)

        total_time = time.time() - t0
        print(f"[Chat] Fast answer generated in {total_time:.3f}s")

        confidence = _compute_confidence(acma_results)

        return {
            "answer":       fast_answer,
            "intent":       "memory_recall",
            "confidence":   confidence,
            "memories_used": acma_results,
            "goal_context": [],
            "sources":      sources,
            "plan":         {},
            "fast_answer":  True,
        }

    # ------------------------------------------------------------------------
    # 6. Complex path: build context + call Ollama
    # ------------------------------------------------------------------------

    print("Building context + prompt...")

    context_start = time.time()

    try:
        intent = detect_intent(query)
    except Exception as e:
        print("[Chat] Intent detection error:", e)
        intent = "unknown"

    try:
        ctx = build_context(acma_results)
    except Exception as e:
        print("[Chat] Context builder error:", e)
        ctx = {"context": "", "memories": acma_results, "goal_context": []}

    try:
        plan = build_plan(query, ctx.get("memories", acma_results))
    except Exception as e:
        print("[Chat] Planner error:", e)
        plan = {}

    context_time = time.time() - context_start
    print(f"Context + Planner: {context_time:.2f}s")

    memories_used = ctx.get("memories", acma_results)
    goal_context = ctx.get("goal_context", [])

    memory_context = _build_memory_context(memories_used)

    intent_value = (
        intent.value if hasattr(intent, "value") else str(intent)
    )

    prompt = f"""
{SYSTEM_PROMPT}

User question:
{query}

Retrieved memory context:
{memory_context}

Answer:
""".strip()

    print(f"Prompt characters: {len(prompt)}")

    # ------------------------------------------------------------------------
    # 7. Ollama Generation (with graceful fallback)
    # ------------------------------------------------------------------------

    print(f"[Chat] Calling Ollama: {OLLAMA_MODEL}")

    ollama_start = time.time()
    answer: str
    used_fast_fallback = False

    try:
        answer, ollama_time = _call_ollama(prompt)

        print(f"[Chat] Ollama answered in {ollama_time:.2f}s")

        if not answer:
            answer = _build_fast_memory_answer(query, acma_results)
            used_fast_fallback = True

    except requests.exceptions.Timeout:
        ollama_time = time.time() - ollama_start
        print(f"[Chat] Ollama TIMEOUT after {ollama_time:.2f}s — using fast fallback")

        # ✅ Graceful fallback: return structured memory answer, not an error
        answer = _build_fast_memory_answer(query, acma_results)
        used_fast_fallback = True

    except requests.exceptions.ConnectionError:
        ollama_time = time.time() - ollama_start
        print(f"[Chat] Ollama CONNECTION ERROR after {ollama_time:.2f}s — using fast fallback")

        answer = _build_fast_memory_answer(query, acma_results)
        used_fast_fallback = True

    except requests.exceptions.RequestException as e:
        ollama_time = time.time() - ollama_start
        print(f"[Chat] Ollama REQUEST ERROR: {e}")

        answer = _build_fast_memory_answer(query, acma_results)
        used_fast_fallback = True

    except Exception as e:
        ollama_time = time.time() - ollama_start
        print(f"[Chat] Ollama UNEXPECTED ERROR: {e}")

        answer = _build_fast_memory_answer(query, acma_results)
        used_fast_fallback = True

    # ------------------------------------------------------------------------
    # 8. Confidence + Timing
    # ------------------------------------------------------------------------

    confidence = _compute_confidence(memories_used)

    total_time = time.time() - t0

    print("-" * 70)
    print(f"CHAT COMPLETE | Retrieval: {retrieval_time:.2f}s | Context: {context_time:.2f}s | Total: {total_time:.2f}s")
    print(f"Fast fallback used: {used_fast_fallback}")
    print("-" * 70)

    # ------------------------------------------------------------------------
    # 9. Final Response
    # ------------------------------------------------------------------------

    return {
        "answer":        answer,
        "intent":        intent_value,
        "confidence":    confidence,
        "goal_context":  goal_context,
        "sources":       sources,          # enriched with file_path + abstract
        "memories_used": memories_used,
        "plan":          plan,
        "fast_answer":   used_fast_fallback,
    }


def _compute_confidence(memories: List[Dict[str, Any]]) -> float:
    """Compute average confidence from retrieved memories."""
    if not memories:
        return 0.0

    values = []
    for mem in memories:
        val = mem.get("activation_score", mem.get("confidence", mem.get("score", 0)))
        try:
            v = float(val)
            if 0.0 < v <= 1.0:
                v = v * 100.0
            values.append(v)
        except (TypeError, ValueError):
            continue

    if values:
        return round(sum(values) / len(values), 1)
    return 90.0


# ============================================================================
# Local Test
# ============================================================================

if __name__ == "__main__":

    from unittest.mock import MagicMock

    mock_db = MagicMock(spec=Session)

    test_query = "Tell me about my resume"

    result = chat_with_memories(test_query, mock_db)

    print("\n" + "=" * 70)
    print("RESULT")
    print("=" * 70)
    print("Answer:", result["answer"])
    print("Fast Answer:", result["fast_answer"])
    print("Sources:", len(result["sources"]))
    for s in result["sources"]:
        print(f"  - {s['title']} | {s['file_path']} | {s['abstract'][:80]}")
