"""
Rotas RAG: upload de documentos (PDF) e perguntas com contexto.

- Depende de `get_db()` (MongoDB), `embed_texts` e `chat_completion` (OpenAI), e `upsert_document`/`search_similar_chunks`.
- Upload valida PDFs e limita a 15 páginas para extração.

Variáveis de ambiente (indiretas):
- OPENAI_API_KEY, OPENAI_EMBEDDING_MODEL, OPENAI_CHAT_MODEL.
- MONGODB_URI, MONGODB_DB.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status, UploadFile, File, Form
import io
from starlette.concurrency import run_in_threadpool
from app.db.mongo import get_db
from app.schemas.rag import UploadDocResponse, AskRequest, AnswerResponse
from app.rag.store import upsert_document, hybrid_search_chunks, get_owned_document_oid
from app.rag.rerank import rerank
from app.llm.openai_client import embed_texts, chat_completion
from app.deps.auth import get_current_user_id
from app.guardrails import apply_input_rail, apply_output_rail
from pypdf import PdfReader

router = APIRouter(tags=["rag"])

@router.post("/rag/documents", response_model=UploadDocResponse)
async def upload_document(
    db=Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
    # multipart com PDF
    file: UploadFile = File(...),
    title: str = Form(...),
):
    """Recebe um PDF e cria chunks com embeddings ligados ao documento.

    Regras:
    - Valida MIME/arquivo .pdf, não vazio, e extração de texto.
    - Limite de 15 páginas na extração.
    - Retorna id do documento e total de chunks.
    """
    # Opcional: proteger com token -> current_user = Depends(get_current_user_id)

    # validações de PDF
    if file.content_type not in {"application/pdf", "application/x-pdf", "binary/octet-stream"} and not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Envie um arquivo PDF válido")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo PDF vazio")

    # Extração de texto do PDF
    text = _extract_text_from_pdf_bytes(data)
    if not text or not text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Não foi possível extrair texto do PDF")

    res = await upsert_document(db, title, text,owner_id=current_user_id)
    return UploadDocResponse(**res)


def _extract_text_from_pdf_bytes(data: bytes) -> str:
    """Extrai texto de um PDF em bytes com limite de até 15 páginas.

    Lança HTTP 400 em falhas de leitura/arquivo inválido ou PDF muito grande.
    """
   
    # Tenta abrir o PDF e trata erros de leitura/arquivo inválido
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Falha ao ler PDF: {str(e)}",
        )

    pages = getattr(reader, "pages", [])
    # Limite de páginas: até 15
    try:
        page_count = len(pages)
    except Exception:
        page_count = 0
    if page_count > 15:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PDF excede o limite de 15 páginas")

    texts = []
    for page in pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        if t:
            texts.append(t)
    return "\n\n".join(texts)


@router.post("/rag/ask", response_model=AnswerResponse)
async def ask(
    body: AskRequest,
    request: Request,
    db=Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)):
    """Responde uma pergunta com base em chunks mais similares ao contexto do documento.

    Etapas:
    1) Input rail: valida a pergunta antes de tocar o LLM (curto-circuito se reprovar).
    2) Gera embedding da pergunta (já anonimizada, se aplicável).
    3) Busca híbrida (vetorial + lexical/BM25) restringida ao documento, recuperando
       um conjunto amplo (`candidates`).
    4) Re-ranking dos candidatos e seleção dos `k` melhores.
    5) Monta prompt (system/user) e chama LLM.
    6) Output rail: valida a resposta antes de devolvê-la ao usuário.
    7) Retorna resposta e fontes (ids dos chunks).
    """
    request_id = getattr(request.state, "request_id", None)

    # Verifica s o documento pertence ao usuário
    oid = await get_owned_document_oid(db, body.doc_id, current_user_id)
    if not oid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found or not owned by user")

    # 1) INPUT RAIL — nada chega ao Ollama sem passar pela validação de entrada
    gin = await apply_input_rail(
        body.question, db=db, request_id=request_id,
        user_id=current_user_id, doc_id=body.doc_id,
    )
    if not gin.allowed:
        # Curto-circuito: devolve a resposta segura padrão sem nunca acionar o LLM
        return AnswerResponse(answer=gin.safe_response, sources=[])
    question = gin.text  # pergunta (possivelmente anonimizada) que segue ao LLM

    # 2) embedding da pergunta
    q_emb = embed_texts([question])[0]

    # 3) busca híbrida (vetorial + BM25) recuperando um conjunto amplo de candidatos
    candidates = await hybrid_search_chunks(
        db, body.doc_id, question, q_emb, k=body.candidates
    )
    if not candidates:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No context found")

    # 4) re-ranking e seleção dos k melhores
    results = rerank(question, candidates, top_n=body.k)

    # 5) monta prompt com contexto
    context = "".join([r.get("chunk", "") for r in results])
    system = "Você é um assistente que responde com base apenas no CONTEXTO fornecido. Se não houver informação suficiente, diga que não sabe."
    user = f"CONTEXTO: {context} PERGUNTA: {question}"

    # 5) chama LLM (cliente síncrono isolado em threadpool para não bloquear o loop)
    answer = await run_in_threadpool(chat_completion, system, user)

    # 6) OUTPUT RAIL — nada chega ao usuário sem passar pela validação de saída
    gout = await apply_output_rail(
        answer, context=context, question=question, db=db,
        request_id=request_id, user_id=current_user_id, doc_id=body.doc_id,
    )
    # Referencia as fontes pelos IDs dos chunks retornados
    sources = [f"chunk_id={str(r.get('_id'))}" for r in results]
    return AnswerResponse(answer=gout.text, sources=sources)
