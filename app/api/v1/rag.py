"""
Rotas RAG: upload de documentos (PDF) e perguntas com contexto.

- Depende de `get_db()` (MongoDB), `embed_texts` e `chat_completion` (OpenAI), e `upsert_document`/`search_similar_chunks`.
- Upload valida PDFs e limita a 15 páginas para extração.

Variáveis de ambiente (indiretas):
- OPENAI_API_KEY, OPENAI_EMBEDDING_MODEL, OPENAI_CHAT_MODEL.
- MONGODB_URI, MONGODB_DB.
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
import io
from app.db.mongo import get_db
from app.schemas.rag import UploadDocResponse, AskRequest, AnswerResponse
from app.rag.store import upsert_document, hybrid_search_chunks, get_owned_document_oid
from app.rag.rerank import rerank
from app.llm.openai_client import embed_texts, chat_completion
from app.deps.auth import get_current_user_id
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
    db=Depends(get_db),
    current_user_id: str = Depends(get_current_user_id)):
    """Responde uma pergunta com base em chunks mais similares ao contexto do documento.

    Etapas:
    1) Gera embedding da pergunta.
    2) Busca híbrida (vetorial + lexical/BM25) restringida ao documento, recuperando
       um conjunto amplo (`candidates`).
    3) Re-ranking dos candidatos e seleção dos `k` melhores.
    4) Monta prompt (system/user) e chama LLM.
    5) Retorna resposta e fontes (ids dos chunks).
    """

    # Verifica s o documento pertence ao usuário
    oid = await get_owned_document_oid(db, body.doc_id, current_user_id)
    if not oid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found or not owned by user")

    # 1) embedding da pergunta
    q_emb = embed_texts([body.question])[0]

    # 2) busca híbrida (vetorial + BM25) recuperando um conjunto amplo de candidatos
    candidates = await hybrid_search_chunks(
        db, body.doc_id, body.question, q_emb, k=body.candidates
    )
    if not candidates:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No context found")

    # 3) re-ranking e seleção dos k melhores
    results = rerank(body.question, candidates, top_n=body.k)

    # 4) monta prompt com contexto
    context = "".join([r.get("chunk", "") for r in results])
    system = "Você é um assistente que responde com base apenas no CONTEXTO fornecido. Se não houver informação suficiente, diga que não sabe."
    user = f"CONTEXTO: {context} PERGUNTA: {body.question}"
    
    # 4) chama LLM
    answer = chat_completion(system, user)
    # Referencia as fontes pelos IDs dos chunks retornados
    sources = [f"chunk_id={str(r.get('_id'))}" for r in results]
    return AnswerResponse(answer=answer, sources=sources)
